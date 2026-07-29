"""ResourcePreloader 单元测试"""
import pytest
from unittest.mock import patch, MagicMock

from src.skills.resource_preloader import (
    ResourcePreloader,
    PreloadConfig,
    PreloadResult,
)


class TestParseConfig:
    """parse_config 测试"""

    def test_empty_ext_info(self):
        preloader = ResourcePreloader(tenant_id=0)
        assert preloader.parse_config("") is None
        assert preloader.parse_config("{}") is None
        assert preloader.parse_config(None) is None

    def test_invalid_json(self):
        preloader = ResourcePreloader(tenant_id=0)
        assert preloader.parse_config("not json") is None

    def test_no_preload_resources_key(self):
        preloader = ResourcePreloader(tenant_id=0)
        assert preloader.parse_config('{"tags": ["crm"]}') is None

    def test_valid_config_from_string(self):
        preloader = ResourcePreloader(tenant_id=0)
        ext_info = '''{
            "preload_resources": {
                "always": ["knowledge/industries/_index.md"],
                "scene_map": {
                    "续约|流失": ["knowledge/analysis-strategies/risk-scoring-models.md"]
                },
                "max_preload": 3
            }
        }'''
        config = preloader.parse_config(ext_info)
        assert config is not None
        assert config.always == ["knowledge/industries/_index.md"]
        assert len(config.scene_map) == 1
        assert config.max_preload == 3

    def test_valid_config_from_dict(self):
        preloader = ResourcePreloader(tenant_id=0)
        ext_info = {
            "preload_resources": {
                "always": ["a.md", "b.md"],
                "scene_map": {},
                "max_preload": 5,
            }
        }
        config = preloader.parse_config(ext_info)
        assert config is not None
        assert config.always == ["a.md", "b.md"]
        assert config.max_preload == 5

    def test_defaults_when_fields_missing(self):
        preloader = ResourcePreloader(tenant_id=0)
        ext_info = {"preload_resources": {"always": ["x.md"]}}
        config = preloader.parse_config(ext_info)
        assert config is not None
        assert config.scene_map == {}
        assert config.max_preload == 4  # default


class TestMatchScene:
    """match_scene 测试"""

    def setup_method(self):
        self.preloader = ResourcePreloader(tenant_id=0)
        self.config = PreloadConfig(
            always=["knowledge/industries/_index.md"],
            scene_map={
                "新客开拓|新客|开拓": ["biz-model.md", "signal.md"],
                "续约|流失|健康度": ["risk-scoring.md", "signal.md"],
                "商机|推进|赢单": ["value-prop.md", "incumbent.md"],
            },
            max_preload=4,
        )

    def test_always_files_included(self):
        paths = self.preloader.match_scene(self.config, {"user_intent": "随便看看"})
        assert "knowledge/industries/_index.md" in paths

    def test_scene_match_new_customer(self):
        paths = self.preloader.match_scene(self.config, {"user_intent": "新客开拓分析"})
        assert "knowledge/industries/_index.md" in paths
        assert "biz-model.md" in paths
        assert "signal.md" in paths

    def test_scene_match_renewal(self):
        paths = self.preloader.match_scene(self.config, {"user_intent": "续约风险评估"})
        assert "risk-scoring.md" in paths

    def test_scene_match_case_insensitive(self):
        """中文匹配不涉及大小写，但确保 lower() 不破坏中文"""
        paths = self.preloader.match_scene(self.config, {"user_intent": "分析续约情况"})
        assert "risk-scoring.md" in paths

    def test_no_scene_match(self):
        """无场景匹配时只返回 always"""
        paths = self.preloader.match_scene(self.config, {"user_intent": "其他任务"})
        assert paths == ["knowledge/industries/_index.md"]

    def test_max_preload_limit(self):
        """超过 max_preload 时截断"""
        config = PreloadConfig(
            always=["a.md", "b.md"],
            scene_map={"测试": ["c.md", "d.md", "e.md"]},
            max_preload=3,
        )
        paths = self.preloader.match_scene(config, {"user_intent": "测试场景"})
        assert len(paths) == 3

    def test_dedup(self):
        """always 和 scene_map 有重复时去重"""
        config = PreloadConfig(
            always=["signal.md"],
            scene_map={"新客": ["signal.md", "biz.md"]},
            max_preload=4,
        )
        paths = self.preloader.match_scene(config, {"user_intent": "新客分析"})
        assert paths.count("signal.md") == 1
        assert "biz.md" in paths

    def test_multiple_arguments(self):
        """多个 arguments 值拼接匹配"""
        paths = self.preloader.match_scene(
            self.config,
            {"data_id": "12345", "user_intent": "帮我推进这个商机"},
        )
        assert "value-prop.md" in paths


class TestBuildNameVariants:
    """_build_name_variants 测试"""

    def test_camel_case(self):
        names = ResourcePreloader._build_name_variants("accountInsight")
        assert "accountInsight" in names
        assert "account-insight" in names

    def test_kebab_case(self):
        names = ResourcePreloader._build_name_variants("account-insight")
        assert "account-insight" in names
        assert "account_insight" in names
        assert "accountInsight" in names

    def test_snake_case(self):
        names = ResourcePreloader._build_name_variants("account_insight")
        assert "account_insight" in names
        assert "account-insight" in names

    def test_simple_name(self):
        names = ResourcePreloader._build_name_variants("diagnose")
        assert "diagnose" in names


class TestFormatPreloadedContext:
    """format_preloaded_context 测试"""

    def test_empty_result(self):
        result = PreloadResult(files=[])
        text = ResourcePreloader.format_preloaded_context(result)
        assert text == ""

    def test_single_file(self):
        result = PreloadResult(files=[{
            "path": "knowledge/industries/_index.md",
            "content": "# 行业索引\n\n| 行业 | 文件 |\n|:---|:---|\n| 制造业 | manufacturing.md |",
            "description": "行业知识包索引",
        }])
        text = ResourcePreloader.format_preloaded_context(result)
        assert "预加载知识文件" in text
        assert "knowledge/industries/_index.md" in text
        assert "行业索引" in text
        assert "无需再次调用 read_skill_resource" in text

    def test_multiple_files(self):
        result = PreloadResult(files=[
            {"path": "a.md", "content": "content A", "description": "desc A"},
            {"path": "b.md", "content": "content B", "description": ""},
        ])
        text = ResourcePreloader.format_preloaded_context(result)
        assert "a.md" in text
        assert "b.md" in text
        assert "content A" in text
        assert "content B" in text


class TestPreload:
    """preload 方法测试（mock DB）"""

    @pytest.mark.asyncio
    async def test_preload_success(self):
        preloader = ResourcePreloader(tenant_id=0)

        mock_rows = [
            ("knowledge/industries/_index.md", "# 索引内容", "行业索引"),
            ("knowledge/analysis-strategies/signal-patterns.md", "# 信号模式", "信号库"),
        ]

        with patch("src.store.pg_pool.get_conn") as mock_get_conn:
            mock_conn = MagicMock()
            mock_cur = MagicMock()
            mock_cur.fetchall.return_value = mock_rows
            mock_conn.cursor.return_value = mock_cur
            mock_get_conn.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_get_conn.return_value.__exit__ = MagicMock(return_value=False)

            result = await preloader.preload(
                "accountInsight",
                ["knowledge/industries/_index.md", "knowledge/analysis-strategies/signal-patterns.md"],
            )

        assert len(result.files) == 2
        assert result.files[0]["path"] == "knowledge/industries/_index.md"
        assert result.files[1]["content"] == "# 信号模式"

    @pytest.mark.asyncio
    async def test_preload_empty_paths(self):
        preloader = ResourcePreloader(tenant_id=0)
        result = await preloader.preload("accountInsight", [])
        assert result.files == []

    @pytest.mark.asyncio
    async def test_preload_db_error_graceful(self):
        preloader = ResourcePreloader(tenant_id=0)

        with patch("src.store.pg_pool.get_conn") as mock_get_conn:
            mock_get_conn.side_effect = Exception("DB connection failed")

            result = await preloader.preload("accountInsight", ["a.md"])

        assert result.files == []
        assert result.duration_ms >= 0

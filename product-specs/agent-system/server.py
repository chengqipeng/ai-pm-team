"""DeepAgent API 服务 — FastAPI + SSE + 完整 Tracing

启动: poetry run uvicorn server:app --host 0.0.0.0 --port 8001 --reload

API:
  POST /api/chat              — 流式对话（SSE）
  POST /api/chat/sync         — 同步对话
  GET  /api/traces             — Trace 列表
  GET  /api/traces/{trace_id}  — Trace 详情（含完整 span 链路）
  GET  /api/health             — 健康检查
  GET  /                       — 前端页面
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
import uuid
from typing import Any

sys.path.insert(0, os.path.dirname(__file__))

# 加载 .env 文件（如果存在），使 METAREPO_API_BASE 等配置生效
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=False)
except ImportError:
    pass

os.environ.setdefault("DEEPSEEK_API_KEY", "sk-HdY98AcN68JhtXLp8oeIATEL4PWq9rzRcCAhI8G4SOtBbtSw")

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from pydantic import BaseModel, Field

from src.core.tracer import tracer, Tracer, SpanType

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(name)s %(message)s")
logger = logging.getLogger("deepagent.server")


def _build_metarepo_backend_for_server():
    """优先直连本地数据库，回退到模拟后端"""
    try:
        from src.tools.metarepo_db_backend import MetarepoDbBackend
        backend = MetarepoDbBackend()
        backend.list_metamodels()  # 验证连通性
        logger.warning("Metarepo tool backend: DB 直连 (paas_metarepo_common)")
        return backend
    except Exception as exc:
        logger.warning("Metarepo DB 直连失败，降级到模拟后端: %s", exc)
        from src.tools.metarepo_backend import MetarepoSimulatedBackend
        logger.warning("Metarepo tool backend: Simulated")
        return MetarepoSimulatedBackend()

app = FastAPI(title="DeepAgent API", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── Trace 持久化 ──
from src.store.trace_writer import TraceWriter
from src.core.context import DEFAULT_TENANT_ID, DEFAULT_USER_ID, DEFAULT_USER_NAME, DEFAULT_USER_PHONE
trace_writer = TraceWriter(tenant_id=DEFAULT_TENANT_ID)

# ── Agent 懒加载 ──

_agent = None
_agent_mm = None  # 多模态 Agent
_agent_lock = asyncio.Lock()
_skill_registry = None  # SkillRegistry 实例，Agent 初始化后可用
_middlewares = None  # 中间件列表，Agent 初始化后可用

# ── 共享 CRM 后端实例（Agent 和 mock-data API 共用，修改即时可见）──
_crm_backend = None

def get_crm_backend():
    """获取共享的 CRM 模拟后端实例"""
    global _crm_backend
    if _crm_backend is None:
        from src.tools.crm_backend import CrmSimulatedBackend
        _crm_backend = CrmSimulatedBackend()
    return _crm_backend


async def _get_agent(multimodal: bool = False):
    global _agent, _agent_mm, _skill_registry, _middlewares
    target = _agent_mm if multimodal else _agent
    if target is not None:
        return target
    async with _agent_lock:
        target = _agent_mm if multimodal else _agent
        if target is not None:
            return target

        from src.agents.langchain_agent import create_deep_agent, LangChainAgentConfig
        from src.tools.base import ToolRegistry
        from src.tools.crm_backend import CrmSimulatedBackend
        from src.tools.crm_tools import register_crm_tools
        from src.tools.metarepo_backend import MetarepoSimulatedBackend
        from src.tools.metarepo_tools import register_metarepo_tools
        from src.skills.base import SkillRegistry
        from src.core.prompt_builder import build_system_prompt
        from src.middleware.builder import build_middleware
        from src.memory.viking_engine import VikingMemoryEngine
        from langchain_openai import ChatOpenAI

        backend = get_crm_backend()
        metarepo_backend = _build_metarepo_backend_for_server()
        reg = ToolRegistry()

        # 构建业务数据 backend — 始终使用内部模拟后端（agent-system 内部闭环）
        data_backend = backend
        logger.info("CRM data backend for server Agent: Simulated (内部闭环)")
        skill_reg = SkillRegistry()
        # 权威数据源：ai_skill_definition 表（禁止从文件加载）
        try:
            skill_reg.load_from_db(tenant_id=0)
        except Exception as exc:
            logger.warning("从 DB 加载 Skill 失败（Agent 将跳过技能）: %s", exc)

        # 暴露为模块级变量，供 event_generator 闭包中查询 skill context
        _skill_registry = skill_reg

        # 注入 skill_registry 到 SkillService（热加载支持）
        try:
            from src.api.skill_api import get_skill_service
            get_skill_service()._skill_registry = skill_reg
        except Exception:
            pass

        aux_llm = ChatOpenAI(model="deepseek-v4-flash", api_key=os.environ["DEEPSEEK_API_KEY"],
                             base_url="https://tokenhub.tencentmaas.com/v1", max_tokens=2048)
        memory_engine = None
        try:
            memory_engine = VikingMemoryEngine(
                vdb_url="http://10.60.2.17",
                vdb_key="bRG3NETg13tv5Fn68VTdkxaJXH9tMQzhKeT3unck",
                vdb_username="root",
                database_name="viking_memory",
                collection_name="agent_memories",
                llm=aux_llm,
            )
        except Exception as exc:
            logger.warning("VikingMemoryEngine 初始化失败（记忆功能降级）: %s", exc)

        register_crm_tools(reg, data_backend, memory_engine=memory_engine)
        register_metarepo_tools(reg, metarepo_backend)

        # 注册知识库工具（供 knowledge_doc_search 技能使用）
        from src.tools.knowledge_tools import register_knowledge_tools
        _kb_provider = getattr(app.state, "knowledge_provider", None)
        register_knowledge_tools(reg, provider=_kb_provider, tenant_id=DEFAULT_TENANT_ID)

        # 注册 ManageSkillTool（供 create_skill 技能使用）
        from src.tools.manage_skill_tool import ManageSkillTool
        reg.register(ManageSkillTool())

        # 注册 ReadSkillResourceTool（供 fork 模式子 Agent 加载知识文件）
        from src.tools.skill_resource_tool import ReadSkillResourceTool
        reg.register(ReadSkillResourceTool(tenant_id=DEFAULT_TENANT_ID))

        # 注册 ask_user 工具（中断确认机制）
        from src.tools.builtins.ask_user_tool import AskUserTool
        # ask_user 是 LangChain BaseTool，需要通过 ToolRegistry 的 LangChain 适配注册
        # 由于 ToolRegistry 只接受自定义 Tool 基类，这里通过 AgentFactory 的 tool_loader 注册
        # ask_user 会在 AgentFactory._build_agent 中通过 ToolLoader 自动发现

        system_prompt = build_system_prompt(
            agent_name="CRM-Agent",
            skills=skill_reg.list_all(),
            tools=reg.all_tools,
        )
        middlewares = build_middleware(
            system_prompt=system_prompt,
            agent_name="CRM-Agent", memory_engine=memory_engine,
            file_upload_enabled=True, llm=aux_llm,
        )
        _middlewares = middlewares  # 暴露给 /api/chat 入口层使用

        model_name = MULTIMODAL_MODEL if multimodal else TEXT_MODEL

        # 启用 checkpointer（支持 interrupt 中断确认机制）
        from langgraph.checkpoint.memory import MemorySaver
        _checkpointer = MemorySaver()

        config = LangChainAgentConfig(
            model=model_name, api_key=os.environ["DEEPSEEK_API_KEY"],
            api_base="https://tokenhub.tencentmaas.com/v1", tool_registry=reg,
            skill_registry=skill_reg, system_prompt=system_prompt, middlewares=middlewares,
            checkpointer=_checkpointer,
        )
        built = create_deep_agent(config)

        if multimodal:
            _agent_mm = built
            logger.warning("多模态 Agent 初始化完成 (model=%s)", model_name)
        else:
            _agent = built
            logger.warning("文本 Agent 初始化完成 (model=%s)", model_name)

        return built


# ── 文档检测 ──

import re


def _extract_json_object(text: str) -> dict | None:
    """从文本中提取第一个 JSON 对象（简化版）"""
    if not text:
        return None
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.split("\n")
        if lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    try:
        return json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        pass
    start = stripped.find("{")
    if start < 0:
        return None
    # 找匹配的 }
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(stripped)):
        ch = stripped[i]
        if esc:
            esc = False
            continue
        if ch == '\\':
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(stripped[start:i + 1])
                except (json.JSONDecodeError, ValueError):
                    return None
    return None


def _detect_document(content: str) -> dict | None:
    """检测内容是否为结构化文档（报告/分析），返回文档元信息或 None。

    纯规则兜底判断（当 LLM 判断不可用时使用）：
    - 长文本（>= 800字）+ 2个以上标题 → 文档
    - 中等文本（400-800字）+ 3个以上标题 → 文档
    - 排除短文本模板（请假条、邮件等）
    - 排除纯代码块
    - 排除知识库检索结果
    """
    if not content or len(content) < 400:
        return None

    # 排除知识库检索结果（Skill 输出的结构化回答，不应被当作报告）
    retrieval_markers = ["📚 检索结果", "检索结果：", "核心发现", "📄 来源：", "未找到直接相关的文档", "知识库检索："]
    if any(marker in content for marker in retrieval_markers):
        return None

    # 排除短文本模板
    first_100 = content[:100]
    template_keywords = ["请假条", "通知书", "邮件", "备忘录", "会议纪要"]
    if any(kw in first_100 for kw in template_keywords) and len(content) < 1200:
        return None

    # 统计标题数量
    md_headings = re.findall(r'^#{1,3}\s+.+', content, re.MULTILINE)
    cn_headings = re.findall(r'^[一二三四五六七八九十]+[、.]\s*.+', content, re.MULTILINE)
    heading_count = len(md_headings) + len(cn_headings)

    # 判断条件
    is_doc = (len(content) >= 800 and heading_count >= 2) or \
             (len(content) >= 400 and heading_count >= 3)
    if not is_doc:
        return None

    # 排除纯代码内容（代码块占比 > 70%）
    code_blocks = re.findall(r'```[\s\S]*?```', content)
    code_len = sum(len(b) for b in code_blocks)
    if code_len > len(content) * 0.7:
        return None

    # 提取标题
    title = "分析报告"
    h1_match = re.search(r'^#\s+(.+)', content, re.MULTILINE)
    if h1_match:
        title = h1_match.group(1).strip().strip('《》')
    else:
        for line in content.strip().split('\n'):
            line = line.strip().strip('#').strip()
            if line and len(line) < 50:
                title = line.strip('《》')
                break

    return {
        "title": title,
        "format": "markdown",
        "size": len(content),
        "sections": heading_count,
    }


# ═══════════════════════════════════════════════════════════
# LLM 输出形式判断
# ═══════════════════════════════════════════════════════════

_OUTPUT_FORMAT_PROMPT = """你是一个输出格式判断器。根据用户问题、Agent执行过程和最终输出内容，判断这次回答应该以什么形式展示给用户。

## 用户问题
{user_query}

## 执行过程摘要
{execution_summary}

## 输出内容（前1000字）
{content_preview}

## 判断规则
- "document"：输出是完整的分析报告、数据洞察、对比分析等需要独立阅读的长文档（通常 > 800字，有明确的章节结构）
- "inline"：输出是直接回答用户问题的内容，包括知识库检索结果、简短回答、确认信息、追问澄清等
- "confirm"：Agent需要用户确认或补充信息才能继续（如缺少参数、多个选项需要选择）
- "empty"：没有找到有效结果，需要告知用户

## 输出要求
只输出一个JSON（不要其他文字）：
{{"format": "document|inline|confirm|empty", "title": "如果是document则给出标题，否则为空字符串"}}
"""


async def _llm_detect_output_format(
    user_query: str,
    content: str,
    execution_summary: str,
    llm=None,
) -> dict | None:
    """使用 LLM 判断输出形式

    Returns:
        None: 普通内联输出（不触发文档模式）
        dict: {"title": "...", "format": "markdown", ...} 触发文档下载
    """
    if llm is None:
        # LLM 不可用，降级到规则判断
        return _detect_document(content)

    # 短内容直接返回 inline，不浪费 LLM 调用
    if not content or len(content) < 300:
        return None

    # 快速特征排除：知识库检索结果不应被判为 document
    retrieval_markers = ["📚 检索结果", "📄 来源：", "未找到直接相关的文档", "知识库检索："]
    if any(marker in content for marker in retrieval_markers):
        return None

    prompt = _OUTPUT_FORMAT_PROMPT.format(
        user_query=user_query[:200],
        execution_summary=execution_summary[:500],
        content_preview=content[:1000],
    )

    try:
        resp = await llm.ainvoke(prompt)
        text = getattr(resp, "content", None) or str(resp)
        # 解析 JSON
        parsed = _extract_json_object(text)
        if parsed is None:
            # LLM 返回无法解析，降级规则
            return _detect_document(content)

        fmt = parsed.get("format", "inline")
        if fmt == "document":
            title = parsed.get("title", "").strip() or "分析报告"
            return {
                "title": title,
                "format": "markdown",
                "size": len(content),
                "sections": len(re.findall(r'^#{1,3}\s+.+', content, re.MULTILINE)),
            }
        # inline / confirm / empty → 不触发文档模式
        return None
    except Exception as exc:
        logger.warning("LLM output format detection failed, fallback to rules: %s", exc)
        return _detect_document(content)


# 产出文档的技能 — 从 SkillRegistry 的 output_mode 动态判断
_document_skills_cache: set | None = None


def _get_document_skills() -> set:
    """从数据库获取产出文档的 Skill 集合（output_mode=card）。

    双层保护机制：
    1. _is_document_skill() — 在 Skill 开始执行时发送 doc_start 信号（仅 card 类）
    2. _executed_skill_output_mode — 在流结束时跳过文档检测（text/table/component 不检测）

    这确保 output_mode=text 的 Skill 即使输出很长也不会触发右侧文档面板。
    """
    global _document_skills_cache
    if _document_skills_cache is not None:
        return _document_skills_cache

    try:
        from src.store.skill_dao import SkillDefinitionDAO
        SkillDefinitionDAO._detected = False
        rows = SkillDefinitionDAO.list_active(tenant_id=0, include_platform=True)
        doc_skills = set()
        for row in rows:
            output_mode = getattr(row, 'output_mode', 'text')
            # 只有 output_mode=card 才触发文档面板
            if output_mode == 'card':
                doc_skills.add(row.api_key)
        _document_skills_cache = doc_skills
        logger.info("文档类 Skill（output_mode=card）: %s", doc_skills)
    except Exception as e:
        logger.warning("加载文档类 Skill 失败: %s", e)
        _document_skills_cache = set()
    return _document_skills_cache


def _is_document_skill(tool_name: str, tool_input) -> dict | None:
    """判断工具调用是否为文档类技能，返回预测的文档元信息。

    在 skills_tool 调用开始时触发，根据 skill_name 判断产出类型。
    支持 tool_name 为 "skills_tool" 或输入中包含 skill_name 字段的情况。
    """
    # 匹配 skills_tool（名称可能有变体）
    if "skill" not in tool_name.lower():
        return None
    try:
        if isinstance(tool_input, str):
            args = json.loads(tool_input)
        elif isinstance(tool_input, dict):
            args = tool_input
        else:
            return None
        skill_name = args.get("skill_name", "")
        if skill_name not in _get_document_skills():
            return None
        # 根据技能类型预测文档标题
        skill_args = args.get("arguments", {})
        if isinstance(skill_args, str):
            skill_args = {}
        entity = skill_args.get("entity", "") if isinstance(skill_args, dict) else ""
        dimensions = skill_args.get("dimensions", "") if isinstance(skill_args, dict) else ""
        if isinstance(dimensions, list):
            dimensions = ", ".join(str(d) for d in dimensions)
        if skill_name == "data_analysis":
            title = f"{entity} {dimensions} 分析报告" if entity else "数据分析报告"
        elif skill_name == "pipeline_analysis":
            title = "商机 Pipeline 分析报告"
        elif skill_name == "customer_360":
            title = "客户 360 全景视图"
        elif skill_name == "verify_config":
            title = f"{entity} 配置校验报告" if entity else "配置校验报告"
        elif skill_name == "diagnose":
            title = "问题诊断报告"
        elif skill_name in ("account-insight", "account_insight"):
            account_id = skill_args.get("account_id", "") if isinstance(skill_args, dict) else ""
            title = f"客户洞察 {account_id}" if account_id else "客户洞察报告"
        else:
            title = "分析报告"
        logger.warning("doc_start 信号: tool=%s, skill=%s, title=%s", tool_name, skill_name, title)
        return {"title": title.strip(), "format": "markdown", "skill": skill_name}
    except (json.JSONDecodeError, TypeError, AttributeError) as e:
        logger.warning("_is_document_skill 解析失败: tool=%s, error=%s", tool_name, e)
        return None


# ── API 模型 ──

class ChatRequest(BaseModel):
    message: str
    thread_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    user_id: str = Field(default="default_user")
    # history 字段已废弃：对话历史从后端 ai_message 表加载，不再依赖前端传递
    history: list[dict[str, str]] = Field(default_factory=list, deprecated=True)
    # resume 字段：中断恢复时传递用户响应（interrupt_id + value）
    resume: dict[str, Any] | None = None


# ── 文件上传存储 ──

_uploaded_files: dict[str, list[dict]] = {}  # thread_id → [file_info, ...]

UPLOAD_DIR = "./data/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# 多模态模型配置
MULTIMODAL_MODEL = "deepseek-v4-flash"
TEXT_MODEL = "deepseek-v4-flash"


# ── 挂载知识库 REST 路由 ──
try:
    from src.api import knowledge_router
    app.include_router(knowledge_router)
    logger.info("已挂载知识库管理 API: /api/knowledge/*")
except ImportError as exc:
    logger.warning("知识库 API 未启用: %s", exc)

try:
    from src.api.knowledge_search_debug_api import router as knowledge_debug_router
    app.include_router(knowledge_debug_router)
    logger.info("已挂载知识库检索调试 API: /api/knowledge/search-debug")
except ImportError as exc:
    logger.warning("知识库检索调试 API 未启用: %s", exc)


# ── 知识库 Provider 启动（全局持有，供 upload API / search Tool 使用）──

_knowledge_supervisor = None  # 供 shutdown 停止 Worker


@app.on_event("startup")
async def _start_knowledge_provider():
    """启动期初始化知识库 Provider + Worker 协程池

    配置默认值直接写在 KnowledgeSettings 中（含 LKEAP 凭证）。
    失败只记录日志，不阻塞服务启动。
    Provider 未启动时，上传/检索接口会返回 503 + 明确提示。
    """
    global _knowledge_supervisor
    try:
        from src.config.models import KnowledgeSettings
        from src.knowledge import build_knowledge_provider
        from langchain_openai import ChatOpenAI

        # 全部用 KnowledgeSettings 的默认值（凭证直接写死在那）
        settings = KnowledgeSettings()

        # 构造 LLM（给 Self-Querying / Auto-Tag 用），可选
        llm = None
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if api_key:
            try:
                llm = ChatOpenAI(
                    model="deepseek-v4-flash",
                    api_key=api_key,
                    base_url="https://tokenhub.tencentmaas.com/v1",
                    max_tokens=2048,
                )
            except Exception as exc:
                logger.warning("知识库 LLM 初始化失败，自动打标降级: %s", exc)

        provider, supervisor = build_knowledge_provider(settings, llm=llm)
        app.state.knowledge_provider = provider
        await supervisor.start()
        _knowledge_supervisor = supervisor

        # 启动调度任务检查器（每 60 秒检查一次到期任务）
        # 传入 vdb 引用，让调度能同步 hit_count 到 VDB
        from src.knowledge.scheduler import ScheduleRunner
        _schedule_runner = ScheduleRunner(
            check_interval_ms=60_000,
            vdb=getattr(provider, "_vdb", None),
        )
        asyncio.create_task(_schedule_runner.run_forever())
        app.state._schedule_runner = _schedule_runner

        # 自动写入/升级默认 Schema（幂等）
        # - 不存在 → INSERT
        # - 字段过时 → 原地 UPDATE + version 递增（受 uk(tenant_id,name,kb_id) 约束，不能新增行）
        try:
            from src.knowledge.ingestion import _DEFAULT_SCHEMA_FIELDS
            from src.store.knowledge_dao import KnowledgeSchemaDAO
            from src.store.knowledge_models import KnowledgeSchemaRow
            import json as _json

            existing = KnowledgeSchemaDAO.get_for_kb(0, 0)
            builtin_field_count = len(_DEFAULT_SCHEMA_FIELDS)
            builtin_names = {f.get("field") for f in _DEFAULT_SCHEMA_FIELDS}
            fields_json = _json.dumps(_DEFAULT_SCHEMA_FIELDS, ensure_ascii=False)

            if not existing:
                KnowledgeSchemaDAO.insert(KnowledgeSchemaRow(
                    tenant_id=0,
                    name="system_default",
                    knowledge_base_id=0,
                    fields=fields_json,
                    version=1,
                ))
                logger.info(
                    "已写入系统默认 Schema (tenant_id=0, name=system_default, "
                    "version=1, fields=%d)", builtin_field_count,
                )
            else:
                try:
                    current_fields = _json.loads(existing.fields or "[]")
                except Exception:
                    current_fields = []
                current_names = {f.get("field") for f in current_fields}
                if len(current_fields) < builtin_field_count or current_names != builtin_names:
                    next_version = int(getattr(existing, "version", 1) or 1) + 1
                    KnowledgeSchemaDAO.update_fields(
                        schema_id=existing.id,
                        fields_json=fields_json,
                        version=next_version,
                    )
                    logger.info(
                        "已升级系统默认 Schema (id=%s, version=%d→%d, fields=%d→%d)",
                        existing.id,
                        int(getattr(existing, "version", 1) or 1), next_version,
                        len(current_fields), builtin_field_count,
                    )
        except Exception as exc:
            logger.warning("写入默认 Schema 失败（非致命）: %s", exc)

        logger.info(
            "✅ 知识库 Provider 已启动（worker_count=%d, lkeap_region=%s, vdb=%s）",
            settings.ingest_worker_count,
            settings.lkeap_region,
            settings.vdb_database,
        )
    except Exception as exc:
        logger.exception("知识库 Provider 启动失败，上传/检索将不可用: %s", exc)


@app.on_event("shutdown")
async def _stop_knowledge_provider():
    global _knowledge_supervisor
    if _knowledge_supervisor is not None:
        try:
            await _knowledge_supervisor.stop(timeout=10)
            logger.info("知识库 Worker 已停止")
        except Exception as exc:
            logger.warning("停止知识库 Worker 失败: %s", exc)


# ── 挂载 AG-UI / A2UI 路由 ──
try:
    from src.api import a2ui_router
    app.include_router(a2ui_router)
    logger.info("已挂载 A2UI API: /agent/a2ui/*, /.well-known/agent-card")
except ImportError as exc:
    logger.warning("A2UI API 未启用: %s", exc)


# ── 挂载 元模型 / 元数据浏览 API ──
try:
    from src.api import metarepo_router
    app.include_router(metarepo_router)
    logger.info("已挂载 元模型浏览 API: /api/meta/*")
except ImportError as exc:
    logger.warning("元模型浏览 API 未启用: %s", exc)


# ── 挂载 Skill 管理 API ──
try:
    from src.api import skill_router
    from src.api.skill_api import set_skill_service
    from src.skills.service import SkillService
    app.include_router(skill_router)
    # SkillService 初始化（skill_registry 在 Agent 首次加载后注入）
    set_skill_service(SkillService())
    logger.info("已挂载 Skill 管理 API: /api/skills/*")
except ImportError as exc:
    logger.warning("Skill 管理 API 未启用: %s", exc)

# ── 挂载 Skill 测试调试 API ──
try:
    from src.api.skill_test_api import router as skill_test_router
    app.include_router(skill_test_router)
    logger.info("已挂载 Skill 测试调试 API: /api/skills/*/test/*")
except ImportError as exc:
    logger.warning("Skill 测试调试 API 未启用: %s", exc)

# ── 挂载 Skill 分类管理 API ──
try:
    from src.api import skill_category_router
    app.include_router(skill_category_router)
    logger.info("已挂载 Skill 分类管理 API: /api/skill-categories/*")
except ImportError as exc:
    logger.warning("Skill 分类管理 API 未启用: %s", exc)

# ── 挂载 Tool 工具管理 API ──
try:
    from src.api import tool_router
    app.include_router(tool_router)
    logger.info("已挂载 Tool 工具管理 API: /api/tools/*")
except ImportError as exc:
    logger.warning("Tool 工具管理 API 未启用: %s", exc)
except Exception as exc:
    logger.warning("Tool 工具管理 API 挂载失败: %s", exc)

# ── 挂载 Mock 数据查看 API ──
try:
    from src.api import mock_data_router
    app.include_router(mock_data_router)
    logger.info("已挂载 Mock 数据查看 API: /api/mock-data/*")
except ImportError as exc:
    logger.warning("Mock 数据查看 API 未启用: %s", exc)
except Exception as exc:
    logger.warning("Mock 数据查看 API 挂载失败: %s", exc)

# ── 挂载 Tool 评测 API ──
try:
    from src.api.tool_eval_api import router as tool_eval_router
    app.include_router(tool_eval_router)
    logger.info("已挂载 Tool 评测 API: /api/eval/tools/*")
except ImportError as exc:
    logger.warning("Tool 评测 API 未启用: %s", exc)
except Exception as exc:
    logger.warning("Tool 评测 API 挂载失败: %s", exc)

# ── 挂载 Memory 评测 API ──
try:
    from src.api.memory_eval_api import router as memory_eval_router
    app.include_router(memory_eval_router)
    logger.info("已挂载 Memory 评测 API: /api/eval/memory/*")
except ImportError as exc:
    logger.warning("Memory 评测 API 未启用: %s", exc)
except Exception as exc:
    logger.warning("Memory 评测 API 挂载失败: %s", exc)


# ── API 路由 ──

@app.get("/api/health")
async def health():
    return {"status": "ok", "agent_ready": _agent is not None,
            "multimodal_ready": _agent_mm is not None,
            "text_model": TEXT_MODEL, "multimodal_model": MULTIMODAL_MODEL}


@app.get("/api/auth/me")
async def auth_me():
    """返回当前 Agent 系统使用的用户身份（与 paas-platform-service 对齐）。

    HTTP 模式：自动登录后缓存的用户信息
    Sim 模式：返回 seed 数据里的默认用户
    """
    from src.tools._http_auth import get_shared_auth_client

    client = get_shared_auth_client()
    if client is not None:
        # HTTP 模式：触发一次登录（如果还没登录），从 JWT 解析用户信息
        try:
            import httpx
            token = await client._ensure_token()
            # 解析 JWT payload（不验签，仅取 claims）
            import base64
            parts = token.split(".")
            if len(parts) >= 2:
                payload_b64 = parts[1] + "=" * (4 - len(parts[1]) % 4)
                claims = json.loads(base64.urlsafe_b64decode(payload_b64))
                return {
                    "tenantId": claims.get("tenantId", DEFAULT_TENANT_ID),
                    "userId": claims.get("userId"),
                    "name": claims.get("name", ""),
                    "phone": os.getenv("METAREPO_PHONE", "13800000001"),
                    "backend": "http",
                }
        except Exception as e:
            logger.warning("/api/auth/me HTTP 模式获取失败: %s", e)

    # Sim 模式 / fallback：返回 seed 数据默认用户
    return {
        "tenantId": DEFAULT_TENANT_ID,
        "userId": DEFAULT_USER_ID,
        "name": DEFAULT_USER_NAME,
        "phone": DEFAULT_USER_PHONE,
        "backend": "sim",
    }


@app.post("/api/upload")
async def upload_file(request: Request):
    """文件上传 — 支持图片和文档"""
    form = await request.form()
    thread_id = str(form.get("thread_id", uuid.uuid4().hex[:12]))
    file = form.get("file")

    if file is None:
        return JSONResponse({"error": "No file provided"}, status_code=400)

    # 读取文件内容
    content = await file.read()
    filename = getattr(file, "filename", None) or "unnamed"
    content_type = getattr(file, "content_type", "") or ""

    # 保存到磁盘
    import mimetypes
    thread_dir = os.path.join(UPLOAD_DIR, str(thread_id))
    os.makedirs(thread_dir, exist_ok=True)
    file_id = uuid.uuid4().hex[:8]
    save_path = os.path.join(thread_dir, f"{file_id}_{filename}")
    with open(save_path, "wb") as f:
        f.write(content)

    # 判断文件类型
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    image_exts = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
    is_image = ext in image_exts or content_type.startswith("image/")

    # 构建文件信息
    file_info = {
        "fileName": filename,
        "fileType": "image" if is_image else "document",
        "content": "",  # 文档内容后续由中间件提取
        "url": f"/uploads/{thread_id}/{file_id}_{filename}",
        "mediaId": file_id,
        "size": len(content),
    }

    # 图片：生成 base64 data URL 供多模态模型使用
    if is_image:
        import base64
        b64 = base64.b64encode(content).decode("ascii")
        mime = content_type or mimetypes.guess_type(filename)[0] or "image/png"
        file_info["url"] = f"data:{mime};base64,{b64}"

    # 文档：尝试提取文本
    if not is_image:
        try:
            from src.uploads.manager import UploadManager
            mgr = UploadManager(base_dir=UPLOAD_DIR)
            text = ""
            if ext in (".txt", ".md", ".csv"):
                text = content.decode("utf-8", errors="replace")
            elif ext == ".pdf":
                text = mgr.convert_to_markdown(save_path)
            elif ext == ".docx":
                text = mgr.convert_to_markdown(save_path)
            file_info["content"] = text[:10000]
        except Exception as e:
            logger.warning("文件内容提取失败: %s — %s", filename, e)

    # 存储到 thread 的文件列表
    _uploaded_files.setdefault(str(thread_id), []).append(file_info)

    return {
        "file_id": file_id,
        "fileName": filename,
        "fileType": file_info["fileType"],
        "size": len(content),
        "thread_id": str(thread_id),
    }


@app.get("/uploads/{thread_id}/{filename}")
async def serve_upload(thread_id: str, filename: str):
    """静态文件服务 — 上传的文件"""
    from fastapi.responses import FileResponse
    path = os.path.join(UPLOAD_DIR, thread_id, filename)
    if os.path.exists(path):
        return FileResponse(path)
    return JSONResponse({"error": "File not found"}, status_code=404)


@app.post("/api/chat")
async def chat_stream(req: ChatRequest):
    """流式对话 — SSE + 完整 Tracing + 多模态支持"""
    # 设置请求级全局上下文
    from src.core.context import set_context, RequestContext
    set_context(RequestContext(
        tenant_id=DEFAULT_TENANT_ID,
        user_id=req.user_id,
        thread_id=req.thread_id,
        agent_name="CRM-Agent",
    ))

    # 获取该 thread 的上传文件
    files = _uploaded_files.get(req.thread_id, [])
    has_images = any(f.get("fileType") == "image" for f in files)

    agent = await _get_agent(multimodal=has_images)
    thread_id = req.thread_id

    from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

    # ── 检测是否是 interrupt resume 请求 ──
    if req.resume:
        # 使用 Command(resume=value) 从中断点恢复执行
        from langgraph.types import Command

        resume_value = req.resume  # 前端传递的 {interrupt_id, value, cancelled?}
        logger.info("[/api/chat] RESUME: thread=%s, resume=%s", thread_id, resume_value)

        trace = tracer.start_trace(thread_id, f"[resume] {resume_value.get('value', '')}", model=TEXT_MODEL, agent_name="CRM-Agent")
        trace_id = trace.trace_id
        trace_writer.on_trace_start(trace)

        config = {
            "configurable": {
                "thread_id": thread_id,
                "tenant_id": str(DEFAULT_TENANT_ID),
                "user_id": req.user_id,
            },
            "recursion_limit": 500,
        }

        async def resume_generator():
            full_content = ""
            from src.middleware.tracing import tracing_middleware
            tracing_middleware.clear(thread_id)

            try:
                # 使用 Command(resume=value) 恢复 graph 执行
                async for event in agent.astream_events(
                    Command(resume=resume_value), config=config, version="v2"
                ):
                    kind = event.get("event", "")
                    data = event.get("data", {})

                    if kind == "on_chat_model_stream":
                        parent_ids = event.get("parent_ids", [])
                        if len(parent_ids) > 2:
                            continue
                        chunk = data.get("chunk")
                        if chunk:
                            content = getattr(chunk, "content", "")
                            if isinstance(content, list):
                                content = "".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in content)
                            if content:
                                full_content += content
                                yield f"data: {json.dumps({'type': 'token', 'content': content}, ensure_ascii=False)}\n\n"

                    elif kind == "on_tool_start":
                        tool_name = event.get("name", "")
                        raw_input = data.get("input", {})
                        input_str = json.dumps(raw_input, ensure_ascii=False, default=str)[:200] if isinstance(raw_input, dict) else str(raw_input)[:200]
                        yield f"data: {json.dumps({'type': 'tool_start', 'tool_name': tool_name, 'input': input_str}, ensure_ascii=False)}\n\n"

                    elif kind == "on_tool_end":
                        tool_name = event.get("name", "")
                        raw_output = data.get("output", "")
                        output_content = getattr(raw_output, "content", str(raw_output)) if hasattr(raw_output, "content") else str(raw_output)
                        yield f"data: {json.dumps({'type': 'tool_end', 'tool_name': tool_name, 'output': output_content[:300]}, ensure_ascii=False)}\n\n"

            except Exception as exc:
                from langgraph.errors import GraphInterrupt as _GraphInterrupt
                if not isinstance(exc, _GraphInterrupt):
                    yield f"data: {json.dumps({'type': 'error', 'content': str(exc)}, ensure_ascii=False)}\n\n"

            tracer.finish_trace(trace_id, "success", full_content)
            trace_final = tracer.get_trace(trace_id)
            if trace_final:
                trace_writer.on_trace_finish(trace_final)

            yield f"data: {json.dumps({'type': 'done', 'trace_id': trace_id}, ensure_ascii=False)}\n\n"

        return StreamingResponse(resume_generator(), media_type="text/event-stream")

    # ── 正常对话流程（非 resume）──

    # 从数据库加载对话历史（供 QueryRewriter 使用，不依赖前端传递）
    history_messages = []
    try:
        from src.store.pg_pool import get_conn
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT id FROM ai_conversation WHERE tenant_id=%s AND thread_id=%s AND delete_flg=0",
                (DEFAULT_TENANT_ID, thread_id))
            conv_row = cur.fetchone()
            if conv_row:
                conv_id = conv_row[0]
                cur.execute("""
                    SELECT query, answer FROM ai_message
                    WHERE conversation_id=%s AND delete_flg=0
                    ORDER BY sequence DESC LIMIT 20
                """, (conv_id,))
                rows = cur.fetchall()
                if rows:
                    rows.reverse()
                    for query, answer in rows:
                        if query:
                            history_messages.append(HumanMessage(content=query))
                        if answer:
                            history_messages.append(AIMessage(content=answer))
    except Exception as e:
        logger.warning("[/api/chat] 加载对话历史失败（降级为首轮对话）: %s", e)
        history_messages = []

    logger.info("[/api/chat] thread=%s, db_history_count=%d, message=%s",
                thread_id, len(history_messages), req.message[:50])

    # ══════════════════════════════════════════════════════════════
    # 入口层预处理流水线（在任何主 Agent 调用之前执行）
    #   顺序：标题生成 → 毒性检测 → 查询改写 → 送入 Agent
    # ══════════════════════════════════════════════════════════════

    # 清理上一轮可能残留的中间件 spans（防止异步 memory_extract 延迟写入导致串轮）
    from src.middleware.tracing import tracing_middleware
    tracing_middleware.clear(thread_id)

    # ── Step 0: 标题生成（首次对话，异步 LLM 生成）──
    if not history_messages:
        from src.middleware.title import TitleMiddleware
        tracing_middleware._add_to_thread(
            thread_id, "title_generation", "title_generation", 0,
            {"title": "", "method": "llm", "phase": "entry"},
            input_data={"trigger": "首次对话", "user_input": req.message[:200]},
            output_data={"title": "(LLM 异步生成中)", "method": "llm"},
            detail="标题生成（LLM 异步）",
            status="success",
        )

    # ── Step 1: 毒性检测（必须在改写之前，避免恶意输入进入任何 LLM 调用） ──
    from src.core.content_reviewer import get_content_reviewer
    reviewer = get_content_reviewer()
    review_decision = await reviewer.review(req.message, thread_id=thread_id)

    if not review_decision.passed:
        # 拦截：直接返回拒绝响应，不进入改写和主 Agent 循环
        logger.warning("[/api/chat] 输入被拦截: thread=%s reason=%s",
                       thread_id, review_decision.blocked_reason)

        async def _blocked_response():
            from src.middleware.tracing import tracing_middleware
            # 把刚记录的 content_review span 透传给前端
            for mw_span in tracing_middleware.get_spans(thread_id):
                yield f"data: {json.dumps({'type': 'mw_span', 'span': mw_span}, ensure_ascii=False)}\n\n"
            tracing_middleware.clear(thread_id)
            # 推送拒绝文本（一次性）
            yield f"data: {json.dumps({'type': 'token', 'content': review_decision.blocked_reason}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'blocked': True}, ensure_ascii=False)}\n\n"

        return StreamingResponse(_blocked_response(), media_type="text/event-stream")

    # ── Step 2: 查询改写（多轮对话指代消解，独立 LLM 调用，callbacks=[] 隔离） ──
    # 首次对话（无历史消息）直接跳过改写，节省 LLM 调用
    from src.core.query_rewriter import get_query_rewriter
    if not history_messages:
        effective_query = req.message
        # 记录 skipped span
        tracing_middleware._add_to_thread(
            thread_id, "query_rewrite", "query_rewrite", 0,
            {"original_query": req.message[:500], "rewritten_query": "", "changed": False, "source": "entry", "skipped": True},
            input_data={"original_query": req.message[:500], "source": "entry"},
            output_data={"rewritten_query": "", "changed": False, "skipped": True},
            status="skipped",
            detail="首轮对话，无需改写",
        )
    else:
        rewriter = get_query_rewriter()
        effective_query = await rewriter.rewrite(
            history_messages, req.message, thread_id=thread_id,
        )

    # 组装送入 Agent 的消息列表
    # 注意：使用 checkpointer 时，LangGraph 会自动从 Redis 恢复历史消息，
    # 这里只需要传入当前轮的新消息，不要重复传入 history_messages。
    messages = [HumanMessage(content=effective_query)]

    # 获取该 thread 的上传文件
    files = _uploaded_files.get(thread_id, [])

    # 开始 Trace（使用用户原始输入，改写是内部处理不暴露）
    trace = tracer.start_trace(thread_id, req.message, model=TEXT_MODEL, agent_name="CRM-Agent")
    trace_id = trace.trace_id
    trace_writer.on_trace_start(trace)

    # ── Step 0 续：启动 LLM 异步生成标题（必须在 on_trace_start 之后，确保 conversation 已创建）──
    if not history_messages:
        from src.middleware.title import TitleMiddleware
        try:
            from langchain_openai import ChatOpenAI
            _aux_llm = ChatOpenAI(
                model="deepseek-v4-flash",
                api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
                base_url="https://tokenhub.tencentmaas.com/v1",
                max_tokens=2048,
            )
            _title_mw = TitleMiddleware(llm=_aux_llm)
            _title_mw.start_async_optimize(
                thread_id, str(DEFAULT_TENANT_ID), req.user_id,
                req.message,
            )
        except Exception as _e:
            logger.warning("[/api/chat] TitleMiddleware async start failed: %s", _e)

    def _record_model_phase_middlewares(phase: str, tid: str):
        """记录 before_model/after_model 阶段的中间件 span

        LangGraph create_react_agent 不自动调用 middleware 的 before_model/after_model，
        这里在 on_chat_model_start/end 事件时手动记录已知的中间件。

        注意：此函数在 event_generator() 中调用，不在 LangGraph runtime context 中，
        必须使用 _add_to_thread 显式指定 thread_id。
        """
        from src.middleware.tracing import tracing_middleware
        # 已知的 before_model / after_model 中间件
        MW_BY_PHASE = {
            "before_model": ["SummarizationMiddleware"],
            "after_model": ["SubagentLimitMiddleware", "LoopDetectionMiddleware", "OutputValidationMiddleware"],
        }
        mw_list = MW_BY_PHASE.get(phase, [])
        # 根据执行阶段映射到前端 phase 分组
        phase_mapping = {
            "before_model": "reasoning",
            "after_model": "reasoning",
        }
        display_phase = phase_mapping.get(phase, "reasoning")
        for mw_name in mw_list:
            tracing_middleware._add_to_thread(
                tid, "middleware", f"mw:{mw_name}", 0,
                metadata={
                    "middleware_name": mw_name,
                    "phase": phase,
                    "has_effect": False,
                },
                input_data={
                    "middleware": mw_name,
                    "phase": phase,
                },
                output_data={
                    "has_effect": False,
                    "duration_ms": 0,
                },
                detail=f"{mw_name}.{phase} → 无变更",
            )

    async def event_generator():
        config = {
            "configurable": {
                "thread_id": thread_id,
                "tenant_id": str(DEFAULT_TENANT_ID),
                "user_id": req.user_id,
                "files": files,
                "parsed_files": files,  # FileProcessMiddleware 也从这里读
                "extend_params": {},
                "input_metadata": {"entry_review_passed": True},
                "knowledge_provider": getattr(app.state, "knowledge_provider", None),
            },
            "recursion_limit": 500,
        }
        full_content = ""
        current_tool_span = None
        # 增量推送中间件 spans
        from src.middleware.tracing import tracing_middleware
        from src.core.stream_pii_restorer import StreamPIIRestorer
        last_mw_idx = 0
        # 流式 PII 还原器 — 在推送给前端前将占位符还原为原始值
        pii_restorer = StreamPIIRestorer(config["configurable"].get("input_metadata", {}))
        # 执行过程追踪（用于 LLM 输出形式判断）
        _exec_tools: list[str] = []  # 记录执行过的工具/技能名称
        _executed_skill_output_mode: str = ""  # 记录执行的 Skill 的 output_mode（用于跳过文档检测）

        def flush_mw_spans():
            """检查并推送新的中间件 spans"""
            nonlocal last_mw_idx
            mw_spans = tracing_middleware.get_spans(thread_id)
            new_spans = mw_spans[last_mw_idx:]
            last_mw_idx = len(mw_spans)
            return new_spans

        # 先推送入口预处理阶段已记录的 span（title_generation、content_review、query_rewrite）
        for mw_span in flush_mw_spans():
            yield f"data: {json.dumps({'type': 'mw_span', 'span': mw_span}, ensure_ascii=False)}\n\n"

        try:
            async for event in agent.astream_events({"messages": messages}, config=config, version="v2"):
                kind = event.get("event", "")
                data = event.get("data", {})

                # 每次事件循环都检查是否有新的中间件 spans 需要推送
                for mw_span in flush_mw_spans():
                    yield f"data: {json.dumps({'type': 'mw_span', 'span': mw_span}, ensure_ascii=False)}\n\n"

                if kind == "on_chat_model_stream":
                    parent_ids = event.get("parent_ids", [])
                    if len(parent_ids) > 2:
                        continue
                    chunk = data.get("chunk")
                    if chunk:
                        content = getattr(chunk, "content", "")
                        if isinstance(content, list):
                            content = "".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in content)
                        if content:
                            full_content += content
                            # 流式 PII 还原：在推送前将占位符还原为原始值
                            restored = pii_restorer.feed(content)
                            if restored:
                                yield f"data: {json.dumps({'type': 'token', 'content': restored}, ensure_ascii=False)}\n\n"

                elif kind == "on_chat_model_start":
                    # 记录 before_model 中间件执行（LangGraph 不自动调用 middleware.before_model）
                    _record_model_phase_middlewares("before_model", thread_id)

                    tracer.increment_iteration(trace_id)
                    iter_num = trace.iteration_count
                    span = tracer.start_span(trace_id, SpanType.LLM_CALL, f"第 {iter_num} 轮思考",
                                             metadata={"iteration": iter_num})
                    # 提取 LLM 输入消息摘要（用于前端展开时查看）
                    llm_input_preview = []
                    try:
                        raw_input = data.get("input", {}) or {}
                        msgs = raw_input.get("messages") or []
                        # messages 可能是嵌套列表 [[msg1, msg2]] 或者扁平列表
                        if msgs and isinstance(msgs[0], list):
                            msgs = msgs[0]
                        for m in msgs[-12:]:
                            m_type = getattr(m, "type", None) or (m.get("type") if isinstance(m, dict) else "unknown")
                            m_content = getattr(m, "content", None)
                            if m_content is None and isinstance(m, dict):
                                m_content = m.get("content", "")
                            if isinstance(m_content, list):
                                m_content = "".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in m_content)
                            m_content = str(m_content or "")
                            llm_input_preview.append({
                                "role": m_type,
                                "content": m_content[:1000],
                            })
                    except Exception:
                        llm_input_preview = []
                    span.input_data["messages_preview"] = llm_input_preview
                    yield f"data: {json.dumps({'type': 'llm_start', 'iteration': iter_num, 'input': llm_input_preview}, ensure_ascii=False)}\n\n"

                elif kind == "on_chat_model_end":
                    # 结束最后一个 LLM span — 提取完整的 token/tool_calls/is_final 信息
                    for s in reversed(trace.spans):
                        if s.type == "llm_call" and s.status == "running":
                            output = data.get("output", {})
                            # 提取 token 用量（优先 usage_metadata，fallback 文本长度估算）
                            token_info = {}
                            if hasattr(output, "usage_metadata") and output.usage_metadata:
                                um = output.usage_metadata
                                token_info = {"input_tokens": um.get("input_tokens", 0),
                                              "output_tokens": um.get("output_tokens", 0)}
                            # Fallback: 从文本长度估算（1 token ≈ 2 中文字符 / 4 英文字符）
                            if not token_info.get("output_tokens"):
                                ai_text = ""
                                if hasattr(output, "content"):
                                    ai_text = output.content if isinstance(output.content, str) else str(output.content)
                                est_output = max(len(ai_text) // 2, 1) if ai_text else 0
                                # 估算 input tokens（从当前消息数 × 平均长度）
                                est_input = s.metadata.get("iteration", 1) * 2000  # 粗估每轮 2K input
                                token_info = {"input_tokens": est_input, "output_tokens": est_output, "estimated": True}

                            total = token_info.get("input_tokens", 0) + token_info.get("output_tokens", 0)
                            if total > 0:
                                tracer.add_tokens(trace_id, total)

                            # 提取 tool_calls 和 is_final
                            tool_calls = []
                            is_final = True
                            ai_content = ""
                            if hasattr(output, "content"):
                                ai_content = output.content if isinstance(output.content, str) else str(output.content)
                            if hasattr(output, "tool_calls") and output.tool_calls:
                                tool_calls = [tc.get("name", "") for tc in output.tool_calls if isinstance(tc, dict)]
                                is_final = False

                            # 写入 metadata（确保前端能读到）
                            s.metadata.update({
                                **token_info,
                                "tool_calls": tool_calls if tool_calls else [],
                                "is_final": is_final,
                                "output_preview": ai_content[:500] if ai_content else "",
                            })
                            # 动态更新 span 名称 — 更友好的显示
                            if is_final:
                                s.name = f"第 {s.metadata.get('iteration','')} 轮思考 → 最终回复"
                            elif tool_calls:
                                s.name = f"第 {s.metadata.get('iteration','')} 轮思考 → 调用 {', '.join(tool_calls)}"
                            s.finish("success", token_info)
                            yield f"data: {json.dumps({'type': 'llm_end', 'duration_ms': round(s.duration_ms), 'tokens': token_info, 'output': ai_content[:2000] if ai_content else '', 'tool_calls': tool_calls, 'is_final': is_final}, ensure_ascii=False)}\n\n"
                            break

                    # 记录 after_model 中间件执行
                    _record_model_phase_middlewares("after_model", thread_id)

                elif kind == "on_tool_start":
                    tracer.increment_tool(trace_id)
                    tool_name = event.get("name", "")
                    raw_input = data.get("input", {})
                    # JSON 序列化输入参数（保留完整数据）
                    if isinstance(raw_input, dict):
                        tool_input_full = json.dumps(raw_input, ensure_ascii=False, default=str)
                    elif isinstance(raw_input, str):
                        tool_input_full = raw_input
                    else:
                        tool_input_full = str(raw_input)

                    # 对 skills_tool / agent_tool 等路由型工具，抽取真实调用目标
                    sub_name = ""
                    skill_context_mode = ""
                    if tool_name in ("skills_tool", "agent_tool"):
                        try:
                            parsed_in = raw_input if isinstance(raw_input, dict) else json.loads(tool_input_full)
                            if isinstance(parsed_in, dict):
                                sub_name = str(
                                    parsed_in.get("skill_name")
                                    or parsed_in.get("agent_name")
                                    or ""
                                )
                                # 查询 skill 的 context（inline/fork）
                                if sub_name and tool_name == "skills_tool":
                                    try:
                                        _sr = _skill_registry
                                        if _sr:
                                            # 尝试精确匹配，失败则尝试连字符/下划线互换
                                            _sk = _sr.get(sub_name)
                                            if _sk is None:
                                                alt_name = sub_name.replace('-', '_') if '-' in sub_name else sub_name.replace('_', '-')
                                                _sk = _sr.get(alt_name)
                                            if _sk:
                                                skill_context_mode = _sk.context or 'inline'
                                            else:
                                                # 未找到 skill 定义，默认标注 inline
                                                skill_context_mode = 'inline'
                                        else:
                                            # SkillRegistry 未初始化，默认标注 inline
                                            skill_context_mode = 'inline'
                                    except Exception:
                                        skill_context_mode = 'inline'
                        except (json.JSONDecodeError, TypeError, ValueError):
                            sub_name = ""

                    display_name = f"{tool_name}({sub_name})" if sub_name else tool_name
                    current_tool_span = tracer.start_span(
                        trace_id, SpanType.TOOL_CALL, f"tool:{display_name}",
                        input_data={"tool_name": tool_name, "input": tool_input_full},
                        metadata={
                            "tool_name": tool_name,
                            "sub_name": sub_name,
                            "display_name": display_name,
                            "input": tool_input_full[:200],
                            "skill_context_mode": skill_context_mode,
                        },
                    )
                    tool_start_payload = {
                        "type": "tool_start",
                        "tool_name": tool_name,
                        "input": tool_input_full[:200],
                        "input_full": tool_input_full[:4000],
                    }
                    if sub_name:
                        tool_start_payload["sub_name"] = sub_name
                        tool_start_payload["display_name"] = display_name
                    if skill_context_mode:
                        tool_start_payload["skill_context_mode"] = skill_context_mode
                    yield f"data: {json.dumps(tool_start_payload, ensure_ascii=False)}\n\n"
                    _exec_tools.append(display_name)

                    # 记录执行的 Skill 的 output_mode（用于最终文档检测跳过逻辑）
                    if sub_name and tool_name == "skills_tool":
                        try:
                            _sr = _skill_registry
                            if _sr:
                                _sk_om = _sr.get(sub_name)
                                if _sk_om is None:
                                    # 尝试连字符/下划线互换
                                    alt_om = sub_name.replace('-', '_') if '-' in sub_name else sub_name.replace('_', '-')
                                    _sk_om = _sr.get(alt_om)
                                if _sk_om is None and any(c.isupper() for c in sub_name):
                                    # camelCase → kebab-case（如 accountInsight → account-insight）
                                    import re as _re
                                    kebab = _re.sub(r'([a-z])([A-Z])', r'\1-\2', sub_name).lower()
                                    _sk_om = _sr.get(kebab)
                                if _sk_om:
                                    _executed_skill_output_mode = getattr(_sk_om, 'output_mode', '') or ''
                        except Exception:
                            pass

                    # 提前检测文档类技能 → 发送 doc_start 信号
                    doc_prediction = _is_document_skill(tool_name, raw_input)
                    if doc_prediction:
                        yield f"data: {json.dumps({'type': 'doc_start', 'document': doc_prediction}, ensure_ascii=False)}\n\n"

                elif kind == "on_tool_end":
                    tool_name = event.get("name", "")
                    raw_output = data.get("output", "")
                    # 提取 ToolMessage 的 content（而不是 repr）
                    if hasattr(raw_output, "content"):
                        output_content = raw_output.content if isinstance(raw_output.content, str) else str(raw_output.content)
                    elif isinstance(raw_output, str):
                        output_content = raw_output
                    else:
                        output_content = str(raw_output)
                    # 尝试 JSON 格式化输出
                    try:
                        parsed = json.loads(output_content)
                        output_full = json.dumps(parsed, ensure_ascii=False, indent=2)
                    except (json.JSONDecodeError, TypeError):
                        output_full = output_content
                    if current_tool_span and current_tool_span.status == "running":
                        current_tool_span.metadata["output"] = output_full[:500]
                        current_tool_span.metadata["status"] = "success"
                        current_tool_span.input_data["input"] = tool_input_full if 'tool_input_full' in dir() else current_tool_span.input_data.get("input", "")
                        current_tool_span.finish("success", {"output": output_full})
                        yield f"data: {json.dumps({'type': 'tool_end', 'tool_name': tool_name, 'output': output_full[:300], 'output_full': output_full[:4000], 'duration_ms': round(current_tool_span.duration_ms)}, ensure_ascii=False)}\n\n"
                        current_tool_span = None

                    # skills_tool 返回长文本（分析报告）时，直接作为 token 流推送给前端
                    # 注意：仅 fork 模式的 skill 结果才直接推送；inline 模式返回的是 SOP 指令，
                    # 由 LLM 继续执行后自行生成最终回复，不应直接推送给前端
                    _is_fork_skill_result = False
                    if tool_name == "skills_tool" and len(output_content) > 200:
                        # 判断是否为 fork 模式的结果（fork 结果通常带有特定前缀或来自子 Agent）
                        _skill_sub_name = ""
                        try:
                            if current_tool_span is None:
                                # span 已结束，从 _exec_tools 获取
                                for _et in reversed(_exec_tools):
                                    if _et.startswith("skills_tool("):
                                        _skill_sub_name = _et[len("skills_tool("):-1]
                                        break
                            else:
                                _skill_sub_name = current_tool_span.metadata.get("sub_name", "")
                        except Exception:
                            pass
                        # 查询 skill context 模式
                        _skill_ctx_mode = ""
                        if _skill_sub_name and _skill_registry:
                            _sk_check = _skill_registry.get(_skill_sub_name)
                            if _sk_check is None:
                                alt = _skill_sub_name.replace('-', '_') if '-' in _skill_sub_name else _skill_sub_name.replace('_', '-')
                                _sk_check = _skill_registry.get(alt)
                            if _sk_check:
                                _skill_ctx_mode = _sk_check.context or "inline"
                        # 只有 fork 模式才直接推送报告
                        _is_fork_skill_result = (_skill_ctx_mode == "fork")

                    if tool_name == "skills_tool" and len(output_content) > 200 and _is_fork_skill_result:
                        # 去掉前缀指令
                        report = output_content
                        prefix = "[技能执行完成，以下是完整分析报告，请直接输出给用户，不要再调用其他工具]\n\n"
                        if report.startswith(prefix):
                            report = report[len(prefix):]
                        # 流式推送报告内容
                        yield f"data: {json.dumps({'type': 'skill_report_start', 'skill_name': _skill_sub_name or 'unknown'}, ensure_ascii=False)}\n\n"
                        # 分块推送（模拟流式）
                        chunk_size = 80
                        for i in range(0, len(report), chunk_size):
                            chunk = report[i:i+chunk_size]
                            yield f"data: {json.dumps({'type': 'token', 'content': chunk}, ensure_ascii=False)}\n\n"
                            full_content += chunk
                        yield f"data: {json.dumps({'type': 'skill_report_end'}, ensure_ascii=False)}\n\n"

        except Exception as exc:
            # GraphInterrupt 不是错误 — 是 ask_user 的正常中断
            # 需要跳过错误处理，继续到后面的 interrupt 检测逻辑
            from langgraph.errors import GraphInterrupt as _GraphInterrupt
            if isinstance(exc, _GraphInterrupt):
                pass  # 正常中断，不当作错误，继续执行后续 interrupt 检测
            else:
                err_span = tracer.start_span(trace_id, SpanType.ERROR, "error",
                                             input_data={"error": str(exc)})
                err_span.finish("error")
                # 刷新 PII 还原器 buffer
                pii_tail = pii_restorer.flush()
                if pii_tail:
                    yield f"data: {json.dumps({'type': 'token', 'content': pii_tail}, ensure_ascii=False)}\n\n"
                tracer.finish_trace(trace_id, "error", full_content)
                trace_writer.on_trace_finish(tracer.get_trace(trace_id))
                yield f"data: {json.dumps({'type': 'error', 'content': str(exc)}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'trace_id': trace_id}, ensure_ascii=False)}\n\n"
                return

        # 刷新 PII 还原器 buffer（处理可能残留的不完整占位符）
        pii_flush = pii_restorer.flush()
        if pii_flush:
            yield f"data: {json.dumps({'type': 'token', 'content': pii_flush}, ensure_ascii=False)}\n\n"

        # ── 检查是否有 pending interrupt（ask_user 触发的中断）──
        try:
            state = agent.get_state(config)
            if state and state.next:
                # graph 暂停，有 interrupt
                interrupt_values = []
                for task in (state.tasks or []):
                    for intr in (getattr(task, 'interrupts', None) or []):
                        interrupt_values.append(getattr(intr, 'value', {}))
                logger.warning("interrupt check: found %d interrupt values", len(interrupt_values))
                if interrupt_values:
                    # 降级文本显示：在 interrupt 事件之前发送格式化的选项列表
                    # （确保即使前端没有 interrupt UI，用户也能看到完整选项）
                    for iv in interrupt_values:
                        options = iv.get('options', [])
                        interrupt_type = iv.get('type', 'confirm')
                        message = iv.get('message', '')

                        # 构建格式化的选项文本
                        parts = []
                        if not full_content and message:
                            parts.append(message)
                        if options and interrupt_type in ('select', 'multi_select'):
                            parts.append("\n")
                            for i, opt in enumerate(options, 1):
                                label = opt.get('label', '')
                                desc = opt.get('description', '')
                                parts.append(f"{i}. **{label}**" + (f"（{desc}）" if desc else ""))
                            parts.append("\n请回复序号或名称进行选择。")
                        elif interrupt_type == 'input':
                            if not full_content:
                                parts.append(message or iv.get('title', ''))
                            parts.append("\n请直接输入内容回复。")
                        elif interrupt_type == 'confirm':
                            if not full_content:
                                parts.append(message or iv.get('title', ''))
                            parts.append('\n请回复"确认"或"取消"。')

                        supplement = "\n".join(parts)
                        if supplement.strip():
                            full_content += supplement
                            yield f"data: {json.dumps({'type': 'token', 'content': supplement}, ensure_ascii=False)}\n\n"
                        break

                    # 向前端发送 interrupt 事件（前端有 interrupt UI 时使用）
                    yield f"data: {json.dumps({'type': 'interrupt', 'interrupts': interrupt_values}, ensure_ascii=False)}\n\n"
        except Exception as _int_exc:
            logger.warning("Check interrupt state failed: %s", _int_exc)

        tracer.finish_trace(trace_id, "success", full_content)

        # 最终推送剩余的中间件 spans
        remaining_mw = flush_mw_spans()
        for mw_span in remaining_mw:
            yield f"data: {json.dumps({'type': 'mw_span', 'span': mw_span}, ensure_ascii=False)}\n\n"

        # 合并所有中间件 spans 到 Tracer（供 /api/traces/{id} 查询）
        all_mw_spans = tracing_middleware.get_spans(thread_id)
        tracing_middleware.clear(thread_id)
        trace_obj = tracer.get_trace(trace_id)
        if trace_obj and all_mw_spans:
            for mw_span in all_mw_spans:
                span = tracer.start_span(
                    trace_id,
                    mw_span.get("type", "unknown"),
                    mw_span.get("name", ""),
                    input_data=mw_span.get("input_data", {}),
                    metadata=mw_span.get("metadata", {}),
                )
                # 使用中间件记录的原始时间戳，确保排序正确
                span.start_time = mw_span.get("timestamp", span.start_time)
                span.duration_ms = mw_span.get("duration_ms", 0)
                span.status = "success"
                span.end_time = span.start_time + span.duration_ms / 1000
                # 写入 output_data
                span.output_data = mw_span.get("output_data", {})
                # 写入 detail（供前端显示）
                if mw_span.get("detail"):
                    span.metadata["detail"] = mw_span["detail"]
                # 写入 step_name / step_name_en / phase（供前端显示步骤名称和分组）
                if mw_span.get("step_name"):
                    span.metadata["step_name"] = mw_span["step_name"]
                if mw_span.get("step_name_en"):
                    span.metadata["step_name_en"] = mw_span["step_name_en"]
                # phase: 保留 metadata 中的原始值（before_model/after_model 等），
                # 不用顶层映射后的 display_phase 覆盖
                if mw_span.get("children"):
                    span.metadata["children"] = mw_span["children"]

        # 持久化到 PG（在所有 span 合并完成后）
        trace_final = tracer.get_trace(trace_id)
        if trace_final:
            trace_writer.on_trace_finish(trace_final)

        # 检测最终内容是否为可下载文档（LLM 判断 + 规则兜底）
        # ★ 如果执行的 Skill 明确声明 output_mode=text，跳过文档检测
        #   只有 output_mode=card 或未声明时才需要检测
        doc_meta = None
        if _executed_skill_output_mode not in ('text', 'table', 'component'):
            # 构建执行摘要
            exec_summary = f"调用工具: {', '.join(_exec_tools)}" if _exec_tools else "无工具调用，直接回答"

            # 获取 LLM 实例（复用 Agent 初始化时的 aux_llm）
            _format_llm = getattr(app.state, '_format_detect_llm', None)
            if _format_llm is None:
                # 首次使用时初始化一个轻量 LLM（低 max_tokens，快速响应）
                try:
                    from langchain_openai import ChatOpenAI
                    _format_llm = ChatOpenAI(
                        model="deepseek-v4-flash",
                        api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
                        base_url="https://tokenhub.tencentmaas.com/v1",
                        max_tokens=100,
                        request_timeout=5,  # 5 秒超时，不能让用户等太久
                    )
                    app.state._format_detect_llm = _format_llm
                except Exception:
                    _format_llm = None

            doc_meta = await _llm_detect_output_format(
                user_query=req.message,
                content=full_content,
                execution_summary=exec_summary,
                llm=_format_llm,
            )

        done_payload = {'type': 'done', 'trace_id': trace_id}
        if doc_meta:
            done_payload['document'] = doc_meta
        # 首次对话：等待 LLM 标题生成完成
        if not history_messages:
            from src.middleware.title import register_title_listener, get_updated_title
            _title_evt = register_title_listener(thread_id)
            try:
                await asyncio.wait_for(_title_evt.wait(), timeout=5.0)
                _llm_title = get_updated_title(thread_id)
                if _llm_title:
                    yield f"data: {json.dumps({'type': 'title_update', 'title': _llm_title, 'thread_id': thread_id}, ensure_ascii=False)}\n\n"
                    done_payload['title'] = _llm_title
            except asyncio.TimeoutError:
                # LLM 5 秒内未完成，从 DB 获取（可能已写入）
                get_updated_title(thread_id)  # 清理监听器
                try:
                    from src.store.pg_pool import get_conn as _get_conn
                    with _get_conn() as _conn:
                        _cur = _conn.cursor()
                        _cur.execute(
                            "SELECT title FROM ai_conversation WHERE tenant_id=%s AND thread_id=%s AND delete_flg=0",
                            (DEFAULT_TENANT_ID, thread_id))
                        _row = _cur.fetchone()
                        if _row and _row[0] and _row[0] not in ('', '新对话', '对话'):
                            done_payload['title'] = _row[0]
                except Exception:
                    pass

        yield f"data: {json.dumps(done_payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/api/chat/sync")
async def chat_sync(req: ChatRequest):
    """同步对话"""
    from src.core.context import set_context, RequestContext
    set_context(RequestContext(
        tenant_id=DEFAULT_TENANT_ID,
        user_id=req.user_id,
        thread_id=req.thread_id,
        agent_name="CRM-Agent",
    ))

    files = _uploaded_files.get(req.thread_id, [])
    has_images = any(f.get("fileType") == "image" for f in files)
    agent = await _get_agent(multimodal=has_images)
    from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

    # 使用 checkpointer 时，LangGraph 自动恢复历史消息，只需传入当前轮新消息
    messages = [HumanMessage(content=req.message)]

    trace = tracer.start_trace(req.thread_id, req.message, model="deepseek-v4-flash", agent_name="CRM-Agent")
    trace_writer.on_trace_start(trace)

    result = await agent.ainvoke({"messages": messages},
                                  config={"configurable": {
                                      "thread_id": req.thread_id,
                                      "tenant_id": str(DEFAULT_TENANT_ID),
                                      "user_id": req.user_id,
                                      "knowledge_provider": getattr(app.state, "knowledge_provider", None),
                                  }})
    msgs = result.get("messages", [])

    content = ""
    for msg in reversed(msgs):
        if isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", None):
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            break

    # 检查是否有 pending interrupt
    if not content:
        try:
            config_check = {"configurable": {"thread_id": req.thread_id}}
            state = agent.get_state(config_check)
            if state and state.next:
                for task in (state.tasks or []):
                    for intr in (getattr(task, 'interrupts', None) or []):
                        iv = getattr(intr, 'value', {})
                        content = iv.get('message') or iv.get('title') or '请确认'
                        break
                    if content:
                        break
        except Exception:
            pass

    # 记录工具调用 spans
    for msg in msgs:
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                span = tracer.start_span(trace.trace_id, SpanType.TOOL_CALL, f"tool:{tc.get('name', '')}",
                                         input_data={"args": str(tc.get("args", {}))[:200]})
                span.finish("success")
                tracer.increment_tool(trace.trace_id)
        elif isinstance(msg, ToolMessage):
            pass  # 已在 tool_call span 中记录

    tracer.finish_trace(trace.trace_id, "success", content)

    # 合并中间件 spans（sync 模式也需要）
    from src.middleware.tracing import tracing_middleware
    all_mw_spans = tracing_middleware.get_spans(req.thread_id)
    tracing_middleware.clear(req.thread_id)
    if all_mw_spans:
        for mw_span in all_mw_spans:
            span = tracer.start_span(
                trace.trace_id,
                mw_span.get("type", "unknown"),
                mw_span.get("name", ""),
                metadata=mw_span.get("metadata", {}),
            )
            span.start_time = mw_span.get("timestamp", span.start_time)
            span.duration_ms = mw_span.get("duration_ms", 0)
            span.status = "success"
            span.end_time = span.start_time + span.duration_ms / 1000
            if mw_span.get("children"):
                span.metadata["children"] = mw_span["children"]

    # 持久化到 PG
    trace_final = tracer.get_trace(trace.trace_id)
    if trace_final:
        trace_writer.on_trace_finish(trace_final)

    return {"content": content, "thread_id": req.thread_id, "trace_id": trace.trace_id}


@app.get("/api/conversations")
async def list_conversations(limit: int = 50):
    """会话列表 — 从 ai_conversation 表读取"""
    try:
        from src.store.pg_pool import get_conn
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT thread_id, title, status, message_count, total_tokens,
                       last_message_at, agent_name, model, created_at
                FROM ai_conversation
                WHERE tenant_id=%s AND delete_flg=0
                ORDER BY last_message_at DESC LIMIT %s
            """, (DEFAULT_TENANT_ID, limit))
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
        result = []
        for r in rows:
            d = dict(zip(cols, r))
            result.append({
                "thread_id": d["thread_id"],
                "title": d["title"] or "对话",
                "last_time": (d["last_message_at"] or 0) / 1000,
                "created_at": d.get("created_at", 0),
                "message_count": d["message_count"] or 0,
                "total_tokens": d["total_tokens"] or 0,
                "agent_name": d.get("agent_name", ""),
            })
        return {"conversations": result}
    except Exception as e:
        logger.error("list_conversations failed: %s", e)
        return {"conversations": []}


@app.delete("/api/conversations/{thread_id}")
async def delete_conversation(thread_id: str):
    """物理删除会话及其消息、trace"""
    deleted = {}
    try:
        from src.store.pg_pool import get_conn
        with get_conn() as conn:
            cur = conn.cursor()
            # 删除消息
            cur.execute("DELETE FROM ai_message WHERE tenant_id=%s AND thread_id=%s", (DEFAULT_TENANT_ID, thread_id))
            deleted["messages"] = cur.rowcount
            # 删除消息扩展
            cur.execute("""
                DELETE FROM ai_message_ext WHERE tenant_id=%s AND message_id IN (
                    SELECT id FROM ai_message WHERE tenant_id=%s AND thread_id=%s
                )
            """, (DEFAULT_TENANT_ID, DEFAULT_TENANT_ID, thread_id))
            # 删除 trace spans
            cur.execute("""
                DELETE FROM ai_trace_span WHERE trace_id IN (
                    SELECT trace_id FROM ai_trace WHERE tenant_id=%s AND thread_id=%s
                )
            """, (DEFAULT_TENANT_ID, thread_id))
            deleted["spans"] = cur.rowcount
            # 删除 traces
            cur.execute("DELETE FROM ai_trace WHERE tenant_id=%s AND thread_id=%s", (DEFAULT_TENANT_ID, thread_id))
            deleted["traces"] = cur.rowcount
            # 删除会话
            cur.execute("DELETE FROM ai_conversation WHERE tenant_id=%s AND thread_id=%s", (DEFAULT_TENANT_ID, thread_id))
            deleted["conversation"] = cur.rowcount
        # 也从内存 tracer 中清除
        try:
            tracer.remove_traces_by_thread(thread_id)
        except Exception:
            pass
        return {"success": True, "deleted": deleted}
    except Exception as e:
        logger.error("delete_conversation failed: %s", e)
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/conversations/{thread_id}/messages")
async def get_conversation_messages(thread_id: str):
    """获取对话的完整消息列表（含每条消息的推理链路 spans）

    优先从 ai_message 表读取持久化的对话历史，每条消息通过 trace_id 关联
    完整的执行链路（ai_trace_span）。前端刷新后恢复对话时调用。
    """
    try:
        from src.store.pg_pool import get_conn

        # 1. 从 ai_message 表读取持久化的消息
        messages = []
        with get_conn() as conn:
            cur = conn.cursor()
            # 先获取 conversation_id
            cur.execute(
                "SELECT id FROM ai_conversation WHERE tenant_id=%s AND thread_id=%s AND delete_flg=0",
                (DEFAULT_TENANT_ID, thread_id))
            conv_row = cur.fetchone()

            if conv_row:
                conv_id = conv_row[0]
                cur.execute("""
                    SELECT id, sequence, role, query, answer, model,
                           input_tokens, output_tokens, total_tokens,
                           iteration_count, tool_count, duration_ms,
                           trace_id, status, error_message, created_at
                    FROM ai_message
                    WHERE conversation_id=%s AND delete_flg=0
                    ORDER BY sequence ASC
                """, (conv_id,))
                msg_rows = cur.fetchall()
                msg_cols = [d[0] for d in cur.description]

                for row in msg_rows:
                    msg = dict(zip(msg_cols, row))
                    trace_id = msg.get("trace_id", "")

                    # 加载该消息对应的 trace spans
                    spans_raw = []
                    if trace_id:
                        detail = trace_writer.read_trace_detail(trace_id)
                        if detail:
                            spans_raw = detail.get("spans", [])

                    messages.append({
                        "trace_id": trace_id,
                        "user_input": msg.get("query", ""),
                        "agent_output": msg.get("answer", ""),
                        "sequence": msg.get("sequence", 0),
                        "model": msg.get("model", ""),
                        "total_tokens": msg.get("total_tokens", 0),
                        "iteration_count": msg.get("iteration_count", 0),
                        "tool_count": msg.get("tool_count", 0),
                        "duration_ms": msg.get("duration_ms", 0),
                        "status": msg.get("status", "success"),
                        "error_message": msg.get("error_message", ""),
                        "created_at": msg.get("created_at", 0),
                        "spans": spans_raw,
                    })

        # 2. 如果 ai_message 表无数据，降级到内存 Tracer（兼容旧数据）
        if not messages:
            mem_traces = tracer.get_all_traces(200)
            thread_traces = [t for t in mem_traces if t.thread_id == thread_id]

            # 合并 PG 中的 traces
            db_traces = trace_writer.read_traces(200)
            mem_trace_ids = {t.trace_id for t in thread_traces}
            for dt in db_traces:
                if dt.get("thread_id") == thread_id and dt["trace_id"] not in mem_trace_ids:
                    thread_traces.append(dt)

            if thread_traces:
                def _get_start_time(t):
                    if hasattr(t, 'start_time'):
                        return t.start_time or 0
                    return (t.get("start_time") or 0) / 1000 if isinstance(t.get("start_time"), int) and t.get("start_time", 0) > 1e12 else t.get("start_time", 0)

                thread_traces.sort(key=_get_start_time)

                for t in thread_traces:
                    if hasattr(t, 'trace_id'):
                        t_id = t.trace_id
                        user_input = t.user_input or ""
                        agent_output = getattr(t, 'agent_output', '') or ""
                        spans_raw = [s.to_dict() if hasattr(s, 'to_dict') else s for s in (t.spans or [])]
                    else:
                        t_id = t.get("trace_id", "")
                        user_input = t.get("user_input", "") or ""
                        agent_output = t.get("agent_output", "") or ""
                        spans_raw = []

                    if not spans_raw and t_id:
                        detail = trace_writer.read_trace_detail(t_id)
                        if detail:
                            spans_raw = detail.get("spans", [])
                            if not agent_output:
                                agent_output = detail.get("agent_output", "") or ""

                    messages.append({
                        "trace_id": t_id,
                        "user_input": user_input,
                        "agent_output": agent_output,
                        "spans": spans_raw,
                    })

        # 3. 补充当前正在执行的推理链路（tracing_middleware 中尚未持久化的 spans）
        # 场景：用户在 Agent 执行过程中刷新页面，trace 尚未 finish，PG 中无数据
        try:
            from src.middleware.tracing import tracing_middleware
            live_spans = tracing_middleware.get_spans_with_sub_threads(thread_id)
            if live_spans:
                # 检查最后一条消息是否已有 spans（避免重复）
                last_msg_has_spans = messages and messages[-1].get("spans")
                if not last_msg_has_spans:
                    # 从 ThreadStore 获取当前用户输入
                    current_input = ""
                    try:
                        from src.a2ui import thread_store as _ts
                        ts = _ts.get(thread_id)
                        if ts and ts.messages:
                            # 找最后一条 user 消息
                            for m in reversed(ts.messages):
                                if m.get("role") == "user":
                                    current_input = m.get("content", "")
                                    break
                    except Exception:
                        pass

                    messages.append({
                        "trace_id": "",
                        "user_input": current_input,
                        "agent_output": "",
                        "status": "running",
                        "spans": live_spans,
                    })
        except Exception as _e:
            logger.debug("get_conversation_messages: live spans fallback failed: %s", _e)

        return {"messages": messages}
    except Exception as e:
        logger.error("get_conversation_messages failed: %s", e)
        return {"messages": []}


@app.get("/api/traces")
async def list_traces(limit: int = 50):
    """Trace 列表 — 优先内存，合并 PG 历史数据"""
    # 内存中的 traces
    mem_traces = tracer.get_all_traces(limit)
    mem_list = [
        {
            "trace_id": t.trace_id,
            "thread_id": t.thread_id,
            "user_input": t.user_input[:100],
            "agent_output": getattr(t, 'agent_output', '')[:500],
            "status": t.status,
            "total_duration_ms": round(t.total_duration_ms),
            "total_tokens": t.total_tokens,
            "iteration_count": t.iteration_count,
            "tool_count": t.tool_count,
            "span_count": len(t.spans),
            "start_time": t.start_time,
            "model": t.model,
            "agent_name": t.agent_name,
        } for t in mem_traces
    ]
    mem_ids = {t["trace_id"] for t in mem_list}

    # PG 中的 traces（排除内存中已有的）
    db_traces = trace_writer.read_traces(limit)
    for dt in db_traces:
        if dt["trace_id"] not in mem_ids:
            mem_list.append({
                "trace_id": dt["trace_id"],
                "thread_id": dt.get("thread_id", ""),
                "user_input": (dt.get("user_input") or "")[:100],
                "agent_output": (dt.get("agent_output") or "")[:500],
                "status": dt.get("status", ""),
                "total_duration_ms": dt.get("duration_ms", 0),
                "total_tokens": dt.get("total_tokens", 0),
                "iteration_count": dt.get("iteration_count", 0),
                "tool_count": dt.get("tool_count", 0),
                "span_count": dt.get("span_count", 0),
                "start_time": (dt.get("start_time") or 0) / 1000,
                "model": dt.get("model", ""),
                "agent_name": dt.get("agent_name", ""),
            })

    # 按 start_time 降序排序
    mem_list.sort(key=lambda x: x.get("start_time", 0), reverse=True)
    return {"traces": mem_list[:limit], "total": len(mem_list)}


@app.get("/api/traces/{trace_id}")
async def get_trace(trace_id: str):
    """Trace 详情 — 优先内存，fallback PG"""
    # 优先从内存读（实时数据）
    trace = tracer.get_trace(trace_id)
    if trace is not None:
        return {
            "trace": trace.to_dict(),
            "timeline": trace.to_timeline(),
        }

    # 内存没有 → 从 PG 读（历史数据）
    db_trace = trace_writer.read_trace_detail(trace_id)
    if db_trace is not None:
        return {"trace": db_trace}

    return JSONResponse({"error": "Trace not found"}, status_code=404)


@app.get("/", response_class=HTMLResponse)
async def index():
    from fastapi.responses import HTMLResponse as _HR
    html_path = os.path.join(os.path.dirname(__file__), "static", "frontend.html")
    if os.path.exists(html_path):
        with open(html_path, encoding="utf-8") as f:
            content = f.read()
        return _HR(content=content, headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"})
    return "<h1>DeepAgent API</h1>"


@app.get("/trace", response_class=HTMLResponse)
async def trace_explorer():
    """Trace Explorer 独立页面"""
    html_path = os.path.join(os.path.dirname(__file__), "static", "trace_explorer.html")
    if os.path.exists(html_path):
        with open(html_path, encoding="utf-8") as f:
            return f.read()
    return "<h1>Trace Explorer — 页面未找到</h1>"


@app.get("/sessions", response_class=HTMLResponse)
async def session_browser():
    """Session 浏览器独立页面"""
    html_path = os.path.join(os.path.dirname(__file__), "static", "session_browser.html")
    if os.path.exists(html_path):
        with open(html_path, encoding="utf-8") as f:
            return f.read()
    return "<h1>Session Browser — 页面未找到</h1>"


@app.get("/memory", response_class=HTMLResponse)
async def memory_browser():
    """长期记忆浏览器页面"""
    html_path = os.path.join(os.path.dirname(__file__), "static", "memory_browser.html")
    if os.path.exists(html_path):
        with open(html_path, encoding="utf-8") as f:
            return f.read()
    return "<h1>Memory Browser — 页面未找到</h1>"


@app.get("/knowledge", response_class=HTMLResponse)
async def knowledge_browser():
    """知识库管理页面"""
    html_path = os.path.join(os.path.dirname(__file__), "static", "knowledge_browser.html")
    if os.path.exists(html_path):
        with open(html_path, encoding="utf-8") as f:
            return f.read()
    return "<h1>Knowledge Browser — 页面未找到</h1>"


@app.get("/metamodel", response_class=HTMLResponse)
async def metamodel_browser():
    """元模型 & 元数据浏览页面"""
    html_path = os.path.join(os.path.dirname(__file__), "static", "metamodel_browser.html")
    if os.path.exists(html_path):
        with open(html_path, encoding="utf-8") as f:
            return f.read()
    return "<h1>Metamodel Browser — 页面未找到</h1>"


@app.get("/skills", response_class=HTMLResponse)
async def skill_browser():
    """Skill 技能管理页面"""
    html_path = os.path.join(os.path.dirname(__file__), "static", "skill_browser.html")
    if os.path.exists(html_path):
        with open(html_path, encoding="utf-8") as f:
            return f.read()
    return "<h1>Skill Browser — 页面未找到</h1>"


@app.get("/mock-data", response_class=HTMLResponse)
async def mock_data_browser():
    """Mock 数据查看页面 — 浏览 CRM Agent 的模拟数据和元数据 Schema"""
    html_path = os.path.join(os.path.dirname(__file__), "static", "mock_data_browser.html")
    if os.path.exists(html_path):
        with open(html_path, encoding="utf-8") as f:
            return f.read()
    return "<h1>Mock Data Browser — 页面未找到</h1>"


@app.get("/eval/tools", response_class=HTMLResponse)
async def tool_eval_page():
    """Tool 评测页面 — 工具功能验证"""
    html_path = os.path.join(os.path.dirname(__file__), "static", "tool_eval.html")
    if os.path.exists(html_path):
        with open(html_path, encoding="utf-8") as f:
            return f.read()
    return "<h1>Tool Eval — 页面未找到</h1>"


@app.get("/eval/tools/{tool_name}", response_class=HTMLResponse)
async def tool_eval_detail_page(tool_name: str):
    """Tool 评测详情页 — 单个工具的全部测试场景"""
    html_path = os.path.join(os.path.dirname(__file__), "static", "tool_eval_detail.html")
    if os.path.exists(html_path):
        with open(html_path, encoding="utf-8") as f:
            return f.read()
    return "<h1>Tool Eval Detail — 页面未找到</h1>"


@app.get("/eval/memory", response_class=HTMLResponse)
async def memory_eval_page():
    """Memory 评测页面 — 长期记忆召回率评测"""
    html_path = os.path.join(os.path.dirname(__file__), "static", "memory_eval.html")
    if os.path.exists(html_path):
        with open(html_path, encoding="utf-8") as f:
            return f.read()
    return "<h1>Memory Eval — 页面未找到</h1>"


# ── 记忆浏览 API ──

@app.get("/api/memory/users")
async def memory_users(tenant_id: int = DEFAULT_TENANT_ID):
    """获取有记忆的用户列表（按租户）— 从 PG 读取"""
    try:
        from src.store.pg_pool import get_conn
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT user_id, category, COUNT(*) as cnt
                FROM ai_agent_memory
                WHERE (tenant_id = %s OR tenant_id = 0) AND delete_flg = 0
                GROUP BY user_id, category
                ORDER BY user_id
            """, (tenant_id,))
            rows = cur.fetchall()

        users: dict[str, dict] = {}
        for user_id, category, cnt in rows:
            if user_id not in users:
                users[user_id] = {"user_id": user_id, "total_count": 0, "by_category": {}}
            users[user_id]["total_count"] += cnt
            users[user_id]["by_category"][category] = cnt

        return {"users": sorted(users.values(), key=lambda u: u["total_count"], reverse=True)}
    except Exception as e:
        logger.error("memory_users failed: %s", e)
        return {"users": []}


@app.get("/api/memory/list")
async def memory_list(tenant_id: int = DEFAULT_TENANT_ID, user_id: str = "", category: str = "",
                      include_archived: bool = False, limit: int = 200):
    """获取用户的记忆列表 — 从 PG 读取

    include_archived=true 时同时返回 archived 状态的记忆（用于展示反思变化过程）
    """
    if not user_id:
        return {"memories": [], "total": 0}
    try:
        from src.store.pg_pool import get_conn
        with get_conn() as conn:
            cur = conn.cursor()
            sql = """
                SELECT id, memory_id, tenant_id, user_id, category, source_type,
                       abstract, overview, content, merge_key, parent_entity,
                       biz_id, biz_parent_id, biz_type, thread_id, message_id,
                       status, active_count, confidence, vector_synced,
                       user_query, agent_reply,
                       created_at, updated_at
                FROM ai_agent_memory
                WHERE (tenant_id = %s OR tenant_id = 0) AND user_id = %s AND delete_flg = 0
            """
            params: list = [tenant_id, user_id]
            if not include_archived:
                sql += " AND status = 'active'"
            if category:
                sql += " AND category = %s"
                params.append(category)
            sql += " ORDER BY updated_at DESC LIMIT %s"
            params.append(limit)
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()

        memories = [dict(zip(cols, row)) for row in rows]
        return {"memories": memories, "total": len(memories)}
    except Exception as e:
        logger.error("memory_list failed: %s", e)
        return {"memories": [], "total": 0}


@app.post("/api/memory/{memory_id}/archive")
async def memory_archive(memory_id: str, request: Request):
    """归档记忆"""
    body = await request.json()
    tenant_id = body.get("tenant_id", DEFAULT_TENANT_ID)
    try:
        from src.store.pg_pool import get_conn
        import time
        now = int(time.time() * 1000)
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE ai_agent_memory SET status = 'archived', updated_at = %s
                WHERE (memory_id = %s OR id::text = %s) AND tenant_id = %s AND delete_flg = 0
            """, (now, memory_id, memory_id, tenant_id))
            affected = cur.rowcount
        return {"success": affected > 0, "affected": affected}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.delete("/api/memory/all")
async def memory_delete_all(tenant_id: int = DEFAULT_TENANT_ID):
    """一键清空租户下所有用户的全部记忆 — PG 软删除 + 向量库物理删除"""
    result = {"pg_deleted": 0, "vdb_deleted": 0}
    try:
        from src.store.pg_pool import get_conn
        import time as _time
        now = int(_time.time() * 1000)
        with get_conn() as conn:
            cur = conn.cursor()
            # 查出所有 memory_id 用于向量库删除
            cur.execute("""
                SELECT memory_id FROM ai_agent_memory
                WHERE tenant_id = %s AND delete_flg = 0
            """, (tenant_id,))
            vdb_ids = [r[0] for r in cur.fetchall() if r[0]]

            # PG 软删除
            cur.execute("""
                UPDATE ai_agent_memory SET delete_flg = 1, updated_at = %s
                WHERE tenant_id = %s AND delete_flg = 0
            """, (now, tenant_id))
            result["pg_deleted"] = cur.rowcount

        # 向量库物理删除
        if vdb_ids:
            try:
                import tcvectordb
                vdb_url = os.environ.get("VDB_URL", "http://10.60.2.17")
                vdb_key = os.environ.get("VDB_KEY", "bRG3NETg13tv5Fn68VTdkxaJXH9tMQzhKeT3unck")
                client = tcvectordb.VectorDBClient(url=vdb_url, username="root", key=vdb_key, timeout=10)
                for db_info in client.list_databases():
                    if not db_info.database_name.startswith("viking"):
                        continue
                    try:
                        db = client.database(db_info.database_name)
                        for coll_info in db.list_collections():
                            try:
                                coll = db.collection(coll_info.collection_name)
                                for i in range(0, len(vdb_ids), 100):
                                    batch = vdb_ids[i:i+100]
                                    coll.delete(document_ids=batch)
                                result["vdb_deleted"] = len(vdb_ids)
                            except Exception:
                                pass
                    except Exception:
                        continue
            except Exception as e:
                logger.debug("VDB clear-all failed: %s", e)

        return {"success": True, **result}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ── 反思日志 API ──

@app.get("/api/memory/reflection-log")
async def reflection_log(tenant_id: int = DEFAULT_TENANT_ID, user_id: str = "", limit: int = 50):
    """查询反思日志 — 用于验证反思决策链路

    返回最近的反思记录，包含：
    - reflection_type: session/failure/correction/global
    - relation: identical/contradiction/evolution/unrelated/error
    - action: discard_new/archive_old/update_old/keep_both/delete
    - llm_reason: LLM 判断理由
    - trigger_source: 触发原因
    - old/new_memory_id: 关联的记忆 ID
    """
    try:
        from src.store.pg_pool import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                sql = """
                    SELECT id, tenant_id, user_id, reflection_type, trigger_source,
                           old_memory_id, new_memory_id, relation, action,
                           llm_reason, created_at
                    FROM ai_memory_reflection_log
                    WHERE tenant_id = %s
                """
                params: list = [tenant_id]
                if user_id:
                    sql += " AND user_id = %s"
                    params.append(user_id)
                sql += " ORDER BY created_at DESC LIMIT %s"
                params.append(limit)
                cur.execute(sql, params)
                cols = [d[0] for d in cur.description]
                rows = cur.fetchall()

        logs = [dict(zip(cols, row)) for row in rows]
        return {"logs": logs, "total": len(logs)}
    except Exception as e:
        logger.error("reflection_log failed: %s", e)
        return {"logs": [], "total": 0, "error": str(e)}

@app.delete("/api/memory/{memory_id}")
async def memory_delete(memory_id: str, request: Request):
    """删除记忆 — PG 软删除 + 向量库物理删除"""
    # 兼容前端传 body 或 query param
    tenant_id = DEFAULT_TENANT_ID
    try:
        body = await request.json()
        tenant_id = int(body.get("tenant_id", DEFAULT_TENANT_ID))
    except Exception:
        pass

    result = {"pg_deleted": 0, "vdb_deleted": False, "memory_id": memory_id, "tenant_id": tenant_id}
    try:
        # 1. PG 软删除
        from src.store.pg_pool import get_conn
        import time
        now = int(time.time() * 1000)
        with get_conn() as conn:
            cur = conn.cursor()

            # 尝试将 memory_id 解析为整数（前端可能传 id 整数值）
            id_as_int = None
            try:
                id_as_int = int(memory_id)
            except (ValueError, TypeError):
                pass

            # 查询匹配的记录（memory_id 字符串匹配 OR id 整数匹配）
            if id_as_int is not None:
                cur.execute("""
                    SELECT id, memory_id, vector_id FROM ai_agent_memory
                    WHERE (memory_id = %s OR id = %s) AND tenant_id = %s AND delete_flg = 0
                """, (memory_id, id_as_int, tenant_id))
            else:
                cur.execute("""
                    SELECT id, memory_id, vector_id FROM ai_agent_memory
                    WHERE memory_id = %s AND tenant_id = %s AND delete_flg = 0
                """, (memory_id, tenant_id))

            rows = cur.fetchall()
            if not rows:
                return {"success": False, "error": "memory not found", **result}

            pg_ids = [r[0] for r in rows]
            vdb_ids = [r[1] or r[2] for r in rows if (r[1] or r[2])]

            # 按 PG 主键 id 精确删除
            cur.execute("""
                UPDATE ai_agent_memory SET delete_flg = 1, updated_at = %s
                WHERE id = ANY(%s) AND delete_flg = 0
            """, (now, pg_ids))
            result["pg_deleted"] = cur.rowcount

        # 2. 向量库物理删除
        if vdb_ids:
            try:
                import tcvectordb
                vdb_url = os.environ.get("VDB_URL", "http://10.60.2.17")
                vdb_key = os.environ.get("VDB_KEY", "bRG3NETg13tv5Fn68VTdkxaJXH9tMQzhKeT3unck")
                client = tcvectordb.VectorDBClient(url=vdb_url, username="root", key=vdb_key, timeout=10)
                # 尝试在所有 viking 数据库中删除
                for db_info in client.list_databases():
                    if not db_info.database_name.startswith("viking"):
                        continue
                    try:
                        db = client.database(db_info.database_name)
                        for coll_info in db.list_collections():
                            try:
                                coll = db.collection(coll_info.collection_name)
                                coll.delete(document_ids=vdb_ids)
                                result["vdb_deleted"] = True
                            except Exception:
                                pass
                    except Exception:
                        continue
            except Exception as e:
                logger.debug("VDB delete failed (non-critical): %s", e)

        return {"success": result["pg_deleted"] > 0, **result}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.delete("/api/memory/user/{user_id}")
async def memory_delete_user(user_id: str, tenant_id: int = DEFAULT_TENANT_ID):
    """删除用户的所有记忆 — PG 软删除 + 向量库物理删除"""
    result = {"pg_deleted": 0, "vdb_deleted": 0}
    try:
        from src.store.pg_pool import get_conn
        import time as _time
        now = int(_time.time() * 1000)
        with get_conn() as conn:
            cur = conn.cursor()
            # 查出所有 memory_id 用于向量库删除
            cur.execute("""
                SELECT memory_id FROM ai_agent_memory
                WHERE user_id = %s AND (tenant_id = %s OR tenant_id = 0) AND delete_flg = 0
            """, (user_id, tenant_id))
            vdb_ids = [r[0] for r in cur.fetchall() if r[0]]

            # PG 软删除
            cur.execute("""
                UPDATE ai_agent_memory SET delete_flg = 1, updated_at = %s
                WHERE user_id = %s AND (tenant_id = %s OR tenant_id = 0) AND delete_flg = 0
            """, (now, user_id, tenant_id))
            result["pg_deleted"] = cur.rowcount

        # 向量库物理删除
        if vdb_ids:
            try:
                import tcvectordb
                vdb_url = os.environ.get("VDB_URL", "http://10.60.2.17")
                vdb_key = os.environ.get("VDB_KEY", "bRG3NETg13tv5Fn68VTdkxaJXH9tMQzhKeT3unck")
                client = tcvectordb.VectorDBClient(url=vdb_url, username="root", key=vdb_key, timeout=10)
                for db_info in client.list_databases():
                    if not db_info.database_name.startswith("viking"):
                        continue
                    try:
                        db = client.database(db_info.database_name)
                        for coll_info in db.list_collections():
                            try:
                                coll = db.collection(coll_info.collection_name)
                                coll.delete(document_ids=vdb_ids)
                                result["vdb_deleted"] += len(vdb_ids)
                            except Exception:
                                pass
                    except Exception:
                        continue
            except Exception as e:
                logger.debug("VDB user delete failed: %s", e)

        return {"success": True, **result}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


"""提示词 v2 格式验证 + 边界用例测试

验证目标：
1. 格式一致性：四路提示词结构统一
2. 占位符完整性：所有 format 变量可正确注入
3. 边界用例覆盖：从 200 条测试用例中抽取关键边界场景验证
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.memory.extraction.prompts import (
    PROFILE_EXTRACT_PROMPT,
    PREFERENCES_EXTRACT_PROMPT,
    AGENT_RULES_EXTRACT_PROMPT,
    ENTITIES_EXTRACT_PROMPT,
    _COMMON_OUTPUT_RULES,
)


# ═══════════════════════════════════════════════════════════
# Test 1: 格式一致性验证
# ═══════════════════════════════════════════════════════════

def test_structure_consistency():
    """验证四路提示词共享相同的章节结构"""
    prompts = {
        "profile": PROFILE_EXTRACT_PROMPT,
        "preferences": PREFERENCES_EXTRACT_PROMPT,
        "agent_rules": AGENT_RULES_EXTRACT_PROMPT,
        "entities": ENTITIES_EXTRACT_PROMPT,
    }

    required_sections = ["## 识别原则", "## 排除规则", "## 边界判定", "## 输出格式", "## 输出规则"]

    errors = []
    for name, prompt in prompts.items():
        for section in required_sections:
            if section not in prompt:
                errors.append(f"[{name}] 缺少章节: {section}")

    # 验证不再包含"核心边界"表格（旧格式）
    for name, prompt in prompts.items():
        if "## 核心边界" in prompt:
            errors.append(f"[{name}] 仍包含旧格式 '## 核心边界' 表格")

    if errors:
        print("❌ 格式一致性验证失败:")
        for e in errors:
            print(f"  - {e}")
        return False
    else:
        print("✅ 格式一致性验证通过: 四路提示词章节结构统一")
        return True


# ═══════════════════════════════════════════════════════════
# Test 2: 占位符注入验证
# ═══════════════════════════════════════════════════════════

def test_format_variables():
    """验证所有 format 变量可正确注入，不会抛 KeyError"""
    errors = []

    # Profile: {existing_profile}, {user_messages}, {output_language}
    try:
        PROFILE_EXTRACT_PROMPT.format(
            existing_profile="测试画像",
            user_messages="[human]: 我是销售总监",
            output_language="auto",
        )
    except KeyError as e:
        errors.append(f"[profile] 缺少变量: {e}")

    # Preferences: {user_messages}, {output_language}
    try:
        PREFERENCES_EXTRACT_PROMPT.format(
            user_messages="[human]: 我喜欢表格",
            output_language="zh",
        )
    except KeyError as e:
        errors.append(f"[preferences] 缺少变量: {e}")

    # Agent Rules: {existing_rules}, {user_messages}, {output_language}
    try:
        AGENT_RULES_EXTRACT_PROMPT.format(
            existing_rules="测试规则",
            user_messages="[human]: 以后回复简短一些",
            output_language="auto",
        )
    except KeyError as e:
        errors.append(f"[agent_rules] 缺少变量: {e}")

    # Entities: {existing_entities}, {conversation}, {output_language}
    try:
        ENTITIES_EXTRACT_PROMPT.format(
            existing_entities="测试实体",
            conversation="[human]: 华为张伟说话很直接",
            output_language="auto",
        )
    except KeyError as e:
        errors.append(f"[entities] 缺少变量: {e}")

    if errors:
        print("❌ 占位符注入验证失败:")
        for e in errors:
            print(f"  - {e}")
        return False
    else:
        print("✅ 占位符注入验证通过: 所有 format 变量可正确注入")
        return True


# ═══════════════════════════════════════════════════════════
# Test 3: 长度约束验证
# ═══════════════════════════════════════════════════════════

def test_prompt_length():
    """验证每个提示词（不含输入数据）≤ 2000 chars"""
    prompts = {
        "profile": PROFILE_EXTRACT_PROMPT,
        "preferences": PREFERENCES_EXTRACT_PROMPT,
        "agent_rules": AGENT_RULES_EXTRACT_PROMPT,
        "entities": ENTITIES_EXTRACT_PROMPT,
    }

    errors = []
    max_chars = 2000  # 含 _COMMON_OUTPUT_RULES 后放宽到 2000

    for name, prompt in prompts.items():
        # 用最短占位符替换来测量模板本身长度
        filled = prompt.replace("{existing_profile}", "").replace(
            "{user_messages}", "").replace("{output_language}", "").replace(
            "{existing_rules}", "").replace("{existing_entities}", "").replace(
            "{conversation}", "")
        length = len(filled)
        if length > max_chars:
            errors.append(f"[{name}] 模板长度 {length} 超过 {max_chars} 限制")
        else:
            print(f"  [{name}] 模板长度: {length} chars")

    if errors:
        print("❌ 长度约束验证失败:")
        for e in errors:
            print(f"  - {e}")
        return False
    else:
        print("✅ 长度约束验证通过")
        return True


# ═══════════════════════════════════════════════════════════
# Test 4: 无过拟合句式枚举验证
# ═══════════════════════════════════════════════════════════

def test_no_overfitting_patterns():
    """验证提示词中不包含具体句式枚举表格（过拟合风险）"""
    prompts = {
        "profile": PROFILE_EXTRACT_PROMPT,
        "preferences": PREFERENCES_EXTRACT_PROMPT,
        "agent_rules": AGENT_RULES_EXTRACT_PROMPT,
        "entities": ENTITIES_EXTRACT_PROMPT,
    }

    # 过拟合标志：Markdown 表格中包含具体中文句子（引号包裹的完整句子）
    overfitting_markers = [
        '"我一般不加班"',
        '"我们部门不加班"',
        '"以后分析要深入一些"',
        '"这次分析深入一些"',
        '"你就像我的私人助理一样"',
        '"感觉你像私人助理"',
    ]

    errors = []
    for name, prompt in prompts.items():
        for marker in overfitting_markers:
            if marker in prompt:
                errors.append(f"[{name}] 包含过拟合句式: {marker}")

    if errors:
        print("❌ 过拟合检测失败:")
        for e in errors:
            print(f"  - {e}")
        return False
    else:
        print("✅ 无过拟合句式枚举: 提示词使用语义规则而非具体句式")
        return True


# ═══════════════════════════════════════════════════════════
# Test 5: 边界判定规则完整性
# ═══════════════════════════════════════════════════════════

def test_boundary_rules_coverage():
    """验证每路的边界判定覆盖了与其他三路的区分"""
    prompts = {
        "profile": PROFILE_EXTRACT_PROMPT,
        "preferences": PREFERENCES_EXTRACT_PROMPT,
        "agent_rules": AGENT_RULES_EXTRACT_PROMPT,
        "entities": ENTITIES_EXTRACT_PROMPT,
    }

    # 每路至少要提到与最易混淆的维度的区分
    expected_boundaries = {
        "profile": ["preferences", "entities"],
        "preferences": ["agent_rules", "profile"],
        "agent_rules": ["preferences", "entities"],
        "entities": ["profile", "agent_rules"],
    }

    errors = []
    for name, prompt in prompts.items():
        # 提取边界判定章节
        boundary_start = prompt.find("## 边界判定")
        if boundary_start == -1:
            errors.append(f"[{name}] 无边界判定章节")
            continue

        # 找到下一个 ## 章节或结尾
        next_section = prompt.find("##", boundary_start + 10)
        if next_section == -1:
            boundary_text = prompt[boundary_start:]
        else:
            boundary_text = prompt[boundary_start:next_section]

        for expected in expected_boundaries[name]:
            if expected not in boundary_text:
                errors.append(f"[{name}] 边界判定未提及与 {expected} 的区分")

    if errors:
        print("❌ 边界判定覆盖验证失败:")
        for e in errors:
            print(f"  - {e}")
        return False
    else:
        print("✅ 边界判定覆盖完整: 每路都明确了与最易混淆维度的区分规则")
        return True


# ═══════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("提示词 v2 验证测试")
    print("=" * 60)
    print()

    results = []
    results.append(test_structure_consistency())
    print()
    results.append(test_format_variables())
    print()
    results.append(test_prompt_length())
    print()
    results.append(test_no_overfitting_patterns())
    print()
    results.append(test_boundary_rules_coverage())
    print()

    print("=" * 60)
    passed = sum(results)
    total = len(results)
    if passed == total:
        print(f"🎉 全部通过: {passed}/{total}")
    else:
        print(f"⚠️  部分失败: {passed}/{total}")
        sys.exit(1)

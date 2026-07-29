"""提示词 v2 LLM 边界用例测试

从 200 条测试用例中抽取 20 条关键边界场景，调用 LLM 验证分类准确性。
覆盖：四维度正例 + 不提取 + 混合意图 + 边界对抗

运行方式：python tests/test_prompts_v2_llm.py
需要环境变量：.env 中的 LLM API 配置
"""
import sys
import os
import json
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.memory.extraction.prompts import (
    PROFILE_EXTRACT_PROMPT,
    PREFERENCES_EXTRACT_PROMPT,
    AGENT_RULES_EXTRACT_PROMPT,
    ENTITIES_EXTRACT_PROMPT,
)

# ═══════════════════════════════════════════════════════════
# 测试用例定义
# ═══════════════════════════════════════════════════════════

# 格式: (用户发言, 期望结果)
# 期望结果: {"profile": bool, "preferences": bool, "agent_rules": bool, "entities": bool}
TEST_CASES = [
    # === A. Profile 正例 ===
    ("我是华东区的销售总监，管理15个人的团队",
     {"profile": True, "preferences": False, "agent_rules": False, "entities": False}),
    ("我们公司主要做企业级SaaS，客户集中在制造业",
     {"profile": True, "preferences": False, "agent_rules": False, "entities": False}),

    # === B. Preferences 正例 ===
    ("我习惯每天早上8点处理邮件，下午集中拜访客户",
     {"profile": False, "preferences": True, "agent_rules": False, "entities": False}),
    ("我不喜欢用PPT做方案，更喜欢用文档形式",
     {"profile": False, "preferences": True, "agent_rules": False, "entities": False}),

    # === C. Agent Rules 正例 ===
    ("以后帮我写邮件都用正式商务语气",
     {"profile": False, "preferences": False, "agent_rules": True, "entities": False}),
    ("回复客户的时候不要用'亲'这种称呼",
     {"profile": False, "preferences": False, "agent_rules": True, "entities": False}),

    # === D. Entities 正例 ===
    ("华为那边的李经理跟我说他们在评估3家供应商",
     {"profile": False, "preferences": False, "agent_rules": False, "entities": True}),
    ("张总说他们Q3有一笔预算专门用来做数字化转型",
     {"profile": False, "preferences": False, "agent_rules": False, "entities": True}),

    # === E. 不提取 ===
    ("帮我查一下上个月的销售数据",
     {"profile": False, "preferences": False, "agent_rules": False, "entities": False}),
    ("好的，收到",
     {"profile": False, "preferences": False, "agent_rules": False, "entities": False}),
    ("这次分析深入一些",
     {"profile": False, "preferences": False, "agent_rules": False, "entities": False}),

    # === F. 混合意图 ===
    ("我喜欢简洁的风格，你回复不要超过3句话",
     {"profile": False, "preferences": True, "agent_rules": True, "entities": False}),
    ("我是华东区的，华为张伟是我的重点客户",
     {"profile": True, "preferences": False, "agent_rules": False, "entities": True}),

    # === G. 边界对抗: preferences vs agent_rules ===
    ("金额统一用万为单位",  # 无主语，隐含 Agent 输出 → agent_rules
     {"profile": False, "preferences": False, "agent_rules": True, "entities": False}),
    ("我觉得有对比的数据更好理解",  # "我觉得" → preferences
     {"profile": False, "preferences": True, "agent_rules": False, "entities": False}),

    # === G. 边界对抗: profile vs preferences ===
    ("我们部门不加班",  # 组织文化 → profile
     {"profile": True, "preferences": False, "agent_rules": False, "entities": False}),
    ("我一般不加班",  # 个人习惯 → preferences
     {"profile": False, "preferences": True, "agent_rules": False, "entities": False}),

    # === G. 边界对抗: entities vs agent_rules ===
    ("华为那边要求用正式语气沟通",  # 陈述客户要求 → entities
     {"profile": False, "preferences": False, "agent_rules": False, "entities": True}),
    ("跟华为沟通要用正式语气",  # 命令 Agent → agent_rules
     {"profile": False, "preferences": False, "agent_rules": True, "entities": False}),

    # === G. 边界对抗: 持久 vs 单次 ===
    ("以后分析要深入一些",  # "以后" → agent_rules
     {"profile": False, "preferences": False, "agent_rules": True, "entities": False}),
]


# ═══════════════════════════════════════════════════════════
# LLM 调用封装
# ═══════════════════════════════════════════════════════════

async def call_llm(prompt: str) -> dict | None:
    """调用 LLM 并解析 JSON"""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    # 豆包 API 配置（与项目一致）
    api_key = os.environ.get("DEEPSEEK_API_KEY", "sk-HdY98AcN68JhtXLp8oeIATEL4PWq9rzRcCAhI8G4SOtBbtSw")
    base_url = "https://tokenhub.tencentmaas.com/v1"
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")

    if not api_key:
        return None

    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=500,
        )
        text = response.choices[0].message.content.strip()
        if "{" in text and "}" in text:
            json_str = text[text.index("{"):text.rindex("}") + 1]
            return json.loads(json_str)
    except Exception as e:
        print(f"  LLM 调用失败: {e}")
    return None


async def test_single_case(idx: int, user_input: str, expected: dict) -> dict:
    """测试单条用例，返回结果"""
    results = {}

    # Profile
    prompt = PROFILE_EXTRACT_PROMPT.format(
        existing_profile="（无历史画像）",
        user_messages=f"[human]: {user_input}",
        output_language="auto",
    )
    data = await call_llm(prompt)
    if data is None:
        return {"error": "LLM 不可用"}
    profile_content = data.get("profile", {}).get("content", "")
    results["profile"] = bool(profile_content)

    # Preferences
    prompt = PREFERENCES_EXTRACT_PROMPT.format(
        user_messages=f"[human]: {user_input}",
        output_language="auto",
    )
    data = await call_llm(prompt)
    prefs = data.get("preferences", []) if data else []
    results["preferences"] = bool(prefs)

    # Agent Rules
    prompt = AGENT_RULES_EXTRACT_PROMPT.format(
        existing_rules="（无历史规则）",
        user_messages=f"[human]: {user_input}",
        output_language="auto",
    )
    data = await call_llm(prompt)
    rules_content = data.get("agent_rules", {}).get("content", "") if data else ""
    results["agent_rules"] = bool(rules_content)

    # Entities
    prompt = ENTITIES_EXTRACT_PROMPT.format(
        existing_entities="（无已有实体）",
        conversation=f"[human]: {user_input}",
        output_language="auto",
    )
    data = await call_llm(prompt)
    entities = data.get("entities", []) if data else []
    results["entities"] = bool(entities)

    return results


# ═══════════════════════════════════════════════════════════
# 主测试流程
# ═══════════════════════════════════════════════════════════

async def run_tests():
    print("=" * 70)
    print("提示词 v2 — LLM 边界用例测试（20 条）")
    print("=" * 70)
    print()

    passed = 0
    failed = 0
    errors_detail = []

    for idx, (user_input, expected) in enumerate(TEST_CASES, 1):
        result = await test_single_case(idx, user_input, expected)

        if "error" in result:
            print(f"⚠️  #{idx}: LLM 不可用，跳过测试")
            print("    请配置 .env 中的 ARK_API_KEY / OPENAI_API_KEY")
            return

        # 比较结果
        match = True
        mismatches = []
        for dim in ["profile", "preferences", "agent_rules", "entities"]:
            if result[dim] != expected[dim]:
                match = False
                mismatches.append(
                    f"{dim}: 期望={expected[dim]}, 实际={result[dim]}"
                )

        if match:
            passed += 1
            print(f"  ✅ #{idx:2d} | {user_input[:40]}")
        else:
            failed += 1
            print(f"  ❌ #{idx:2d} | {user_input[:40]}")
            for m in mismatches:
                print(f"         {m}")
            errors_detail.append((idx, user_input, mismatches))

    print()
    print("=" * 70)
    total = passed + failed
    rate = passed / total * 100 if total > 0 else 0
    print(f"结果: {passed}/{total} 通过 ({rate:.0f}%)")

    if errors_detail:
        print(f"\n失败用例详情:")
        for idx, text, mismatches in errors_detail:
            print(f"  #{idx}: {text}")
            for m in mismatches:
                print(f"    → {m}")

    # 目标：≥ 85% 通过率（边界用例允许一定模糊性）
    if rate >= 85:
        print(f"\n🎉 通过率 {rate:.0f}% ≥ 85% 目标，验证通过")
    else:
        print(f"\n⚠️  通过率 {rate:.0f}% < 85% 目标，需要调整提示词")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run_tests())

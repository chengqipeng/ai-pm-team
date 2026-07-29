"""提示词 v2 快速验证 — 只测之前失败的边界用例"""
import sys, os, json, asyncio
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.memory.extraction.prompts import (
    PROFILE_EXTRACT_PROMPT, PREFERENCES_EXTRACT_PROMPT,
    AGENT_RULES_EXTRACT_PROMPT, ENTITIES_EXTRACT_PROMPT,
)

# 之前失败的 4 条 + 补充的关键边界
TEST_CASES = [
    # #5 之前失败：实际上是混合意图（偏好正式 + Agent 行为约束）
    ("以后帮我写邮件都用正式商务语气",
     {"profile": False, "preferences": "any", "agent_rules": True, "entities": False},
     "Agent 行为约束必须命中，preferences 可选（正式语气可解读为偏好）"),

    # #6 之前失败：实际上是混合意图（厌恶"亲" + Agent 回复约束）
    ("回复客户的时候不要用'亲'这种称呼",
     {"profile": False, "preferences": True, "agent_rules": True, "entities": False},
     "混合：厌恶'亲'称呼 + Agent 回复约束"),

    # #14 之前失败：已修复，纯 Agent 格式指令
    ("金额统一用万为单位",
     {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
     "省略主语的 Agent 输出格式指令"),

    # #18 之前失败：陈述第三方要求（可能同时触发 agent_rules 作为隐含行为指导）
    ("华为那边要求用正式语气沟通",
     {"profile": False, "preferences": False, "agent_rules": "any", "entities": True},
     "陈述第三方要求 → entities 必须命中，agent_rules 可选"),

    # 补充：混合意图确认
    ("我喜欢简洁，你回复不超过3句",
     {"profile": False, "preferences": True, "agent_rules": True, "entities": False},
     "混合：偏好简洁 + Agent 字数约束"),

    # 补充：持久 vs 单次
    ("以后分析要深入一些",
     {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
     "以后 = 持久 → agent_rules"),

    # 补充：纯 entities 不触发 agent_rules
    ("张总说他们公司明年要上市",
     {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
     "纯第三方事实陈述"),

    # 补充：纯 preferences 不触发 agent_rules
    ("我习惯每天早上先看数据看板",
     {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
     "纯个人习惯"),
]


async def call_llm(prompt: str) -> dict | None:
    api_key = os.environ.get("DEEPSEEK_API_KEY", "sk-HdY98AcN68JhtXLp8oeIATEL4PWq9rzRcCAhI8G4SOtBbtSw")
    base_url = "https://tokenhub.tencentmaas.com/v1"
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        response = await client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": prompt}],
            temperature=0, max_tokens=500,
        )
        text = response.choices[0].message.content.strip()
        if "{" in text and "}" in text:
            json_str = text[text.index("{"):text.rindex("}") + 1]
            return json.loads(json_str)
    except Exception as e:
        print(f"  LLM error: {e}")
    return None


async def test_case(user_input: str) -> dict:
    results = {}

    # Profile
    p = PROFILE_EXTRACT_PROMPT.format(existing_profile="（无）", user_messages=f"[human]: {user_input}", output_language="auto")
    d = await call_llm(p)
    results["profile"] = bool(d.get("profile", {}).get("content", "")) if d else False

    # Preferences
    p = PREFERENCES_EXTRACT_PROMPT.format(user_messages=f"[human]: {user_input}", output_language="auto")
    d = await call_llm(p)
    results["preferences"] = bool(d.get("preferences", [])) if d else False

    # Agent Rules
    p = AGENT_RULES_EXTRACT_PROMPT.format(existing_rules="（无）", user_messages=f"[human]: {user_input}", output_language="auto")
    d = await call_llm(p)
    results["agent_rules"] = bool(d.get("agent_rules", {}).get("content", "")) if d else False

    # Entities
    p = ENTITIES_EXTRACT_PROMPT.format(existing_entities="（无）", conversation=f"[human]: {user_input}", output_language="auto")
    d = await call_llm(p)
    results["entities"] = bool(d.get("entities", [])) if d else False

    return results


async def main():
    print("=" * 60)
    print("提示词 v2 — 边界修复验证（6 条关键用例）")
    print("=" * 60)

    passed = failed = 0
    for idx, (text, expected, desc) in enumerate(TEST_CASES, 1):
        result = await test_case(text)
        if "error" in str(result):
            print(f"⚠️  LLM 不可用"); return

        match = all(
            expected[d] == "any" or result[d] == expected[d]
            for d in ["profile", "preferences", "agent_rules", "entities"]
        )
        if match:
            passed += 1
            print(f"  ✅ #{idx} | {text[:35]} — {desc}")
        else:
            failed += 1
            print(f"  ❌ #{idx} | {text[:35]} — {desc}")
            for d in ["profile", "preferences", "agent_rules", "entities"]:
                if expected[d] != "any" and result[d] != expected[d]:
                    print(f"         {d}: 期望={expected[d]}, 实际={result[d]}")

    print(f"\n结果: {passed}/{passed+failed} 通过")
    if failed:
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())

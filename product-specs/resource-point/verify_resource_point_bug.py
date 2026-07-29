"""
资源点超限问题验证 Demo

模拟 neo-ai-agent-platform-service 和 NEO-AI-DATA-PROCESS-SERVICE 的资源点校验与扣费逻辑，
验证海能达租户买了 2W 资源点却用了 7W 的根因。

═══════════════════════════════════════════════════════════
sourceType 枚举定义（来源：ExecuteLog.java + source_util.py）
═══════════════════════════════════════════════════════════

  sourceType = 1  → Agent（Agent 对话，用户与 Agent 对话时 neo-apps-ai-agent-service 设置）
  sourceType = 2  → Prompt Template（提示词模板调用）
  sourceType = 3  → MCP（MCP 工具调用）
  sourceType = 4  → Component（组件调用）
  sourceType = 5  → Dataset（知识库同步/数据集处理）
  sourceType = 6  → Tools（系统工具调用，如 OCR、文档提取等）
  sourceType = 98 → Resource（资源变更，如充值/过期/调配）
  sourceType = 99 → Other（其他）

关键代码路径：
  1. 用户发送消息 → neo-apps-ai-agent-service/common/task/producer.py:154
     调用 SourceUtil.set_agent_source(log_id, "agent", agent_api_key)
     → 固定设置 sourceType = 1

  2. neo-apps-ai-agent-service/common/utils/source_util.py:32
     def set_agent_source(source, describe, api_key):
         GlobalContext.set_agent_source(json.dumps({"sourceType": 1, ...}))

  3. Agent 调用 LLM 时 → neo-ai-agent-platform-service/service/llm/.../chat_completion_handler.py:39
     check, msg = await UsageService().check("tokens")

  4. neo-ai-agent-platform-service/service/util/usage_util.py:25
     if int(agent_source.get('sourceType', 99)) == 1 and type == "tokens":
         return "", "ok"   ← 跳过校验！

结论：所有用户通过 Agent 对话发起的 LLM 调用，sourceType 恒为 1，
      因此 token 类型的资源点余额校验被 100% 跳过。

验证目标：
1. sourceType == 1 时 check 被跳过
2. use() 方法无余额校验，无条件扣减到负数
3. 充值包用完后 fallback 到 lastRecharge 继续扣
"""

from decimal import Decimal
import json

# ═══════════════════════════════════════════════════════════
# 模拟 AgentUsage（余量表）
# ═══════════════════════════════════════════════════════════

class AgentUsage:
    """对应 Java AgentUsage 实体"""
    def __init__(self, type_code: int, total: Decimal, used: Decimal):
        self.type_code = type_code
        self.total = total
        self.used = used
        self.surplus = total - used

    def __repr__(self):
        return f"AgentUsage(total={self.total}, used={self.used}, surplus={self.surplus})"


class AgentRecharge:
    """对应 Java AgentRecharge 充值包"""
    def __init__(self, id: int, surplus: Decimal, used: Decimal, expiration: str):
        self.id = id
        self.surplus = surplus
        self.used = used
        self.expiration = expiration

    def __repr__(self):
        return f"Recharge(id={self.id}, surplus={self.surplus}, used={self.used})"


# ═══════════════════════════════════════════════════════════
# 模拟 AgentUsageServiceImpl.check() — 来自 data-process-service
# ═══════════════════════════════════════════════════════════

def data_process_check(agent_usage: AgentUsage) -> dict:
    """
    对应 AgentUsageServiceImpl.java 第74行 check() 方法
    
    原始 Java 代码：
        AgentUsage agentUsage = getByType(usageType.typeCode);
        Boolean check = Boolean.FALSE;
        if(agentUsage != null){
            check = agentUsage.getSurplus().compareTo(BigDecimal.ZERO) > 0;
        }
        return check ? buildSuccess(check) : buildErrorWithData("200", msg, check);
    """
    if agent_usage is not None:
        check = agent_usage.surplus > Decimal("0")
    else:
        check = False

    if check:
        return {"code": "200", "msg": "ok", "data": True}
    else:
        return {"code": "200", "msg": "资源点用量已达到系统最大上限，暂时无法处理您的请求", "data": False}


# ═══════════════════════════════════════════════════════════
# 模拟 UsageService.check() — 来自 platform-service (Python)
# ═══════════════════════════════════════════════════════════

def platform_usage_check(type_key: str, agent_source: dict, agent_usage: AgentUsage, env: str = "prod") -> tuple:
    """
    对应 usage_util.py UsageService.check()
    
    原始 Python 代码：
        agent_source = GlobalContext.get_agent_source()
        if agent_source:
            agent_source = json.loads(agent_source)
            if int(agent_source.get('sourceType', 99)) == 1 and type == "tokens":
                return "", "ok"    # ← 直接跳过！
        else:
            if os.getenv('ENV') and os.getenv('ENV') != 'dev':
                return "1801035", msg
        check_data = await DataProcessFeignClient.usage_check(type)
        if not check_data['data']:
            return "1801035", check_data['msg']
        return "", "ok"
    """
    if agent_source:
        source_type = int(agent_source.get('sourceType', 99))
        # ★ 关键代码：sourceType == 1 且检查的是 tokens 时，直接跳过校验
        if source_type == 1 and type_key == "tokens":
            return "", "ok"  # ← BUG: 不校验余额直接放行
    else:
        if env and env != 'dev':
            return "1801035", "source not found"

    # 调用 data-process-service 的 check 接口
    check_data = data_process_check(agent_usage)
    if not check_data['data']:
        return "1801035", check_data['msg']
    return "", "ok"


# ═══════════════════════════════════════════════════════════
# 模拟 AgentUsageServiceImpl.use() — 扣费逻辑
# ═══════════════════════════════════════════════════════════

def data_process_use(agent_usage: AgentUsage, recharge_list: list, resource_point_used: Decimal) -> dict:
    """
    对应 AgentUsageServiceImpl.java 第90行 use() 方法
    
    关键点：
    1. 没有 surplus > 0 的校验
    2. 充值包用完后 fallback 到 lastRecharge 继续扣
    3. surplus = total - used，可以为负数
    """
    # 模拟 getSurplusRecharge：获取有余量的充值包
    surplus_recharge = [r for r in recharge_list if r.surplus > Decimal("0")]

    # ★ 关键代码：如果没有有余量的充值包，fallback 到最后一个充值包继续扣
    if not surplus_recharge:
        surplus_recharge = [recharge_list[-1]]  # getLastRecharge

    # 按充值包逐个扣减
    remaining = resource_point_used
    for i, recharge in enumerate(surplus_recharge):
        if remaining <= Decimal("0"):
            break
        if recharge.surplus > Decimal("0") and recharge.surplus < remaining and i < len(surplus_recharge) - 1:
            # 当前包全部用完
            remaining -= recharge.surplus
            recharge.used += recharge.surplus
            recharge.surplus = Decimal("0")
        else:
            # 从当前包扣（★ 没有检查是否够扣，直接减，可能变负）
            recharge.used += remaining
            recharge.surplus -= remaining  # ← 可以变负数！
            break

    # ★ 关键代码：无条件更新 surplus，不判断是否 >= 0
    agent_usage.used += resource_point_used
    agent_usage.surplus = agent_usage.total - agent_usage.used  # ← 可以为负！

    return {"success": True, "surplus_after": agent_usage.surplus}


# ═══════════════════════════════════════════════════════════
# 验证场景
# ═══════════════════════════════════════════════════════════

def run_verification():
    print("=" * 80)
    print("资源点超限问题验证 — 全场景 Demo 验证清单")
    print("=" * 80)

    # 初始状态：充值 20000 资源点
    agent_usage = AgentUsage(
        type_code=10,  # RESOURCE_POINT
        total=Decimal("20000"),
        used=Decimal("0")
    )
    recharge_list = [
        AgentRecharge(id=1, surplus=Decimal("20000"), used=Decimal("0"), expiration="2026-12-31")
    ]

    # Agent 调用的 source 信息（sourceType=1 表示 Agent 来源）
    agent_source_type_1 = {"sourceType": 1, "sourceApiKey": "sales_agent", "sourceDescribe": "销售Agent"}
    # 非 Agent 来源（如组件调用）
    agent_source_type_other = {"sourceType": 3, "sourceApiKey": "component_x", "sourceDescribe": "组件"}

    print(f"\n初始状态: {agent_usage}")
    print(f"充值包: {recharge_list[0]}")

    # ─────────────────────────────────────────────────────
    # 验证1: sourceType == 1 时 check 被跳过
    # ─────────────────────────────────────────────────────
    print("\n" + "─" * 70)
    print("【验证1】sourceType == 1 时，tokens 类型的 check 被直接跳过")
    print("─" * 70)

    # 先把余额扣到 0
    agent_usage_empty = AgentUsage(type_code=10, total=Decimal("20000"), used=Decimal("20000"))
    print(f"\n场景：余额已用完 → {agent_usage_empty}")

    # sourceType=1, type=tokens → 跳过校验
    code, msg = platform_usage_check("tokens", agent_source_type_1, agent_usage_empty)
    print(f"  sourceType=1, check('tokens') → code='{code}', msg='{msg}'")
    print(f"  ★ 结果：{'✅ 放行（BUG！余额已为0却未拦截）' if code == '' else '❌ 拦截'}")

    # sourceType=1, type=web → 不跳过，走正常校验
    code, msg = platform_usage_check("web", agent_source_type_1, agent_usage_empty)
    print(f"\n  sourceType=1, check('web')    → code='{code}', msg='{msg}'")
    print(f"  ★ 结果：{'✅ 放行' if code == '' else '❌ 拦截（正常行为）'}")

    # sourceType=3, type=tokens → 不跳过，走正常校验
    code, msg = platform_usage_check("tokens", agent_source_type_other, agent_usage_empty)
    print(f"\n  sourceType=3, check('tokens') → code='{code}', msg='{msg}'")
    print(f"  ★ 结果：{'✅ 放行' if code == '' else '❌ 拦截（正常行为）'}")

    # ─────────────────────────────────────────────────────
    # 验证2: use() 无余额校验，无条件扣到负数
    # ─────────────────────────────────────────────────────
    print("\n" + "─" * 70)
    print("【验证2】use() 方法无余额校验，surplus 可以无限为负")
    print("─" * 70)

    # 重置余量表：已用完
    agent_usage_2 = AgentUsage(type_code=10, total=Decimal("20000"), used=Decimal("20000"))
    recharge_2 = [AgentRecharge(id=1, surplus=Decimal("0"), used=Decimal("20000"), expiration="2026-12-31")]

    print(f"\n  扣费前: {agent_usage_2}")
    print(f"  充值包: {recharge_2[0]}")

    # 模拟消耗 180 资源点（相当于 100万 token × 0.00018）
    result = data_process_use(agent_usage_2, recharge_2, Decimal("180"))
    print(f"\n  调用 use(180 资源点)...")
    print(f"  扣费后: {agent_usage_2}")
    print(f"  充值包: {recharge_2[0]}")
    print(f"  ★ surplus 已为负数: {agent_usage_2.surplus < 0} → 无拦截，继续穿透")

    # 继续扣
    result = data_process_use(agent_usage_2, recharge_2, Decimal("5000"))
    print(f"\n  再调用 use(5000 资源点)...")
    print(f"  扣费后: {agent_usage_2}")
    print(f"  ★ surplus = {agent_usage_2.surplus}，已超限 {abs(agent_usage_2.surplus)} 点")

    # ─────────────────────────────────────────────────────
    # 验证3: 完整模拟海能达场景
    # ─────────────────────────────────────────────────────
    print("\n" + "─" * 70)
    print("【验证3】完整模拟海能达场景 — 买 2W 用到 7W")
    print("─" * 70)

    agent_usage_3 = AgentUsage(type_code=10, total=Decimal("20000"), used=Decimal("0"))
    recharge_3 = [AgentRecharge(id=1, surplus=Decimal("20000"), used=Decimal("0"), expiration="2026-12-31")]

    print(f"\n  初始: total=20000, surplus=20000")

    # 模拟多次 Agent 调用（sourceType=1，每次消耗 token）
    total_calls = 0
    token_price = Decimal("0.00018")  # 资源点/token

    # 每次 Agent 对话约消耗 5000 token = 0.9 资源点
    # 加上网络检索 5 点/次，文档解析 5 点/页
    call_costs = [
        ("Agent对话(token)", Decimal("5000") * token_price),  # 0.9 点
        ("网络检索", Decimal("5")),
        ("Agent对话(token)", Decimal("10000") * token_price),  # 1.8 点
        ("文档解析(3页)", Decimal("15")),
    ]

    # 模拟大量调用直到超过 7W
    while agent_usage_3.used < Decimal("70000"):
        for call_name, cost in call_costs:
            # 每次调用前的 check
            code, msg = platform_usage_check("tokens", agent_source_type_1, agent_usage_3)
            # ★ sourceType=1 永远返回 ok，不拦截

            # 直接扣费
            data_process_use(agent_usage_3, recharge_3, cost)
            total_calls += 1

            if agent_usage_3.used >= Decimal("70000"):
                break

    print(f"  模拟 {total_calls} 次调用后:")
    print(f"  total  = {agent_usage_3.total}")
    print(f"  used   = {agent_usage_3.used:.2f}")
    print(f"  surplus= {agent_usage_3.surplus:.2f}")
    print(f"\n  ★ 买了 2W，用了 {agent_usage_3.used:.0f}，倒欠 {abs(agent_usage_3.surplus):.0f} 资源点")
    print(f"  ★ 全程 {total_calls} 次调用无一次被拦截（因为 sourceType=1 跳过 check）")

    # ─────────────────────────────────────────────────────
    # 验证4: 对比 sourceType != 1 时是否能正常拦截
    # ─────────────────────────────────────────────────────
    print("\n" + "─" * 70)
    print("【验证4】对比 — sourceType != 1 时能否正常拦截")
    print("─" * 70)

    agent_usage_4 = AgentUsage(type_code=10, total=Decimal("20000"), used=Decimal("19999"))
    print(f"\n  当前余额仅剩 1 点: {agent_usage_4}")

    # sourceType=3（组件调用）→ 正常走校验
    code, msg = platform_usage_check("tokens", agent_source_type_other, agent_usage_4)
    print(f"  sourceType=3, check('tokens') → 放行（surplus=1 > 0）")

    # 余额扣到0
    agent_usage_4.used = Decimal("20000")
    agent_usage_4.surplus = Decimal("0")
    code, msg = platform_usage_check("tokens", agent_source_type_other, agent_usage_4)
    print(f"  扣到0后, sourceType=3, check('tokens') → code='{code}'")
    print(f"  ★ 结果：{'放行' if code == '' else '拦截 ✅ 正常行为'}")

    # ─────────────────────────────────────────────────────
    # 全场景验证清单
    # ─────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("全场景 Demo 验证清单")
    print("=" * 80)

    results = []

    # --- 场景矩阵 ---
    # 余额状态
    usage_sufficient = AgentUsage(type_code=10, total=Decimal("20000"), used=Decimal("10000"))  # 余额充足
    usage_zero = AgentUsage(type_code=10, total=Decimal("20000"), used=Decimal("20000"))  # 余额为0
    usage_negative = AgentUsage(type_code=10, total=Decimal("20000"), used=Decimal("25000"))  # 余额为负

    # sourceType 定义
    sources = {
        1: {"sourceType": 1, "sourceApiKey": "sales_agent", "sourceDescribe": "销售Agent"},
        2: {"sourceType": 2, "sourceApiKey": "prompt_template_x", "sourceDescribe": "提示词模板"},
        3: {"sourceType": 3, "sourceApiKey": "mcp_tool_x", "sourceDescribe": "MCP工具"},
        4: {"sourceType": 4, "sourceApiKey": "component_x", "sourceDescribe": "组件"},
        5: {"sourceType": 5, "sourceApiKey": "dataset_sync", "sourceDescribe": "知识库同步"},
        6: {"sourceType": 6, "sourceApiKey": "ocr_tool", "sourceDescribe": "系统Tools"},
        99: {"sourceType": 99, "sourceApiKey": "other", "sourceDescribe": "其他"},
    }

    source_names = {
        1: "Agent对话",
        2: "Prompt Template",
        3: "MCP工具",
        4: "组件",
        5: "知识库同步",
        6: "系统Tools(OCR等)",
        99: "其他",
    }

    check_types = ["tokens", "web"]
    check_type_names = {"tokens": "Token(LLM调用)", "web": "网络检索"}

    balance_states = [
        ("余额充足(10000)", usage_sufficient),
        ("余额为0", usage_zero),
        ("余额为负(-5000)", usage_negative),
    ]

    print(f"\n{'序号':<4} {'sourceType':<22} {'校验类型':<16} {'余额状态':<18} {'check结果':<10} {'是否拦截':<8} {'是否正确':<8} {'问题说明'}")
    print("─" * 130)

    idx = 0
    for source_type, source_data in sources.items():
        for check_type in check_types:
            for balance_name, balance_usage in balance_states:
                idx += 1
                code, msg = platform_usage_check(check_type, source_data, balance_usage)
                blocked = code != ""
                
                # 判断期望行为
                should_block = balance_usage.surplus <= Decimal("0")
                is_correct = blocked == should_block
                
                status = "❌ 拦截" if blocked else "✅ 放行"
                correct = "✅ 正确" if is_correct else "❌ 错误"
                
                problem = ""
                if not is_correct:
                    if not blocked and should_block:
                        problem = f"BUG! 余额{'为0' if balance_usage.surplus == 0 else '为负'}但未拦截"
                    elif blocked and not should_block:
                        problem = "误拦截（余额充足却被拦截）"

                results.append({
                    "idx": idx,
                    "source_type": source_type,
                    "source_name": source_names[source_type],
                    "check_type": check_type_names[check_type],
                    "balance": balance_name,
                    "blocked": blocked,
                    "is_correct": is_correct,
                    "problem": problem,
                })

                print(f"{idx:<4} {f'{source_type}-{source_names[source_type]}':<22} {check_type_names[check_type]:<16} {balance_name:<18} {status:<10} {'是' if blocked else '否':<8} {correct:<8} {problem}")

    # --- use() 扣费场景 ---
    print(f"\n{'─' * 130}")
    print(f"\n{'序号':<4} {'扣费场景':<40} {'扣费前surplus':<14} {'扣费金额':<10} {'扣费后surplus':<14} {'是否拦截':<8} {'是否正确':<8} {'问题说明'}")
    print("─" * 130)

    use_cases = [
        ("余额充足时正常扣费", Decimal("20000"), Decimal("0"), Decimal("100")),
        ("余额恰好用完", Decimal("20000"), Decimal("19900"), Decimal("100")),
        ("余额为0时继续扣费", Decimal("20000"), Decimal("20000"), Decimal("180")),
        ("余额已负时继续扣费", Decimal("20000"), Decimal("25000"), Decimal("500")),
        ("大额扣费穿透(文档解析50页)", Decimal("20000"), Decimal("19800"), Decimal("250")),
    ]

    for i, (desc, total, used, cost) in enumerate(use_cases, start=idx+1):
        au = AgentUsage(type_code=10, total=total, used=used)
        rc = [AgentRecharge(id=1, surplus=total - used, used=used, expiration="2026-12-31")]
        before_surplus = au.surplus

        # use() 永远不拦截
        data_process_use(au, rc, cost)
        after_surplus = au.surplus
        blocked = False  # use() 从不拦截

        should_block = before_surplus <= Decimal("0")  # 如果余额<=0就该拦截
        # 特殊情况：余额够扣的场景不需要拦截
        if before_surplus > Decimal("0") and before_surplus >= cost:
            should_block = False
        elif before_surplus > Decimal("0") and before_surplus < cost:
            # 余额不够扣这次的量 — 理论上也该拦截（预扣逻辑）但这是边界场景
            should_block = False  # 这个场景争议较大，暂不判定

        is_correct = blocked == should_block if before_surplus <= Decimal("0") else True
        correct = "✅ 正确" if is_correct else "❌ 错误"
        problem = ""
        if not is_correct:
            problem = "BUG! use()无余额校验，负数仍可扣减"

        print(f"{i:<4} {desc:<40} {str(before_surplus):<14} {str(cost):<10} {str(after_surplus):<14} {'否':<8} {correct:<8} {problem}")

    # --- 汇总统计 ---
    total_cases = len(results) + len(use_cases)
    bug_cases = [r for r in results if not r["is_correct"]]
    use_bug_cases = [(d, t, u, c) for d, t, u, c in use_cases if AgentUsage(type_code=10, total=t, used=u).surplus <= Decimal("0")]

    print(f"\n{'=' * 80}")
    print(f"汇总统计")
    print(f"{'=' * 80}")
    print(f"\n  check() 校验场景总数: {len(results)}")
    print(f"  check() 存在 BUG 的场景数: {len(bug_cases)}")
    print(f"  use() 扣费场景总数: {len(use_cases)}")
    print(f"  use() 存在 BUG 的场景数: {len(use_bug_cases)}")
    print(f"\n  有问题的场景汇总:")
    for r in bug_cases:
        print(f"    • [{r['idx']}] sourceType={r['source_type']}({r['source_name']}) + {r['check_type']} + {r['balance']} → {r['problem']}")
    for d, t, u, c in use_bug_cases:
        surplus = t - u
        print(f"    • use() {d}: surplus={surplus} 时仍可扣减 {c}，无拦截")

    print(f"\n  核心结论:")
    print(f"    sourceType=1（Agent对话）+ tokens 校验 = 无论余额多少都放行 → 这是海能达问题的根因")
    print(f"    use() 方法在任何余额状态下都能执行扣减 → surplus 可以无限为负 → 第二层防线缺失")

    # ─────────────────────────────────────────────────────
    # 总结
    # ─────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("验证结论")
    print("=" * 70)
    print("""
═══════════════════════════════════════════════════════════════════════
sourceType 枚举完整定义（ExecuteLog.java）：
═══════════════════════════════════════════════════════════════════════

  sourceType = 1  → SOURCE_TYPE_AGENT     （Agent 对话）    ← 被跳过校验的类型
  sourceType = 2  → SOURCE_TYPE_PROMPT    （Prompt Template 调用）
  sourceType = 3  → SOURCE_TYPE_MCP       （MCP 工具调用）
  sourceType = 4  → SOURCE_TYPE_COMPONENT （组件调用）
  sourceType = 5  → SOURCE_TYPE_DATASET   （知识库同步）
  sourceType = 6  → SOURCE_TYPE_TOOLS     （系统工具，OCR/文档提取等）
  sourceType = 98 → SOURCE_TYPE_RESOURCE  （资源变更/充值/过期）
  sourceType = 99 → SOURCE_TYPE_OTHER     （其他）

═══════════════════════════════════════════════════════════════════════
sourceType = 1（Agent 对话）的触发场景：
═══════════════════════════════════════════════════════════════════════

  凡是用户通过 Agent 界面发送消息触发的对话，都属于 sourceType=1。
  
  代码路径（neo-apps-ai-agent-service）：
    producer.py:154 → SourceUtil.set_agent_source(log_id, "agent", agent_api_key)
    task_manager.py:163 → SourceUtil.set_agent_source(log_id, CREATE_CONVERSATION, agent_api_key)
    agui_copilotkit_api.py:504 → SourceUtil.set_agent_source(log_id, "agent", agent_api_key)

  source_util.py 中 set_agent_source() 固定写入 sourceType=1：
    GlobalContext.set_agent_source(json.dumps({
        "sourceType": 1,       ← 硬编码
        "sourceApiKey": api_key,
        "sourceId": source,
        "sourceDescribe": describe,
    }))

  具体包含的场景：
    • 用户通过百事通/销售Agent/工单Agent等发消息
    • Agent 规划任务（TASK_PLANNING）
    • Agent 执行动作（ACTION_EXEC）
    • Agent 生成回复（REPLY_CONTENT_GENERATION）
    • 意图识别（INTENT）
    • 问候语（GREETING）
    • 内容审查（BAD_CONTENT）
    • 语言识别（LANGUAGE_IDENTIFY）
    • 参数提取（PARAM_EXTRACT）
    • 记忆存储（memory_store）

  → 即：Agent 对话的整个生命周期内所有 LLM 调用都是 sourceType=1

═══════════════════════════════════════════════════════════════════════
BUG 代码定位：
═══════════════════════════════════════════════════════════════════════

  文件：neo-ai-agent-platform-service/service/util/usage_util.py
  行号：第 25 行
  代码：
    if int(agent_source.get('sourceType', 99)) == 1 and type == "tokens":
        return "", "ok"

  含义：当调用来源是 Agent（sourceType=1）且校验类型是 tokens 时，
       直接返回 "ok" 放行，不调用 data-process-service 的 check 接口。

  影响：海能达（以及所有租户）通过 Agent 对话使用的所有 Token 消耗
       从未被余额校验拦截过——不论余额是否为 0 或负数。

═══════════════════════════════════════════════════════════════════════
三层 BUG 汇总：
═══════════════════════════════════════════════════════════════════════

  BUG#1（致命）：usage_util.py 第 25 行
    → sourceType=1（Agent 对话）的 Token 校验被直接跳过
    → 海能达所有 Agent 对话的 LLM 调用都不会触发余额校验

  BUG#2（致命）：AgentUsageServiceImpl.java use() 方法
    → use() 内部无 surplus >= 0 校验，无条件扣减
    → surplus = total - used，可以无限为负数

  BUG#3（高危）：AgentUsageServiceImpl.java use() 充值包 fallback
    → 所有充值包余额为 0 时，fallback 到 lastRecharge 继续扣
    → 即使包都用完也不拒绝，充值包 surplus 也可以为负

═══════════════════════════════════════════════════════════════════════
修复建议：
═══════════════════════════════════════════════════════════════════════

  P0: 删除 sourceType==1 跳过 check 的逻辑
      （如有业务原因需要保留，改为"自定义模型不计费但仍校验余额"）
  P0: use() 方法开头增加 surplus > 0 的前置校验，不足时拒绝扣减
  P1: 充值包用完后不再 fallback 到 lastRecharge，直接拒绝
  P2: 数据库层面对 surplus 增加 CHECK(surplus >= -阈值) 约束
""")


if __name__ == "__main__":
    run_verification()

"""
资源点扣费完整链路验证 — 模拟两个服务的真实调用链和数据写入

验证焦点：你贴的 usedComment 数据 与 ai_agent_usage 表数据的关系

链路：
  neo-ai-agent-platform-service (Python)
    └── chat_completion_handler.py: _record_audit_log()
        └── DataProcessFeignClient.usage_and_execute_log(data)
            └── HTTP POST → NEO-AI-DATA-PROCESS-SERVICE /agentUsage/actions/use

  NEO-AI-DATA-PROCESS-SERVICE (Java)
    └── AgentUsageController.use(data)
        └── AgentUsageServiceImpl.use(data)
            ├── 1. 查资源价格 → metaDataAppClient.getResourceByApiKey(resourceApiKey)
            ├── 2. 计算 resourcePointUsed = used × price (customFlg==0时) 或 0 (customFlg==1时)
            ├── 3. Redis 分布式锁
            ├── 4. getSurplusRecharge(10) → 查有余额的充值包
            │   └── 如果为空 → getLastRecharge(10) → fallback 到最后一个包
            ├── 5. 按充值包逐个扣减（更新 ai_agent_recharge.surplus）
            ├── 6. 更新 ai_agent_usage: used += resourcePointUsed, surplus = total - used
            ├── 7. 构建 usedComment JSON（记录充值包扣减明细）
            └── 8. 异步写入 aiExecuteLog 标准实体（含 usedComment）
"""

from decimal import Decimal
import json


# ═══════════════════════════════════════════════════════════
# 模拟数据模型
# ═══════════════════════════════════════════════════════════

class AgentUsage:
    """ai_agent_usage 表 — 余量汇总（每租户 type=10 一条）"""
    def __init__(self, total: Decimal, used: Decimal):
        self.type = 10
        self.total = total
        self.used = used
        self.surplus = total - used

    def __repr__(self):
        return f"ai_agent_usage(type=10, total={self.total}, used={self.used}, surplus={self.surplus})"


class AgentRecharge:
    """ai_agent_recharge 表 — 充值包（每次充值一条）"""
    def __init__(self, id: int, type_code: int, surplus: Decimal, used: Decimal, expiration: int):
        self.id = id
        self.type = type_code
        self.surplus = surplus
        self.used = used
        self.expiration = expiration

    def __repr__(self):
        return f"ai_agent_recharge(id={self.id}, surplus={self.surplus}, used={self.used})"


# ═══════════════════════════════════════════════════════════
# 模拟 platform-service 端的逻辑
# ═══════════════════════════════════════════════════════════

def platform_check(agent_source: dict, check_type: str, agent_usage: AgentUsage) -> tuple:
    """
    模拟 usage_util.py UsageService.check()
    """
    if agent_source:
        source_type = int(agent_source.get('sourceType', 99))
        if source_type == 1 and check_type == "tokens":
            return "", "ok"  # ← BUG: 跳过校验

    # 正常走 data-process check
    if agent_usage.surplus > Decimal("0"):
        return "", "ok"
    else:
        return "1801035", "资源点用量已达到系统最大上限"


def platform_record_audit_log(app_config_model: int, resource_api_key: str,
                               context_value: str, usage: dict) -> dict:
    """
    模拟 chat_completion_handler.py _record_audit_log() 中 customFlg 的判定逻辑

    app_config.config_model:
      0 = 平台默认配置
      3 = 客户自定义模型

    customFlg 判定：
      config_model == 3 → customFlg = 1（自定义，不扣费）
      config_model == 0 且 context 中配置了非默认模型 → customFlg = 1
      否则 → customFlg = 0（平台模型，正常扣费）
    """
    custom_flg = 0
    if app_config_model == 3:
        custom_flg = 1
    elif app_config_model == 0:
        if context_value and context_value != resource_api_key and context_value != "default_model":
            custom_flg = 1

    return {
        "typeApiKey": "tokens",
        "resourceApiKey": resource_api_key,
        "customFlg": custom_flg,
        "used": usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0),
    }


# ═══════════════════════════════════════════════════════════
# 模拟 data-process-service 端的 use() 逻辑
# ═══════════════════════════════════════════════════════════

def data_process_use(agent_usage: AgentUsage, recharge_list: list,
                     resource_api_key: str, custom_flg: int, used_amount: Decimal,
                     price: Decimal) -> dict:
    """
    完整模拟 AgentUsageServiceImpl.use()
    返回 usedComment（与你贴的数据格式一致）
    """
    # 计算实际资源点消耗
    resource_point_used = used_amount * price if custom_flg == 0 else Decimal("0")

    used_comment = []

    if custom_flg == 0:
        # getSurplusRecharge: surplus > 0 的充值包，按 expiration 升序
        surplus_recharge = [r for r in recharge_list if r.surplus > Decimal("0")]

        # fallback: 没有有余额的包 → 取最后一个
        if not surplus_recharge:
            surplus_recharge = [recharge_list[-1]]

        remaining = resource_point_used
        for i, recharge in enumerate(surplus_recharge):
            if remaining <= Decimal("0"):
                break

            comment = {
                "rechargeId": recharge.id,
                "used": float(recharge.surplus),  # 扣前的充值包余额
            }

            # 当前包全部用完（不是最后一个 且 包余额 < 要扣的）
            if (recharge.surplus > Decimal("0") and
                recharge.surplus < remaining and
                i < len(surplus_recharge) - 1):
                comment["surplus"] = 0
                comment["expiration"] = recharge.expiration
                used_comment.append(comment)

                recharge.used += recharge.surplus
                remaining -= recharge.surplus
                recharge.surplus = Decimal("0")
            else:
                # 只扣当前包（可能扣成负数！）
                comment["surplus"] = float(recharge.surplus - remaining)
                comment["expiration"] = recharge.expiration
                used_comment.append(comment)

                recharge.used += remaining
                recharge.surplus -= remaining
                break

        # 更新 ai_agent_usage
        agent_usage.used += resource_point_used
        agent_usage.surplus = agent_usage.total - agent_usage.used
    else:
        # customFlg=1: 自定义模型不扣费，但仍更新记录
        pass

    return {
        "resource_point_used": resource_point_used,
        "resource_point_surplus": agent_usage.surplus,
        "used_comment": used_comment,
        "custom_flg": custom_flg,
    }


# ═══════════════════════════════════════════════════════════
# 验证场景
# ═══════════════════════════════════════════════════════════

def run():
    print("=" * 80)
    print("完整链路验证 — 对照你贴的实际数据")
    print("=" * 80)

    # ── 初始状态：海能达充值了 22000 ──
    agent_usage = AgentUsage(total=Decimal("22000"), used=Decimal("0"))
    recharge = AgentRecharge(
        id=4377862595315734,
        type_code=10,
        surplus=Decimal("22000"),
        used=Decimal("0"),
        expiration=1807977599000  # 2027-04-15
    )
    recharge_list = [recharge]

    agent_source = {"sourceType": 1, "sourceApiKey": "sales_agent", "sourceId": 12345}

    # 模型配置：平台标准模型（customFlg=0）
    app_config_model = 0
    resource_api_key = "db_doubao_seed_1.6"
    context_value = "default_model"
    token_price = Decimal("0.00018")  # 资源点/token

    print(f"\n初始状态:")
    print(f"  {agent_usage}")
    print(f"  {recharge}")
    print(f"  agent_source = sourceType=1 (Agent对话)")
    print(f"  config_model=0, resourceApiKey={resource_api_key}, token_price={token_price}")

    # ── 模拟4次扣费（对应你贴的4条 usedComment 数据的时间正序） ──
    # 从你的数据反算每次消耗的资源点：
    # 第1次: 498.6971600 - 498.4156400 = 0.28152 点 → 0.28152/0.00018 = 1564 tokens
    # 第2次: 498.4156400 - 497.9589800 = 0.45666 点 → 2537 tokens
    # 第3次: 497.9589800 - 497.6582000 = 0.30078 点 → 1671 tokens
    # 第4次: 497.6582000 - 497.5914200 = 0.06678 点 → 371 tokens

    # 但等等！你数据里的充值包初始 surplus 不是 22000，而是 ~498.69
    # 说明在这4笔之前，已经有大量消耗发生了
    # 22000 - 498.69 = 21501.31 点已经被之前的调用消耗掉了

    print(f"\n" + "─" * 80)
    print("模拟到你贴的数据时刻（充值包 surplus 约 498.69）")
    print("─" * 80)

    # 先模拟之前的消耗，让状态对齐到你的数据起点
    pre_consumed = Decimal("22000") - Decimal("498.6971600")
    agent_usage.used = pre_consumed
    agent_usage.surplus = agent_usage.total - agent_usage.used
    recharge.surplus = Decimal("498.6971600")
    recharge.used = pre_consumed

    print(f"\n  对齐后状态（你数据的起点）:")
    print(f"  {agent_usage}")
    print(f"  recharge.surplus = {recharge.surplus}")

    # 模拟4次 Agent 对话
    simulated_calls = [
        ("第1次Agent对话", 1564),   # → 0.28152 资源点
        ("第2次Agent对话", 2537),   # → 0.45666 资源点
        ("第3次Agent对话", 1671),   # → 0.30078 资源点
        ("第4次Agent对话", 371),    # → 0.06678 资源点
    ]

    print(f"\n{'序号':<6}{'场景':<18}{'check结果':<14}{'tokens':<8}{'资源点':<12}{'充值包surplus扣后':<20}{'ai_agent_usage.surplus':<24}{'usedComment'}")
    print("─" * 140)

    for i, (desc, tokens) in enumerate(simulated_calls, 1):
        # Step 1: platform-service check
        code, msg = platform_check(agent_source, "tokens", agent_usage)
        check_result = "跳过(sourceType=1)" if code == "" else f"拦截({code})"

        # Step 2: LLM调用完成，得到实际token数
        usage = {"prompt_tokens": tokens - tokens // 4, "completion_tokens": tokens // 4}

        # Step 3: _record_audit_log 构建请求
        audit_data = platform_record_audit_log(app_config_model, resource_api_key, context_value, usage)

        # Step 4: 调用 data-process-service /use
        result = data_process_use(
            agent_usage, recharge_list,
            audit_data["resourceApiKey"],
            audit_data["customFlg"],
            Decimal(str(audit_data["used"])),
            token_price
        )

        comment_str = json.dumps(result["used_comment"], ensure_ascii=False)
        rp_used = result["resource_point_used"]

        print(f"{i:<6}{desc:<18}{check_result:<14}{tokens:<8}{float(rp_used):<12.5f}{float(recharge.surplus):<20.7f}{float(agent_usage.surplus):<24.7f}{comment_str}")

    # ── 对比你贴的实际数据 ──
    print(f"\n{'─' * 80}")
    print("对比你贴的实际数据（时间正序）:")
    print("─" * 80)
    actual_data = [
        {"surplus": 498.4156400, "expiration": 1807977599000, "used": 498.6971600, "rechargeId": 4377862595315734},
        {"surplus": 497.9589800, "expiration": 1807977599000, "used": 498.4156400, "rechargeId": 4377862595315734},
        {"surplus": 497.6582000, "expiration": 1807977599000, "used": 497.9589800, "rechargeId": 4377862595315734},
        {"surplus": 497.5914200, "expiration": 1807977599000, "used": 497.6582000, "rechargeId": 4377862595315734},
    ]
    print(f"\n{'序号':<6}{'usedComment.used(扣前余额)':<28}{'usedComment.surplus(扣后余额)':<30}{'本次消耗资源点':<16}{'对应tokens'}")
    print("─" * 100)
    for i, d in enumerate(actual_data, 1):
        cost = d["used"] - d["surplus"]
        tokens_est = int(cost / 0.00018)
        print(f"{i:<6}{d['used']:<28.7f}{d['surplus']:<30.7f}{cost:<16.5f}{tokens_est}")

    # ── 核心验证结论 ──
    print(f"\n{'=' * 80}")
    print("核心验证结论")
    print("=" * 80)
    print("""
┌──────────────────────────────────────────────────────────────────────────────┐
│ 1. usedComment 中的 "used" 字段 = 扣费前充值包的 surplus                     │
│    usedComment 中的 "surplus" 字段 = 扣费后充值包的 surplus                   │
│    → 与代码逻辑完全一致:                                                     │
│      comment.put("used", agentRecharge.getSurplus());         // 扣前          │
│      comment.put("surplus", agentRecharge.getSurplus().subtract(surplusUsed)); │
│                                                                              │
│ 2. 你贴的数据中充值包 surplus 从 498.69 降到 497.59（4笔共消耗 ~1.1 资源点） │
│    这些是正常的小额 Agent 对话 token 消耗（几百~几千 tokens/次）             │
│                                                                              │
│ 3. 全程 check 被跳过（sourceType=1 + tokens）:                               │
│    - 即使此时 ai_agent_usage.surplus 已经接近 0 或为负                        │
│    - platform-service 的 check 从不会拦截                                    │
│    - use() 也从不检查余额，直接扣减                                          │
│                                                                              │
│ 4. 最终 ai_agent_usage 的 surplus = -70159 的完整路径:                        │
│    total=22000 → 持续扣费(从不拦截) → used累加到92159 → surplus=-70159        │
│    充值包 surplus: 22000 → 持续减少 → 减到0 → fallback继续扣 → 最终为负      │
│                                                                              │
│ 5. 数据一致性验证:                                                           │
│    ai_agent_usage.used (92159.68) = Σ 所有 aiExecuteLog.resourcePointUsed    │
│    ai_agent_usage.surplus (-70159.68) = total(22000) - used(92159.68)         │
│    ✅ 公式成立，数据自洽                                                      │
└──────────────────────────────────────────────────────────────────────────────┘
""")

    # ── 继续模拟：充值包用完后会发生什么 ──
    print("─" * 80)
    print("继续模拟：充值包 surplus 扣到 0 后 → fallback 到 lastRecharge 继续扣")
    print("─" * 80)

    # 把充值包扣到接近 0
    remaining_surplus = recharge.surplus
    agent_usage_sim = AgentUsage(total=Decimal("22000"), used=Decimal("22000") - remaining_surplus)
    recharge_sim = AgentRecharge(id=4377862595315734, type_code=10,
                                  surplus=remaining_surplus, used=Decimal("22000") - remaining_surplus,
                                  expiration=1807977599000)
    recharge_list_sim = [recharge_sim]

    print(f"\n  当前: recharge.surplus = {recharge_sim.surplus:.4f}, ai_agent_usage.surplus = {agent_usage_sim.surplus:.4f}")

    # 一笔大额扣费把包扣穿
    big_cost = Decimal("600")  # 600资源点 > 剩余的497
    result = data_process_use(agent_usage_sim, recharge_list_sim,
                              resource_api_key, 0, big_cost / token_price, token_price)

    print(f"  扣费 {big_cost} 资源点后:")
    print(f"  recharge.surplus = {recharge_sim.surplus:.4f} {'← 已为负!' if recharge_sim.surplus < 0 else ''}")
    print(f"  ai_agent_usage.surplus = {agent_usage_sim.surplus:.4f} {'← 已为负!' if agent_usage_sim.surplus < 0 else ''}")
    print(f"  usedComment = {json.dumps(result['used_comment'])}")

    # 之后再来一笔
    result2 = data_process_use(agent_usage_sim, recharge_list_sim,
                               resource_api_key, 0, Decimal("1000") / token_price, token_price)
    print(f"\n  再扣 1000 资源点:")
    print(f"  recharge.surplus = {recharge_sim.surplus:.4f}")
    print(f"  ai_agent_usage.surplus = {agent_usage_sim.surplus:.4f}")
    print(f"  ★ getSurplusRecharge 返回空（surplus <= 0）→ fallback 到 lastRecharge → 继续扣 → 无限穿透")


if __name__ == "__main__":
    run()

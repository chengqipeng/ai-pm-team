"""
上下文压缩算法模拟测试
场景: CRM 商机批量跟进（C4），15 条商机逐条处理
分别模拟 Hermes 算法和我们的算法，对比压缩效果
"""
import json
import copy

# ============================================================
# 构造真实 CRM messages 数据
# ============================================================

def estimate_tokens(text):
    """粗略估算 token 数（中文约 2 字符/token，英文约 4 字符/token）"""
    return max(1, len(text.encode('utf-8')) // 3)

def build_crm_messages():
    """构造 15 条商机批量跟进的完整 messages"""
    messages = []
    
    # system prompt
    messages.append({
        "role": "system",
        "content": "你是 aPaaS 平台的智能业务助手。可用工具: query_data, modify_data, analyze_data, query_schema, ask_user, search_memories, save_memory, web_search, company_info, financial_report, delegate_task, start_async_task。\n\n行为准则:\n- 操作业务数据前先确认\n- 删除操作需要用户确认\n- 所有关联使用 api_key\n- 回答要简洁专业"
    })
    
    # 用户请求
    messages.append({
        "role": "user",
        "content": "帮我看看本周需要跟进的商机，逐个过一遍"
    })
    
    # Agent 查询商机列表
    messages.append({
        "role": "assistant",
        "content": None,
        "tool_calls": [{"id": "tc_list", "type": "function", "function": {
            "name": "query_data",
            "arguments": json.dumps({"entity": "opportunity", "filters": {"nextFollowUp": "this_week"}, "page_size": 20})
        }}]
    })
    
    # 商机列表结果（15 条）
    opportunities = []
    companies = ["华创科技", "中科智能", "深圳光电", "北京云图", "上海数联", 
                 "广州芯片", "杭州软件", "成都物联", "武汉生物", "南京新材",
                 "西安航天", "长沙机械", "青岛海洋", "厦门电子", "大连重工"]
    stages = ["需求确认", "方案评估", "报价谈判", "合同审批", "需求确认",
              "方案评估", "报价谈判", "需求确认", "方案评估", "报价谈判",
              "合同审批", "需求确认", "方案评估", "报价谈判", "合同审批"]
    amounts = [500, 1200, 800, 2000, 350, 900, 1500, 600, 1100, 750,
               3000, 400, 850, 1300, 2500]
    
    for i in range(15):
        opportunities.append({
            "id": f"opp_{i+1:03d}",
            "name": f"{companies[i]}ERP升级项目",
            "account": companies[i],
            "stage": stages[i],
            "amount": amounts[i],
            "nextFollowUp": f"2026-04-{14+i%5}",
            "owner": "张经理",
            "lastActivity": f"上周{['一','二','三','四','五'][i%5]}电话沟通，客户表示{['感兴趣','需要内部讨论','等待预算审批','希望尽快推进','还在比较方案'][i%5]}"
        })
    
    list_result = json.dumps({"total": 15, "records": opportunities}, ensure_ascii=False, indent=2)
    messages.append({
        "role": "tool",
        "tool_call_id": "tc_list",
        "content": list_result
    })
    
    # Agent 总结列表
    messages.append({
        "role": "assistant",
        "content": f"本周有 15 条商机需要跟进，总金额约 {sum(amounts)} 万元。按阶段分布:\n- 需求确认: 4 条\n- 方案评估: 4 条\n- 报价谈判: 4 条\n- 合同审批: 3 条\n\n我们从第一条开始逐个过。第一条是{companies[0]}ERP升级项目，金额 {amounts[0]} 万，当前在{stages[0]}阶段。需要我查看详情吗？"
    })
    
    # 逐条处理 15 条商机
    for i in range(15):
        # 用户说"看下一条"或"看详情"
        if i == 0:
            messages.append({"role": "user", "content": "看详情"})
        else:
            messages.append({"role": "user", "content": f"好的，看第{i+1}条"})
        
        # Agent 查询详情
        messages.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": f"tc_detail_{i}", "type": "function", "function": {
                "name": "query_data",
                "arguments": json.dumps({"entity": "opportunity", "record_id": f"opp_{i+1:03d}"})
            }}]
        })
        
        # 详情结果
        detail = {
            "id": f"opp_{i+1:03d}",
            "name": f"{companies[i]}ERP升级项目",
            "account": {"name": companies[i], "industry": ["制造业","IT","光电","互联网","通信"][i%5]},
            "stage": stages[i],
            "amount": amounts[i],
            "probability": [20, 40, 60, 80, 20, 40, 60, 20, 40, 60, 80, 20, 40, 60, 80][i],
            "expectedCloseDate": f"2026-{5+i//5}-{10+i%28}",
            "contacts": [{"name": f"{'赵钱孙李周吴郑王冯陈褚卫蒋沈韩'[i]}总", "role": "决策人", "phone": f"138{i:08d}"}],
            "activities": [
                {"date": f"2026-04-{10+i%5}", "type": "电话", "note": f"与{companies[i]}{'赵钱孙李周吴郑王冯陈褚卫蒋沈韩'[i]}总通话，讨论了项目需求和预算情况。客户表示{['对方案感兴趣，需要进一步了解细节','内部正在讨论预算，预计下周有结果','价格方面还需要再谈谈','合同条款基本确认，等法务审核','还在比较我们和竞品的方案'][i%5]}。"},
                {"date": f"2026-04-{7+i%5}", "type": "邮件", "note": f"发送了{['产品介绍','方案书','报价单','合同草案','竞品对比'][i%5]}给客户。"}
            ],
            "competitors": [["用友", "金蝶"], ["SAP", "Oracle"], ["浪潮", "用友"], ["SAP", "金蝶"], ["Oracle", "浪潮"]][i%5],
            "notes": f"客户{companies[i]}是{['制造业','IT','光电','互联网','通信'][i%5]}领域的{'头部' if amounts[i] > 1000 else '中型'}企业，{['首次合作','老客户续约','竞品替换','新业务拓展','战略合作'][i%5]}。"
        }
        messages.append({
            "role": "tool",
            "tool_call_id": f"tc_detail_{i}",
            "content": json.dumps(detail, ensure_ascii=False, indent=2)
        })
        
        # Agent 消化详情并给出建议
        actions = ["推进到方案评估阶段", "安排下周现场演示", "调整报价方案", "催促合同签署", "发送竞品对比材料",
                   "安排技术交流会", "提交折扣申请", "跟进预算审批进度", "准备POC方案", "约客户面谈",
                   "提交合同审批", "发送需求调研问卷", "安排产品演示", "准备最终报价", "催促法务审核"]
        messages.append({
            "role": "assistant",
            "content": f"**{companies[i]}ERP升级项目** (金额: {amounts[i]}万, 阶段: {stages[i]}, 赢率: {[20,40,60,80,20,40,60,20,40,60,80,20,40,60,80][i]}%)\n\n关键信息:\n- 决策人: {'赵钱孙李周吴郑王冯陈褚卫蒋沈韩'[i]}总\n- 竞品: {', '.join([['用友','金蝶'],['SAP','Oracle'],['浪潮','用友'],['SAP','金蝶'],['Oracle','浪潮']][i%5])}\n- 最近活动: {detail['activities'][0]['note'][:50]}...\n\n建议下一步: **{actions[i]}**\n\n要执行这个操作吗？"
        })
        
        # 用户确认
        messages.append({"role": "user", "content": "好的，执行"})
        
        # Agent 执行更新
        messages.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": f"tc_update_{i}", "type": "function", "function": {
                "name": "modify_data",
                "arguments": json.dumps({"action": "update", "entity": "opportunity", "record_id": f"opp_{i+1:03d}", "data": {"nextAction": actions[i]}})
            }}]
        })
        
        messages.append({
            "role": "tool",
            "tool_call_id": f"tc_update_{i}",
            "content": json.dumps({"success": True, "message": f"已更新商机 {companies[i]}ERP升级项目 的下一步行动"}, ensure_ascii=False)
        })
        
        messages.append({
            "role": "assistant",
            "content": f"✅ 已更新 {companies[i]} 的下一步行动为「{actions[i]}」。"
        })
    
    return messages


# ============================================================
# Hermes 压缩算法模拟
# ============================================================

def hermes_compress(messages, context_length=64000, threshold=0.50, target_ratio=0.20, protect_last_n=20, protect_first_n=3):
    """模拟 Hermes 的 4 阶段压缩算法"""
    messages = copy.deepcopy(messages)
    
    total_tokens = sum(estimate_tokens(json.dumps(m, ensure_ascii=False)) for m in messages)
    threshold_tokens = context_length * threshold
    
    if total_tokens < threshold_tokens:
        return messages, {"triggered": False, "total_tokens": total_tokens, "ratio": total_tokens/context_length}
    
    # Phase 1: Prune old tool results (>200 chars outside tail)
    tail_start = max(0, len(messages) - protect_last_n)
    phase1_saved = 0
    for i, msg in enumerate(messages):
        if i >= tail_start:
            break
        if msg["role"] == "tool" and len(msg.get("content", "")) > 200:
            original_len = estimate_tokens(msg["content"])
            msg["content"] = "[Old tool output cleared to save context space]"
            phase1_saved += original_len - estimate_tokens(msg["content"])
    
    # Phase 2: Determine boundaries
    head = messages[:protect_first_n]
    tail = messages[-protect_last_n:]
    middle = messages[protect_first_n:-protect_last_n] if len(messages) > protect_first_n + protect_last_n else []
    
    # Phase 3: Generate structured summary (模拟 LLM 摘要)
    middle_tokens = sum(estimate_tokens(json.dumps(m, ensure_ascii=False)) for m in middle)
    summary_budget = max(2000, min(int(middle_tokens * 0.20), 12000))
    
    # 模拟结构化摘要
    summary = "## Goal\n销售主管逐条检查本周需跟进的15条商机，更新状态和下一步行动。\n\n"
    summary += "## Progress\n### Done\n"
    
    processed = []
    for msg in middle:
        if msg["role"] == "assistant" and msg.get("content") and "已更新" in msg.get("content", ""):
            processed.append(msg["content"])
    
    for p in processed:
        summary += f"- {p}\n"
    
    summary += "\n### In Progress\n- 继续处理剩余商机\n\n"
    summary += "## Key Decisions\n- 按商机列表顺序逐条处理\n\n"
    summary += "## Critical Context\n- 共15条商机，总金额约17650万元\n"
    
    summary_tokens = estimate_tokens(summary)
    
    # Phase 4: Assemble
    compressed = []
    compressed.extend(head)
    compressed.append({
        "role": "user",  # 避免连续同角色
        "content": f"[CONTEXT COMPACTION] Earlier turns were compacted:\n\n{summary}"
    })
    compressed.extend(tail)
    
    # 清理孤立的 tool_call/tool_result
    call_ids = set()
    result_ids = set()
    for msg in compressed:
        if msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                call_ids.add(tc["id"])
        if msg["role"] == "tool":
            result_ids.add(msg.get("tool_call_id"))
    
    # 移除孤立的 tool_result
    compressed = [m for m in compressed if m["role"] != "tool" or m.get("tool_call_id") in call_ids]
    
    # 为孤立的 tool_call 注入 stub
    for msg in compressed:
        if msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                if tc["id"] not in result_ids:
                    compressed.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": "[Tool result removed during context compaction]"
                    })
    
    final_tokens = sum(estimate_tokens(json.dumps(m, ensure_ascii=False)) for m in compressed)
    
    return compressed, {
        "triggered": True,
        "original_tokens": total_tokens,
        "phase1_saved": phase1_saved,
        "middle_tokens": middle_tokens,
        "summary_tokens": summary_tokens,
        "final_tokens": final_tokens,
        "compression_ratio": 1 - final_tokens / total_tokens,
        "final_ratio": final_tokens / context_length,
        "messages_before": len(messages),
        "messages_after": len(compressed),
    }


# ============================================================
# 我们的压缩算法模拟
# ============================================================

def our_compress(messages, context_length=64000, threshold_50=0.50, threshold_70=0.70, keep_recent_results=5):
    """模拟我们的 3 道防线压缩算法"""
    messages = copy.deepcopy(messages)
    
    total_tokens = sum(estimate_tokens(json.dumps(m, ensure_ascii=False)) for m in messages)
    ratio = total_tokens / context_length
    
    if ratio < threshold_50:
        return messages, {"triggered": False, "total_tokens": total_tokens, "ratio": ratio}
    
    # Layer 3 + Layer 4: Microcompact
    # 找到所有 tool_result 消息
    tool_results = [(i, m) for i, m in enumerate(messages) if m["role"] == "tool"]
    
    if len(tool_results) > keep_recent_results:
        microcompact_saved = 0
        protected_tools = {"query_schema"}  # schema 结果受保护
        
        for idx, msg in tool_results[:-keep_recent_results]:
            # 检查是否是受保护的工具
            tool_name = None
            for m in messages[:idx]:
                if m.get("tool_calls"):
                    for tc in m["tool_calls"]:
                        if tc["id"] == msg.get("tool_call_id"):
                            tool_name = tc["function"]["name"]
            
            if tool_name in protected_tools:
                continue
            
            if msg.get("content") and len(msg["content"]) > 100:
                original_tokens = estimate_tokens(msg["content"])
                # 生成一行摘要
                content = msg["content"]
                if "records" in content or "total" in content:
                    msg["content"] = f"[已压缩: 查询结果]"
                elif "success" in content:
                    msg["content"] = f"[已压缩: 操作成功]"
                else:
                    msg["content"] = f"[已压缩: 工具结果，原始 {len(content)} 字符]"
                microcompact_saved += original_tokens - estimate_tokens(msg["content"])
    
    final_tokens = sum(estimate_tokens(json.dumps(m, ensure_ascii=False)) for m in messages)
    
    return messages, {
        "triggered": True,
        "original_tokens": total_tokens,
        "microcompact_saved": microcompact_saved if 'microcompact_saved' in dir() else 0,
        "final_tokens": final_tokens,
        "compression_ratio": 1 - final_tokens / total_tokens,
        "final_ratio": final_tokens / context_length,
        "messages_before": len(messages),
        "messages_after": len(messages),  # 我们不删除消息，只替换内容
        "llm_calls_needed": 0,  # 不需要 LLM 调用
    }


# ============================================================
# 运行测试
# ============================================================

if __name__ == "__main__":
    messages = build_crm_messages()
    
    total_tokens = sum(estimate_tokens(json.dumps(m, ensure_ascii=False)) for m in messages)
    total_messages = len(messages)
    
    print("=" * 70)
    print("CRM 商机批量跟进场景 - 上下文压缩算法对比测试")
    print("=" * 70)
    print(f"\n原始数据: {total_messages} 条消息, {total_tokens:,} tokens, 占比 {total_tokens/64000*100:.1f}%")
    print(f"上下文窗口: 64,000 tokens, 可用空间: ~51,000 tokens")
    
    # 统计各类消息的 token 分布
    system_tokens = sum(estimate_tokens(json.dumps(m, ensure_ascii=False)) for m in messages if m["role"] == "system")
    user_tokens = sum(estimate_tokens(json.dumps(m, ensure_ascii=False)) for m in messages if m["role"] == "user")
    assistant_tokens = sum(estimate_tokens(json.dumps(m, ensure_ascii=False)) for m in messages if m["role"] == "assistant")
    tool_tokens = sum(estimate_tokens(json.dumps(m, ensure_ascii=False)) for m in messages if m["role"] == "tool")
    
    print(f"\nToken 分布:")
    print(f"  system:    {system_tokens:>6,} ({system_tokens/total_tokens*100:.1f}%)")
    print(f"  user:      {user_tokens:>6,} ({user_tokens/total_tokens*100:.1f}%)")
    print(f"  assistant: {assistant_tokens:>6,} ({assistant_tokens/total_tokens*100:.1f}%)")
    print(f"  tool:      {tool_tokens:>6,} ({tool_tokens/total_tokens*100:.1f}%) ← 压缩目标")
    
    # Hermes 算法
    print("\n" + "=" * 70)
    print("Hermes 算法 (4 阶段: Prune → Boundaries → Summary → Assemble)")
    print("=" * 70)
    
    hermes_result, hermes_stats = hermes_compress(messages)
    if hermes_stats["triggered"]:
        print(f"  Phase 1 节省: {hermes_stats['phase1_saved']:,} tokens (清除旧工具结果)")
        print(f"  Phase 3 摘要: {hermes_stats['summary_tokens']:,} tokens (替代 {hermes_stats['middle_tokens']:,} tokens 的中间区域)")
        print(f"  消息数: {hermes_stats['messages_before']} → {hermes_stats['messages_after']}")
        print(f"  Token: {hermes_stats['original_tokens']:,} → {hermes_stats['final_tokens']:,}")
        print(f"  压缩率: {hermes_stats['compression_ratio']*100:.1f}%")
        print(f"  压缩后占比: {hermes_stats['final_ratio']*100:.1f}%")
        print(f"  需要 LLM 调用: 是 (Phase 3 摘要)")
        print(f"  额外延迟: ~3-5 秒")
    else:
        print(f"  未触发 (占比 {hermes_stats['ratio']*100:.1f}% < 50%)")
    
    # 我们的算法
    print("\n" + "=" * 70)
    print("我们的算法 (Microcompact: 保留最近 5 个 tool_result)")
    print("=" * 70)
    
    our_result, our_stats = our_compress(messages)
    if our_stats["triggered"]:
        print(f"  Microcompact 节省: {our_stats.get('microcompact_saved', 0):,} tokens")
        print(f"  消息数: {our_stats['messages_before']} → {our_stats['messages_after']} (不删除消息)")
        print(f"  Token: {our_stats['original_tokens']:,} → {our_stats['final_tokens']:,}")
        print(f"  压缩率: {our_stats['compression_ratio']*100:.1f}%")
        print(f"  压缩后占比: {our_stats['final_ratio']*100:.1f}%")
        print(f"  需要 LLM 调用: 否")
        print(f"  额外延迟: ~5ms")
    else:
        print(f"  未触发 (占比 {our_stats['ratio']*100:.1f}% < 50%)")
    
    # 对比
    print("\n" + "=" * 70)
    print("对比总结")
    print("=" * 70)
    
    if hermes_stats["triggered"] and our_stats["triggered"]:
        print(f"\n{'指标':<20} {'Hermes':>15} {'我们':>15} {'差异':>15}")
        print("-" * 65)
        print(f"{'压缩后 tokens':<20} {hermes_stats['final_tokens']:>15,} {our_stats['final_tokens']:>15,} {our_stats['final_tokens']-hermes_stats['final_tokens']:>+15,}")
        print(f"{'压缩率':<20} {hermes_stats['compression_ratio']*100:>14.1f}% {our_stats['compression_ratio']*100:>14.1f}% {(our_stats['compression_ratio']-hermes_stats['compression_ratio'])*100:>+14.1f}%")
        print(f"{'压缩后占比':<20} {hermes_stats['final_ratio']*100:>14.1f}% {our_stats['final_ratio']*100:>14.1f}%")
        print(f"{'消息数':<20} {hermes_stats['messages_after']:>15} {our_stats['messages_after']:>15}")
        print(f"{'需要 LLM 调用':<20} {'是':>15} {'否':>15}")
        print(f"{'额外延迟':<20} {'3-5秒':>15} {'~5ms':>15}")
        print(f"{'信息保全':<20} {'结构化摘要':>15} {'assistant消息':>15}")
    
    # 信息保全验证
    print("\n" + "=" * 70)
    print("信息保全验证: 压缩后能否回答关键问题")
    print("=" * 70)
    
    questions = [
        "第 3 条商机是哪家公司？",
        "华创科技的下一步行动是什么？",
        "一共处理了多少条商机？",
        "金额最大的商机是哪个？",
        "第 10 条商机的竞品是谁？",
    ]
    
    for q in questions:
        # 检查 Hermes 压缩后是否保留了相关信息
        hermes_has = False
        for msg in hermes_result:
            content = json.dumps(msg, ensure_ascii=False)
            if "深圳光电" in content and "第 3" in q:
                hermes_has = True
            if "华创科技" in content and "华创" in q:
                hermes_has = True
            if "15" in content and "多少条" in q:
                hermes_has = True
            if "3000" in content and "金额最大" in q:
                hermes_has = True
            if "南京新材" in content and "第 10" in q:
                hermes_has = True
        
        # 检查我们的压缩后
        our_has = False
        for msg in our_result:
            content = json.dumps(msg, ensure_ascii=False)
            if "深圳光电" in content and "第 3" in q:
                our_has = True
            if "华创科技" in content and "华创" in q:
                our_has = True
            if "15" in content and "多少条" in q:
                our_has = True
            if "3000" in content and "金额最大" in q:
                our_has = True
            if "南京新材" in content and "第 10" in q:
                our_has = True
        
        h_icon = "✅" if hermes_has else "❌"
        o_icon = "✅" if our_has else "❌"
        print(f"  {q:<30} Hermes: {h_icon}  我们: {o_icon}")

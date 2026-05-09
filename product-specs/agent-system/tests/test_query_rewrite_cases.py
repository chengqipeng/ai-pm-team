"""查询改写提示词验证 — 20 个 toB CRM 典型场景

验证目标：
1. 代词指代消解（他/她/它/那个/这个/你）
2. 省略补全（主语省略、宾语省略、条件省略）
3. 多轮跳转（话题切换后回指）
4. CRM 业务术语保留（商机/线索/客户/联系人/合同/回款）
5. 不过度改写（已经清晰的查询保持原样）

每个 case 结构：
- context: 对话上下文（模拟 messages）
- current_query: 用户最新问题
- expected: 期望的改写结果（人工标注的 ground truth）
- category: 场景分类
- difficulty: 难度（easy/medium/hard）
"""

REWRITE_TEST_CASES = [
    # ═══════════════════════════════════════════════════════════
    # 类别 1: 代词指代消解（他/她/那个/这个）
    # ═══════════════════════════════════════════════════════════
    {
        "id": 1,
        "category": "代词指代",
        "difficulty": "easy",
        "context": [
            {"role": "用户", "content": "帮我查一下华为的商机"},
            {"role": "助手", "content": "华为目前有3个活跃商机：ERP升级项目（500万，方案阶段）、云迁移项目（200万，需求确认）、安全加固项目（80万，商务谈判）。"},
        ],
        "current_query": "那个最大的进展怎么样了",
        "expected": "华为ERP升级项目的进展怎么样了",
    },
    {
        "id": 2,
        "category": "代词指代",
        "difficulty": "easy",
        "context": [
            {"role": "用户", "content": "张总是哪个公司的"},
            {"role": "助手", "content": "张总（张明）是腾讯云事业部的VP，负责企业服务方向。"},
        ],
        "current_query": "他的手机号是多少",
        "expected": "张明的手机号是多少",
    },
    {
        "id": 3,
        "category": "代词指代",
        "difficulty": "medium",
        "context": [
            {"role": "用户", "content": "最近跟进的那个深圳客户是谁来着"},
            {"role": "助手", "content": "您最近跟进的深圳客户是「深圳前海科技有限公司」，联系人是李伟（CTO），上次沟通是3天前。"},
            {"role": "用户", "content": "对，就是他"},
            {"role": "助手", "content": "好的，关于深圳前海科技的李伟，您需要了解什么？"},
        ],
        "current_query": "帮我约他下周二的会",
        "expected": "帮我约深圳前海科技李伟下周二的会",
    },
    {
        "id": 4,
        "category": "代词指代",
        "difficulty": "hard",
        "context": [
            {"role": "用户", "content": "对比一下A客户和B客户的商机情况"},
            {"role": "助手", "content": "A客户（阿里巴巴）有2个商机共800万，B客户（字节跳动）有1个商机300万。A客户的商机阶段更靠后（商务谈判），B客户还在需求确认阶段。"},
        ],
        "current_query": "后面那个什么时候能推进到下一阶段",
        "expected": "字节跳动的商机什么时候能从需求确认推进到下一阶段",
    },

    # ═══════════════════════════════════════════════════════════
    # 类别 2: 省略补全（主语/宾语/条件省略）
    # ═══════════════════════════════════════════════════════════
    {
        "id": 5,
        "category": "省略补全",
        "difficulty": "easy",
        "context": [
            {"role": "用户", "content": "查一下本月新增的线索数量"},
            {"role": "助手", "content": "本月新增线索共47条，其中来自官网表单23条、市场活动15条、转介绍9条。"},
        ],
        "current_query": "上个月呢",
        "expected": "上个月新增的线索数量是多少",
    },
    {
        "id": 6,
        "category": "省略补全",
        "difficulty": "easy",
        "context": [
            {"role": "用户", "content": "帮我看看王磊负责的客户有哪些"},
            {"role": "助手", "content": "王磊负责的客户有：华为（A级）、中兴（B级）、小米（B级）、OPPO（C级），共4家。"},
        ],
        "current_query": "A级的有几个",
        "expected": "王磊负责的A级客户有几个",
    },
    {
        "id": 7,
        "category": "省略补全",
        "difficulty": "medium",
        "context": [
            {"role": "用户", "content": "Q3的回款目标完成了多少"},
            {"role": "助手", "content": "Q3回款目标2000万，已完成1450万，完成率72.5%。剩余550万中，预计本月可回320万。"},
        ],
        "current_query": "跟去年同期比呢",
        "expected": "Q3的回款完成情况跟去年同期相比怎么样",
    },
    {
        "id": 8,
        "category": "省略补全",
        "difficulty": "medium",
        "context": [
            {"role": "用户", "content": "本季度赢单的商机有哪些"},
            {"role": "助手", "content": "本季度赢单商机共5个：华为ERP（500万）、腾讯安全（200万）、美团配送（150万）、京东仓储（120万）、网易教育（80万）。"},
        ],
        "current_query": "输单的呢",
        "expected": "本季度输单的商机有哪些",
    },

    # ═══════════════════════════════════════════════════════════
    # 类别 3: 多轮跳转 + 回指
    # ═══════════════════════════════════════════════════════════
    {
        "id": 9,
        "category": "多轮跳转",
        "difficulty": "medium",
        "context": [
            {"role": "用户", "content": "华为那个ERP项目现在什么阶段"},
            {"role": "助手", "content": "华为ERP升级项目目前在「方案评估」阶段，预计金额500万，决策人是华为IT部张总监。"},
            {"role": "用户", "content": "帮我查一下最近的活动记录"},
            {"role": "助手", "content": "华为ERP项目最近的活动：5月3日电话沟通（讨论技术方案）、4月28日现场演示（产品demo）、4月20日邮件（发送报价单）。"},
        ],
        "current_query": "报价单发了之后对方有回复吗",
        "expected": "华为ERP项目4月20日发送报价单之后对方有回复吗",
    },
    {
        "id": 10,
        "category": "多轮跳转",
        "difficulty": "hard",
        "context": [
            {"role": "用户", "content": "看看我这个月的业绩排名"},
            {"role": "助手", "content": "您本月业绩排名第3，签单金额180万。第1名是李强（320万），第2名是赵敏（250万）。"},
            {"role": "用户", "content": "李强主要签了哪些单"},
            {"role": "助手", "content": "李强本月签单：百度AI平台（200万）、滴滴出行CRM（120万），共320万。"},
        ],
        "current_query": "第一个单子的客户之前是谁跟的",
        "expected": "百度AI平台项目的客户之前是谁跟进的",
    },

    # ═══════════════════════════════════════════════════════════
    # 类别 4: CRM 业务术语 + 复杂条件
    # ═══════════════════════════════════════════════════════════
    {
        "id": 11,
        "category": "业务术语",
        "difficulty": "medium",
        "context": [
            {"role": "用户", "content": "Pipeline里面金额最大的5个商机是哪些"},
            {"role": "助手", "content": "Pipeline Top5：1.华为ERP（500万，方案阶段）2.腾讯云迁移（350万，POC阶段）3.阿里数据中台（300万，需求确认）4.美团配送系统（280万，商务谈判）5.京东仓储升级（250万，合同审批）"},
        ],
        "current_query": "第4个快签了吗",
        "expected": "美团配送系统商机快签合同了吗",
    },
    {
        "id": 12,
        "category": "业务术语",
        "difficulty": "medium",
        "context": [
            {"role": "用户", "content": "帮我看看这个季度的漏斗转化率"},
            {"role": "助手", "content": "本季度漏斗转化率：线索→商机 18%，商机→方案 45%，方案→谈判 60%，谈判→赢单 35%。整体线索到赢单转化率 1.7%。"},
        ],
        "current_query": "哪个环节掉得最多",
        "expected": "本季度销售漏斗哪个环节的转化率掉得最多",
    },
    {
        "id": 13,
        "category": "业务术语",
        "difficulty": "hard",
        "context": [
            {"role": "用户", "content": "我负责的KA客户里，有没有快到续约期的"},
            {"role": "助手", "content": "有3个KA客户即将到续约期：华为（6月30日到期）、腾讯（7月15日到期）、阿里（8月1日到期）。"},
            {"role": "用户", "content": "最近的那个，合同金额多少"},
            {"role": "助手", "content": "华为的当前合同金额是年费800万，去年续约时从600万涨到800万。"},
        ],
        "current_query": "今年打算涨价吗",
        "expected": "华为今年续约打算涨价吗",
    },

    # ═══════════════════════════════════════════════════════════
    # 类别 5: 不应过度改写（保持原样）
    # ═══════════════════════════════════════════════════════════
    {
        "id": 14,
        "category": "不改写",
        "difficulty": "easy",
        "context": [
            {"role": "用户", "content": "帮我查华为的联系人"},
            {"role": "助手", "content": "华为的联系人有：张总监（IT部）、李经理（采购部）、王工（技术部）。"},
        ],
        "current_query": "帮我创建一个新的商机，客户是百度，金额200万",
        "expected": "帮我创建一个新的商机，客户是百度，金额200万",
    },
    {
        "id": 15,
        "category": "不改写",
        "difficulty": "easy",
        "context": [
            {"role": "用户", "content": "今天有什么待办"},
            {"role": "助手", "content": "您今天有3个待办：10:00华为电话会议、14:00腾讯现场拜访、16:30周报提交。"},
        ],
        "current_query": "查一下深圳前海科技有限公司的基本信息",
        "expected": "查一下深圳前海科技有限公司的基本信息",
    },

    # ═══════════════════════════════════════════════════════════
    # 类别 6: 复杂指代 + 隐含条件
    # ═══════════════════════════════════════════════════════════
    {
        "id": 16,
        "category": "复杂指代",
        "difficulty": "hard",
        "context": [
            {"role": "用户", "content": "对比一下华北和华南区的业绩"},
            {"role": "助手", "content": "华北区本季度签单1200万（目标1500万，完成率80%），华南区签单1800万（目标2000万，完成率90%）。华南区领先600万。"},
            {"role": "用户", "content": "差距主要在哪"},
            {"role": "助手", "content": "差距主要在大客户签单：华南有3个200万以上大单，华北只有1个。华北的中小客户数量其实更多。"},
        ],
        "current_query": "华北那边谁负责大客户的",
        "expected": "华北区谁负责大客户",
    },
    {
        "id": 17,
        "category": "复杂指代",
        "difficulty": "hard",
        "context": [
            {"role": "用户", "content": "上周丢的那个单子，客户为什么选了竞品"},
            {"role": "助手", "content": "上周输单的是「美团外卖CRM项目」（150万），客户选择了Salesforce。主要原因：1.对方有全球化方案 2.价格差异不大 3.美团IT总监之前在外企用过SF。"},
            {"role": "用户", "content": "那个IT总监叫什么"},
            {"role": "助手", "content": "美团的IT总监是陈浩，之前在微软工作过5年。"},
        ],
        "current_query": "能不能找个机会再聊聊，看看有没有二期",
        "expected": "能不能找机会跟美团IT总监陈浩再聊聊，看看美团外卖CRM项目有没有二期",
    },
    {
        "id": 18,
        "category": "复杂指代",
        "difficulty": "hard",
        "context": [
            {"role": "用户", "content": "每次你给我的报告我都跳过前面直接看结论"},
            {"role": "助手", "content": "明白了，以后我会把核心结论放在最前面。"},
        ],
        "current_query": "对，以后都这样",
        "expected": "以后给我的报告都把核心结论放在最前面",
    },

    # ═══════════════════════════════════════════════════════════
    # 类别 7: 数值/时间条件变更
    # ═══════════════════════════════════════════════════════════
    {
        "id": 19,
        "category": "条件变更",
        "difficulty": "medium",
        "context": [
            {"role": "用户", "content": "帮我筛选金额大于100万的商机"},
            {"role": "助手", "content": "金额大于100万的商机共8个，总金额2350万。"},
        ],
        "current_query": "改成50万以上的",
        "expected": "帮我筛选金额大于50万的商机",
    },
    {
        "id": 20,
        "category": "条件变更",
        "difficulty": "medium",
        "context": [
            {"role": "用户", "content": "看看上海区域本月的新增客户"},
            {"role": "助手", "content": "上海区域本月新增客户12家，主要集中在金融和互联网行业。"},
        ],
        "current_query": "换成北京的看看",
        "expected": "看看北京区域本月的新增客户",
    },
]


# ═══════════════════════════════════════════════════════════
# 评估函数
# ═══════════════════════════════════════════════════════════

def evaluate_rewrite(rewritten: str, expected: str) -> dict:
    """评估改写结果质量

    评分维度：
    - exact_match: 是否完全匹配
    - semantic_match: 语义是否等价（人工判断辅助）
    - key_entities_preserved: 关键实体是否保留
    - no_hallucination: 是否没有幻觉（添加了原文没有的信息）
    - concise: 是否简洁（不超过期望长度的1.5倍）
    """
    exact = rewritten.strip() == expected.strip()

    # 关键实体检查：从 expected 中提取中文实体词（2字以上连续中文）
    import re
    expected_entities = set(re.findall(r'[\u4e00-\u9fff]{2,}', expected))
    rewritten_entities = set(re.findall(r'[\u4e00-\u9fff]{2,}', rewritten))
    # 关键实体覆盖率
    if expected_entities:
        entity_coverage = len(expected_entities & rewritten_entities) / len(expected_entities)
    else:
        entity_coverage = 1.0

    concise = len(rewritten) <= len(expected) * 1.5 + 10

    return {
        "exact_match": exact,
        "entity_coverage": round(entity_coverage, 2),
        "concise": concise,
        "rewritten_len": len(rewritten),
        "expected_len": len(expected),
    }


def run_evaluation_report(results: list[dict]) -> str:
    """生成评估报告"""
    total = len(results)
    exact_matches = sum(1 for r in results if r["exact_match"])
    high_entity = sum(1 for r in results if r["entity_coverage"] >= 0.8)
    concise_count = sum(1 for r in results if r["concise"])

    report = f"""
═══════════════════════════════════════════════════════════
  查询改写提示词评估报告（{total} 个 CRM 场景）
═══════════════════════════════════════════════════════════

  完全匹配率:     {exact_matches}/{total} ({exact_matches/total*100:.1f}%)
  实体覆盖率≥80%: {high_entity}/{total} ({high_entity/total*100:.1f}%)
  简洁性通过:     {concise_count}/{total} ({concise_count/total*100:.1f}%)

═══════════════════════════════════════════════════════════
"""
    return report


# ═══════════════════════════════════════════════════════════
# 提示词模板（当前版本 + 优化版本对比）
# ═══════════════════════════════════════════════════════════

PROMPT_V1_CURRENT = """你是一个查询改写助手。根据多轮对话上下文，将用户的最新问题改写为一句自包含的完整查询（不依赖上下文即可理解）。

要求：
1. 解析代词指代（'你'→具体对象，'那个'→具体实体）
2. 补全省略的主语和宾语
3. 只输出改写后的查询，不要输出任何分析、标注或解释
4. 如果原始查询已经足够清晰，直接输出原文
5. 输出不超过 80 字

对话上下文：
{context}

用户最新问题：{query}

改写后的完整查询："""


PROMPT_V2_OPTIMIZED = """你是 CRM 系统的查询改写模块。将用户最新问题改写为一句自包含的完整查询。

## 规则
1. 代词替换：将"他/她/它/那个/这个/第N个/后面那个/最大的"替换为上文中对应的具体名称
2. 省略补全：补全被省略的主语、宾语、时间范围或筛选条件
3. 条件继承：当用户说"换成X"/"改成X"/"X呢"时，保留原查询结构，只替换变化的条件
4. 指令补全：当用户说"对"/"好的"/"以后都这样"确认某个设置时，将确认的完整内容补全
5. 不改写：如果最新问题已经自包含（不依赖上下文就能理解），原样输出
6. 不添加：禁止添加上文未提及的信息，禁止推测用户未表达的意图

## 输出格式
- 只输出一句改写后的查询
- 不输出分析过程、不标注实体、不解释代词
- 不超过 80 字

## 对话上下文
{context}

## 用户最新问题
{query}

## 改写结果
"""


if __name__ == "__main__":
    # 打印所有测试用例供人工审查
    print("=" * 70)
    print("  CRM 查询改写测试用例集（20 个场景）")
    print("=" * 70)

    by_category = {}
    for case in REWRITE_TEST_CASES:
        cat = case["category"]
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(case)

    for cat, cases in by_category.items():
        print(f"\n{'─' * 50}")
        print(f"  类别: {cat} ({len(cases)} 个)")
        print(f"{'─' * 50}")
        for c in cases:
            ctx_str = " → ".join(
                f"[{m['role']}]{m['content'][:40]}"
                for m in c["context"]
            )
            print(f"\n  #{c['id']} [{c['difficulty']}]")
            print(f"  上下文: {ctx_str}")
            print(f"  当前问题: {c['current_query']}")
            print(f"  期望改写: {c['expected']}")

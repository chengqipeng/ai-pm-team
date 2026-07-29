"""1000 条评测用例数据集 — 84 轮种子 + 1000 条用例 (turn_id 全对齐)

种子数据: 15 客户 × 84 轮对话 (复用 eval_extended_data)
客户→turn_id 映射:
  客户 1  PT Sentosa:  1~6    | 客户 2  CV XYZ:     7~10
  客户 3  华为科技:   11~16   | 客户 4  腾讯云:    17~21
  客户 5  比亚迪:    22~24   | 汇总:             25~30
  客户 6  阿里云:    31~40   | 客户 7  京东:      41~45
  客户 8  美团:     46~49   | 客户 9  百度:      50~56
  客户 10 字节跳动:  57~62   | 客户 11 网易:      63~67
  客户 12 滴滴:     68~72   | 客户 13 小红书:    73~75
  客户 14 拼多多:    76~80   | 客户 15 携程:      81~84

用例分布 (12 类 × 1000 条):
  - 干扰区分 (120) | 意图推理 (100) | 否定排除 (80) | 多跳推理 (100)
  - 长尾定位 (100) | 精确实体 (120) | 模糊语义 (100) | 变更追踪 (80)
  - 决策追踪 (60)  | 负例验证 (80)  | 时效性 (30)   | 跨客户汇总 (30)

用例文件拆分:
  eval_1000cases_part1.py — 干扰区分 + 意图推理 (220)
  eval_1000cases_part2.py — 否定排除 + 多跳推理 (180)
  eval_1000cases_part3.py — 长尾定位 + 精确实体 (220)
  eval_1000cases_part4.py — 模糊语义 + 变更追踪 + 决策追踪 + 负例 + 时效性 + 跨客户 (380)

运行: from eval_1000cases_data import build_1000_seed, build_1000_cases, Case
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Case:
    id: str
    category: str
    query: str
    expected_turns: list[int] = field(default_factory=list)
    expect_no_hit: bool = False


# ═══════════════════════════════════════════════════════════
# 种子数据 — 84 轮 (20 客户)
# ═══════════════════════════════════════════════════════════

def build_1000_seed() -> list[dict]:
    """构造 84 轮对话（15 客户）— turn_id 1~84

    直接复用 eval_extended_data 的完整 84 轮数据集:
      客户 1~5 (turn 1~30):  PT Sentosa, CV XYZ, 华为科技, 腾讯云, 比亚迪
      客户 6~10 (turn 31~62): 阿里云, 京东, 美团, 百度, 字节跳动
      客户 11~15 (turn 63~84): 网易, 滴滴, 小红书, 拼多多, 携程
    """
    from eval_extended_data import build_extended_seed
    turns = build_extended_seed()
    assert len(turns) == 84, f"Expected 84 turns, got {len(turns)}"
    return turns


# ═══════════════════════════════════════════════════════════
# 用例汇总
# ═══════════════════════════════════════════════════════════

def build_1000_cases() -> list[Case]:
    """汇总 1000 条用例（从 4 个分片文件加载）"""
    from eval_1000cases_part1 import build_cases_part1
    from eval_1000cases_part2 import build_cases_part2
    from eval_1000cases_part3 import build_cases_part3
    from eval_1000cases_part4 import build_cases_part4

    cases = []
    cases += build_cases_part1()
    cases += build_cases_part2()
    cases += build_cases_part3()
    cases += build_cases_part4()

    assert len(cases) == 1000, f"Expected 1000 cases, got {len(cases)}"
    # 验证 id 唯一性
    ids = [c.id for c in cases]
    assert len(ids) == len(set(ids)), f"Duplicate case IDs found"
    return cases


# ═══════════════════════════════════════════════════════════
# 快捷入口
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    seed = build_1000_seed()
    cases = build_1000_cases()
    print(f"✅ 种子数据: {len(seed)} 轮 (turn_id {seed[0]['turn_id']}~{seed[-1]['turn_id']})")
    print(f"✅ 评测用例: {len(cases)} 条")

    # 验证所有 expected_turns 都在 seed 范围内
    valid_tids = {t["turn_id"] for t in seed}
    invalid = []
    for c in cases:
        for tid in c.expected_turns:
            if tid not in valid_tids:
                invalid.append((c.id, tid))
    if invalid:
        print(f"❌ 引用了无效的 turn_id: {invalid[:10]}...")
    else:
        print(f"✅ 所有 expected_turns 均在 [1, 84] 范围内")

    # 分类统计
    cats = {}
    for c in cases:
        cats[c.category] = cats.get(c.category, 0) + 1
    print(f"\n📊 分类分布:")
    for cat, cnt in sorted(cats.items(), key=lambda x: -x[1]):
        print(f"   {cat:<10} {cnt:>4} 条")

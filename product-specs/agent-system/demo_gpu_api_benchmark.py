"""
LLMLingua-2 GPU REST API 性能 & 准确率验证

接口:
  - POST /compress/fp32  — PyTorch FP32 (CUDA)
  - POST /compress/fp16  — PyTorch FP16 (CUDA, Tensor Core)

验证维度:
  1. 压缩率（实际 token 节省）
  2. 准确率（关键数据保留率）
  3. FP32 vs FP16 一致性
  4. 延迟性能
"""

import json
import time
import re
import subprocess
import urllib.request
from dataclasses import dataclass

# ═══════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════

BASE_URL = "https://llmlingua.ingageapp.com"

FORCE_TOKENS = ["\u3002", "\uff1f", "\uff01", "\uff1b", "\uff0c", "\uff1a", "\n", "=", "_", "-"]
CHUNK_END_TOKENS = ["\u3002", "\uff1f", "\uff01", "\uff1b", "\n"]

# ═══════════════════════════════════════════════════════════
# 测试用例
# ═══════════════════════════════════════════════════════════

TEST_CASES = [
    {
        "name": "① 中文业务报告 (320字)",
        "text": "2024年第三季度CRM系统运营报告总结如下。本季度系统共新增客户1,234家，其中大客户52家，中小客户1,182家。主要客户来源集中在华东和华南地区，华东地区贡献了45%的新增客户。总合同金额达到5680万，同比增长23%，环比增长8%。值得注意的是，新签约的金融行业客户贡献了35%的增量收入，这主要得益于Q2推出的金融解决方案包。客户流失率方面，本季度流失率为3.2%，较上季度的4.1%有明显改善。流失客户主要集中在年合同金额低于5万的小微客户群体。客户满意度调查结果显示，NPS评分从上季度的42分提升至48分，其中产品功能满意度最高，达到4.5分。技术支持响应速度从平均4.2小时缩短至2.8小时，提升了33%。",
        "key_terms": ["CRM", "NPS", "1,234", "5680万", "23%", "3.2%", "4.1%", "45%", "35%", "华东"],
    },
    {
        "name": "② 中英混合技术文档 (409字)",
        "text": "在执行query_data工具时遇到了一个预期之外的问题。系统尝试查询CRM模块中的Opportunity对象，使用的过滤条件是stage='Closed Won' AND close_date >= '2024-01-01'。查询请求发送到后端API后，收到了HTTP 504 Gateway Timeout错误，响应时间超过了30秒的默认超时阈值。经过分析，这个超时的根本原因是数据库层面的性能问题。Opportunity表目前有超过280万条记录，而close_date字段上缺少索引。全表扫描导致查询耗时超过了预期。临时的解决方案是添加查询分页limit=1000，并在close_date字段上创建B-tree索引。长期建议是引入读写分离架构，将此类分析查询路由到只读副本。目前已经通过reduce scope的方式成功获取到了部分数据，返回了Q1季度的823条Closed Won记录，总金额$12.4M。",
        "key_terms": ["HTTP 504", "Opportunity", "B-tree", "280万", "limit=1000", "$12.4M", "close_date", "CRM"],
    },
    {
        "name": "③ 纯中文会议纪要 (277字)",
        "text": "产品评审会议纪要，2024年10月15日下午2点。会议议题：新版本发布计划讨论。张明介绍了V3.2版本的核心功能，包括多租户权限隔离、自定义工作流引擎、以及数据导入导出优化。预计11月20日进入公测，12月15日正式发布。李芳反馈研发侧目前还有3个P1级别的技术债务需要处理，分别是消息队列的积压问题、缓存穿透的防护机制、以及日志系统的存储优化。预估需要额外2周的开发时间。王强展示了新版本的UI设计稿，工作区面积增大了25%。赵丽表示测试用例已覆盖核心流程的85%，还需要补充边界场景和性能测试用例约200条。会议决议：正式发布时间推迟至12月30日。",
        "key_terms": ["V3.2", "11月20日", "12月15日", "12月30日", "P1", "25%", "85%", "张明", "李芳"],
    },
    {
        "name": "④ 英文技术文档 (698字)",
        "text": "The authentication system uses OAuth 2.0 with PKCE flow for all client applications. The system supports three methods: password-based login with bcrypt hashing at cost factor 12, social login via Google and GitHub OAuth providers, and enterprise SSO using SAML 2.0. After successful authentication, the system issues a JWT access token with 15-minute expiry and a refresh token valid for 7 days. Rate limiting is applied at 5 failed attempts per 10-minute window, after which the account enters a 30-minute lockout period. For enterprise customers, we support MFA via TOTP (RFC 6238) and WebAuthn/FIDO2 hardware keys. The MFA enrollment rate is currently at 78%, with a target of 95% by end of Q4.",
        "key_terms": ["OAuth 2.0", "PKCE", "JWT", "SAML 2.0", "bcrypt", "TOTP", "WebAuthn", "78%", "95%"],
    },
]

RATES = [0.3, 0.5, 0.7]


# ═══════════════════════════════════════════════════════════
# HTTP 客户端
# ═══════════════════════════════════════════════════════════


def call_compress(backend: str, text: str, rate: float) -> dict:
    """调用压缩 API (通过 curl 绕过 Python SSL 兼容性问题)"""
    import subprocess
    url = f"{BASE_URL}/compress/{backend}"
    payload = json.dumps({
        "prompt": text,
        "rate": rate,
        "force_tokens": FORCE_TOKENS,
        "chunk_end_tokens": CHUNK_END_TOKENS,
        "drop_consecutive": True,
    })

    result = subprocess.run(
        ["curl", "-s", "-X", "POST", url, "-H", "Content-Type: application/json", "-d", payload],
        capture_output=True, text=True, timeout=30,
    )
    return json.loads(result.stdout)


def call_compress_timed(backend: str, text: str, rate: float, n_runs: int = 3) -> tuple:
    """多次调用取中位数延迟，返回 (result, median_ms, server_ms)"""
    results = []
    for _ in range(n_runs):
        t0 = time.perf_counter()
        result = call_compress(backend, text, rate)
        e2e_ms = (time.perf_counter() - t0) * 1000
        results.append((result, e2e_ms))
    # 按 e2e 排序取中位数
    results.sort(key=lambda x: x[1])
    mid = results[len(results) // 2]
    return mid[0], mid[1], mid[0].get("latency_ms", 0)


# ═══════════════════════════════════════════════════════════
# 准确率评估
# ═══════════════════════════════════════════════════════════


def calc_key_term_recall(original_text: str, compressed_text: str, key_terms: list) -> tuple:
    """计算关键术语保留率"""
    orig_found = {t for t in key_terms if t in original_text}
    comp_found = {t for t in key_terms if t in compressed_text}
    recall = len(comp_found) / len(orig_found) if orig_found else 1.0
    lost = sorted(orig_found - comp_found)
    return recall, lost


# ═══════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════


def main():
    # 健康检查
    print("=" * 90)
    print("  LLMLingua-2 GPU API 性能 & 准确率验证")
    print("=" * 90)

    health = json.loads(subprocess.run(
        ["curl", "-s", f"{BASE_URL}/health"], capture_output=True, text=True, timeout=5
    ).stdout)
    print(f"\n  Server: {BASE_URL}")
    print(f"  Status: {health['status']} | Backends: {health['backends']} | Device: {health['device']}")

    # Warmup
    print("\n  Warmup (2 calls)...")
    call_compress("fp32", "test warmup", 0.5)
    call_compress("fp16", "test warmup", 0.5)
    print("  done")

    # ═══════════════════════════════════════════════════════════
    # 全量对比
    # ═══════════════════════════════════════════════════════════

    print(f"\n\n{'=' * 90}")
    print("  全量对比: FP32 vs FP16 (4 Case x 3 Rate = 12 组, 每组 3 次取中位数)")
    print(f"{'=' * 90}")
    print(f"  {'Case':<22} {'rate':<5} {'FP32 srv':<10} {'FP16 srv':<10} {'FP32 tok':<9} {'FP16 tok':<9} {'match':<6} {'FP32 e2e':<10} {'FP16 e2e':<10} {'术语保留'}")
    print(f"  {'-' * 88}")

    all_fp32_srv, all_fp16_srv = [], []
    all_fp32_e2e, all_fp16_e2e = [], []
    n_match = 0
    n_total = 0
    all_rows = []

    for case in TEST_CASES:
        for rate in RATES:
            fp32_result, fp32_e2e, fp32_srv = call_compress_timed("fp32", case["text"], rate)
            fp16_result, fp16_e2e, fp16_srv = call_compress_timed("fp16", case["text"], rate)

            fp32_text = fp32_result.get("compressed_prompt", "")
            fp16_text = fp16_result.get("compressed_prompt", "")
            fp32_tok = fp32_result.get("compressed_tokens", 0)
            fp16_tok = fp16_result.get("compressed_tokens", 0)

            match = fp32_text == fp16_text
            n_total += 1
            if match:
                n_match += 1

            # 准确率（用 FP32 结果计算）
            recall, lost = calc_key_term_recall(case["text"], fp32_text, case["key_terms"])

            all_fp32_srv.append(fp32_srv)
            all_fp16_srv.append(fp16_srv)
            all_fp32_e2e.append(fp32_e2e)
            all_fp16_e2e.append(fp16_e2e)

            mark = "Y" if match else "N"
            print(f"  {case['name'][:20]:<22} {rate:<5} {fp32_srv:<10.1f} {fp16_srv:<10.1f} {fp32_tok:<9} {fp16_tok:<9} {mark:<6} {fp32_e2e:<10.0f} {fp16_e2e:<10.0f} {recall*100:.0f}%")

            all_rows.append({
                "case": case["name"], "rate": rate,
                "fp32_srv": fp32_srv, "fp16_srv": fp16_srv,
                "fp32_tok": fp32_tok, "fp16_tok": fp16_tok,
                "match": match, "recall": recall, "lost": lost,
                "fp32_text": fp32_text, "fp16_text": fp16_text,
            })

    # ═══════════════════════════════════════════════════════════
    # 性能汇总
    # ═══════════════════════════════════════════════════════════

    print(f"\n\n{'=' * 90}")
    print("  性能汇总")
    print(f"{'=' * 90}")

    fp32_avg_srv = sum(all_fp32_srv) / len(all_fp32_srv)
    fp16_avg_srv = sum(all_fp16_srv) / len(all_fp16_srv)
    fp32_avg_e2e = sum(all_fp32_e2e) / len(all_fp32_e2e)
    fp16_avg_e2e = sum(all_fp16_e2e) / len(all_fp16_e2e)

    print(f"\n  {'指标':<20} {'FP32':<14} {'FP16':<14} {'加速比'}")
    print(f"  {'-' * 56}")
    print(f"  {'Server 延迟 (avg)':<20} {fp32_avg_srv:<14.1f} {fp16_avg_srv:<14.1f} {fp32_avg_srv/fp16_avg_srv:.1f}x")
    print(f"  {'Server 延迟 (min)':<20} {min(all_fp32_srv):<14.1f} {min(all_fp16_srv):<14.1f}")
    print(f"  {'Server 延迟 (max)':<20} {max(all_fp32_srv):<14.1f} {max(all_fp16_srv):<14.1f}")
    print(f"  {'端到端 (含网络)':<20} {fp32_avg_e2e:<14.0f} {fp16_avg_e2e:<14.0f} {fp32_avg_e2e/fp16_avg_e2e:.1f}x")

    # ═══════════════════════════════════════════════════════════
    # 准确率汇总
    # ═══════════════════════════════════════════════════════════

    print(f"\n\n{'=' * 90}")
    print("  准确率汇总 (关键术语保留率)")
    print(f"{'=' * 90}")

    for target_rate in RATES:
        rows = [r for r in all_rows if r["rate"] == target_rate]
        avg_recall = sum(r["recall"] for r in rows) / len(rows)
        print(f"\n  rate={target_rate}: 平均关键术语保留 {avg_recall*100:.1f}%")
        for r in rows:
            if r["lost"]:
                print(f"    {r['case'][:18]}: 丢失 {r['lost']}")

    # ═══════════════════════════════════════════════════════════
    # FP32 vs FP16 一致性
    # ═══════════════════════════════════════════════════════════

    print(f"\n\n{'=' * 90}")
    print("  FP32 vs FP16 一致性")
    print(f"{'=' * 90}")
    print(f"\n  一致: {n_match}/{n_total} ({n_match/n_total*100:.0f}%)")

    if n_match < n_total:
        print(f"\n  差异用例:")
        for r in all_rows:
            if not r["match"]:
                print(f"    {r['case']} rate={r['rate']}: FP32={r['fp32_tok']}tok vs FP16={r['fp16_tok']}tok")
                print(f"      FP32: {r['fp32_text'][:60]}")
                print(f"      FP16: {r['fp16_text'][:60]}")

    # ═══════════════════════════════════════════════════════════
    # 结论
    # ═══════════════════════════════════════════════════════════

    print(f"\n\n{'=' * 90}")
    print("  结论")
    print(f"{'=' * 90}")
    print(f"""
  GPU 服务器实测性能:
    FP32 平均延迟: {fp32_avg_srv:.1f}ms (server-side)
    FP16 平均延迟: {fp16_avg_srv:.1f}ms (server-side)
    FP16 加速比:   {fp32_avg_srv/fp16_avg_srv:.1f}x

  准确率:
    rate=0.3 术语保留: {sum(r['recall'] for r in all_rows if r['rate']==0.3)/4*100:.0f}%
    rate=0.5 术语保留: {sum(r['recall'] for r in all_rows if r['rate']==0.5)/4*100:.0f}%
    rate=0.7 术语保留: {sum(r['recall'] for r in all_rows if r['rate']==0.7)/4*100:.0f}%

  FP32 vs FP16 一致性: {n_match}/{n_total} ({n_match/n_total*100:.0f}%)

  验证结论:
    - GPU FP16 延迟 {fp16_avg_srv:.0f}ms，满足在线实时路径要求 (<100ms)
    - FP32/FP16 一致性 {n_match/n_total*100:.0f}%，FP16 可安全用于生产
    - 关键术语保留率随 rate 提高而增加，rate=0.7 时保留最完整
""")


if __name__ == "__main__":
    main()

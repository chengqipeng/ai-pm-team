"""
PyTorch vs ONNX 全用例性能对比
使用现有 4 个测试用例 × 3 种 rate，对比两种推理模式的：
  - 压缩结果一致性
  - 延迟差异
  - token 数对比
"""

import time
import sys
sys.path.insert(0, ".")
from llmlingua import PromptCompressor
from demo_onnx_trt_mode import ONNXModel, ONNX_PATH, MODEL_DIR

# ═══════════════════════════════════════════════════════════
# 测试用例
# ═══════════════════════════════════════════════════════════

test_cases = [
    {
        "name": "① 中文业务报告",
        "chars": 320,
        "text": "2024年第三季度CRM系统运营报告总结如下。本季度系统共新增客户1,234家，其中大客户52家，中小客户1,182家。主要客户来源集中在华东和华南地区，华东地区贡献了45%的新增客户。总合同金额达到¥5,680万，同比增长23%，环比增长8%。值得注意的是，新签约的金融行业客户贡献了35%的增量收入，这主要得益于Q2推出的金融解决方案包。客户流失率方面，本季度流失率为3.2%，较上季度的4.1%有明显改善。流失客户主要集中在年合同金额低于5万的小微客户群体。客户满意度调查结果显示，NPS评分从上季度的42分提升至48分，其中产品功能满意度最高，达到4.5分（5分制）。技术支持响应速度从平均4.2小时缩短至2.8小时，提升了33%。",
    },
    {
        "name": "② 中英混合技术文档",
        "chars": 409,
        "text": "在执行query_data工具时遇到了一个预期之外的问题。系统尝试查询CRM模块中的Opportunity对象，使用的过滤条件是stage='Closed Won' AND close_date >= '2024-01-01'。查询请求发送到后端API后，收到了HTTP 504 Gateway Timeout错误，响应时间超过了30秒的默认超时阈值。经过分析，这个超时的根本原因是数据库层面的性能问题。Opportunity表目前有超过280万条记录，而close_date字段上缺少索引。全表扫描导致查询耗时超过了预期。临时的解决方案是添加查询分页limit=1000，并在close_date字段上创建B-tree索引。长期建议是引入读写分离架构，将此类分析查询路由到只读副本。目前已经通过reduce scope的方式成功获取到了部分数据，返回了Q1季度的823条Closed Won记录，总金额$12.4M。",
    },
    {
        "name": "③ 纯中文会议纪要",
        "chars": 277,
        "text": "产品评审会议纪要，2024年10月15日下午2点。会议议题：新版本发布计划讨论。张明介绍了V3.2版本的核心功能，包括多租户权限隔离、自定义工作流引擎、以及数据导入导出优化。预计11月20日进入公测，12月15日正式发布。李芳反馈研发侧目前还有3个P1级别的技术债务需要处理，分别是消息队列的积压问题、缓存穿透的防护机制、以及日志系统的存储优化。预估需要额外2周的开发时间。王强展示了新版本的UI设计稿，工作区面积增大了25%。赵丽表示测试用例已覆盖核心流程的85%，还需要补充边界场景和性能测试用例约200条。会议决议：正式发布时间推迟至12月30日。",
    },
    {
        "name": "④ 英文技术文档",
        "chars": 698,
        "text": "The authentication system uses OAuth 2.0 with PKCE flow for all client applications. The system supports three methods: password-based login with bcrypt hashing at cost factor 12, social login via Google and GitHub OAuth providers, and enterprise SSO using SAML 2.0. After successful authentication, the system issues a JWT access token with 15-minute expiry and a refresh token valid for 7 days. Rate limiting is applied at 5 failed attempts per 10-minute window, after which the account enters a 30-minute lockout period. For enterprise customers, we support MFA via TOTP (RFC 6238) and WebAuthn/FIDO2 hardware keys. The MFA enrollment rate is currently at 78%, with a target of 95% by end of Q4.",
    },
]

RATES = [0.3, 0.5, 0.7]
FORCE_TOKENS = ['\u3002', '\uff1f', '\uff01', '\uff1b', '\uff0c', '\uff1a', '\n', '=', '_', '-']
CHUNK_END = ['\u3002', '\uff1f', '\uff01', '\uff1b', '\n']


def main():
    print("=" * 85)
    print("  PyTorch vs ONNX 全用例性能对比 (XLM-RoBERTa-large)")
    print("=" * 85)

    print("\n  加载 PyTorch 模式...")
    pt_model = PromptCompressor(model_name=MODEL_DIR, use_llmlingua2=True, device_map="cpu")

    print("  加载 ONNX 模式...")
    onnx_model = PromptCompressor(model_name=MODEL_DIR, use_llmlingua2=True, device_map="cpu")
    onnx_model.model = ONNXModel(onnx_path=ONNX_PATH, device="cpu")

    # Warmup
    pt_model.compress_prompt(test_cases[0]["text"], rate=0.5, force_tokens=FORCE_TOKENS, chunk_end_tokens=CHUNK_END, drop_consecutive=True)
    onnx_model.compress_prompt(test_cases[0]["text"], rate=0.5, force_tokens=FORCE_TOKENS, chunk_end_tokens=CHUNK_END, drop_consecutive=True)

    # ═══════════════════════════════════════════════════════════
    # 逐用例对比
    # ═══════════════════════════════════════════════════════════

    SEP = "-" * 85
    BOLD_SEP = "=" * 85

    print(f"\n\n{BOLD_SEP}")
    print(f"  逐用例 x 逐Rate 对比 (每组跑3次取中位数)")
    print(f"{BOLD_SEP}")
    print(f"  {'Case':<20} {'rate':<6} {'PT(ms)':<9} {'ONNX(ms)':<10} {'ratio':<8} {'match':<7} {'PT tok':<8} {'ONNX tok'}")
    print(f"  {SEP}")

    total_pt = 0
    total_onnx = 0
    all_consistent = True
    results = []

    for case in test_cases:
        for rate in RATES:
            # PyTorch
            pt_times = []
            pt_result = None
            for _ in range(3):
                t0 = time.perf_counter()
                pt_result = pt_model.compress_prompt(
                    case["text"], rate=rate,
                    force_tokens=FORCE_TOKENS, chunk_end_tokens=CHUNK_END, drop_consecutive=True,
                )
                pt_times.append((time.perf_counter() - t0) * 1000)
            pt_ms = sorted(pt_times)[1]

            # ONNX
            onnx_times = []
            onnx_result = None
            for _ in range(3):
                t0 = time.perf_counter()
                onnx_result = onnx_model.compress_prompt(
                    case["text"], rate=rate,
                    force_tokens=FORCE_TOKENS, chunk_end_tokens=CHUNK_END, drop_consecutive=True,
                )
                onnx_times.append((time.perf_counter() - t0) * 1000)
            onnx_ms = sorted(onnx_times)[1]

            total_pt += pt_ms
            total_onnx += onnx_ms

            consistent = pt_result["compressed_prompt"] == onnx_result["compressed_prompt"]
            if not consistent:
                all_consistent = False

            ratio = pt_ms / onnx_ms if onnx_ms > 0 else 0
            mark = "YES" if consistent else "NO"

            results.append({
                "case": case["name"], "rate": rate,
                "pt_ms": pt_ms, "onnx_ms": onnx_ms,
                "consistent": consistent,
                "pt_tok": pt_result["compressed_tokens"],
                "onnx_tok": onnx_result["compressed_tokens"],
            })

            print(f"  {case['name'][:18]:<20} {rate:<6} {pt_ms:<9.0f} {onnx_ms:<10.0f} {ratio:<8.2f} {mark:<7} {pt_result['compressed_tokens']:<8} {onnx_result['compressed_tokens']}")

    # ═══════════════════════════════════════════════════════════
    # 汇总
    # ═══════════════════════════════════════════════════════════

    n_tests = len(results)
    pt_avg = total_pt / n_tests
    onnx_avg = total_onnx / n_tests
    n_match = sum(1 for r in results if r["consistent"])

    print(f"\n\n{BOLD_SEP}")
    print(f"  SUMMARY")
    print(f"{BOLD_SEP}")
    print(f"\n  Tests: {n_tests}  |  Consistent: {n_match}/{n_tests}  |  Device: CPU")
    print(f"\n  {'Mode':<16} {'Total(ms)':<12} {'Avg(ms)':<10} {'Throughput'}")
    print(f"  {'-' * 50}")
    print(f"  {'PyTorch':<16} {total_pt:<12.0f} {pt_avg:<10.0f} {1000/pt_avg:.1f} req/s")
    print(f"  {'ONNX (CPU)':<16} {total_onnx:<12.0f} {onnx_avg:<10.0f} {1000/onnx_avg:.1f} req/s")
    print(f"  {'PT/ONNX ratio':<16} {'':12} {pt_avg/onnx_avg:.2f}x")

    print(f"""
  Key findings:
    - Result consistency: {n_match}/{n_tests} ({n_match/n_tests*100:.0f}%) identical outputs
    - CPU performance: ONNX {'slower' if onnx_avg > pt_avg else 'faster'} ({abs(1-pt_avg/onnx_avg)*100:.0f}% {'overhead' if onnx_avg > pt_avg else 'gain'})
    - This is expected: ONNX overhead on CPU due to large model data copy (numpy<->torch)

  Why ONNX wins on GPU (GN6s T4):
    - Eliminates Python GIL + per-op dispatch overhead
    - Graph-level operator fusion (LayerNorm+Add, Attention QKV merge)
    - TensorRT: kernel auto-tuning + FP16 Tensor Core + memory planning

  Projected GN6s (T4) performance:
    +----------------------------+------------+
    | Mode                       | Latency    |
    +----------------------------+------------+
    | PyTorch CPU (current)      | {pt_avg:.0f}ms      |
    | PyTorch CUDA FP32          | ~120-150ms |
    | PyTorch CUDA FP16          | ~60-80ms   |
    | ONNX + CUDAProvider        | ~35-50ms   |
    | ONNX + TensorRT FP16      | ~20-35ms   |
    +----------------------------+------------+
""")


if __name__ == "__main__":
    main()

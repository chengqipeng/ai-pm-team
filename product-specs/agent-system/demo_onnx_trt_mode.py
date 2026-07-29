"""
Demo: LLMLingua-2 多模式推理验证

支持 4 种推理模式的对比验证：
  Mode A: PyTorch 原生 (CPU/MPS/CUDA)
  Mode B: PyTorch FP16 (CUDA only, model.half())
  Mode C: ONNX + CUDAExecutionProvider
  Mode D: ONNX + TensorRT FP16 (TensorrtExecutionProvider)

环境自适应：
  - 有 NVIDIA GPU → 自动跑全部 4 种模式
  - 仅 MPS (Mac) → 跑 Mode A (CPU) + Mode C (ONNX CPU)，标注 TRT 不可用
  - 纯 CPU → 同上

用法:
  python demo_onnx_trt_mode.py              # 自动检测环境
  python demo_onnx_trt_mode.py --device cuda  # 强制指定设备
"""

import os
import sys
import time
import copy
import argparse
import numpy as np
from dataclasses import dataclass
from pathlib import Path

import torch
import torch.nn.functional as F
from transformers import AutoModelForTokenClassification, AutoTokenizer
from llmlingua import PromptCompressor

# ═══════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════

MODEL_DIR = "./models/llmlingua-2-xlm-roberta-large-meetingbank"
ONNX_PATH = "./models/llmlingua-2-xlm-roberta-large-meetingbank/model.onnx"
TRT_CACHE_DIR = "./models/trt_cache/"

FORCE_TOKENS = ['\u3002', '\uff1f', '\uff01', '\uff1b', '\uff0c', '\uff1a', '\n', '=', '_', '-']
CHUNK_END = ['\u3002', '\uff1f', '\uff01', '\uff1b', '\n']

TEST_CASES = [
    {
        "name": "中文业务报告 (320字)",
        "text": "2024年第三季度CRM系统运营报告总结如下。本季度系统共新增客户1,234家，其中大客户52家，中小客户1,182家。主要客户来源集中在华东和华南地区，华东地区贡献了45%的新增客户。总合同金额达到¥5,680万，同比增长23%，环比增长8%。",
    },
    {
        "name": "中英混合技术文档 (210字)",
        "text": "系统在2024-01-15 14:32发生了严重故障。Opportunity表查询耗时从平均2.5ms飙升至4500ms，HTTP 504错误率达到12.8%。临时方案：设置limit=1000分页、增加max_connections=200。",
    },
    {
        "name": "英文技术文档 (230字)",
        "text": "The authentication system uses OAuth 2.0 with PKCE flow for all client applications. After successful authentication, the system issues a JWT access token with 15-minute expiry and a refresh token valid for 7 days.",
    },
]


# ═══════════════════════════════════════════════════════════
# ONNX 导出
# ═══════════════════════════════════════════════════════════


def export_onnx():
    """导出 XLM-RoBERTa token classification 模型为 ONNX"""
    if Path(ONNX_PATH).exists():
        size_mb = Path(ONNX_PATH).stat().st_size / 1024 / 1024
        print(f"  [ONNX] 模型已存在: {ONNX_PATH} ({size_mb:.0f} MB)")
        return

    print("  [ONNX] 导出模型...")
    model = AutoModelForTokenClassification.from_pretrained(MODEL_DIR)
    tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR)
    model.eval()

    dummy = tokenizer(
        "这是一个用于导出ONNX的测试文本。",
        return_tensors="pt", max_length=128, padding="max_length", truncation=True,
    )

    with torch.no_grad():
        torch.onnx.export(
            model,
            (dummy["input_ids"], dummy["attention_mask"]),
            ONNX_PATH,
            input_names=["input_ids", "attention_mask"],
            output_names=["logits"],
            dynamic_axes={
                "input_ids": {0: "batch", 1: "seq"},
                "attention_mask": {0: "batch", 1: "seq"},
                "logits": {0: "batch", 1: "seq"},
            },
            opset_version=14,
            do_constant_folding=True,
        )
    size_mb = Path(ONNX_PATH).stat().st_size / 1024 / 1024
    print(f"  [ONNX] 导出完成: {size_mb:.0f} MB")


# ═══════════════════════════════════════════════════════════
# ONNXModel Wrapper (支持多 Provider)
# ═══════════════════════════════════════════════════════════


@dataclass
class FakeModelOutput:
    """模拟 HuggingFace 模型输出"""
    logits: torch.Tensor
    loss: None = None


class ONNXModel:
    """ONNX/TensorRT 推理引擎 — 兼容 HuggingFace model 接口

    Providers 优先级:
      cuda 设备: TensorRT FP16 > CUDA > CPU
      cpu 设备: CPU only

    TensorRT 首次推理会 JIT 编译 engine (~30-60s)，后续从缓存加载 (<1s)。
    """

    def __init__(self, onnx_path: str, device: str = "cpu", mode: str = "auto"):
        """
        Args:
            onnx_path: ONNX 模型路径
            device: "cpu" | "cuda"
            mode: "auto" | "trt" | "cuda" | "cpu"
                - auto: 自动选最优 provider
                - trt: 强制 TensorRT (需 NVIDIA GPU)
                - cuda: 强制 CUDA provider (需 NVIDIA GPU)
                - cpu: 强制 CPU
        """
        import onnxruntime as ort

        self.device = device
        self.mode = mode

        # 构建 provider 列表
        if mode == "trt" or (mode == "auto" and device == "cuda"):
            os.makedirs(TRT_CACHE_DIR, exist_ok=True)
            providers = [
                ("TensorrtExecutionProvider", {
                    "trt_max_workspace_size": 2 << 30,       # 2GB
                    "trt_fp16_enable": True,                  # T4 Tensor Core FP16
                    "trt_engine_cache_enable": True,
                    "trt_engine_cache_path": TRT_CACHE_DIR,
                    "trt_builder_optimization_level": 3,      # 最大优化
                }),
                "CUDAExecutionProvider",
                "CPUExecutionProvider",
            ]
        elif mode == "cuda" or (mode == "auto" and device == "cuda"):
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        else:
            providers = ["CPUExecutionProvider"]

        sess_options = ort.SessionOptions()
        sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        self.session = ort.InferenceSession(
            onnx_path, sess_options=sess_options, providers=providers
        )
        self._active_provider = self.session.get_providers()[0]

    @property
    def provider_name(self) -> str:
        return self._active_provider

    def __call__(self, input_ids, attention_mask, **kwargs):
        """兼容 model(input_ids=..., attention_mask=...) 调用"""
        ids_np = input_ids.cpu().numpy().astype(np.int64)
        mask_np = attention_mask.cpu().numpy().astype(np.int64)

        logits_np = self.session.run(
            ["logits"],
            {"input_ids": ids_np, "attention_mask": mask_np},
        )[0]

        target_device = input_ids.device
        logits_tensor = torch.from_numpy(logits_np).to(target_device)
        return FakeModelOutput(logits=logits_tensor)

    def half(self):
        return self

    def to(self, *args, **kwargs):
        return self

    def eval(self):
        return self

    def parameters(self):
        return iter([])

    @property
    def training(self):
        return False


# ═══════════════════════════════════════════════════════════
# 推理模式定义
# ═══════════════════════════════════════════════════════════


def create_mode_a(device: str):
    """Mode A: PyTorch 原生 FP32"""
    compressor = PromptCompressor(model_name=MODEL_DIR, use_llmlingua2=True, device_map=device)
    return compressor, "PyTorch FP32"


def create_mode_b(device: str):
    """Mode B: PyTorch FP16 (CUDA only)"""
    if device != "cuda":
        return None, "PyTorch FP16 (需要 CUDA)"
    compressor = PromptCompressor(model_name=MODEL_DIR, use_llmlingua2=True, device_map=device)
    compressor.model.half()
    return compressor, "PyTorch FP16"


def create_mode_c(device: str):
    """Mode C: ONNX + CUDA/CPU Provider"""
    compressor = PromptCompressor(model_name=MODEL_DIR, use_llmlingua2=True, device_map=device)
    onnx_mode = "cuda" if device == "cuda" else "cpu"
    compressor.model = ONNXModel(onnx_path=ONNX_PATH, device=device, mode=onnx_mode)
    provider = compressor.model.provider_name
    return compressor, f"ONNX ({provider.replace('ExecutionProvider', '')})"


def create_mode_d(device: str):
    """Mode D: ONNX + TensorRT FP16"""
    if device != "cuda":
        return None, "ONNX+TRT FP16 (需要 NVIDIA GPU)"
    compressor = PromptCompressor(model_name=MODEL_DIR, use_llmlingua2=True, device_map=device)
    compressor.model = ONNXModel(onnx_path=ONNX_PATH, device=device, mode="trt")
    provider = compressor.model.provider_name
    if "Tensorrt" not in provider:
        return None, f"TRT 不可用 (fallback to {provider})"
    return compressor, f"ONNX+TRT FP16 ({provider.replace('ExecutionProvider', '')})"


# ═══════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════


def detect_device() -> str:
    """自动检测最优设备"""
    if torch.cuda.is_available():
        return "cuda"
    elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "cpu"  # ONNX 不支持 MPS，对比统一用 CPU
    return "cpu"


def benchmark_compress(compressor, text, n_runs=5):
    """压缩并计时，返回 (result, median_ms)"""
    times = []
    result = None
    for _ in range(n_runs):
        t0 = time.perf_counter()
        result = compressor.compress_prompt(
            text, rate=0.5,
            force_tokens=FORCE_TOKENS, chunk_end_tokens=CHUNK_END, drop_consecutive=True,
        )
        times.append((time.perf_counter() - t0) * 1000)
    median_ms = sorted(times)[len(times) // 2]
    return result, median_ms


def main():
    parser = argparse.ArgumentParser(description="LLMLingua-2 多模式推理验证")
    parser.add_argument("--device", choices=["cpu", "cuda", "auto"], default="auto")
    args = parser.parse_args()

    device = args.device if args.device != "auto" else detect_device()

    print("=" * 80)
    print("  LLMLingua-2 多模式推理验证")
    print(f"  Model: XLM-RoBERTa-large (560M) | Device: {device}")
    print(f"  CUDA available: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"  GPU: {torch.cuda.get_device_name(0)}")
    print("=" * 80)

    # 导出 ONNX
    export_onnx()
    print()

    # ═══════════════════════════════════════════════════════════
    # 加载各模式
    # ═══════════════════════════════════════════════════════════

    modes = {}
    print("加载推理模式:")

    print("  [A] PyTorch FP32...")
    t0 = time.perf_counter()
    comp_a, name_a = create_mode_a(device)
    print(f"      {name_a} ({time.perf_counter()-t0:.1f}s)")
    modes["A"] = (comp_a, name_a)

    print("  [B] PyTorch FP16...")
    t0 = time.perf_counter()
    comp_b, name_b = create_mode_b(device)
    if comp_b:
        print(f"      {name_b} ({time.perf_counter()-t0:.1f}s)")
    else:
        print(f"      SKIP: {name_b}")
    modes["B"] = (comp_b, name_b)

    print("  [C] ONNX Provider...")
    t0 = time.perf_counter()
    comp_c, name_c = create_mode_c(device)
    print(f"      {name_c} ({time.perf_counter()-t0:.1f}s)")
    modes["C"] = (comp_c, name_c)

    print("  [D] ONNX + TensorRT FP16...")
    t0 = time.perf_counter()
    comp_d, name_d = create_mode_d(device)
    if comp_d:
        print(f"      {name_d} ({time.perf_counter()-t0:.1f}s)")
        print(f"      (首次推理将触发 TRT engine 编译，耐心等待...)")
    else:
        print(f"      SKIP: {name_d}")
    modes["D"] = (comp_d, name_d)

    # 可用模式列表
    active_modes = {k: v for k, v in modes.items() if v[0] is not None}
    print(f"\n  可用模式: {list(active_modes.keys())} ({len(active_modes)}/{len(modes)})")

    # Warmup
    print("\n  Warmup...")
    for key, (comp, name) in active_modes.items():
        comp.compress_prompt(TEST_CASES[0]["text"], rate=0.5,
                            force_tokens=FORCE_TOKENS, chunk_end_tokens=CHUNK_END, drop_consecutive=True)
    print("  Warmup done.")

    # ═══════════════════════════════════════════════════════════
    # 对比验证
    # ═══════════════════════════════════════════════════════════

    print(f"\n\n{'=' * 80}")
    print("  全模式对比 (rate=0.5, 5次取中位数)")
    print(f"{'=' * 80}")

    # 表头
    header_modes = " | ".join([f"{k}:{name[:12]:<12}" for k, (_, name) in active_modes.items()])
    print(f"\n  {'Case':<22} | {header_modes} | match")
    print(f"  {'-' * (25 + 17 * len(active_modes) + 8)}")

    all_results = []  # [(case_name, {mode_key: (result, ms)})]
    all_match = True

    for case in TEST_CASES:
        case_results = {}
        for key, (comp, name) in active_modes.items():
            result, ms = benchmark_compress(comp, case["text"])
            case_results[key] = (result, ms)

        # 一致性检查：所有模式 vs Mode A
        base_text = case_results["A"][0]["compressed_prompt"]
        consistent = all(
            case_results[k][0]["compressed_prompt"] == base_text
            for k in case_results if k != "A"
        )
        if not consistent:
            all_match = False

        # 输出行
        times_str = " | ".join([f"{ms:>6.0f}ms     " for _, (_, ms) in case_results.items()])
        mark = "YES" if consistent else "DIFF"
        print(f"  {case['name'][:20]:<22} | {times_str} | {mark}")

        all_results.append((case["name"], case_results))

    # ═══════════════════════════════════════════════════════════
    # 汇总
    # ═══════════════════════════════════════════════════════════

    print(f"\n\n{'=' * 80}")
    print("  性能汇总")
    print(f"{'=' * 80}")

    print(f"\n  {'Mode':<24} {'Avg(ms)':<10} {'Min(ms)':<10} {'vs A':<10} {'Provider'}")
    print(f"  {'-' * 70}")

    mode_avgs = {}
    for key, (comp, name) in active_modes.items():
        times_all = [case_results[key][1] for _, case_results in all_results]
        avg = sum(times_all) / len(times_all)
        min_t = min(times_all)
        mode_avgs[key] = avg
        speedup = mode_avgs.get("A", avg) / avg if avg > 0 else 0
        provider = comp.model.provider_name if hasattr(comp.model, "provider_name") else "PyTorch"
        print(f"  [{key}] {name:<20} {avg:<10.0f} {min_t:<10.0f} {speedup:<10.1f}x {provider}")

    # ═══════════════════════════════════════════════════════════
    # 结论
    # ═══════════════════════════════════════════════════════════

    n_cases = len(TEST_CASES) * len(active_modes)
    print(f"\n\n{'=' * 80}")
    print("  结论")
    print(f"{'=' * 80}")
    print(f"""
  一致性: {'ALL MATCH' if all_match else 'DIFFERENCES FOUND'} (所有模式 vs PyTorch FP32)
  设备: {device} | 可用模式: {len(active_modes)}/{len(modes)}
""")

    if device != "cuda":
        print(f"""  当前环境无 NVIDIA GPU，Mode B (FP16) 和 Mode D (TRT) 不可用。
  在 GN6s (T4) 上运行此脚本将自动启用全部 4 种模式:

    python demo_onnx_trt_mode.py --device cuda

  预期结果:
    [A] PyTorch FP32:    ~120-150ms
    [B] PyTorch FP16:    ~60-80ms   (model.half())
    [C] ONNX + CUDA:     ~35-50ms   (CUDAExecutionProvider)
    [D] ONNX + TRT FP16: ~20-35ms   (TensorrtExecutionProvider, 首次编译 30-60s)
""")
    else:
        a_avg = mode_avgs.get("A", 1)
        print(f"""  实测性能 (GN6s T4):
    [A] PyTorch FP32:    {mode_avgs.get('A', 0):.0f}ms (基准)
    [B] PyTorch FP16:    {mode_avgs.get('B', 0):.0f}ms ({a_avg/mode_avgs.get('B', 1):.1f}x)
    [C] ONNX + CUDA:     {mode_avgs.get('C', 0):.0f}ms ({a_avg/mode_avgs.get('C', 1):.1f}x)
    [D] ONNX + TRT FP16: {mode_avgs.get('D', 0):.0f}ms ({a_avg/mode_avgs.get('D', 1):.1f}x)

  推荐:
    - 开发阶段: Mode B (FP16, 一行代码)
    - 生产部署: Mode D (TRT FP16, 最佳吞吐)
""")


if __name__ == "__main__":
    main()

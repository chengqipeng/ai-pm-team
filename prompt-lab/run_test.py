#!/usr/bin/env python3
"""
Prompt Lab - 提示词测试执行脚本

用法:
  python prompt-lab/run_test.py \
    --prompt contract-inspection/data-consistency \
    --dataset contract-inspection/case-001

  # 测试某功能下所有用例
  python prompt-lab/run_test.py \
    --prompt contract-inspection/data-consistency \
    --dataset contract-inspection/

  # 指定配置文件
  python prompt-lab/run_test.py \
    --prompt contract-inspection/data-consistency \
    --dataset contract-inspection/case-001 \
    --config prompt-lab/config.yaml
"""

import argparse
import json
import os
import sys
import re
import glob
from datetime import datetime
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).parent
PROMPTS_DIR = BASE_DIR / "prompts"
DATASETS_DIR = BASE_DIR / "datasets"
EVALUATORS_DIR = BASE_DIR / "evaluators"
RESULTS_DIR = BASE_DIR / "results"


def load_config(config_path: str = None) -> dict:
    path = Path(config_path) if config_path else BASE_DIR / "config.yaml"
    if not path.exists():
        print(f"[ERROR] 配置文件不存在: {path}")
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_prompt(prompt_name: str) -> str:
    path = PROMPTS_DIR / f"{prompt_name}.md"
    if not path.exists():
        print(f"[ERROR] 提示词文件不存在: {path}")
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def load_dataset(dataset_name: str) -> list[dict]:
    """加载单个用例或目录下所有用例"""
    path = DATASETS_DIR / dataset_name
    if path.is_file():
        with open(path, "r", encoding="utf-8") as f:
            return [json.load(f)]
    elif path.is_dir():
        cases = []
        for fp in sorted(path.glob("case-*.json")):
            with open(fp, "r", encoding="utf-8") as f:
                case = json.load(f)
                case["_file"] = fp.name
                cases.append(case)
        if not cases:
            print(f"[WARN] 目录下无测试用例: {path}")
        return cases
    else:
        # 尝试补 .json 后缀
        json_path = path.with_suffix(".json")
        if json_path.exists():
            with open(json_path, "r", encoding="utf-8") as f:
                return [json.load(f)]
        print(f"[ERROR] 数据集不存在: {path}")
        sys.exit(1)


def render_prompt(template: str, variables: dict) -> str:
    """将模板中的 ${变量名} 替换为实际值"""
    result = template
    for key, value in variables.items():
        result = result.replace(f"${{{key}}}", str(value))
    return result


def call_model(config: dict, prompt: str, role: str = "target") -> str:
    """调用大模型 API，支持 OpenAI 兼容接口"""
    model_cfg = config["model"][role]
    provider = model_cfg.get("provider", "openai")
    endpoint = model_cfg["endpoint"]
    api_key = model_cfg["api_key"]
    model_name = model_cfg["model_name"]
    temperature = model_cfg.get("temperature", 0.0)
    max_tokens = model_cfg.get("max_tokens", 4096)

    if not endpoint or not api_key:
        print(f"[ERROR] 请在 config.yaml 中配置 {role} 模型的 endpoint 和 api_key")
        sys.exit(1)

    import urllib.request
    import urllib.error

    # 构建 OpenAI 兼容请求
    url = endpoint.rstrip("/")
    if not url.endswith("/chat/completions"):
        url += "/chat/completions"

    payload = json.dumps({
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return body["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else ""
        print(f"[ERROR] API 调用失败 ({e.code}): {error_body}")
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] API 调用异常: {e}")
        sys.exit(1)


def extract_json(text: str) -> dict | None:
    """从模型输出中提取 JSON"""
    # 尝试直接解析
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
    # 尝试从 markdown code block 中提取
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass
    # 尝试找第一个 { 到最后一个 }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    return None


def normalize_field_name(name: str) -> str:
    """归一化字段名用于匹配：去空格、标点、统一大小写"""
    import unicodedata
    s = name.strip().lower()
    # 去除所有空格和常见标点
    s = re.sub(r"[\s\-_—–·・,，.。:：;；!！?？()（）\[\]【】{}\"'""'']+", "", s)
    return s


def evaluate(config: dict, model_output: dict, expected: dict, evaluator_cfg: dict) -> dict:
    """评估模型输出与期望输出的差异，使用 fieldName 做主匹配键"""
    actual_items = model_output.get("inconsistencies", [])
    expected_items = expected.get("inconsistencies", [])

    # 用归一化后的 fieldName 做匹配
    actual_names = {normalize_field_name(item.get("fieldName", "")): item for item in actual_items}
    expected_names = {normalize_field_name(item.get("fieldName", "")): item for item in expected_items}

    actual_name_set = set(actual_names.keys())
    expected_name_set = set(expected_names.keys())

    false_positives = actual_name_set - expected_name_set
    false_negatives = expected_name_set - actual_name_set

    fp_count = len(false_positives)
    fn_count = len(false_negatives)

    weights = evaluator_cfg.get("metrics", {})
    fp_weight = weights.get("false_positive", {}).get("weight", 3.0)
    fn_weight = weights.get("false_negative", {}).get("weight", 1.0)

    score = -(fp_count * fp_weight + fn_count * fn_weight)

    pass_criteria = evaluator_cfg.get("pass_criteria", {})
    passed = True
    if pass_criteria.get("zero_false_positives") and fp_count > 0:
        passed = False
    if pass_criteria.get("zero_false_negatives") and fn_count > 0:
        passed = False
    if score < pass_criteria.get("min_score", 0):
        passed = False

    # 如果有评估模型配置，调用评估模型做描述质量评分
    description_eval = None
    if config["model"].get("evaluator", {}).get("api_key"):
        eval_prompt = (
            f"对比以下两个JSON输出，评估模型输出的质量：\n\n"
            f"【模型输出】\n{json.dumps(model_output, ensure_ascii=False, indent=2)}\n\n"
            f"【期望输出】\n{json.dumps(expected, ensure_ascii=False, indent=2)}\n\n"
            f"{evaluator_cfg.get('evaluator_prompt', '')}"
        )
        try:
            eval_response = call_model(config, eval_prompt, role="evaluator")
            description_eval = extract_json(eval_response)
        except Exception:
            description_eval = None

    return {
        "passed": passed,
        "score": score,
        "false_positives": list(false_positives),
        "false_negatives": list(false_negatives),
        "fp_count": fp_count,
        "fn_count": fn_count,
        "description_eval": description_eval,
    }


def run_single_case(config: dict, prompt_template: str, case: dict, evaluator_cfg: dict) -> dict:
    """执行单个测试用例"""
    case_name = case.get("meta", {}).get("name", "unnamed")
    case_file = case.get("_file", "unknown")
    print(f"\n{'='*60}")
    print(f"用例: {case_name} ({case_file})")
    print(f"{'='*60}")

    # 渲染提示词
    variables = case["input"]
    rendered = render_prompt(prompt_template, variables)

    # 调用目标模型
    print("[1/3] 调用目标模型...")
    raw_response = call_model(config, rendered, role="target")

    # 解析输出
    print("[2/3] 解析模型输出...")
    model_output = extract_json(raw_response)
    if model_output is None:
        print("[WARN] 无法从模型输出中解析 JSON")
        model_output = {"inconsistencies": [], "_parse_error": True}

    # 评估
    print("[3/3] 评估结果...")
    expected = case["expected"]
    eval_result = evaluate(config, model_output, expected, evaluator_cfg)

    # 打印结果
    status = "✅ PASS" if eval_result["passed"] else "❌ FAIL"
    print(f"\n结果: {status}")
    print(f"得分: {eval_result['score']}")
    if eval_result["fp_count"] > 0:
        print(f"误报 ({eval_result['fp_count']}): {eval_result['false_positives']}")
    if eval_result["fn_count"] > 0:
        print(f"漏报 ({eval_result['fn_count']}): {eval_result['false_negatives']}")

    return {
        "case_name": case_name,
        "case_file": case_file,
        "rendered_prompt": rendered,
        "raw_response": raw_response,
        "model_output": model_output,
        "expected": expected,
        "evaluation": eval_result,
    }


def save_results(results: list[dict], prompt_name: str):
    """保存测试结果"""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = prompt_name.replace("/", "_")
    result_file = RESULTS_DIR / f"{safe_name}_{timestamp}.json"

    summary = {
        "timestamp": timestamp,
        "prompt": prompt_name,
        "total_cases": len(results),
        "passed": sum(1 for r in results if r["evaluation"]["passed"]),
        "failed": sum(1 for r in results if not r["evaluation"]["passed"]),
        "cases": results,
    }

    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"测试完成: {summary['passed']}/{summary['total_cases']} 通过")
    print(f"结果保存至: {result_file}")
    return summary


def main():
    parser = argparse.ArgumentParser(description="Prompt Lab 测试执行器")
    parser.add_argument("--prompt", required=True, help="提示词路径 (相对于 prompts/，不含 .md)")
    parser.add_argument("--dataset", required=True, help="数据集路径 (相对于 datasets/，可以是文件或目录)")
    parser.add_argument("--config", default=None, help="配置文件路径")
    parser.add_argument("--evaluator", default=None, help="评估器路径 (相对于 evaluators/)")
    args = parser.parse_args()

    # 加载配置
    config = load_config(args.config)

    # 加载提示词
    prompt_template = load_prompt(args.prompt)

    # 加载数据集
    cases = load_dataset(args.dataset)
    print(f"已加载 {len(cases)} 个测试用例")

    # 加载评估器
    evaluator_cfg = {}
    if args.evaluator:
        eval_path = EVALUATORS_DIR / args.evaluator
        if not eval_path.suffix:
            eval_path = eval_path.with_suffix(".json")
        if eval_path.exists():
            with open(eval_path, "r", encoding="utf-8") as f:
                evaluator_cfg = json.load(f)
    else:
        # 自动匹配评估器：取 prompt 路径的第一段作为功能名
        feature = args.prompt.split("/")[0]
        auto_path = EVALUATORS_DIR / f"{feature}.json"
        if auto_path.exists():
            with open(auto_path, "r", encoding="utf-8") as f:
                evaluator_cfg = json.load(f)
            print(f"自动匹配评估器: {auto_path.name}")

    # 执行测试
    results = []
    for case in cases:
        result = run_single_case(config, prompt_template, case, evaluator_cfg)
        results.append(result)

    # 保存结果
    save_results(results, args.prompt)


if __name__ == "__main__":
    main()

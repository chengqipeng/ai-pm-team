# Prompt Lab — 提示词测试与评估体系

## 目录结构

```
prompt-lab/
├── prompts/                    # 提示词模板
│   └── contract-inspection/    # 合同质检
│       └── data-consistency.md # 数据一致性检查提示词
├── datasets/                   # 测试数据集
│   └── contract-inspection/    # 合同质检测试数据
│       └── case-001.json       # 测试用例（输入 + 期望输出）
├── evaluators/                 # 评估规则
│   └── contract-inspection.json
├── results/                    # 测试结果（自动生成，git可忽略）
├── config.yaml                 # 模型API配置（不要提交到git）
├── run_test.py                 # 测试执行脚本
└── README.md
```

## 使用流程

### 1. 配置模型 API
编辑 `config.yaml`，填入模型 endpoint 和 API key。

### 2. 编写/更新提示词
在 `prompts/<功能名>/` 下维护提示词模板，模板中用 `${变量名}` 标记需要替换的变量。

### 3. 准备测试数据
在 `datasets/<功能名>/` 下创建测试用例 JSON，包含：
- `input`：模拟的变量数据（会替换到提示词模板中）
- `expected`：期望输出（用于评估）

### 4. 运行测试
```bash
python prompt-lab/run_test.py --prompt contract-inspection/data-consistency --dataset contract-inspection/case-001
```

### 5. 查看结果
测试结果保存在 `results/` 目录下，包含模型原始输出、评估得分、差异分析。

## 评估机制

评估器对比模型输出与期望输出：
- **误报检查**：模型输出了 expected 中不存在的 inconsistency → 扣分
- **漏报检查**：expected 中存在但模型未输出的 inconsistency → 扣分
- **描述质量**：diffDescription 是否准确描述了差异 → 人工复核

评估结果为 PASS / FAIL，附带详细的差异报告。

"""评测模块

提供 Tool 评测 + Memory 评测能力。

Tool 评测：
    验证每个 Tool 在给定输入时能否返回正确结果。
    不经过 Agent 推理，直接调用 Tool.call()。

Memory 评测：
    验证记忆子系统的写入正确性、检索召回率和冲突消解能力。
    使用 VikingEvalEngine 基于真实 VDB + LLM 执行评测。

核心组件：
    - tool_eval_runner: Tool 评测执行引擎（断言引擎 + 用例执行）
    - tool_eval_presets: Tool 预置用例集（手动维护的基线用例）
    - case_combination_generator: 参数组合自动生成器（自动推导正向/逆向/边界用例）
    - memory_eval_runner: Memory 评测执行引擎（五层评测 + 检索/提取验证）
    - viking_eval_engine: 基于真实 VDB 的评测引擎（替代 InMemoryEvalEngine）
    - memory_eval_cases: 检索召回评测用例集（200 条）
    - memory_extract_eval_cases: 四维度提取评测用例集（250 条）

存储：
    - ai_eval_tool_suite / ai_eval_tool_case / ai_eval_tool_report: Tool 评测
    - ai_eval_memory_suite / ai_eval_memory_case / ai_eval_memory_report: Memory 评测
"""

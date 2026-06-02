"""Tool 评测模块

提供独立的工具功能评测能力，验证每个 Tool 在给定输入时能否返回正确结果。
不经过 Agent 推理，直接调用 Tool.call()。

核心组件：
    - tool_eval_runner: 评测执行引擎（断言引擎 + 用例执行）
    - tool_eval_presets: 预置用例集（手动维护的基线用例）
    - case_combination_generator: 参数组合自动生成器（自动推导正向/逆向/边界用例）

存储：
    - ai_eval_tool_suite: 评测套件
    - ai_eval_tool_case: 评测用例（持久化，支持按工具/方法/分类查询）
    - ai_eval_tool_report: 评测报告
    - ai_eval_tool_case_result: 用例执行明细
"""

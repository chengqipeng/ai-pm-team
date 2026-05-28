/**
 * 对话式创建 Skill — 类型定义
 *
 * 用于 Chat 中 interrupt_type="skill_confirm" 的渲染和交互。
 */

/** Skill 定义（Agent 生成 + 用户可编辑） */
export interface SkillDefinition {
  api_key: string;
  name: string;
  description: string;
  when_to_use: string;
  category: string;
  arguments: string[];
  argument_descriptions: Record<string, string>;
  allowed_tools: string[];
  risk_level: 'read_only' | 'mutating' | 'destructive';
  max_tool_calls: number;
  timeout_ms: number;
  prompt: string;
}

/** interrupt() 传递给前端的中断数据 */
export interface SkillInterruptData {
  interrupt_id: string;
  type: 'skill_confirm';
  title: string;
  message: string;
  options: Array<{
    id: string;
    label: string;
    description: string; // JSON.stringify(SkillDefinition)
  }>;
  default_value?: string;
}

/** 用户确认后 resume 给 Agent 的值 */
export interface SkillResumeValue {
  action: 'confirm';
  value: SkillDefinition;
}

/** 用户取消时 resume 给 Agent 的值 */
export interface SkillCancelValue {
  cancelled: true;
}

/** resume 的联合类型 */
export type SkillResumePayload = SkillResumeValue | SkillCancelValue;

/** 可用工具列表（用于编辑器下拉选择） */
export const AVAILABLE_TOOLS = [
  'query_data',
  'modify_data',
  'analyze_data',
  'web_search',
  'query_schema',
  'query_permission',
] as const;

/** 分类选项 */
export const CATEGORY_OPTIONS = [
  { value: 'crm', label: 'CRM 业务' },
  { value: 'analysis', label: '数据分析' },
  { value: 'automation', label: '自动化操作' },
  { value: 'metarepo', label: '元数据管理' },
  { value: 'custom', label: '自定义' },
] as const;

/** 风险等级选项 */
export const RISK_LEVEL_OPTIONS = [
  { value: 'read_only', label: '只读', color: 'green' },
  { value: 'mutating', label: '写入', color: 'orange' },
  { value: 'destructive', label: '破坏性', color: 'red' },
] as const;

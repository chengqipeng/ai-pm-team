/**
 * Skill 管理前端类型定义
 */

export type SkillCategory = 'crm' | 'metarepo' | 'analysis' | 'automation' | 'custom' | '';

export type RiskLevel = 'read_only' | 'mutating' | 'destructive';

export type SkillContext = 'inline' | 'fork';

export interface Skill {
  api_key: string;
  name: string;
  description: string;
  when_to_use: string;
  category: SkillCategory;
  tags: string[];
  icon: string;
  context: SkillContext;
  agent: string;
  model: string;
  allowed_tools: string[];
  arguments: string[];
  prompt: string;
  risk_level: RiskLevel;
  requires_confirmation: boolean;
  max_tool_calls: number;
  timeout_ms: number;
  version: string;
  enabled: boolean;
  owner: string;
  sort_num: number;
  exec_count: number;
  success_count: number;
  avg_duration_ms: number;
  tenant_id: number;
  created_at: number;
  updated_at: number;
}

export interface SkillListResponse {
  total: number;
  page: number;
  page_size: number;
  items: Skill[];
}

export interface SkillCreateRequest {
  api_key: string;
  name: string;
  description: string;
  prompt: string;
  when_to_use?: string;
  category?: SkillCategory;
  tags?: string[];
  context?: SkillContext;
  agent?: string;
  model?: string;
  allowed_tools?: string[];
  arguments?: string[];
  risk_level?: RiskLevel;
  requires_confirmation?: boolean;
  max_tool_calls?: number;
  timeout_ms?: number;
  owner?: string;
  icon?: string;
  sort_num?: number;
}

export interface SkillUpdateRequest {
  name?: string;
  description?: string;
  prompt?: string;
  when_to_use?: string;
  category?: SkillCategory;
  tags?: string[];
  context?: SkillContext;
  agent?: string;
  model?: string;
  allowed_tools?: string[];
  arguments?: string[];
  risk_level?: RiskLevel;
  requires_confirmation?: boolean;
  max_tool_calls?: number;
  timeout_ms?: number;
  owner?: string;
  icon?: string;
  sort_num?: number;
}

export interface SkillToggleRequest {
  enabled: boolean;
}

export interface SkillCloneRequest {
  new_api_key: string;
}

export interface SkillTestRequest {
  arguments: Record<string, string>;
}

export interface SkillTestResponse {
  api_key: string;
  output: string;
}

export interface SkillStats {
  total_skills: number;
  enabled_count: number;
  disabled_count: number;
  total_executions: number;
  total_success: number;
  success_rate: number;
}

export interface CategoryItem {
  key: string;
  label: string;
  icon: string;
}

/**
 * Skill 管理 API 客户端
 */
import type {
  Skill,
  SkillListResponse,
  SkillCreateRequest,
  SkillUpdateRequest,
  SkillToggleRequest,
  SkillCloneRequest,
  SkillTestRequest,
  SkillTestResponse,
  SkillStats,
  CategoryItem,
} from './types';

const BASE_URL = '/api/skills';

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ message: res.statusText }));
    throw new Error(err.detail?.message || err.message || `HTTP ${res.status}`);
  }
  return res.json();
}

export const skillApi = {
  /** 列表 */
  list(params: {
    tenant_id?: number;
    enabled?: boolean | null;
    category?: string;
    keyword?: string;
    page?: number;
    page_size?: number;
  }): Promise<SkillListResponse> {
    const searchParams = new URLSearchParams();
    if (params.tenant_id !== undefined) searchParams.set('tenant_id', String(params.tenant_id));
    if (params.enabled !== null && params.enabled !== undefined) searchParams.set('enabled', String(params.enabled));
    if (params.category) searchParams.set('category', params.category);
    if (params.keyword) searchParams.set('keyword', params.keyword);
    if (params.page) searchParams.set('page', String(params.page));
    if (params.page_size) searchParams.set('page_size', String(params.page_size));
    return request(`${BASE_URL}?${searchParams.toString()}`);
  },

  /** 详情 */
  get(apiKey: string, tenantId = 0): Promise<Skill> {
    return request(`${BASE_URL}/${apiKey}?tenant_id=${tenantId}`);
  },

  /** 创建 */
  create(data: SkillCreateRequest, tenantId = 0): Promise<Skill> {
    return request(`${BASE_URL}?tenant_id=${tenantId}`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  /** 编辑 */
  update(apiKey: string, data: SkillUpdateRequest, tenantId = 0): Promise<Skill> {
    return request(`${BASE_URL}/${apiKey}?tenant_id=${tenantId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  },

  /** 启用/禁用 */
  toggle(apiKey: string, data: SkillToggleRequest, tenantId = 0): Promise<Skill & { message: string }> {
    return request(`${BASE_URL}/${apiKey}/toggle?tenant_id=${tenantId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  },

  /** 克隆 */
  clone(apiKey: string, data: SkillCloneRequest, tenantId = 0): Promise<Skill> {
    return request(`${BASE_URL}/${apiKey}/clone?tenant_id=${tenantId}`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  /** 测试执行 */
  test(apiKey: string, data: SkillTestRequest, tenantId = 0): Promise<SkillTestResponse> {
    return request(`${BASE_URL}/${apiKey}/test?tenant_id=${tenantId}`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  /** 删除 */
  delete(apiKey: string, tenantId = 0): Promise<{ message: string }> {
    return request(`${BASE_URL}/${apiKey}?tenant_id=${tenantId}`, {
      method: 'DELETE',
    });
  },

  /** 分类列表 */
  categories(): Promise<CategoryItem[]> {
    return request(`${BASE_URL}/categories`);
  },

  /** 统计概览 */
  stats(tenantId = 0): Promise<SkillStats> {
    return request(`${BASE_URL}/stats?tenant_id=${tenantId}`);
  },
};

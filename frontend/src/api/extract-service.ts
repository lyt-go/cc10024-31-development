/** 抽取适用集接口封装：原页确认、适用模板查询、正式清洗、补采领取回填与审计回查。 */
import { request } from './client'

export type Candidate = {
  template_id: number
  模板编号: string
  模板版本: string
  version_fingerprint: string
  适用页面类型: string
  来源标识: string
  覆盖字段: string[]
  出数字段: string[]
  缺失字段: string[]
  解析失败字段: string[]
  页面类型匹配: boolean
  decision: '选中' | '未用' | '不足'
  decision_reason: string
}

export type ScopeSet = {
  scope_id: string
  page_id: string
  页面类型: string
  页面版本: string
  pipeline_id: string
  round: number
  recompute: boolean
  selected_template_id: number | null
  selected_template_code: string
  candidate_count: number
  candidates: Candidate[]
  created_at: string
}

export type FieldResult = {
  field: string
  value: unknown
  status: '出数' | '未出数'
  source: string
}

export type CleanRow = {
  row_id: string
  page_id: string
  页面类型: string
  页面版本: string
  pipeline_id: string
  scope_id: string
  template_id: number
  模板编号: string
  模板版本: string
  template_version_fingerprint: string
  来源标识: string
  covered_fields: string[]
  produced_fields: string[]
  missing_fields: string[]
  field_results: FieldResult[]
  status: string
  created_at: string
  updated_at: string
}

export type SupplementTask = {
  task_id: string
  page_id: string
  row_id: string
  field: string
  status: '待领取' | '已领取' | '已回填' | '已取消'
  claimed_at: string
  backfilled_at: string
  value: unknown
  created_at: string
}

export type CollectedPage = {
  page_id: string
  页面类型: string
  页面版本: string
  来源标识: string
  解析字段: Record<string, unknown>
  status: string
  registered_at: string
  confirmed_at: string
}

type ApiResult<T> = {
  ok: boolean
  message: string
  data: T
}

async function call<T>(path: string, init?: RequestInit): Promise<ApiResult<T>> {
  const response = await request(path, init)
  return (await response.json()) as ApiResult<T>
}

export async function demoSeed(): Promise<ApiResult<unknown>> {
  return call('/api/extract/demo-seed', { method: 'POST' })
}

export async function listPages(): Promise<CollectedPage[]> {
  const r = await call<CollectedPage[]>('/api/extract/pages')
  return r.data ?? []
}

export async function registerPage(values: {
  page_id: string
  page_type: string
  page_version: string
  source: string
  resolved_fields: Record<string, unknown>
}): Promise<ApiResult<CollectedPage>> {
  return call('/api/extract/pages', { method: 'POST', body: JSON.stringify(values) })
}

export async function confirmPage(pageId: string): Promise<ApiResult<CollectedPage>> {
  return call(`/api/extract/pages/${encodeURIComponent(pageId)}/confirm`, { method: 'POST' })
}

export async function listScopeSets(pageId?: string): Promise<ScopeSet[]> {
  const query = pageId ? `?page_id=${encodeURIComponent(pageId)}` : ''
  const r = await call<ScopeSet[]>(`/api/extract/scope-sets${query}`)
  return r.data ?? []
}

export async function computeScopeSet(
  pageId: string,
  recompute = false,
): Promise<ApiResult<ScopeSet>> {
  return call(
    `/api/extract/pages/${encodeURIComponent(pageId)}/scope-sets?recompute=${recompute}`,
    { method: 'POST' },
  )
}

export async function startCleaning(payload: {
  page_id: string
  pipeline_id?: string
  template_id?: number | null
}): Promise<ApiResult<CleanRow>> {
  return call('/api/extract/cleaning', { method: 'POST', body: JSON.stringify(payload) })
}

export async function listCleanRows(params: {
  page_id?: string
  template_version?: string
} = {}): Promise<CleanRow[]> {
  const query = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v) as [string, string][],
  ).toString()
  const r = await call<CleanRow[]>(`/api/extract/clean-rows?${query}`)
  return r.data ?? []
}

export async function listSupplementTasks(params: {
  page_id?: string
  status?: string
} = {}): Promise<SupplementTask[]> {
  const query = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v) as [string, string][],
  ).toString()
  const r = await call<SupplementTask[]>(`/api/extract/supplement-tasks?${query}`)
  return r.data ?? []
}

export async function claimTask(taskId: string): Promise<ApiResult<SupplementTask>> {
  return call(`/api/extract/supplement-tasks/${encodeURIComponent(taskId)}/claim`, {
    method: 'POST',
  })
}

export async function backfillTask(
  taskId: string,
  value: unknown,
): Promise<ApiResult<SupplementTask>> {
  return call(
    `/api/extract/supplement-tasks/${encodeURIComponent(taskId)}/backfill`,
    { method: 'POST', body: JSON.stringify({ value }) },
  )
}

export async function auditEvents(): Promise<Record<string, unknown[]>> {
  const r = await call<Record<string, unknown[]>>('/api/extract/audit')
  return r.data ?? {}
}

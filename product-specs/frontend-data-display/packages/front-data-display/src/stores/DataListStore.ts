/**
 * DataListStore — 列表数据状态管理
 *
 * 对齐老项目 apps-ingage-web/base/stores/ 的 MobX-State-Tree 模式
 * 管理列表页的数据、分页、筛选、排序状态
 *
 * 新项目使用 MobX + mobx-react-lite（轻量版），
 * 保持与老项目 MST 相似的 observable/action 模式
 */
import { makeAutoObservable, runInAction } from 'mobx'
import type { DataRecord, Pagination, SortParam, FilterCondition, FieldMeta } from '../types'

export class DataListStore {
  entityApiKey = ''
  fields: FieldMeta[] = []
  records: DataRecord[] = []
  pagination: Pagination = { current: 1, pageSize: 20, total: 0 }
  sort: SortParam | undefined = undefined
  filters: FilterCondition[] = []
  loading = false
  searchKeyword = ''

  /** 数据加载函数（外部注入，对齐老项目 getEnv(self).fetcher 模式） */
  private fetcher?: (params: any) => Promise<{ records: DataRecord[]; total: number }>
  private fieldFetcher?: (entityApiKey: string) => Promise<FieldMeta[]>

  constructor(fetcher?: typeof DataListStore.prototype.fetcher, fieldFetcher?: typeof DataListStore.prototype.fieldFetcher) {
    makeAutoObservable(this)
    this.fetcher = fetcher
    this.fieldFetcher = fieldFetcher
  }

  setEntityApiKey(apiKey: string) {
    this.entityApiKey = apiKey
    this.pagination.current = 1
    this.filters = []
    this.sort = undefined
    this.searchKeyword = ''
  }

  setPage(page: number) {
    this.pagination.current = page
  }

  setSort(sort: SortParam | undefined) {
    this.sort = sort
    this.pagination.current = 1
  }

  setFilters(filters: FilterCondition[]) {
    this.filters = filters
    this.pagination.current = 1
  }

  setSearchKeyword(keyword: string) {
    this.searchKeyword = keyword
  }

  async loadFields() {
    if (!this.fieldFetcher || !this.entityApiKey) return
    try {
      const fields = await this.fieldFetcher(this.entityApiKey)
      runInAction(() => { this.fields = fields })
    } catch {
      runInAction(() => { this.fields = [] })
    }
  }

  async loadData() {
    if (!this.fetcher || !this.entityApiKey) return
    runInAction(() => { this.loading = true })
    try {
      const result = await this.fetcher({
        entityApiKey: this.entityApiKey,
        page: this.pagination.current,
        pageSize: this.pagination.pageSize,
        sort: this.sort,
        filters: this.filters,
        keyword: this.searchKeyword,
      })
      runInAction(() => {
        this.records = result.records
        this.pagination.total = result.total
      })
    } catch {
      runInAction(() => { this.records = []; this.pagination.total = 0 })
    } finally {
      runInAction(() => { this.loading = false })
    }
  }
}

import axios from 'axios'

export const api = axios.create({ baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1', timeout: 15000 })

export const getMorningCache = () => api.get('/morning/cache').then((response) => response.data)
export const getMorningHistory = (limit = 20) => api.get('/morning/history', { params: { limit } }).then((response) => response.data)
export const getMorningStreamUrl = (params: Record<string, string | number | boolean>) => {
  const base = import.meta.env.VITE_API_BASE_URL || '/api/v1'
  const query = new URLSearchParams(Object.entries(params).map(([key, value]) => [key, String(value)]))
  return `${base}/morning/stream?${query.toString()}`
}
export const getMorningReportUrl = (path: string, format = 'html') => {
  const base = import.meta.env.VITE_API_BASE_URL || '/api/v1'
  return `${base}/morning/report?path=${encodeURIComponent(path)}&format=${format}`
}

const redactForLog = (value: unknown): unknown => {
  if (!value || typeof value !== 'object') return value
  if (Array.isArray(value)) return value.slice(0, 20).map(redactForLog)
  return Object.fromEntries(Object.entries(value as Record<string, unknown>).map(([key, item]) => {
    const sensitive = /password|token|secret|api.?key|authorization|cookie/i.test(key)
    return [key, sensitive ? '***REDACTED***' : redactForLog(item)]
  }))
}
const compactForLog = (value: unknown) => {
  try {
    const text = JSON.stringify(redactForLog(value))
    return text.length > 2000 ? `${text.slice(0, 2000)}...<truncated>` : text
  } catch {
    return '<unserializable>'
  }
}

type RequestMetadata = { startedAt: number; requestId: string }
type RequestConfig = typeof api.defaults & { metadata?: RequestMetadata }

api.interceptors.request.use((config) => {
  const requestConfig = config as typeof config & { metadata?: RequestMetadata }
  const requestId = requestConfig.metadata?.requestId || crypto.randomUUID()
  requestConfig.metadata = { startedAt: Date.now(), requestId }
  config.headers = config.headers || {}
  config.headers['X-Request-ID'] = requestId
  console.info('[api-request]', config.method?.toUpperCase(), config.url, {
    requestId: requestConfig.metadata.requestId, params: redactForLog(config.params), data: redactForLog(config.data),
  })
  return config
})
api.interceptors.response.use((response) => {
  const metadata = (response.config as typeof response.config & { metadata?: { startedAt: number; requestId: string } }).metadata
  console.info('[api-response]', response.status, response.config.url, {
    requestId: metadata?.requestId, durationMs: metadata ? Date.now() - metadata.startedAt : undefined,
    data: compactForLog(response.data),
  })
  return response
}, (error) => {
  const config = error.config as RequestConfig | undefined
  console.error('[api-error]', error.message, {
    requestId: config?.metadata?.requestId, url: config?.url, status: error.response?.status,
    durationMs: config?.metadata ? Date.now() - config.metadata.startedAt : undefined,
    response: compactForLog(error.response?.data),
  })
  return Promise.reject(error)
})

export type ApiRow = Record<string, any>
export type Signal = ApiRow & { stock_code?: string; signal_type?: string; signal_status?: string; signal_date?: string }
export type Kline = ApiRow & { trade_date: string; open_price: number; high_price: number; low_price: number; close_price: number; volume?: number }

export const getOverview = () => api.get('/dashboard/overview').then((response) => response.data)
export const getOpportunities = (params?: Record<string, string | number | boolean | string[]>) => api.get('/opportunities', {
  params,
  paramsSerializer: (values) => {
    const search = new URLSearchParams()
    Object.entries(values).forEach(([key, value]) => {
      if (Array.isArray(value)) value.forEach((item) => search.append(key, item))
      else if (value !== '' && value != null && value !== false) search.append(key, String(value))
    })
    return search.toString()
  },
}).then((response) => response.data)
export const scanOpportunities = (params?: Record<string, string>) => api.post('/opportunities/scan', null, { params, timeout: 10 * 60 * 1000 }).then((response) => response.data)
export const getOpportunityDetail = (stockCode: string, signalDate: string) => api.get(`/opportunities/${stockCode}/${signalDate}`).then((response) => response.data)
const withoutEmptyParams = (params?: Record<string, string | number>) =>
  Object.fromEntries(Object.entries(params || {}).filter(([, value]) => value !== ''))

export const getSectorOpportunities = (params?: Record<string, string | number>) =>
  api.get('/sector-opportunities', { params: withoutEmptyParams(params) }).then((response) => response.data)
export const scanSectorOpportunities = (params?: Record<string, string | number>) =>
  api.post('/sector-opportunities/scan', null, { params: withoutEmptyParams(params), timeout: 10 * 60 * 1000 }).then((response) => response.data)
export const getSectorOpportunityDetail = (id: number) => api.get(`/sector-opportunities/${id}`).then((response) => response.data)
export const getSignals = (params?: Record<string, string | number>) => api.get('/signals', { params }).then((response) => response.data)
export const getKline = (code: string, limit = 120) => api.get('/stocks/daily', { params: { code, limit } }).then((response) => response.data)
export const getSyncOverview = () => api.get('/sync/overview').then((response) => response.data)
export const getSyncLogDetail = (logId: number) => api.get(`/sync/logs/${logId}`).then((response) => response.data)
export const getSyncTasks = () => api.get('/sync/tasks').then((response) => response.data)
export const runSyncTask = (taskName: string, parameters: Record<string, unknown> = {}) => api.post(`/sync/run/${taskName}`, parameters).then((response) => response.data)
export const retrySyncTask = (taskName: string) => runSyncTask(taskName)
export const getSyncLogs = (params?: Record<string, string | number>) => api.get('/sync/logs', { params: { limit: 20, ...params } }).then((response) => response.data)
export const getQlibDataSourceStatus = () => api.get('/qlib/data-source/status').then((response) => response.data)
export const syncQlibDataSource = (force = false) => api.post('/qlib/data-source/sync', null, { params: { force } }).then((response) => response.data)
export const getQlibDataSyncRun = (syncRunId: string) => api.get(`/qlib/data-source/sync/${syncRunId}`).then((response) => response.data)
export const getQlibDataSyncLogs = (syncRunId: string) => api.get(`/qlib/data-source/sync/${syncRunId}/logs`).then((response) => response.data)
export const getQlibTimeSplit = (params?: Record<string, string>) => api.get('/qlib/research/time-split', { params }).then((response) => response.data)
export const getQlibResearchRuns = (limit = 20) => api.get('/qlib/research/runs', { params: { limit } }).then((response) => response.data)
export const getQlibResearchRun = (runId: string) => api.get(`/qlib/research/runs/${runId}`).then((response) => response.data)
export const getQlibResearchPools = () => api.get('/qlib/research/pools').then((response) => response.data)
export const validateQlibResearchPool = (payload: Record<string, unknown>) => api.post('/qlib/research/pools/validate', payload).then((response) => response.data)
export const createQlibResearchRun = (payload: Record<string, unknown>) => api.post('/qlib/research/runs', payload, { timeout: 10 * 60 * 1000 }).then((response) => response.data)
export const cancelQlibResearchRun = (runId: string) => api.post(`/qlib/research/runs/${runId}/cancel`).then((response) => response.data)
export const getQlibResearchPredictions = (runId: string, params?: Record<string, string | number>) => api.get(`/qlib/research/runs/${runId}/predictions`, { params }).then((response) => response.data)
export const getQlibResearchLogs = (runId: string) => api.get(`/qlib/research/runs/${runId}/logs`).then((response) => response.data)
export const getRisks = (params?: Record<string, string | number>) => api.get('/risks', { params }).then((response) => response.data)
export const checkRisk = (payload: Record<string, unknown>) => api.post('/risk/check', payload).then((response) => response.data)
export const getRiskStatus = () => api.get('/risk/status').then((response) => response.data)
export const getRiskAlerts = (status = 'active') => api.get('/risk/alerts', { params: { status } }).then((response) => response.data)
export const acknowledgeRiskAlert = (id: number) => api.post(`/risk/alerts/${id}/acknowledge`).then((response) => response.data)
export const getTradePlans = (params?: Record<string, string | number>) => api.get('/trade-plans', { params }).then((response) => response.data)
export const createTradePlan = (payload: Record<string, unknown>) => api.post('/trade-plans', payload).then((response) => response.data)
export const updateTradePlan = (id: string, action: 'accept' | 'reject') => api.post(`/trade-plans/${id}/${action}`).then((response) => response.data)
export const runBacktest = (payload: Record<string, unknown>) => api.post('/backtest/run', payload).then((response) => response.data)

export type DiagnosisRequest = {
  symbol: string
  periods?: string[]
  modules?: string[]
  date_range?: { start?: string; end?: string }
  start_date?: string
  end_date?: string
  force_refresh?: boolean
  agent_types?: string[]
  risk_budget?: number
  min_holding_days?: number
  max_holding_days?: number
}

export type ChatRequest = { message: string; session_id: string }
export const sendChatMessage = (payload: ChatRequest) => api.post('/chat', payload, { timeout: 180000 }).then((response) => response.data)

export const searchDiagnosisStocks = (q = '', limit = 20) => api.get('/diagnoses/stocks/search', { params: { q, limit } }).then((response) => response.data)
export const getDiagnosisStockOverview = (symbol: string) => api.get(`/diagnoses/stocks/${symbol}/overview`).then((response) => response.data)
export const createDiagnosis = (payload: DiagnosisRequest) => api.post('/diagnoses', payload).then((response) => response.data)
export const getDiagnoses = (symbol?: string, limit = 20) => api.get('/diagnoses', { params: { ...(symbol ? { symbol } : {}), limit } }).then((response) => response.data)
export const getDiagnosisStatus = (diagnosisId: string) => api.get(`/diagnoses/${diagnosisId}/status`).then((response) => response.data)
export const getDiagnosisReport = (diagnosisId: string) => api.get(`/diagnoses/${diagnosisId}/report`).then((response) => response.data)
export const createDiagnosisResearchReport = (diagnosisId: string) => api.post(`/diagnoses/${diagnosisId}/research-report`).then((response) => response.data)
export const getDiagnosisResearchReport = (diagnosisId: string) => api.get(`/diagnoses/${diagnosisId}/research-report`).then((response) => response.data)
export const getDiagnosisEvents = (diagnosisId: string, limit = 100) => api.get(`/diagnoses/${diagnosisId}/event-analysis`, { params: { limit } }).then((response) => response.data)
export const getDiagnosisAgents = (diagnosisId: string) => api.get(`/diagnoses/${diagnosisId}/agents`).then((response) => response.data)
export const getDiagnosisDebate = (diagnosisId: string) => api.get(`/diagnoses/${diagnosisId}/debate`).then((response) => response.data)
export const getDiagnosisConsensus = (diagnosisId: string) => api.get(`/diagnoses/${diagnosisId}/consensus`).then((response) => response.data)
export const getDiagnosisNewsPolicy = (diagnosisId: string) => api.get(`/diagnoses/${diagnosisId}/news-policy`).then((response) => response.data)
export const getDiagnosisRiskReward = (diagnosisId: string) => api.get(`/diagnoses/${diagnosisId}/risk-reward`).then((response) => response.data)
export const getDiagnosisIndustryComparison = (diagnosisId: string) => api.get(`/diagnoses/${diagnosisId}/industry-comparison`).then((response) => response.data)
export const cancelDiagnosis = (diagnosisId: string) => api.post(`/diagnoses/${diagnosisId}/cancel`).then((response) => response.data)
export const retryDiagnosis = (diagnosisId: string) => api.post(`/diagnoses/${diagnosisId}/retry`).then((response) => response.data)
export const diagnosisExportUrl = (diagnosisId: string) => `${api.defaults.baseURL}/diagnoses/${diagnosisId}/export`

// ============================================================ 舆情分析师 / 舆情报告
export const getSentimentAggregate = (stockCode?: string, limit = 20) =>
  api.get('/sentiment/aggregate', { params: { stock_code: stockCode, limit } }).then((response) => response.data)
export const getSentimentDetail = (stockCode?: string, sentiment?: string, limit = 50) =>
  api.get('/sentiment/detail', { params: { stock_code: stockCode, sentiment, limit } }).then((response) => response.data)
export const getSentimentEvents = (stockCode?: string, eventType?: string, limit = 50) =>
  api.get('/sentiment/events', { params: { stock_code: stockCode, event_type: eventType, limit } }).then((response) => response.data)
export const getFearIndexHistory = (limit = 60) =>
  api.get('/sentiment/fear-index', { params: { limit } }).then((response) => response.data)

export const generateSentimentReport = (stockCode: string, days = 7) =>
  api.post(`/sentiment-reports/${stockCode}`, null, { params: { days }, timeout: 15 * 60 * 1000 }).then((response) => response.data)
export const getSentimentReport = (stockCode: string, reportId?: string) =>
  api.get(`/sentiment-reports/${stockCode}${reportId ? `/${reportId}` : ''}`).then((response) => response.data)
export const getSentimentReportHistory = (stockCode: string, limit = 20) =>
  api.get(`/sentiment-reports/${stockCode}/history`, { params: { limit } }).then((response) => response.data)
export const getSentimentReportStreamUrl = (params: Record<string, string | number | boolean>) => {
  const base = import.meta.env.VITE_API_BASE_URL || '/api/v1'
  const query = new URLSearchParams(Object.entries(params).map(([key, value]) => [key, String(value)]))
  return `${base}/sentiment-reports/stream?${query.toString()}`
}
export const getSentimentReportFileUrl = (path: string, format: 'html' | 'markdown' = 'html') => {
  const base = import.meta.env.VITE_API_BASE_URL || '/api/v1'
  return `${base}/sentiment-reports/report?path=${encodeURIComponent(path)}&format=${format}`
}

export const getPolymarketSignals = (keyword?: string, limit = 50) =>
  api.get('/polymarket/signals', { params: { keyword, limit } }).then((response) => response.data)
export const getPolymarketSmartMoney = (limit = 20) =>
  api.get('/polymarket/signals/smart-money', { params: { limit } }).then((response) => response.data)
export const getPolymarketAssetSuggestions = (limit = 20) =>
  api.get('/polymarket/signals/asset-suggestions', { params: { limit } }).then((response) => response.data)
export const syncPolymarket = () => api.post('/polymarket/sync').then((response) => response.data)

export const listSentimentWatchlist = (group = 'default') =>
  api.get('/sentiment/watchlist', { params: { group } }).then((response) => response.data)
export const addSentimentWatch = (payload: Record<string, unknown>) =>
  api.post('/sentiment/watchlist', payload).then((response) => response.data)
export const updateSentimentWatch = (group: string, stockCode: string, payload: Record<string, unknown>) =>
  api.put(`/sentiment/watchlist/${group}/${stockCode}`, payload).then((response) => response.data)
export const removeSentimentWatch = (group: string, stockCode: string) =>
  api.delete(`/sentiment/watchlist/${group}/${stockCode}`).then((response) => response.data)
export const getSentimentWatchlistAlerts = (group = 'default') =>
  api.get('/sentiment/watchlist/alerts', { params: { group } }).then((response) => response.data)

// ============================================================ 基本面分析师
export const getFundamentalAnalysis = (stockCode: string) =>
  api.get('/fundamental/analyze', { params: { stock_code: stockCode } }).then((response) => response.data)

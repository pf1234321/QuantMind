import { useEffect, useState } from 'react'
import { Alert, App as AntApp, Button, Card, Collapse, ConfigProvider, Descriptions, Drawer, Empty, Form, Input, InputNumber, Layout, Menu, message, Modal, Progress, Select, Segmented, Space, Statistic, Table, Tag, Typography, theme } from 'antd'
import { DashboardOutlined, RadarChartOutlined, SafetyOutlined, SyncOutlined, ClockCircleOutlined, MessageOutlined, SendOutlined, DeleteOutlined, AuditOutlined, LineChartOutlined } from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { MorningBrief } from './MorningBrief'
import { SentimentAnalystWithContext as SentimentAnalyst } from './SentimentAnalyst'
import { FundamentalAnalyst } from './FundamentalAnalyst'
import TechnicalAnalyst from './TechnicalAnalyst'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { acknowledgeRiskAlert, cancelDiagnosis, checkRisk, createDiagnosis, createQlibResearchRun, diagnosisExportUrl, getDiagnosisReport, getDiagnosisStatus, getDiagnosisStockOverview, getDiagnoses, getQlibDataSourceStatus, getQlibDataSyncLogs, getQlibDataSyncRun, syncQlibDataSource, getQlibResearchLogs, getQlibResearchPools, getQlibResearchPredictions, getQlibResearchRun, getQlibResearchRuns, getQlibTimeSplit, validateQlibResearchPool, createTradePlan, getKline, getOpportunityDetail, getOpportunities, getOverview, getRiskAlerts, getRiskStatus, getSectorOpportunityDetail, sendChatMessage, getSectorOpportunities, getSyncLogs, getSyncTasks, getSyncOverview, retrySyncTask, runSyncTask, getTradePlans, scanOpportunities, scanSectorOpportunities, searchDiagnosisStocks, updateTradePlan } from './api/client'

const { Header, Sider, Content } = Layout
const signalTypeLabels: Record<string, string> = { first_buy: '一买', second_buy: '二买', third_buy: '三买', first_sell: '一卖', second_sell: '二卖', third_sell: '三卖' }
const statusLabels: Record<string, string> = { confirmed: '已确认', pending: '待确认', executed: '已执行', rejected: '已拒绝' }
const actionLabels: Record<string, string> = { candidate: '买入候选', exit_management: '卖出管理', observe: '观察' }
const levelLabels: Record<string, string> = { daily: '日线', weekly: '周线', monthly: '月线' }
const strengthLabels: Record<string, string> = { strong: '强', medium: '中', weak: '弱' }
const strategyLabels: Record<string, string> = { internal_chan_atr: '缠论 ATR 策略' }
const diagnosisModuleLabels: Record<string, string> = { market: '行情数据', fundamental: '基本面', technical: '技术面', chan: '缠论分析', factor: '因子分析', risk: '风险评估', quantitative: '定量风险收益', industry_comparison: '行业横向比较', news_policy: '新闻舆情与政策', agent_analysis: '智能体分析', debate: '多空辩论', consensus: '共识裁决', research: '国泰君安五步法' }
const diagnosisStatusLabels: Record<string, string> = { queued: '排队中', running: '分析中', completed: '已完成', partial: '部分完成（基础诊断已完成）', failed: '失败', cancelled: '已取消', expired: '已过期' }
const diagnosisStageLabels: Record<string, string> = { market: '行情数据', fundamental: '基本面分析', technical: '技术面分析', chan: '缠论分析', factor: '因子分析', risk: '风险评估', quantitative: '定量风险收益', industry_comparison: '行业横向比较', news_policy: '新闻舆情与政策', agent_analysis: '智能体分析', debate: '多空辩论', consensus: '共识裁决', research_report: '国泰君安五步法', report: '综合报告' }
const diagnosisFieldLabels: Record<string, string> = { symbol: '股票代码', stock_code: '股票代码', name: '股票名称', stock_name: '股票名称', sector_1: '一级行业', sector_2: '二级行业', sector_3: '三级行业', list_date: '上市日期', data_as_of: '数据截至', signal_date: '信号日期', score: '评分', trend: '趋势', confidence: '置信度', level: '风险等级', items: '风险项', fundamental_score: '基本面风险得分', fundamental_level: '基本面风险等级', fundamental_tags: '基本面风险标签', fundamental_categories: '基本面风险分类' }
const detailLabels: Record<string, string> = { strategy_name: '策略名称', stock_name: '股票名称', stock_code: '股票代码', signal_type: '信号类型', signal_status: '信号状态', signal_date: '信号日期', signal_market_date: '行情日期', confirmed_date: '确认日期', execution_date: '执行日期', signal_level: '信号级别', signal_price: '策略计算价格', signal_close_price: '信号日收盘价', center_lower: '中枢下沿', center_upper: '中枢上沿', signal_strength: '信号强度', atr_value: 'ATR波动值', lookahead_risk: '前视风险', category: '信号分类', action: '操作建议' }

const formatSignalType = (value: unknown) => signalTypeLabels[String(value)] || String(value || '-')
const formatStatus = (value: unknown) => statusLabels[String(value)] || String(value || '-')
const formatAction = (value: unknown) => actionLabels[String(value)] || String(value || '-')
const formatLevel = (value: unknown) => levelLabels[String(value)] || String(value || '-')
const formatStrength = (value: unknown) => strengthLabels[String(value)] || String(value || '-')
const formatStrategy = (value: unknown) => strategyLabels[String(value)] || String(value || '-')
const formatDiagnosisStatus = (value: unknown) => diagnosisStatusLabels[String(value)] || String(value || '-')
const formatDiagnosisStage = (value: unknown) => diagnosisStageLabels[String(value)] || String(value || '-')
const diagnosisValueLabels: Record<string, string> = { healthy: '数据正常', unavailable: '暂无数据', warning: '需要关注', low: '低风险', medium: '中风险', medium_strength: '中等', high: '高风险', confirmed: '已确认', pending: '待确认', strong: '强', weak: '弱', first_buy: '一买', second_buy: '二买', third_buy: '三买', first_sell: '一卖', second_sell: '二卖', third_sell: '三卖', daily: '日线', weekly: '周线', monthly: '月线', enhanced: '增强', weakened: '减弱', data_missing: '数据缺失', candidate: '买入候选', observe: '观察', exit_management: '卖出管理', true: '是', false: '否' }
const diagnosisDetailLabels: Record<string, string> = { ...diagnosisFieldLabels, report_date: '报告日期', close: '收盘价', open: '开盘价', high: '最高价', low: '最低价', volume: '成交量', amount: '成交额', turnover_rate: '换手率', price: '价格', momentum: '动量', support: '支撑位', resistance: '压力位', macd: 'MACD柱', dif: 'MACD快线（DIF）', dea: 'MACD慢线（DEA）', ma5: '5日均线', ma10: '10日均线', ma20: '20日均线', ma60: '60日均线', ma120: '120日均线', rsi14: 'RSI相对强弱（14日）', volume_ratio: '量比', atr_value: 'ATR波动值', signal_type: '信号类型', signal_status: '信号状态', signal_level: '信号级别', signal_strength: '信号强度', pivot_date: '中枢日期', pivot_type: '中枢类型', center_lower: '中枢下沿', center_upper: '中枢上沿', signal_price: '信号价格', skip_reason: '跳过原因', lookahead_risk: '前视风险', message: '分析结论', description: '说明', type: '类型', source: '数据来源', data_source: '数据来源', factor_version: '因子版本', categories: '分类评分', factors: '因子指标', metrics: '技术指标', history: '历史数据', signals: '信号列表', latest_signal: '最新信号', data_status: '数据状态', change_percent: '涨跌幅', data_quality: '数据质量', issues: '问题项' }
const formatDiagnosisKey = (key: string) => diagnosisDetailLabels[key] || key.split('_').join(' ')
const formatDiagnosisValue = (key: string, value: unknown) => {
  if (value == null || value === '') return '-'
  if (key === 'trend') return ({ up: '上升', down: '下降', flat: '震荡', 上升: '上升', 下降: '下降', 震荡: '震荡' } as Record<string, string>)[String(value)] || String(value)
  if (key === 'level') return ({ low: '低风险', medium: '中风险', high: '高风险' } as Record<string, string>)[String(value)] || String(value)
  if (key === 'data_status') return diagnosisValueLabels[String(value)] || String(value)
  if (key === 'change_percent') return typeof value === 'number' ? `${value >= 0 ? '+' : ''}${value.toFixed(2)}%` : String(value)
  if (key === 'confidence') return typeof value === 'number' && value <= 1 ? `${Math.round(value * 100)}%` : String(value)
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (typeof value === 'string') return diagnosisValueLabels[value] || value
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(4).replace(/0+$/, '').replace(/\.$/, '')
  return String(value)
}
const DiagnosisContent = ({ value, compact = false }: { value: unknown; compact?: boolean }) => {
  if (Array.isArray(value)) return <div className="diagnosis-list">{value.length ? value.map((item, index) => <div className="diagnosis-list-item" key={index}><div className="diagnosis-item-title">{typeof item === 'object' && item ? formatDiagnosisValue('signal_type', (item as Record<string, unknown>).signal_type) || `第 ${index + 1} 项` : `第 ${index + 1} 项`}</div><DiagnosisContent value={item} compact /></div>) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无相关数据" />}</div>
  if (value && typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>)
    const scalarEntries = entries.filter(([, item]) => item == null || typeof item !== 'object')
    const nestedEntries = entries.filter(([, item]) => item && typeof item === 'object')
    return <div className={`diagnosis-content ${compact ? 'diagnosis-content-compact' : ''}`}>
      {scalarEntries.length > 0 && <div className="diagnosis-metric-grid">{scalarEntries.map(([key, item]) => <div className="diagnosis-metric" key={key}><span>{formatDiagnosisKey(key)}</span><strong>{formatDiagnosisValue(key, item)}</strong></div>)}</div>}
      {nestedEntries.map(([key, item]) => <div className="diagnosis-subsection" key={key}><div className="diagnosis-subsection-title">{formatDiagnosisKey(key)}</div><DiagnosisContent value={item} compact /></div>)}
    </div>
  }
  return <Typography.Text>{formatDiagnosisValue('', value)}</Typography.Text>
}

const agentLabels: Record<string, string> = { fundamental: '基本面 Agent', technical: '技术面 Agent', chan: '缠论 Agent', factor: '因子 Agent', risk: '风险 Agent', sentiment: '消息面 Agent' }
const opinionLabels: Record<string, string> = { bullish: '偏多', neutral: '中性', bearish: '偏空' }
const opinionColors: Record<string, string> = { bullish: 'green', neutral: 'blue', bearish: 'red' }
const AgentCard = ({ item, onClick }: { item: any; onClick: () => void }) => <Card size="small" className="agent-result-card clickable-row" hoverable onClick={onClick} title={agentLabels[item.agent_type] || item.agent_type} extra={<Space><Tag color={opinionColors[item.opinion] || 'default'}>{opinionLabels[item.opinion] || item.opinion || '未知'}</Tag><Tag>{item.status === 'completed' ? '已完成' : item.status}</Tag></Space>}><Space direction="vertical" style={{ width: '100%' }}><Typography.Text>{item.summary || '-'}</Typography.Text><Progress percent={Number(item.score || 0)} size="small" format={(value) => `评分 ${value}`} /><Typography.Text type="secondary">置信度：{formatDiagnosisValue('confidence', item.confidence)}　数据截至：{item.data_as_of || '-'}</Typography.Text><Typography.Text type="secondary">点击查看详细分析 →</Typography.Text></Space></Card>
const AgentAnalysisPanel = ({ value, debate, consensus }: { value: any; debate: any; consensus: any }) => { const [selectedAgent, setSelectedAgent] = useState<any>(null); const agents = Object.values(value || {}) as any[]; return <div className="agent-panel"><Typography.Text type="secondary">以下为各专业 Agent 的核心判断，点击卡片查看详细分析。</Typography.Text><div className="agent-grid">{agents.map((item) => <AgentCard item={item} key={item.agent_type} onClick={() => setSelectedAgent(item)} />)}</div><Drawer title={selectedAgent ? `${agentLabels[selectedAgent.agent_type] || selectedAgent.agent_type} · 详细分析` : 'Agent 详细分析'} open={Boolean(selectedAgent)} onClose={() => setSelectedAgent(null)} width={560}>{selectedAgent && <Space direction="vertical" style={{ width: '100%' }}><Descriptions size="small" column={1} items={[{ label: '核心结论', children: selectedAgent.summary || '-' }, { label: '观点', children: <Tag color={opinionColors[selectedAgent.opinion] || 'default'}>{opinionLabels[selectedAgent.opinion] || selectedAgent.opinion || '未知'}</Tag> }, { label: '评分', children: selectedAgent.score ?? '-' }, { label: '置信度', children: formatDiagnosisValue('confidence', selectedAgent.confidence) }, { label: '数据截至', children: selectedAgent.data_as_of || '-' }]} /><Typography.Title level={5}>详细结果</Typography.Title><DiagnosisContent value={selectedAgent} /> </Space>}</Drawer>{debate && <div className="agent-debate"><Typography.Title level={5}>多空观点辩论</Typography.Title><div className="debate-columns"><div><Tag color="green">多头观点</Tag>{(debate.bull_case || []).map((item: string, i: number) => <p key={i}>{item}</p>)}</div><div><Tag color="red">空头观点</Tag>{(debate.bear_case || []).map((item: string, i: number) => <p key={i}>{item}</p>)}</div></div>{debate.disputed_points?.map((item: string, i: number) => <Alert key={i} type="warning" showIcon message={item} />)}</div>}{consensus && <Alert className="consensus-alert" type={consensus.opinion === 'bullish' ? 'success' : consensus.opinion === 'bearish' ? 'error' : 'info'} showIcon message={`共识裁决：${opinionLabels[consensus.opinion] || '暂不可用'}`} description={<Space direction="vertical"><span>综合评分：{consensus.score ?? '-'}　置信度：{formatDiagnosisValue('confidence', consensus.confidence)}</span>{consensus.supporting_factors?.length > 0 && <span>主要支持：{consensus.supporting_factors.join('；')}</span>}{consensus.risk_factors?.length > 0 && <span>主要风险：{consensus.risk_factors.join('；')}</span>}<span>结论失效条件：{(consensus.invalidation_conditions || []).join('；')}</span></Space>} />}</div> }


const menu = [
  // 核心功能
  { key: 'dashboard', icon: <DashboardOutlined />, label: 'Dashboard' },
  { key: 'morning-brief', icon: <ClockCircleOutlined />, label: '晨会分析' },

  // 个股分析
  { key: 'diagnosis', icon: <RadarChartOutlined />, label: '个股诊断' },
  { key: 'fundamental-analyst', icon: <DashboardOutlined />, label: '基本面分析师' },
  { key: 'technical-analyst', icon: <LineChartOutlined />, label: '技术分析师' },
  { key: 'sentiment-analyst', icon: <AuditOutlined />, label: '舆情分析师' },

  // 交易机会
  { key: 'opportunities', icon: <RadarChartOutlined />, label: '缠论机会看板' },
  { key: 'sector-opportunities', icon: <RadarChartOutlined />, label: '板块选股机会' },

  // 风险管理
  { key: 'risk-control', icon: <SafetyOutlined />, label: '独立风控看板' },
  { key: 'risks', icon: <SafetyOutlined />, label: '风险与交易计划' },

  // 高级功能
  { key: 'chat', icon: <MessageOutlined />, label: 'AI 对话分析' },
  { key: 'qlib-research', icon: <ClockCircleOutlined />, label: 'Qlib 因子研究' },

  // 系统管理
  { key: 'sync', icon: <SyncOutlined />, label: '数据同步' },
]

function Dashboard({ onNavigate }: { onNavigate: (page: string) => void }) {
  const overviewQuery = useQuery({ queryKey: ['overview'], queryFn: getOverview })
  const opportunitiesQuery = useQuery({ queryKey: ['dashboard-opportunities'], queryFn: () => getOpportunities({ category: 'chan-buy', page: 1, page_size: 8 }) })
  const risksQuery = useQuery({ queryKey: ['dashboard-risks'], queryFn: () => getRiskAlerts('active') })
  const overview = overviewQuery.data || {}
  const summary = overview.signal_summary || {}
  const opportunities = opportunitiesQuery.data?.data || overview.top_opportunities || []
  const overviewRisks = overview.risk_alerts || []
  const riskResponse = risksQuery.data
  const risks = Array.isArray(riskResponse) ? riskResponse : riskResponse?.data || riskResponse?.alerts || overviewRisks
  const totalSignals = Number(summary.total || 0)
  const buyCount = Number(summary.buy_count || 0)
  const sellCount = Number(summary.sell_count || 0)
  const riskCount = Number(summary.risk_count || risks.length || 0)
  const marketTone = buyCount > sellCount * 1.25 ? '机会占优' : sellCount > buyCount * 1.25 ? '风险偏高' : '多空均衡'
  const toneColor = marketTone === '机会占优' ? '#52c41a' : marketTone === '风险偏高' ? '#ff7875' : '#69b1ff'
  const signalChart = { tooltip: { trigger: 'item' }, legend: { bottom: 0, textStyle: { color: '#9fb3d8' } }, series: [{ type: 'pie', radius: ['58%', '78%'], center: ['50%', '46%'], avoidLabelOverlap: true, label: { show: false }, itemStyle: { borderColor: '#101a2d', borderWidth: 4 }, data: [{ value: buyCount, name: '买入信号', itemStyle: { color: '#52c41a' } }, { value: sellCount, name: '卖出信号', itemStyle: { color: '#ff7875' } }, { value: Math.max(totalSignals - buyCount - sellCount, 0), name: '其他信号', itemStyle: { color: '#59708f' } }] }] }
  const formatSignalDate = (value: unknown) => String(value || '-').slice(0, 10)
  return <div className="dashboard-page">
    <div className="dashboard-hero"><div><Typography.Text className="eyebrow">MARKET CONTROL CENTER</Typography.Text><Typography.Title level={2}>市场全局驾驶舱</Typography.Title><Typography.Text type="secondary">用一屏掌握信号、机会与风险的当前分布</Typography.Text></div><div className="dashboard-status"><span className="status-dot" />{overview.system_status?.scheduler_enabled ? '数据任务运行中' : '研究模式'}<Button type="text" onClick={() => { overviewQuery.refetch(); opportunitiesQuery.refetch(); risksQuery.refetch() }}>刷新数据</Button></div></div>
    <div className="dashboard-signal-banner"><div><Typography.Text type="secondary">当前市场判断</Typography.Text><strong style={{ color: toneColor }}>{marketTone}</strong><Typography.Text type="secondary">基于当前已确认信号的结构性统计</Typography.Text></div><div className="dashboard-banner-meta"><Tag color="green">严格无前视</Tag><span>信号总量 {totalSignals}</span><span>更新时间 {new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}</span></div></div>
    <div className="dashboard-metric-grid">{[['机会信号', buyCount, '可跟踪的买入候选', 'positive'], ['卖出信号', sellCount, '需要管理的退出信号', 'negative'], ['风险提醒', riskCount, '当前待处理风险项', 'warning'], ['信号总量', totalSignals, '系统累计识别信号', 'neutral']].map(([title, value, hint, tone]) => <Card className={`dashboard-metric-card ${tone}`} key={String(title)}><Statistic title={title} value={value} /><Typography.Text type="secondary">{hint}</Typography.Text></Card>)}</div>
    <div className="dashboard-main-grid"><Card className="dashboard-panel" title={<span>机会雷达 <Typography.Text type="secondary">· 最新买入信号</Typography.Text></span>} extra={<Button type="link" onClick={() => onNavigate('opportunities')}>查看全部</Button>}><div className="signal-list">{opportunities.length ? opportunities.map((item: any, index: number) => <div className="signal-row" key={item.id || `${item.stock_code}-${item.signal_date}-${index}`}><div className="signal-rank">{String(index + 1).padStart(2, '0')}</div><div className="signal-stock"><strong>{item.stock_name || item.stock_code || '-'}</strong><span>{item.stock_code || '-'} · {formatSignalDate(item.signal_date)}</span></div><Tag color="green">{formatSignalType(item.signal_type)}</Tag><span className="signal-action">{formatAction(item.action || 'candidate')}</span></div>) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无机会信号" />}</div></Card><Card className="dashboard-panel" title={<span>风险监控 <Typography.Text type="secondary">· 待关注</Typography.Text></span>} extra={<Button type="link" onClick={() => window.dispatchEvent(new CustomEvent('dashboard-navigate', { detail: 'risk-control' }))}>进入风控</Button>}><div className="risk-list">{risks.length ? risks.slice(0, 6).map((item: any, index: number) => <div className="risk-row" key={item.id || `${item.stock_code}-${index}`}><div className={`risk-level ${String(item.level || item.severity || 'medium').toLowerCase()}`}>{String(item.level || item.severity || '中').slice(0, 1)}</div><div><strong>{item.stock_name || item.stock_code || item.title || '系统风险项'}</strong><span>{item.message || item.description || item.risk_type || '需要进一步检查'}</span></div><Typography.Text type="secondary">{formatSignalDate(item.created_at || item.signal_date)}</Typography.Text></div>) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前无活动风险" />}</div></Card></div>
    <div className="dashboard-bottom-grid"><Card className="dashboard-panel signal-distribution" title="信号结构"><ReactECharts option={signalChart} style={{ height: 220 }} notMerge /></Card><Card className="dashboard-panel" title="系统运行状态"><div className="system-checks"><div><span className="check-icon">✓</span><div><strong>信号引擎</strong><Typography.Text type="secondary">严格无前视模式</Typography.Text></div><Tag color="green">正常</Tag></div><div><span className="check-icon">✓</span><div><strong>数据服务</strong><Typography.Text type="secondary">行情与信号数据可用</Typography.Text></div><Tag color="green">正常</Tag></div><div><span className="check-icon">✓</span><div><strong>交易约束</strong><Typography.Text type="secondary">仅研究与交易辅助</Typography.Text></div><Tag color="blue">已启用</Tag></div></div></Card></div>
  </div>
}

function OpportunityDetailDrawer({ detail, detailQuery, detailKlineQuery, onClose }: { detail: any; detailQuery: any; detailKlineQuery: any; onClose: () => void }) {
  const [range, setRange] = useState('120')
  const signal = detailQuery.data?.signals?.[0] || detail
  const allKlineRows = [...(detailKlineQuery.data?.data || [])].reverse()
  const klineRows = range === 'all' ? allKlineRows : allKlineRows.slice(-Number(range))
  const dates = klineRows.map((item: any) => item.trade_date)
  const signalIndex = dates.indexOf(signal?.signal_date)
  const hasChartData = klineRows.length > 0
  const formatValue = (key: string, value: unknown) => {
    if (key === 'strategy_name') return formatStrategy(value)
    if (key === 'signal_type') return formatSignalType(value)
    if (key === 'signal_status') return formatStatus(value)
    if (key === 'action') return formatAction(value)
    if (key === 'signal_level') return formatLevel(value)
    if (key === 'signal_strength') return formatStrength(value)
    if (key === 'lookahead_risk') return value ? '是' : '否'
    return String(value ?? '-')
  }
  const chartOption = {
    animation: false,
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
    grid: [{ left: 58, right: 24, top: 22, height: '58%' }, { left: 58, right: 24, top: '75%', height: '16%' }],
    xAxis: [{ type: 'category', data: dates, boundaryGap: true, axisLabel: { color: '#8fa2c7', hideOverlap: true } }, { type: 'category', gridIndex: 1, data: dates, axisLabel: { show: false } }],
    yAxis: [{ type: 'value', scale: true, axisLabel: { color: '#8fa2c7' }, splitLine: { lineStyle: { color: '#263244' } } }, { type: 'value', gridIndex: 1, axisLabel: { color: '#8fa2c7' }, splitLine: { show: false } }],
    dataZoom: [{ type: 'inside', xAxisIndex: [0, 1] }, { type: 'slider', xAxisIndex: [0, 1], height: 18, bottom: 2, borderColor: '#263244', fillerColor: 'rgba(22,119,255,.2)' }],
    series: [{ name: '日K', type: 'candlestick', data: klineRows.map((item: any) => [item.open_price, item.close_price, item.low_price, item.high_price]), markPoint: signalIndex >= 0 ? { symbol: 'pin', symbolSize: 42, data: [{ coord: [signal.signal_date, signal.signal_price], value: formatSignalType(signal.signal_type), itemStyle: { color: '#ff7a45' } }] } : undefined, itemStyle: { color: '#ef5350', color0: '#26a69a', borderColor: '#ef5350', borderColor0: '#26a69a' } }, { name: '成交量', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: klineRows.map((item: any) => item.volume || 0), itemStyle: { color: '#4c9aff' } }]
  }
  return <Drawer open={Boolean(detail)} onClose={onClose} width={980} title={null} styles={{ body: { padding: 0 } }}>
    {detailQuery.isLoading ? <div style={{ padding: 32 }}><Typography.Text type="secondary">正在加载信号详情...</Typography.Text></div> : <div className="opportunity-detail">
      <div className="opportunity-detail-header"><div><Typography.Title level={3} style={{ margin: 0 }}>{signal?.stock_name || detail?.stock_name || '未知股票'}</Typography.Title><Typography.Text type="secondary">{signal?.stock_code || detail?.stock_code} · 机会信号详情</Typography.Text></div><Space><Tag color={signal?.category === 'chan-buy' ? 'green' : 'red'}>{formatSignalType(signal?.signal_type)}</Tag><Tag color="blue">{formatStatus(signal?.signal_status)}</Tag></Space></div>
      <div className="opportunity-detail-meta"><span>信号日期 <strong>{signal?.signal_date || '-'}</strong></span><span>信号价格 <strong>{signal?.signal_price ?? '-'}</strong></span><span>ATR <strong>{signal?.atr_value ?? '-'}</strong></span><span>信号级别 <strong>{formatLevel(signal?.signal_level)}</strong></span></div>
      <div className="opportunity-detail-section"><div className="section-heading"><div><Typography.Title level={5} style={{ margin: 0 }}>日K走势</Typography.Title><Typography.Text type="secondary">仅展示日线行情，共 {detailKlineQuery.data?.count || 0} 条</Typography.Text></div><Segmented size="small" value={range} onChange={(value) => setRange(String(value))} options={[{ label: '60日', value: '60' }, { label: '120日', value: '120' }, { label: '250日', value: '250' }, { label: '全部', value: 'all' }]} /></div>{detailKlineQuery.isLoading ? <div className="detail-chart-placeholder">正在加载行情...</div> : detailKlineQuery.isError ? <Alert type="error" showIcon message="日K行情加载失败" /> : !hasChartData ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无日K行情数据" /> : <ReactECharts style={{ height: 460 }} option={chartOption} notMerge lazyUpdate />}</div>
      <Collapse ghost items={[{ key: 'fields', label: '查看完整信号字段', children: <Descriptions size="small" column={2} items={Object.entries(detailLabels).filter(([key]) => key in (signal || {})).map(([key, label]) => ({ key, label, children: formatValue(key, signal[key]) }))} />}]} />
    </div>}
  </Drawer>
}

function SectorOpportunities() {
  const [phase, setPhase] = useState('')
  const [sectorName, setSectorName] = useState('')
  const [page, setPage] = useState(1)
  const [detail, setDetail] = useState<any>(null)
  const query = useQuery({ queryKey: ['sector-opportunities', phase, sectorName, page], queryFn: () => getSectorOpportunities({ phase, sector_name: sectorName, page, page_size: 20 }) })
  const detailQuery = useQuery({ queryKey: ['sector-opportunity-detail', detail?.id], queryFn: () => getSectorOpportunityDetail(detail.id), enabled: Boolean(detail) })
  const scanMutation = useMutation({ mutationFn: (sectorNames: string) => scanSectorOpportunities({ sector_names: sectorNames, top_n: 5, top_sector_n: 10 }), onSuccess: () => { message.success('板块扫描完成'); setPage(1); query.refetch() }, onError: (error: any) => { message.error(error?.response?.data?.detail || '板块扫描失败') } })
  const rows = query.data?.data || []
  const phaseLabels: Record<string, string> = { accel_up: '加速上涨 / 强势确认', decel_up: '减速上涨 / 趋势衰减', decel_down: '减速下跌 / 潜在反转', accel_down: '加速下跌 / 回避', neutral: '震荡 / 信号不明' }
  const formatPct = (value: any) => value == null ? '-' : `${(Number(value) * 100).toFixed(2)}%`
  const columns = [
    { title: '板块', dataIndex: 'sector_name', fixed: 'left' as const, width: 150 },
    { title: '阶段', dataIndex: 'phase', width: 170, render: (value: string) => <Tag color={value === 'accel_up' ? 'green' : value === 'decel_up' ? 'orange' : 'default'}>{phaseLabels[value] || value}</Tag> },
    { title: '排名', dataIndex: 'sector_rank', width: 70 },
    { title: '强度分', dataIndex: 'strength_score', width: 90, render: (value: any) => Number(value).toFixed(3) },
    { title: 'MOM21', dataIndex: 'mom_21', width: 90, render: formatPct },
    { title: 'RS60', dataIndex: 'rs_60', width: 90, render: formatPct },
    { title: '量比', dataIndex: 'vol_ratio', width: 80, render: (value: any) => value == null ? '-' : Number(value).toFixed(2) },
    { title: '涨/跌', width: 80, render: (_: any, row: any) => `${row.rise_count || 0}/${row.fall_count || 0}` },
    { title: '确认状态', dataIndex: 'confirmation_status', width: 100 },
    { title: '领涨股', width: 130, render: (_: any, row: any) => `${row.top_stock_name || '-'} ${row.top_stock || ''}` },
    { title: '交易日', dataIndex: 'trade_date', width: 110 },
  ]
  return <Space direction="vertical" style={{ width: '100%' }}><Space align="center"><Typography.Title level={3} style={{ margin: 0 }}>板块选股机会</Typography.Title><Button type="primary" loading={scanMutation.isPending} onClick={() => Modal.confirm({ title: '自定义板块扫描', content: <Input id="sector-scan-names" placeholder="请输入申万二级板块名称，多个名称用逗号分隔" />, onOk: () => { const value = (document.getElementById('sector-scan-names') as HTMLInputElement)?.value.trim() || ''; scanMutation.mutate(value) } })}>执行板块扫描</Button></Space><Alert type="info" message="仅使用最新完整交易日的前复权 K 线；板块信号仅用于研究、模拟和交易辅助，不直接下单。" /><Card size="small" title="查询筛选"><Space wrap><Select allowClear value={phase || undefined} onChange={(value) => { setPhase(value || ''); setPage(1) }} placeholder="全部阶段" options={Object.entries(phaseLabels).map(([value, label]) => ({ value, label }))} style={{ width: 180 }} /><Input value={sectorName} onChange={(event) => { setSectorName(event.target.value); setPage(1) }} placeholder="板块名称" style={{ width: 160 }} /></Space></Card><Table rowKey="id" loading={query.isLoading} dataSource={rows} columns={columns} pagination={{ current: page, pageSize: 20, total: query.data?.count || 0, onChange: setPage, showTotal: (value) => `共 ${value} 条` }} onRow={(row) => ({ onClick: () => setDetail(row) })} scroll={{ x: 1250 }} /><Drawer open={Boolean(detail)} onClose={() => setDetail(null)} width={900} title={detail ? `${detail.sector_name} · 板块机会详情` : ''}>{detailQuery.isLoading ? <Typography.Text>正在加载详情...</Typography.Text> : detailQuery.data ? <Space direction="vertical" style={{ width: '100%' }}><Descriptions column={3} size="small" items={[['阶段', phaseLabels[detailQuery.data.phase] || detailQuery.data.phase], ['强度分', Number(detailQuery.data.strength_score).toFixed(3)], ['板块排名', detailQuery.data.sector_rank], ['MOM21', formatPct(detailQuery.data.mom_21)], ['RS60', formatPct(detailQuery.data.rs_60)], ['量比', Number(detailQuery.data.vol_ratio).toFixed(2)], ['确认', detailQuery.data.confirmation_status], ['交易日', detailQuery.data.trade_date]].map(([label, children], index) => ({ key: index, label, children }))} /><Typography.Title level={5}>板块内候选股票</Typography.Title><Table rowKey="stock_code" size="small" pagination={false} dataSource={detailQuery.data.candidates || []} columns={[{ title: '排名', dataIndex: 'stock_rank' }, { title: '股票', render: (_: any, row: any) => `${row.stock_name} (${row.stock_code})` }, { title: '评分', dataIndex: 'stock_score', render: (value: any) => Number(value).toFixed(4) }, { title: '5日', dataIndex: 'roc_5', render: formatPct }, { title: '20日', dataIndex: 'roc_20', render: formatPct }, { title: '60日', dataIndex: 'roc_60', render: formatPct }, { title: '量比', dataIndex: 'vol_ratio', render: (value: any) => Number(value).toFixed(2) }, { title: '均线', dataIndex: 'ma_status' }, { title: '收盘价', dataIndex: 'close_price' }]} /></Space> : <Empty description="暂无板块机会详情" />}</Drawer></Space>
}

function Opportunities() {
  const [category, setCategory] = useState('all')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [filters, setFilters] = useState({ stock_keyword: '', industry: '', start_date: '', end_date: '', turnover_min: '', turnover_max: '', first_buy: false, second_buy: false, third_buy: false, first_sell: false, second_sell: false, third_sell: false })
  const [draftFilters, setDraftFilters] = useState(filters)
  const [detail, setDetail] = useState<any>(null)
  const [planSignal, setPlanSignal] = useState<any>(null)
  const [scanOpen, setScanOpen] = useState(false)
  const [scanCodes, setScanCodes] = useState('')
  const [scanStartDate, setScanStartDate] = useState('2022-01-01')
  const query = useQuery({ queryKey: ['opportunities', category, page, pageSize, filters], queryFn: () => getOpportunities({ category, page, page_size: pageSize, ...filters }) })
  const scanMutation = useMutation({ mutationFn: (params?: Record<string, string>) => scanOpportunities(params), onSuccess: () => { setPage(1); query.refetch(); message.success('扫描完成，结果已刷新') }, onError: (error: any) => { message.error(error?.response?.data?.detail || '扫描失败，请检查行情数据和服务日志') } })
  const detailQuery = useQuery({ queryKey: ['opportunity-detail', detail?.stock_code, detail?.signal_date], queryFn: () => getOpportunityDetail(detail.stock_code, detail.signal_date), enabled: Boolean(detail) })
  const detailKlineQuery = useQuery({ queryKey: ['opportunity-kline', detail?.stock_code], queryFn: () => getKline(detail.stock_code, 180), enabled: Boolean(detail?.stock_code) })
  const mutation = useMutation({ mutationFn: createTradePlan, onSuccess: () => setPlanSignal(null) })
  const rows = query.data?.data || []
  const total = query.data?.count || 0
  const pagination = { current: page, pageSize, total, showSizeChanger: true, showQuickJumper: true, showTotal: (value: number) => `共 ${value} 条记录`, pageSizeOptions: [10, 20, 50, 100], onChange: (nextPage: number, nextPageSize: number) => { setPage(nextPageSize !== pageSize ? 1 : nextPage); setPageSize(nextPageSize) } }
  const formatNumber = (value: unknown, digits = 2) => value == null || value === '' ? '-' : Number(value).toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
  const hasData = (key: string) => rows.some((row: any) => row[key] != null && row[key] !== '')
  const marketColumns = [
    { title: '信号日收盘价', dataIndex: 'signal_close_price', width: 120, render: (value: unknown, _row: any) => formatNumber(value) },
    { title: '最近收盘价', width: 130, render: (_: unknown, row: any) => <Space direction="vertical" size={0}><span>{formatNumber(row.latest_close_price)}</span><Typography.Text type="secondary" style={{ fontSize: 11 }}>{row.latest_close_date || '-'}</Typography.Text></Space> },
    { title: 'ATR', dataIndex: 'atr_value', width: 90, render: (value: unknown) => formatNumber(value) },
    { title: '行业', width: 150, render: (_: unknown, row: any) => row.sector_2 || row.sector_1 || row.sector_3 || '-' },
    { title: '总股本', dataIndex: 'total_shares', width: 110, render: (value: unknown) => formatNumber(value, 0) },
    { title: '流通股本', dataIndex: 'float_shares', width: 110, render: (value: unknown) => formatNumber(value, 0) },
    { title: '成交量（万股）', dataIndex: 'volume', width: 120, render: (value: unknown) => value == null || value === '' ? '-' : `${formatNumber(Number(value) / 10000)} 万` },
    { title: '成交额（万元）', dataIndex: 'amount', width: 130, render: (value: unknown) => value == null || value === '' ? '-' : `${formatNumber(Number(value) / 10000)} 万` },
    { title: '换手率', dataIndex: 'turnover_rate', width: 100, render: (value: unknown) => value == null ? '-' : `${formatNumber(value)}%` },
  ].filter((column: any) => column.dataIndex ? hasData(column.dataIndex) : rows.some((row: any) => row.sector_1 || row.sector_2 || row.sector_3))
  const opportunityColumns = [{ title: '股票', fixed: 'left' as const, width: 150, render: (_: unknown, row: any) => <Space direction="vertical" size={0}><Typography.Text>{row.stock_name || '未知股票'}</Typography.Text><Typography.Text type="secondary">{row.stock_code}</Typography.Text></Space> }, { title: '信号类型', dataIndex: 'signal_type', width: 100, render: (value: unknown) => formatSignalType(value) }, { title: '信号日期', dataIndex: 'signal_date', width: 115 }, ...marketColumns, { title: '操作', dataIndex: 'action', width: 110, render: (value: unknown) => formatAction(value) }, { title: '交易计划', fixed: 'right' as const, width: 110, render: (_: unknown, row: any) => row.category === 'chan-buy' ? <Button size="small" onClick={(event) => { event.stopPropagation(); setPlanSignal(row) }}>加入计划</Button> : null }]
  const updateDraft = (key: string, value: string | boolean) => setDraftFilters((current) => ({ ...current, [key]: value }))
  const applyFilters = () => {
    const min = draftFilters.turnover_min === '' ? null : Number(draftFilters.turnover_min)
    const max = draftFilters.turnover_max === '' ? null : Number(draftFilters.turnover_max)
    if ((min !== null && !Number.isFinite(min)) || (max !== null && !Number.isFinite(max)) || (min !== null && min < 0) || (max !== null && max < 0) || (min !== null && max !== null && min > max)) return
    setFilters({ ...draftFilters }); setPage(1)
  }
  const resetFilters = () => { const empty = { stock_keyword: '', industry: '', start_date: '', end_date: '', turnover_min: '', turnover_max: '', first_buy: false, second_buy: false, third_buy: false, first_sell: false, second_sell: false, third_sell: false }; setDraftFilters(empty); setFilters(empty); setPage(1) }
  return <Space direction="vertical" style={{ width: '100%' }}><Space align="center"><Typography.Title level={3} style={{ margin: 0 }}>缠论机会看板</Typography.Title><Button type="primary" loading={scanMutation.isPending} onClick={() => { scanMutation.reset(); setScanOpen(true) }}>执行真实扫描</Button></Space>{scanMutation.isPending && <Alert type="info" showIcon message="扫描正在执行" description="正在读取日线行情并识别缠论买卖点，请稍候。扫描期间请勿重复提交。" />}<Alert type="info" message="列表仅展示已执行扫描并持久化的真实信号。信号价格对应信号日期，最近收盘价对应该股票最新交易日。" /><Modal title="执行缠论量化扫描" open={scanOpen} onCancel={() => !scanMutation.isPending && setScanOpen(false)} onOk={() => { const codes = scanCodes.trim(); setScanOpen(false); scanMutation.mutate(codes ? { stock_codes: codes, start_date: scanStartDate } : { start_date: scanStartDate }) }} okText="开始扫描" cancelText="取消" confirmLoading={scanMutation.isPending} width={560}><Alert type="info" showIcon message="不填写股票代码时扫描全部股票；填写后只分析指定股票。" description="支持多个代码，用逗号、空格或换行分隔，例如：000651, 000001, 600519。扫描会读取日线 K 线并识别缠论买卖点。" style={{ marginBottom: 16 }} /><Typography.Text strong>股票代码（可选）</Typography.Text><Input.TextArea value={scanCodes} onChange={(event) => setScanCodes(event.target.value)} placeholder="留空 = 全市场；例如：000651, 600519\n也支持直接粘贴多行代码" autoSize={{ minRows: 4, maxRows: 7 }} style={{ marginTop: 8, marginBottom: 16 }} /><Typography.Text strong>行情起始日期</Typography.Text><Input type="date" value={scanStartDate} onChange={(event) => setScanStartDate(event.target.value)} style={{ display: 'block', width: 180, marginTop: 8 }} /></Modal><Card size="small" title="查询筛选"><Space direction="vertical" size="middle" style={{ width: '100%' }}><Space wrap size="middle"><Input value={draftFilters.stock_keyword} onChange={(event) => updateDraft('stock_keyword', event.target.value)} onPressEnter={applyFilters} placeholder="股票代码或名称" style={{ width: 160 }} /><Input value={draftFilters.industry} onChange={(event) => updateDraft('industry', event.target.value)} onPressEnter={applyFilters} placeholder="行业关键词" style={{ width: 130 }} /><Space size={4}><Typography.Text type="secondary" style={{ fontSize: 12 }}>信号开始日期</Typography.Text><Input type="date" value={draftFilters.start_date} onChange={(event) => updateDraft('start_date', event.target.value)} style={{ width: 160 }} /></Space><Space size={4}><Typography.Text type="secondary" style={{ fontSize: 12 }}>信号结束日期</Typography.Text><Input type="date" value={draftFilters.end_date} onChange={(event) => updateDraft('end_date', event.target.value)} style={{ width: 160 }} /></Space><Input type="number" min={0} step="0.01" value={draftFilters.turnover_min} onChange={(event) => updateDraft('turnover_min', event.target.value)} placeholder="换手率下限 %" style={{ width: 150 }} /><Input type="number" min={0} step="0.01" value={draftFilters.turnover_max} onChange={(event) => updateDraft('turnover_max', event.target.value)} placeholder="换手率上限 %" style={{ width: 150 }} /></Space><Space wrap size="middle"><Select mode="multiple" value={[draftFilters.first_buy && 'first_buy', draftFilters.second_buy && 'second_buy', draftFilters.third_buy && 'third_buy', draftFilters.first_sell && 'first_sell', draftFilters.second_sell && 'second_sell', draftFilters.third_sell && 'third_sell'].filter(Boolean)} onChange={(values) => { updateDraft('first_buy', values.includes('first_buy')); updateDraft('second_buy', values.includes('second_buy')); updateDraft('third_buy', values.includes('third_buy')); updateDraft('first_sell', values.includes('first_sell')); updateDraft('second_sell', values.includes('second_sell')); updateDraft('third_sell', values.includes('third_sell')) }} placeholder="选择信号类型（可多选）" style={{ width: 280 }} options={[{ value: 'first_buy', label: '一买' }, { value: 'second_buy', label: '二买' }, { value: 'third_buy', label: '三买' }, { value: 'first_sell', label: '一卖' }, { value: 'second_sell', label: '二卖' }, { value: 'third_sell', label: '三卖' }]} /><Button type="primary" onClick={applyFilters}>查询</Button><Button onClick={resetFilters}>重置</Button></Space></Space></Card><Menu mode="horizontal" selectedKeys={[category]} onClick={({ key }) => { setCategory(key); setPage(1) }} items={[['all', '全部'], ['chan-buy', '缠论买点'], ['chan-sell', '缠论卖点']].map(([key, label]) => ({ key, label }))} /><Table scroll={{ x: 1180 }} locale={{ emptyText: '暂无扫描结果，请先执行真实扫描' }} pagination={pagination} rowKey="id" loading={query.isLoading} dataSource={rows} onRow={(row) => ({ onClick: () => setDetail(row) })} columns={opportunityColumns} /><OpportunityDetailDrawer detail={detail} detailQuery={detailQuery} detailKlineQuery={detailKlineQuery} onClose={() => setDetail(null)} /><Modal title="创建交易计划" open={Boolean(planSignal)} onCancel={() => setPlanSignal(null)} footer={null}><Form layout="vertical" onFinish={(values) => mutation.mutate({ ...values, stock_code: planSignal.stock_code, action: 'buy', signal_id: planSignal.id, signal_date: planSignal.signal_date })}><Form.Item name="target_weight" label="目标仓位" rules={[{ required: true }]}><InputNumber min={0} max={1} step={0.05} style={{ width: '100%' }} /></Form.Item><Form.Item name="reason" label="计划原因"><Input /></Form.Item><Button type="primary" htmlType="submit" loading={mutation.isPending}>保存计划</Button></Form></Modal></Space>
}

function RiskControlDashboard() {
  const client = useQueryClient()
  const [form] = Form.useForm()
  const [result, setResult] = useState<any>(null)
  const riskStatus = useQuery({ queryKey: ['risk-status'], queryFn: getRiskStatus, refetchInterval: 60000 })
  const riskAlerts = useQuery({ queryKey: ['risk-alerts'], queryFn: () => getRiskAlerts(), refetchInterval: 60000 })
  const checkMutation = useMutation({ mutationFn: checkRisk, onSuccess: (data) => { setResult(data); client.invalidateQueries({ queryKey: ['risk-status'] }); client.invalidateQueries({ queryKey: ['risk-alerts'] }); message.success('风控检查完成') } })
  const acknowledgeMutation = useMutation({ mutationFn: (id: number) => acknowledgeRiskAlert(id), onSuccess: () => { client.invalidateQueries({ queryKey: ['risk-alerts'] }); client.invalidateQueries({ queryKey: ['risk-status'] }) } })
  const latest = result || riskStatus.data?.decision
  const decision = latest?.decision
  const decisionColor = decision === 'HALT' ? 'red' : decision === 'REJECT' ? 'orange' : decision === 'WARN' ? 'gold' : 'green'
  const alerts = riskAlerts.data?.data || []
  return <Space direction="vertical" size={16} style={{ width: '100%' }}><Typography.Title level={3} style={{ margin: 0 }}>独立风控看板</Typography.Title><Alert type="info" showIcon message="独立风控用于组合、持仓和交易计划的执行前检查，仅支持研究、模拟和交易辅助，不会自动下单。" /><Card title="执行风控检查"><Form form={form} layout="inline" initialValues={{ action: 'buy', target_weight: 0.1, industry_weight: 0.2, total_weight: 0.5, daily_pnl_ratio: 0, drawdown: 0 }} onFinish={(values) => checkMutation.mutate({ stock_code: values.stock_code || undefined, action: values.action, target_weight: values.target_weight, industry_weight: values.industry_weight, portfolio_id: 'default', portfolio: { total_weight: values.total_weight, daily_pnl_ratio: values.daily_pnl_ratio, drawdown: values.drawdown } })}><Form.Item name="stock_code" label="股票代码"><Input placeholder="可选，如 600519" style={{ width: 130 }} /></Form.Item><Form.Item name="action" label="动作"><Select options={[{ value: 'buy', label: '买入' }, { value: 'sell', label: '卖出' }]} style={{ width: 90 }} /></Form.Item><Form.Item name="target_weight" label="目标仓位"><InputNumber min={0} max={1} step={0.05} /></Form.Item><Form.Item name="industry_weight" label="行业仓位"><InputNumber min={0} max={1} step={0.05} /></Form.Item><Form.Item name="total_weight" label="总仓位"><InputNumber min={0} max={1} step={0.05} /></Form.Item><Form.Item name="daily_pnl_ratio" label="日亏损"><InputNumber min={-1} max={1} step={0.01} /></Form.Item><Form.Item name="drawdown" label="回撤"><InputNumber min={0} max={1} step={0.01} /></Form.Item><Button type="primary" htmlType="submit" loading={checkMutation.isPending}>执行检查</Button></Form>{checkMutation.isError && <Alert type="error" showIcon message="风控检查失败" description={String((checkMutation.error as any)?.response?.data?.detail || '请检查后端服务')} style={{ marginTop: 16 }} />}</Card><Card title="当前风控决策" loading={riskStatus.isLoading}><Space wrap><Tag color={decisionColor}>{decision || '暂无决策'}</Tag><span>风险等级：{latest?.risk_level || '暂无数据'}</span><span>活跃预警：{riskAlerts.data?.count ?? 0}</span><span>建议最大仓位：{latest?.suggested_max_weight == null ? '-' : `${(Number(latest.suggested_max_weight) * 100).toFixed(1)}%`}</span><span>规则版本：{latest?.rule_version || 'risk-v1'}</span></Space></Card>{result && <Card title="本次规则明细"><Table size="small" rowKey={(row: any) => row.rule} pagination={false} dataSource={result.rules || []} columns={[{ title: '规则', dataIndex: 'rule' }, { title: '结果', dataIndex: 'decision', render: (value: string) => <Tag color={value === 'HALT' || value === 'REJECT' ? 'red' : value === 'WARN' ? 'orange' : 'green'}>{value}</Tag> }, { title: '说明', dataIndex: 'reason' }, { title: '实际值', dataIndex: 'value', render: (value: unknown) => value == null ? '-' : String(value) }]} /></Card>}<Card title="风险预警" loading={riskAlerts.isLoading}><Table size="small" rowKey={(row: any) => row.id} dataSource={alerts} pagination={{ pageSize: 8 }} locale={{ emptyText: '暂无活跃风险预警' }} columns={[{ title: '级别', dataIndex: 'severity', render: (value: string) => <Tag color={value === 'HALT' || value === 'REJECT' ? 'red' : 'orange'}>{value || '-'}</Tag> }, { title: '规则', dataIndex: 'alert_type', render: (value: string) => value || '-' }, { title: '说明', dataIndex: 'message', render: (value: string) => value || '-' }, { title: '时间', dataIndex: 'created_at', render: (value: string) => value || '-' }, { title: '操作', render: (_: unknown, row: any) => <Button size="small" onClick={() => acknowledgeMutation.mutate(Number(row.id))} loading={acknowledgeMutation.isPending}>确认</Button> }]} /></Card></Space>
}

function Risks() {
  const client = useQueryClient()
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [filters, setFilters] = useState({ stock_keyword: '', action: '', status: '', start_date: '', end_date: '' })
  const [draftFilters, setDraftFilters] = useState(filters)
  const plans = useQuery({ queryKey: ['trade-plans', page, pageSize, filters], queryFn: () => getTradePlans({ page, page_size: pageSize, ...filters }) })
  const riskStatus = useQuery({ queryKey: ['risk-status'], queryFn: getRiskStatus, refetchInterval: 60000 })
  const riskAlerts = useQuery({ queryKey: ['risk-alerts'], queryFn: () => getRiskAlerts(), refetchInterval: 60000 })
  const statusMutation = useMutation({ mutationFn: ({ id, action }: { id: string; action: 'accept' | 'reject' }) => updateTradePlan(id, action), onSuccess: () => client.invalidateQueries({ queryKey: ['trade-plans'] }) })
  const rows = plans.data?.data || []
  const total = plans.data?.count || 0
  const updateDraft = (key: string, value: string) => setDraftFilters((current) => ({ ...current, [key]: value }))
  const applyFilters = () => { setFilters({ ...draftFilters }); setPage(1) }
  const resetFilters = () => { const empty = { stock_keyword: '', action: '', status: '', start_date: '', end_date: '' }; setDraftFilters(empty); setFilters(empty); setPage(1) }
  const pagination = { current: page, pageSize, total, showSizeChanger: true, showQuickJumper: true, showTotal: (value: number) => `共 ${value} 条记录`, pageSizeOptions: [10, 20, 50, 100], onChange: (nextPage: number, nextPageSize: number) => { setPage(nextPageSize !== pageSize ? 1 : nextPage); setPageSize(nextPageSize) } }
  return <Space direction="vertical" style={{ width: '100%' }}><Typography.Title level={3} style={{ margin: 0 }}>风险与交易计划</Typography.Title><Card size="small" title="当前风控状态"><Space wrap><Tag color={riskStatus.data?.decision?.decision === 'HALT' ? 'red' : riskStatus.data?.decision?.decision === 'REJECT' ? 'orange' : 'green'}>{riskStatus.data?.decision?.decision || '暂无决策'}</Tag><span>活跃预警：{riskAlerts.data?.count ?? 0}</span><span>风险等级：{riskStatus.data?.decision?.risk_level || '暂无数据'}</span></Space></Card><Alert type="info" message="交易计划仅用于研究、模拟和交易辅助，不会直接触发券商下单。" /><Card size="small" title="查询筛选"><Space wrap><Input value={draftFilters.stock_keyword} onChange={(event) => updateDraft('stock_keyword', event.target.value)} onPressEnter={applyFilters} placeholder="股票代码" style={{ width: 180 }} /><select value={draftFilters.action} onChange={(event) => updateDraft('action', event.target.value)} style={{ width: 120, height: 32, background: '#141d2d', color: 'inherit', border: '1px solid #33466d', borderRadius: 4, padding: '0 8px' }}><option value="">全部动作</option><option value="buy">买入</option><option value="sell">卖出</option></select><select value={draftFilters.status} onChange={(event) => updateDraft('status', event.target.value)} style={{ width: 120, height: 32, background: '#141d2d', color: 'inherit', border: '1px solid #33466d', borderRadius: 4, padding: '0 8px' }}><option value="">全部状态</option><option value="pending">待处理</option><option value="accepted">已接受</option><option value="rejected">已拒绝</option></select><Input type="date" value={draftFilters.start_date} onChange={(event) => updateDraft('start_date', event.target.value)} style={{ width: 150 }} /><Input type="date" value={draftFilters.end_date} onChange={(event) => updateDraft('end_date', event.target.value)} style={{ width: 150 }} /><Button type="primary" onClick={applyFilters}>查询</Button><Button onClick={resetFilters}>重置</Button></Space></Card><Table rowKey="id" loading={plans.isLoading} dataSource={rows} pagination={pagination} columns={[{ title: '计划ID', dataIndex: 'id' }, { title: '股票', dataIndex: 'stock_code' }, { title: '动作', dataIndex: 'action', render: (value: string) => value === 'buy' ? '买入' : '卖出' }, { title: '信号日期', dataIndex: 'signal_date' }, { title: '目标仓位', dataIndex: 'target_weight', render: (value: number) => value == null ? '-' : `${(value * 100).toFixed(2)}%` }, { title: '状态', dataIndex: 'status', render: (value: string) => <Tag color={value === 'accepted' ? 'green' : value === 'rejected' ? 'red' : 'blue'}>{value === 'accepted' ? '已接受' : value === 'rejected' ? '已拒绝' : '待处理'}</Tag> }, { title: '操作', render: (_: unknown, row: any) => row.status === 'pending' ? <Space><Button size="small" onClick={() => statusMutation.mutate({ id: row.id, action: 'accept' })}>接受</Button><Button size="small" danger onClick={() => statusMutation.mutate({ id: row.id, action: 'reject' })}>拒绝</Button></Space> : null }]} /></Space>
}

const syncTaskLabels: Record<string, string> = {
  industry: '行业分类与股本', kline: '股票日线行情', sectors: '板块指数重算', news: '个股新闻',
  report: '研报一致预期', macro: '宏观指标与利率', calendar: '财经日历', catalyst: 'AI 催化剂',
  sentiment: '新闻情感与情绪聚合', events: '市场事件识别', fear_index: '恐慌贪婪指数', financial: '财务数据',
  atr_quarterly_parameter: 'ATR 季度参数验证', announcement: '全市场公告', ann_track: '股票池公告追踪', pdf_sync: '公告 PDF 向量化',
}

const formatSyncTime = (value: unknown) => {
  if (!value) return '-'
  const text = String(value).replace('T', ' ')
  return text.length >= 19 ? text.slice(0, 19) : text
}

const syncStatusColors: Record<string, string> = { success: 'success', failed: 'error', running: 'processing', skipped: 'warning' }
const syncStatusLabels: Record<string, string> = { success: '成功', failed: '失败', running: '执行中', skipped: '已跳过' }
const syncTriggerLabels: Record<string, string> = { manual: '手动', schedule: '定时', retry: '重试' }

const qlibStatusLabels: Record<string, string> = { healthy: '正常', warning: '缺失/需关注', abnormal: '异常', unavailable: '不可用' }
const qlibStatusColors: Record<string, string> = { healthy: 'success', warning: 'warning', abnormal: 'error', unavailable: 'error' }

// QlibDataSourceStatus is kept for the qlib dashboard route.
function QlibDataSourceStatus() {
  const query = useQuery({ queryKey: ['qlib-data-source-status'], queryFn: getQlibDataSourceStatus, refetchInterval: 60000 })
  const data = query.data || {}
  const refresh = () => query.refetch()
  return <Card title="Qlib 因子研究数据源" extra={<Button onClick={refresh} loading={query.isFetching}>刷新状态</Button>}>
    {query.isError ? <Alert type="error" showIcon message="数据源状态查询失败" description="请检查数据库连接后重试" /> : <>
      <Descriptions size="small" column={{ xs: 1, sm: 2, md: 3 }} items={[
        { label: '数据源', children: data.source || 'trade_stock_daily' },
        { label: '数据链路', children: data.pipeline || 'trade_stock_daily → Qlib Adapter → Alpha158' },
        { label: '数据库连接', children: data.connection_status === 'connected' ? <Tag color="success">已连接</Tag> : <Tag color="error">不可用</Tag> },
        { label: '行情范围', children: `${data.min_trade_date || '-'} ~ ${data.max_trade_date || '-'}` },
        { label: '股票总数', children: data.stock_count ?? '-' },
        { label: '交易日数量', children: data.trade_date_count ?? '-' },
        { label: '数据总条数', children: data.row_count ?? '-' },
        { label: '最近同步', children: data.last_sync_at ? formatSyncTime(data.last_sync_at) : '未知' },
        { label: '质量状态', children: <Tag color={qlibStatusColors[data.status] || 'default'}>{qlibStatusLabels[data.status] || data.status || '未知'}</Tag> },
      ]} />
      {data.issues?.length ? <Alert style={{ marginTop: 16 }} type={data.status === 'warning' ? 'warning' : 'error'} showIcon message="数据质量提示" description={data.issues.map((issue: any) => issue.message).join('；')} /> : null}
    </>}
  </Card>
}

function QlibResearch() {
  const queryClient = useQueryClient()
  const [poolType, setPoolType] = useState('hs300')
  const [stockCodes, setStockCodes] = useState('')
  const [benchmark, setBenchmark] = useState('SH000300')
  const [rebalanceFrequency, setRebalanceFrequency] = useState('monthly')
  const [predictionTarget, setPredictionTarget] = useState('future_5d_return')
  const [syncRunId, setSyncRunId] = useState<string | null>(null)
  const [runId, setRunId] = useState<string | null>(null)
  const split = useQuery<any>({ queryKey: ['qlib-time-split'], queryFn: () => getQlibTimeSplit(), refetchInterval: 60000 })
  const pools = useQuery({ queryKey: ['qlib-research-pools'], queryFn: getQlibResearchPools })
  const runs = useQuery({ queryKey: ['qlib-research-runs'], queryFn: () => getQlibResearchRuns(20), refetchInterval: 10000 })
  useEffect(() => {
    const selectedPool = pools.data?.data?.find((item: any) => item.value === poolType)
    if (selectedPool?.benchmark) setBenchmark(selectedPool.benchmark)
  }, [pools.data, poolType])
  const run = useQuery({ queryKey: ['qlib-research-run', runId], queryFn: () => getQlibResearchRun(runId as string), enabled: Boolean(runId), refetchInterval: runId ? 3000 : false })
  const predictions = useQuery({ queryKey: ['qlib-research-predictions', runId], queryFn: () => getQlibResearchPredictions(runId as string, { stage: 'test', top_k: 20 }), enabled: Boolean(runId && run.data?.status === 'success') })
  const logs = useQuery({ queryKey: ['qlib-research-logs', runId], queryFn: () => getQlibResearchLogs(runId as string), enabled: Boolean(runId), refetchInterval: runId ? 3000 : false })
  const validate = useMutation({ mutationFn: () => validateQlibResearchPool({ pool_type: poolType, stock_codes: stockCodes }), onError: (error: any) => message.error(error?.response?.data?.detail || '股票池校验失败') })
  const create = useMutation({ mutationFn: () => createQlibResearchRun({ name: 'Alpha158 研究任务', pool_type: poolType, stock_codes: stockCodes, benchmark, rebalance_frequency: rebalanceFrequency, prediction_target: predictionTarget }), onSuccess: (data: any) => { setRunId(data.run_id); runs.refetch(); message.success(`任务已创建：${data.run_id}`) }, onError: (error: any) => message.error(error?.response?.data?.detail || '研究任务创建失败') })
  const data: any = split.data || {}
  const validation: any = validate.data || {}
  const currentRun: any = run.data || null
  const dataSourceQuery = useQuery({ queryKey: ['qlib-data-source-status'], queryFn: getQlibDataSourceStatus, refetchInterval: 60000 })
  const dataSource: any = dataSourceQuery.data || {}
  const syncRun = useQuery({ queryKey: ['qlib-data-sync-run', syncRunId], queryFn: () => getQlibDataSyncRun(syncRunId as string), enabled: Boolean(syncRunId), refetchInterval: syncRunId ? 2000 : false })
  const syncLogs = useQuery({ queryKey: ['qlib-data-sync-logs', syncRunId], queryFn: () => getQlibDataSyncLogs(syncRunId as string), enabled: Boolean(syncRunId), refetchInterval: syncRunId ? 2000 : false })
  const syncMutation = useMutation({ mutationFn: () => syncQlibDataSource(true), onSuccess: (result: any) => { setSyncRunId(result.sync_run_id); message.success(`最新 Qlib 数据更新任务已创建：${result.sync_run_id}`) }, onError: () => message.error('Qlib 数据更新任务创建失败') })
  useEffect(() => {
    const status = syncRun.data?.status
    if (status === 'success' || status === 'failed' || status === 'skipped') {
      dataSourceQuery.refetch()
      queryClient.invalidateQueries({ queryKey: ['qlib-time-split'] })
    }
  }, [syncRun.data?.status, dataSourceQuery, queryClient])
  const researchEnd = data.research?.end || data.local_qlib_last_date || dataSource.local_qlib_last_date || '-'
  return <div className="research-page">
    <div className="research-hero">
      <div>
        <Typography.Title level={2} style={{ margin: 0 }}>Qlib 因子研究工作台</Typography.Title>
        <Typography.Text type="secondary">构建、训练并评估量化因子模型 · Alpha158 · LightGBM / LGBModel · 本地数据最后完整交易日 <strong>{dataSource.local_qlib_last_date || data.local_qlib_last_date || '-'}</strong></Typography.Text>
      </div>
      <Tag color={dataSource.sync_required ? 'warning' : 'success'}>{dataSource.sync_required ? '有新数据可同步' : '数据已是最新'}</Tag>
    </div>
    <Alert type="info" showIcon message="研究训练仅在后端异步执行；固定时间切分、Alpha158 和模型类型不可切换。" />
    <Card className="research-config-card" title="研究任务配置" extra={<Button size="small" onClick={() => syncMutation.mutate()} loading={syncMutation.isPending}>更新最新数据</Button>}>
      {syncRun.data ? <Alert style={{ marginBottom: 12 }} type={syncRun.data.status === 'failed' ? 'error' : syncRun.data.status === 'success' ? 'success' : 'info'} showIcon message={`数据同步：${syncRun.data.status} · ${syncRun.data.current_stage || '-'} · ${syncRun.data.progress || 0}%`} description={<pre className="research-log">{(syncLogs.data?.data || []).map((item: any) => `[${item.created_at || '-'}] [${item.level}] ${item.stage || '-'} ${item.message}`).join('\\n') || '等待同步日志...'}</pre>} /> : null}
      <Space direction="vertical" style={{ width: '100%' }}>
        <div className="research-time-grid">
          {[['研究范围', `${data.research?.start || '-'} ~ ${researchEnd}`], ['训练集时间', `${data.stages?.train?.requested?.start || '-'} ~ ${data.stages?.train?.requested?.end || '-'}`], ['验证集时间', `${data.stages?.validation?.requested?.start || '-'} ~ ${data.stages?.validation?.requested?.end || '-'}`], ['测试集时间', `${data.stages?.test?.requested?.start || '-'} ~ ${data.stages?.test?.requested?.end || '-'}`]].map(([label, value]) => <div className="research-time-item" key={label}><span>{label}</span><strong>{value}</strong></div>)}
        </div>
        <Form layout="vertical" className="research-form">
          <div className="research-form-grid">
            <Form.Item label="股票池范围" style={{ marginBottom: 0 }}>
              <Select value={poolType} onChange={(value) => { setPoolType(value); validate.reset() }} options={pools.data?.data || []} style={{ width: 180 }} />
            </Form.Item>
            {poolType === 'custom' ? <Form.Item label="自定义股票代码" style={{ marginBottom: 0 }}>
              <Input.TextArea value={stockCodes} onChange={(event) => setStockCodes(event.target.value)} placeholder="支持逗号、空格、换行" autoSize={{ minRows: 1, maxRows: 3 }} style={{ width: 280 }} />
            </Form.Item> : null}
            <Form.Item label="基准指数" style={{ marginBottom: 0 }}>
              <Select value={benchmark} options={(pools.data?.data || []).filter((item: any) => item.benchmark).map((item: any) => ({ value: item.benchmark, label: `${item.label} · ${item.benchmark.slice(2)}.${item.benchmark.slice(0, 2)}` }))} disabled={poolType !== 'custom'} style={{ width: 220 }} />
            </Form.Item>
            <Form.Item label="调仓频率" style={{ marginBottom: 0 }}>
              <Select value={rebalanceFrequency} onChange={setRebalanceFrequency} options={[{ value: 'daily', label: '每日调仓' }, { value: 'weekly', label: '每周调仓' }, { value: 'monthly', label: '每月调仓' }]} style={{ width: 150 }} />
            </Form.Item>
            <Form.Item label="预测目标" style={{ marginBottom: 0 }}>
              <Select value={predictionTarget} onChange={setPredictionTarget} options={[{ value: 'future_1d_return', label: '未来1日收益率' }, { value: 'future_5d_return', label: '未来5日收益率' }, { value: 'future_20d_return', label: '未来20日收益率' }]} style={{ width: 190 }} />
            </Form.Item>
            {poolType === 'custom' ? <Form.Item label=" " style={{ marginBottom: 0 }}>
              <Button onClick={() => validate.mutate()} loading={validate.isPending}>校验股票池</Button>
            </Form.Item> : null}
            <Form.Item label=" " style={{ marginBottom: 0 }}>
              <Button type="primary" onClick={() => create.mutate()} loading={create.isPending}>开始训练</Button>
            </Form.Item>
          </div>
        </Form>
        {validate.data ? <Alert type={validation.status === 'healthy' ? 'success' : validation.status === 'warning' ? 'warning' : 'error'} message={`有效 ${validation.valid_count} · 无效 ${validation.invalid_count} · 缺失 ${validation.missing_count}`} description={validation.issues?.join('；')} /> : null}
      </Space>
    </Card>
    {currentRun ? <Card title={`当前任务 · ${currentRun.name}`} extra={<Tag color={currentRun.status === 'success' ? 'success' : currentRun.status === 'failed' ? 'error' : 'processing'}>{currentRun.status}</Tag>}><Progress percent={currentRun.progress || 0} status={currentRun.status === 'failed' ? 'exception' : undefined} /><Typography.Text>当前阶段：{currentRun.current_stage || '-'} · run_id：{currentRun.run_id}</Typography.Text><Collapse style={{ marginTop: 12 }} items={[{ key: 'logs', label: `执行日志（${logs.data?.data?.length || 0}）`, children: <pre className="research-log">{(logs.data?.data || []).map((item: any) => `[${item.level}] ${item.stage || '-'} ${item.message}`).join('\\n')}</pre> }]} />{predictions.data?.data?.length ? <Table size="small" rowKey="id" dataSource={predictions.data.data} pagination={false} columns={[{ title: '日期', dataIndex: 'trade_date' }, { title: '股票', dataIndex: 'instrument' }, { title: '预测分数', dataIndex: 'prediction' }, { title: '排名', dataIndex: 'stock_rank' }]} /> : null}</Card> : null}
    <Card title="历史研究任务"><Table size="small" rowKey="run_id" dataSource={runs.data?.data || []} loading={runs.isLoading} onRow={(row) => ({ onClick: () => setRunId(row.run_id) })} columns={[{ title: '名称', dataIndex: 'name' }, { title: 'run_id', dataIndex: 'run_id' }, { title: '状态', dataIndex: 'status' }, { title: '阶段', dataIndex: 'current_stage' }, { title: '进度', render: (_: any, row: any) => `${row.progress || 0}%` }, { title: '错误', dataIndex: 'error_message', ellipsis: true }]} /></Card>
  </div>
}

function Sync() {
  const [taskName, setTaskName] = useState('')
  const [status, setStatus] = useState('')
  const [runTask, setRunTask] = useState<any>(null)
  const [selectedLog, setSelectedLog] = useState<any>(null)
  const [runningTask, setRunningTask] = useState<string | null>(null)
  const [monitoringTask, setMonitoringTask] = useState<{ name: string; startedAt: number } | null>(null)
  const [form] = Form.useForm()
  const runMutation = useMutation({ mutationFn: ({ name, parameters }: { name: string; parameters: Record<string, unknown> }) => runSyncTask(name, parameters), onSuccess: (result: any, variables) => { setRunningTask(null); setRunTask(null); form.resetFields(); if (result.status === 'queued') { setMonitoringTask({ name: variables.name, startedAt: Date.now() }); message.info('同步任务已提交，正在后台执行') } else { message[result.status === 'success' ? 'success' : 'error'](result.status === 'success' ? '同步已完成' : (result.error || '同步失败')) }; logs.refetch() }, onError: (error: any) => { setRunningTask(null); message.error(error?.response?.data?.detail || '同步请求失败') } })
  const [startedAfter, setStartedAfter] = useState('')
  const [startedBefore, setStartedBefore] = useState('')
  const [page, setPage] = useState(1)
  const pageSize = 20
  const tasks = useQuery({ queryKey: ['sync-tasks'], queryFn: getSyncTasks, refetchInterval: monitoringTask ? 2000 : 10000 })
  const overview = useQuery({ queryKey: ['sync-overview'], queryFn: getSyncOverview, refetchInterval: monitoringTask ? 2000 : 15000 })
  useEffect(() => {
    if (!monitoringTask) return
    const row = (tasks.data?.tasks || []).find((item: any) => item.task_name === monitoringTask.name)
    const lastRun = row?.last_run
    if (!lastRun || new Date(lastRun.started_at || 0).getTime() < monitoringTask.startedAt - 1000) return
    if (lastRun.status === 'success') { message.success(`${syncTaskLabels[monitoringTask.name] || monitoringTask.name} 同步完成`); setMonitoringTask(null); logs.refetch() }
    if (lastRun.status === 'failed') { message.error(`${syncTaskLabels[monitoringTask.name] || monitoringTask.name} 同步失败，请查看执行日志`); setMonitoringTask(null); logs.refetch() }
  }, [tasks.data, monitoringTask])
  const logParams = {
    ...(taskName ? { task_name: taskName } : {}),
    ...(status ? { status } : {}),
    ...(startedAfter ? { started_after: startedAfter } : {}),
    ...(startedBefore ? { started_before: startedBefore } : {}),
    offset: (page - 1) * pageSize,
  }
  const logs = useQuery<any>({ queryKey: ['sync-logs', logParams], queryFn: () => getSyncLogs(logParams), refetchInterval: 15000 })
  const taskRows = tasks.data?.tasks || []
  const logRows = logs.data?.logs || []
  const overviewData = overview.data || {}
  const summaryByTask = Object.fromEntries((overviewData.summary || []).map((item: any) => [item.task_name, item]))
  const failedTasks = taskRows.filter((row: any) => row.last_run?.status === 'failed')
  const refreshAll = () => { tasks.refetch(); logs.refetch(); overview.refetch() }
  return <Space direction="vertical" size={16} style={{ width: '100%' }}>
    <div className="sync-page-header"><div><Typography.Title level={3} style={{ margin: 0 }}>数据同步</Typography.Title><Typography.Text type="secondary">统一管理行情、行业、资讯与衍生数据链路</Typography.Text></div><Space><Tag color={failedTasks.length ? 'error' : 'success'}>{failedTasks.length ? `发现 ${failedTasks.length} 个异常任务` : '同步系统运行正常'}</Tag><Button icon={<SyncOutlined />} onClick={refreshAll} loading={tasks.isFetching || logs.isFetching}>刷新</Button><Button type="primary" icon={<SyncOutlined />} onClick={() => setRunTask(taskRows[0] || null)} disabled={!taskRows.length}>立即执行</Button></Space></div>
    <div className="sync-metrics"><Card><Statistic title="今日执行" value={overviewData.today_runs ?? 0} suffix="次" /></Card><Card><Statistic title="成功率" value={overviewData.success_rate ?? 0} suffix="%" valueStyle={{ color: '#52c41a' }} /></Card><Card><Statistic title="正在执行" value={overviewData.running_count ?? 0} suffix="个" valueStyle={{ color: '#1677ff' }} /></Card><Card><Statistic title="失败任务" value={overviewData.failed_count ?? 0} suffix="次" valueStyle={{ color: overviewData.failed_count ? '#ff4d4f' : '#52c41a' }} /></Card><Card><Statistic title="最近同步" value={formatSyncTime(overviewData.last_run)} /></Card></div>
    {failedTasks.length ? <Alert type="error" showIcon message="需要处理的同步任务" description={<Space wrap>{failedTasks.map((row: any) => <Button key={row.task_name} type="link" danger onClick={() => { setTaskName(row.task_name); setStatus('failed'); setPage(1) }}>{syncTaskLabels[row.task_name] || row.task_name}：查看失败日志</Button>)}</Space>} /> : <Alert type="success" showIcon message={`已加载 ${taskRows.length} 个定时任务；任务状态每 10 秒、日志每 15 秒自动刷新`} />}

    <Card title="定时任务">
      <Table size="small" rowKey="task_name" dataSource={taskRows} pagination={false} columns={[
        { title: '任务名称', dataIndex: 'task_name', width: 190, render: (value: string) => <Space direction="vertical" size={0}><Typography.Text strong>{syncTaskLabels[value] || value}</Typography.Text><Typography.Text type="secondary">{value}</Typography.Text></Space> },
        { title: '任务描述', dataIndex: 'description' },
        { title: '操作', width: 110, render: (_: unknown, row: any) => <Button type="primary" size="small" icon={<SyncOutlined />} loading={runningTask === row.task_name} onClick={() => { form.resetFields(); setRunTask(row) }}>手动同步</Button> },
        { title: '调度时间', dataIndex: 'cron', width: 150 },
        { title: '状态', width: 150, render: (_: unknown, row: any) => <Space><Tag color={row.enabled ? 'green' : 'default'}>{row.enabled ? '已启用' : '已禁用'}</Tag><Tag color={row.scheduled ? 'blue' : 'default'}>{row.scheduled ? '已注册' : '未运行'}</Tag></Space> },
        { title: '最近执行', width: 190, render: (_: unknown, row: any) => row.last_run ? <Space direction="vertical" size={0}><Tag color={syncStatusColors[row.last_run.status] || 'default'}>{row.last_run.status}</Tag><Typography.Text type="secondary">{formatSyncTime(row.last_run.started_at)}</Typography.Text></Space> : '-' },
        { title: '运行统计', width: 150, render: (_: unknown, row: any) => { const stat = summaryByTask[row.task_name]; return stat ? <Typography.Text type="secondary">成功 {stat.success_count || 0} 次 · 均耗时 {stat.avg_duration_ms ? `${(stat.avg_duration_ms / 1000).toFixed(1)} 秒` : '-'}</Typography.Text> : '-' } },
        { title: '下次运行', dataIndex: 'next_run_time', width: 190, render: formatSyncTime },
        { title: '操作', width: 190, render: (_: unknown, row: any) => <Space><Button size="small" onClick={() => { form.resetFields(); setRunTask(row) }}>执行</Button>{row.last_run?.status === 'failed' && <Button size="small" danger onClick={() => { setRunningTask(row.task_name); retrySyncTask(row.task_name).then(() => { message.success('已重新提交任务'); refreshAll() }).catch(() => message.error('重试失败')).finally(() => setRunningTask(null)) }}>重试</Button>}</Space> },

      ]} />
    </Card>
    <Modal title={`手动同步：${syncTaskLabels[runTask?.task_name] || runTask?.task_name || ''}`} open={Boolean(runTask)} okText="开始同步" cancelText="取消" confirmLoading={Boolean(runningTask)} onCancel={() => !runningTask && setRunTask(null)} onOk={() => form.validateFields().then((values) => { setRunningTask(runTask.task_name); runMutation.mutate({ name: runTask.task_name, parameters: values }) }).catch(() => undefined)}>
      <Form form={form} layout="vertical">
        {(runTask?.parameters || []).map((parameter: any) => <Form.Item key={parameter.name} name={parameter.name} label={parameter.label} rules={[{ required: parameter.required, message: `请输入${parameter.label}` }, ...(parameter.min != null ? [{ type: 'number' as const, min: parameter.min, message: `不能小于 ${parameter.min}` }] : []), ...(parameter.max != null ? [{ type: 'number' as const, max: parameter.max, message: `不能大于 ${parameter.max}` }] : [])]} initialValue={parameter.default}>
          {parameter.type === 'boolean' ? <Select options={[{ value: false, label: '否' }, { value: true, label: '是' }]} /> : parameter.type === 'integer' ? <InputNumber style={{ width: '100%' }} /> : <Input placeholder={parameter.description || ''} />}
        </Form.Item>)}
        {!runTask?.parameters?.length && <Typography.Text type="secondary">此任务无需额外参数。</Typography.Text>}
      </Form>
    </Modal>
    <Card className="sync-log-card" title={<div className="sync-log-title"><div><Typography.Text strong>执行日志</Typography.Text><Typography.Text type="secondary">记录每次同步的结果、耗时与写入情况</Typography.Text></div><Typography.Text type="secondary">点击任意记录查看详情</Typography.Text></div>}>
      <div className="sync-log-toolbar">
        <div className="sync-filter-group">
          <Typography.Text type="secondary">筛选</Typography.Text>
          <select value={taskName} onChange={(event) => { setTaskName(event.target.value); setPage(1) }} style={{ minWidth: 180, height: 32, background: '#141d2d', color: 'inherit', border: '1px solid #33466d', borderRadius: 4, padding: '0 8px' }}>
          <option value="">全部任务</option>{taskRows.map((row: any) => <option key={row.task_name} value={row.task_name}>{syncTaskLabels[row.task_name] || row.task_name}</option>)}
        </select>
        <select value={status} onChange={(event) => { setStatus(event.target.value); setPage(1) }} style={{ minWidth: 120, height: 32, background: '#141d2d', color: 'inherit', border: '1px solid #33466d', borderRadius: 4, padding: '0 8px' }}>
          <option value="">全部状态</option><option value="success">成功</option><option value="failed">失败</option><option value="running">执行中</option><option value="skipped">已跳过</option>
        </select>
        <Input value={startedAfter} onChange={(event) => setStartedAfter(event.target.value)} onPressEnter={() => setPage(1)} placeholder="开始时间 ≥ YYYY-MM-DD HH:mm:ss" style={{ width: 230 }} />
        <Input value={startedBefore} onChange={(event) => setStartedBefore(event.target.value)} onPressEnter={() => setPage(1)} placeholder="开始时间 ≤ YYYY-MM-DD HH:mm:ss" style={{ width: 230 }} />
        <Button onClick={() => setPage(1)}>查询</Button>
        <Button onClick={() => { setTaskName(''); setStatus(''); setStartedAfter(''); setStartedBefore(''); setPage(1) }}>重置</Button>
        </div>
        <Typography.Text type="secondary">共 {logs.data?.total || 0} 条记录</Typography.Text>
      </div>
      <div className="sync-log-table-wrap">
      <Table onRow={(row) => ({ onClick: () => setSelectedLog(row) })} rowClassName="clickable-row" rowKey={(row: any) => String(row.id || `${row.task_name}-${row.started_at}`)} loading={logs.isLoading} dataSource={logRows} pagination={{ current: page, pageSize, total: logs.data?.total || 0, showSizeChanger: false, onChange: (nextPage) => setPage(nextPage), showTotal: (total) => `共 ${total} 条` }} columns={[
        { title: '任务名称', dataIndex: 'task_name', width: 190, render: (value: string) => <Space direction="vertical" size={0}><Typography.Text>{syncTaskLabels[value] || value}</Typography.Text><Typography.Text type="secondary">{value}</Typography.Text></Space> },
        { title: '状态', dataIndex: 'status', width: 100, render: (value: string) => <Tag color={syncStatusColors[value] || 'default'}>{syncStatusLabels[value] || value}</Tag> },
        { title: '触发方式', dataIndex: 'trigger', width: 100, render: (value: string) => <Tag>{syncTriggerLabels[value] || value || '-'}</Tag> },
        { title: '开始时间', dataIndex: 'started_at', width: 180, render: formatSyncTime },
        { title: '结束时间', dataIndex: 'finished_at', width: 180, render: formatSyncTime },
        { title: '耗时', dataIndex: 'duration_ms', width: 90, render: (value: number) => value == null ? '-' : `${(value / 1000).toFixed(1)} 秒` },
        { title: '写入数', dataIndex: 'rows_affected', width: 90, render: (value: number) => value ?? '-' },
        { title: '错误信息', dataIndex: 'error', ellipsis: true, render: (value: string) => value ? <Typography.Text type="danger" ellipsis={{ tooltip: value }}>{value}</Typography.Text> : '-' },
      ]} />
      </div>
    </Card>
    <Drawer title={selectedLog ? `${syncTaskLabels[selectedLog.task_name] || selectedLog.task_name} · 执行详情` : '执行详情'} open={Boolean(selectedLog)} onClose={() => setSelectedLog(null)} width={520}>
      {selectedLog && <Space direction="vertical" style={{ width: '100%' }}><Descriptions column={1} size="small" items={[{ label: '任务', children: syncTaskLabels[selectedLog.task_name] || selectedLog.task_name }, { label: '状态', children: <Tag color={syncStatusColors[selectedLog.status] || 'default'}>{syncStatusLabels[selectedLog.status] || selectedLog.status}</Tag> }, { label: '触发方式', children: syncTriggerLabels[selectedLog.trigger] || selectedLog.trigger || '-' }, { label: '开始时间', children: formatSyncTime(selectedLog.started_at) }, { label: '结束时间', children: formatSyncTime(selectedLog.finished_at) }, { label: '耗时', children: selectedLog.duration_ms == null ? '-' : `${(selectedLog.duration_ms / 1000).toFixed(1)} 秒` }, { label: '写入数量', children: selectedLog.rows_affected ?? '-' }]} /><Typography.Title level={5}>执行摘要</Typography.Title><Typography.Paragraph>{selectedLog.message || '暂无摘要'}</Typography.Paragraph>{selectedLog.error && <Alert type="error" showIcon message="错误详情" description={<pre className="sync-error-detail">{selectedLog.error}</pre>} />}</Space>}
    </Drawer>
  </Space>
}

function ChatBox() {
  const [sessionId, setSessionId] = useState(() => window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`)
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<Array<{ role: 'user' | 'assistant'; content: string }>>([{ role: 'assistant', content: '你好，我是 QuantMind 投研助手。你可以直接问我：某只股票的趋势、基本面风险、技术面信号，或让我们对比两只股票。' }])
  const mutation = useMutation({ mutationFn: (message: string) => sendChatMessage({ message, session_id: sessionId }), onSuccess: (data) => setMessages((current) => [...current, { role: 'assistant', content: data.content }]), onError: (error: any) => { const detail = error?.code === 'ECONNABORTED' ? '分析仍在后台执行，响应时间较长，请稍后重试或查看后台日志。' : error?.response?.data?.detail || '聊天服务暂时不可用，请查看后台日志。'; setMessages((current) => [...current, { role: 'assistant', content: `暂时无法完成分析：${detail}` }]) } })
  const send = () => { const value = input.trim(); if (!value || mutation.isPending) return; setMessages((current) => [...current, { role: 'user', content: value }]); setInput(''); mutation.mutate(value) }
  const clear = () => { setMessages([]); setSessionId(window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`) }
  const quickQuestions = ['分析贵州茅台的基本面和风险', '帮我判断这只股票当前趋势', '对比两只股票的投资逻辑']
  return <Space direction="vertical" size={18} className="chat-page">
    <div className="chat-hero"><div><Typography.Title level={2} style={{ margin: 0 }}>AI 对话分析</Typography.Title><Typography.Text type="secondary">基于 nanobot 的连续对话投研助手，支持股票趋势、基本面、风险与行业比较分析</Typography.Text></div><Button icon={<DeleteOutlined />} onClick={clear}>清空会话</Button></div>
    <Alert type="info" showIcon message="研究辅助提示" description="回答会结合当前配置的 nanobot 工具和数据能力生成，仅供研究、模拟和交易辅助，不构成投资建议。" />
    <Card className="chat-card">
      <div className="chat-messages">{messages.map((item, index) => <div key={`${item.role}-${index}`} className={`chat-message ${item.role}`}><div className="chat-bubble">{item.role === 'assistant' ? <div className="diagnosis-markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{item.content}</ReactMarkdown></div> : <Typography.Text>{item.content}</Typography.Text>}</div></div>)}{mutation.isPending && <div className="chat-message assistant"><div className="chat-bubble"><Typography.Text type="secondary">正在分析，请稍候...</Typography.Text></div></div>}</div>
      <Space wrap className="chat-quick-actions">{quickQuestions.map((question) => <Button key={question} onClick={() => { setInput(question) }}>{question}</Button>)}</Space>
      <div className="chat-input-wrap"><Input.TextArea className="chat-input" value={input} onChange={(event) => setInput(event.target.value)} onPressEnter={(event) => { if (!event.shiftKey) { event.preventDefault(); send() } }} autoSize={{ minRows: 4, maxRows: 10 }} placeholder="输入股票代码、名称或你的分析问题，Enter 发送，Shift+Enter 换行" /></div>
      <div className="chat-compose"><Typography.Text type="secondary">连续会话中，助手会记住本次对话上下文</Typography.Text><Button type="primary" size="large" icon={<SendOutlined />} loading={mutation.isPending} onClick={send}>发送</Button></div>
    </Card>
  </Space>
}

function StockDiagnosis({ onNavigate }: { onNavigate?: (page: string, params?: Record<string, string>) => void } = {}) {
  const [symbol, setSymbol] = useState('')
  const [selected, setSelected] = useState<any>(null)
  const [diagnosisId, setDiagnosisId] = useState<string | null>(null)
  const [status, setStatus] = useState<any>(null)
  const [report, setReport] = useState<any>(null)
  useEffect(() => {
    const pending = sessionStorage.getItem('diagnosis-prefill-symbol')
    if (pending) {
      setSymbol(pending)
      setSelected({ stock_code: pending })
      sessionStorage.removeItem('diagnosis-prefill-symbol')
    }
  }, [])
  const search = useQuery({ queryKey: ['diagnosis-stocks', symbol], queryFn: () => searchDiagnosisStocks(symbol), enabled: symbol.trim().length >= 1 })
  const overview = useQuery({ queryKey: ['diagnosis-overview', selected?.symbol || selected?.stock_code], queryFn: () => getDiagnosisStockOverview(selected.symbol || selected.stock_code), enabled: Boolean(selected?.symbol || selected?.stock_code) })
  const history = useQuery({ queryKey: ['diagnosis-history', selected?.symbol || selected?.stock_code], queryFn: () => getDiagnoses(selected.symbol || selected.stock_code), enabled: Boolean(selected?.symbol || selected?.stock_code) })
  const createMutation = useMutation({ mutationFn: () => createDiagnosis({ symbol: selected.symbol || selected.stock_code }), onSuccess: (data) => { const id = data.diagnosis_id || data.id; setDiagnosisId(id); setStatus(data); setReport(null); message.success('诊断任务已创建') }, onError: (error: any) => message.error(error?.response?.data?.detail || '诊断任务创建失败') })
  useEffect(() => {
    if (!diagnosisId) return
    let active = true
    const poll = async () => { try { const next = await getDiagnosisStatus(diagnosisId); if (!active) return; setStatus(next); if (next.status === 'completed' || next.status === 'partial') { const result = await getDiagnosisReport(diagnosisId); if (active) setReport(result) } else if (!['failed', 'cancelled', 'expired'].includes(next.status)) window.setTimeout(poll, 1500) } catch (error: any) { if (active) message.error(error?.response?.data?.detail || '诊断状态获取失败') } }
    poll()
    return () => { active = false }
  }, [diagnosisId])
  const stockOptions = (search.data?.data || []).map((item: any) => ({ value: item.symbol || item.stock_code, label: `${item.name || item.stock_name || '-'} (${item.symbol || item.stock_code})`, item }))
  const selectStock = (value: string) => { const option = stockOptions.find((item: any) => item.value === value); setSelected(option?.item || { stock_code: value }); setSymbol(value) }
  const research = report?.research
  const quantitative = report?.risk_reward
  const risk = report?.sections?.risk || report?.risk
  const overviewData = overview.data?.data || overview.data || {}
  return <Space direction="vertical" size={20} className="diagnosis-page">
    <div className="diagnosis-hero"><div><Typography.Title level={2} style={{ margin: 0 }}>个股诊断</Typography.Title><Typography.Text type="secondary">从基本面、技术面、缠论与因子维度，快速形成一份可追溯的研究报告</Typography.Text></div><Tag color="blue">研究辅助</Tag></div>
    <Alert type="info" showIcon message="诊断结果基于当前可用数据快照，仅用于研究、模拟和交易辅助，不直接触发下单。" />
    <Card title="诊断配置" className="diagnosis-card"><Space wrap style={{ width: '100%' }}><Select showSearch filterOption={false} value={selected ? (selected.symbol || selected.stock_code) : undefined} onSearch={(value) => { setSymbol(value); setSelected(null) }} onChange={selectStock} options={stockOptions} loading={search.isFetching} placeholder="输入股票代码或名称" style={{ width: 300 }} /><Button type="primary" disabled={!selected} loading={createMutation.isPending} onClick={() => createMutation.mutate()}>开始诊断</Button>{diagnosisId && <Button danger disabled={!status || ['completed', 'partial', 'failed', 'cancelled', 'expired'].includes(status.status)} onClick={() => cancelDiagnosis(diagnosisId).then(setStatus)}>取消任务</Button>}{report && <Button href={diagnosisExportUrl(diagnosisId || '')} target="_blank">导出 PDF 报告</Button>}</Space></Card>
    {selected && <Card title="股票概览" className="diagnosis-card" loading={overview.isLoading} extra={onNavigate ? <Button type="link" onClick={() => onNavigate('sentiment-analyst', { stockCode: selected.symbol || selected.stock_code })}>查看舆情分析 →</Button> : null}><Descriptions size="small" column={{ xs: 1, sm: 2, md: 4 }} items={Object.entries(overviewData).filter(([key]) => !['symbol', 'series', 'latest'].includes(key)).slice(0, 8).map(([key, value]) => ({ key, label: key === 'change_percent' ? `${overviewData.data_as_of || overviewData.latest?.trade_date || '最新交易日'} 涨跌幅` : diagnosisDetailLabels[key] || key, children: formatDiagnosisValue(key, value) }))} /></Card>}
    {status && <Card title="诊断进度" className="diagnosis-card"><Space direction="vertical" style={{ width: '100%' }}><Progress percent={Number(status.progress || 0)} status={status.status === 'failed' ? 'exception' : status.status === 'completed' || status.status === 'partial' ? 'success' : 'active'} /><Typography.Text type="secondary">任务状态：{formatDiagnosisStatus(status.status)}　当前阶段：{formatDiagnosisStage(status.current_stage)}</Typography.Text>{status.error && <Alert type={status.status === 'partial' ? 'warning' : 'error'} showIcon message={status.status === 'partial' ? '诊断已完成，但部分增强分析未生成' : status.error} description={status.status === 'partial' ? status.error : undefined} />}</Space></Card>}
    {report && <Card title="综合报告" className="diagnosis-card"><div className="diagnosis-summary"><Statistic title="综合评分" value={report.summary?.score ?? '-'} /><Statistic title="趋势" value={formatDiagnosisValue('trend', report.summary?.trend)} /><Statistic title="置信度" value={formatDiagnosisValue('confidence', report.summary?.confidence)} /></div>{report.sentiment && <Card type="inner" title="新闻舆情与政策" style={{ marginBottom: 16 }}><Space direction="vertical" style={{ width: '100%' }}><Typography.Text>方向：{report.sentiment.summary?.direction || '待确认'}　强度：{report.sentiment.summary?.strength ?? '-'}</Typography.Text><Typography.Text type="secondary">新闻数量：{report.sentiment.sentiment?.count ?? 0}　证据：{report.sentiment.quality_checks?.evidence_count ?? 0} 条　截止：{report.sentiment.data_as_of || '-'}</Typography.Text>{(report.sentiment.evidence || []).slice(0, 5).map((item: any, index: number) => <Typography.Paragraph key={`${item.document_id || 'evidence'}-${index}`} ellipsis={{ rows: 2 }}><Typography.Text strong>{item.title || '未命名来源'}</Typography.Text>：{item.quote || '暂无原文引用'}</Typography.Paragraph>)}</Space></Card>}{risk && <Card type="inner" title="基本面风险识别" style={{ marginBottom: 16 }}><Descriptions column={{ xs: 1, sm: 2, md: 4 }} items={[['基本面风险得分', risk.fundamental_score ?? '-'], ['基本面风险等级', formatDiagnosisValue('level', risk.fundamental_level || risk.level)], ['风险项数量', (risk.fundamental_tags || risk.items || []).length], ['规则版本', risk.rule_version || '-']].map(([key, children]) => ({ key, label: key, children }))} /><Space wrap>{(risk.fundamental_tags || []).map((item: any) => <Tag key={item.id} color={item.level === 'high' ? 'red' : item.level === 'medium' ? 'orange' : 'blue'}>{item.name}{item.proxy ? '（代理）' : ''}</Tag>)}</Space>{(risk.fundamental_tags || []).slice(0, 8).map((item: any) => <Typography.Paragraph key={item.id} ellipsis={{ rows: 2 }}><Typography.Text strong>{item.name}</Typography.Text>：{item.description}</Typography.Paragraph>)}</Card>}{quantitative && <Card type="inner" title="定量风险收益" style={{ marginBottom: 16 }}><Descriptions column={{ xs: 1, sm: 2, md: 4 }} items={[['目标价格区间', `${quantitative.target_price?.low ?? '-'} - ${quantitative.target_price?.high ?? '-'}`], ['预期涨幅', `${quantitative.expected_return?.low ?? '-'}% - ${quantitative.expected_return?.high ?? '-'}%`], ['持有周期', `${quantitative.holding_period?.days ?? '-'} 个交易日`], ['止损类型', quantitative.stop_loss?.type ?? '-'], ['止损参考价', quantitative.stop_loss?.price ?? '-'], ['触发条件', quantitative.stop_loss?.trigger ?? '-'], ['HV20 / HV60', `${quantitative.volatility?.hv20 ?? '-'} / ${quantitative.volatility?.hv60 ?? '-'}`], ['ATR14', quantitative.volatility?.atr14 ?? '-'], ['风险收益比', quantitative.risk_reward_ratio ?? '-'], ['数据截至', quantitative.data_as_of || '-'], ['规则版本', quantitative.rule_version || '-']].map(([key, children]) => ({ key, label: key, children }))} /><Typography.Text type="secondary">公式：{quantitative.formula || '-'}。价格和止损由规则计算，AI 仅负责解释；本结果仅供研究辅助，不构成投资建议。</Typography.Text></Card>}{research && <Card type="inner" title="国泰君安五步法" style={{ marginBottom: 16 }}><Typography.Text type="secondary">数据截至：{research.data_as_of || report.data_as_of || '-'}　状态：{research.status || 'completed'}</Typography.Text>{research.report && <div className="diagnosis-markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{research.report}</ReactMarkdown></div>}{research.steps && <Collapse items={Object.entries(research.steps).map(([key, value]: [string, any]) => ({ key, label: diagnosisModuleLabels[key] || key, children: <div className="diagnosis-markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{typeof value === 'string' ? value : value?.analysis || value?.content || JSON.stringify(value, null, 2)}</ReactMarkdown></div> }))} />}</Card>}{report.agent_analysis && <AgentAnalysisPanel value={report.agent_analysis} debate={report.debate} consensus={report.consensus} />}</Card>}
    <Card title="历史诊断" className="diagnosis-card"><Table size="small" rowKey="diagnosis_id" loading={history.isLoading} dataSource={history.data?.data || []} pagination={{ pageSize: 5 }} columns={[{ title: '任务编号', dataIndex: 'diagnosis_id', ellipsis: true }, { title: '状态', dataIndex: 'status', render: (value: string) => formatDiagnosisStatus(value) }, { title: '进度', dataIndex: 'progress', render: (value: number) => `${value || 0}%` }, { title: '创建时间', dataIndex: 'created_at' }]} /></Card>
  </Space>
}

export function App() { const [page, setPage] = useState('dashboard'); const handleNavigate = (target: string, params?: Record<string, string>) => { if (params?.stockCode) sessionStorage.setItem('diagnosis-prefill-symbol', params.stockCode); setPage(target) }; return <ConfigProvider theme={{ algorithm: theme.defaultAlgorithm, token: { colorPrimary: '#1677c8', colorInfo: '#1677c8', colorSuccess: '#159b7d', colorWarning: '#c78316', colorError: '#d9485f', colorBgBase: '#f4f7fb', colorBgContainer: '#ffffff', colorBgElevated: '#ffffff', colorBorder: '#dbe4ee', colorText: '#243b53', colorTextSecondary: '#60778c', colorTextTertiary: '#8294a8', fontSize: 14, fontSizeSM: 12, fontSizeLG: 16, borderRadius: 4, borderRadiusLG: 4 } }}><AntApp><Layout className="app-shell" style={{ minHeight: '100vh' }}><Sider className="app-sider"><div className="brand">QuantMind</div><Menu theme="dark" mode="inline" selectedKeys={[page]} items={menu} onClick={({ key }) => setPage(key)} /></Sider><Layout className="app-main"><Header className="topbar"><span>QUANTMIND</span><span className="topbar-status"><i /> LIVE RESEARCH</span></Header><Content className="content">{page === 'dashboard' && <Dashboard onNavigate={setPage} />}{page === 'chat' && <ChatBox />}{page === 'diagnosis' && <StockDiagnosis onNavigate={handleNavigate} />}{page === 'technical-analyst' && <TechnicalAnalyst />}{page === 'sentiment-analyst' && <SentimentAnalyst initialStockCode={sessionStorage.getItem('diagnosis-prefill-symbol') || undefined} onNavigateToDiagnosis={(code) => handleNavigate('diagnosis', { stockCode: code })} />}{page === 'fundamental-analyst' && <FundamentalAnalyst initialStockCode={sessionStorage.getItem('diagnosis-prefill-symbol') || undefined} />}{page === 'morning-brief' && <MorningBrief />}{page === 'opportunities' && <Opportunities />}{page === 'sector-opportunities' && <SectorOpportunities />}{page === 'risk-control' && <RiskControlDashboard />}{page === 'risks' && <Risks />}{page === 'sync' && <Sync />}{page === 'qlib-research' && <QlibResearch />}</Content></Layout></Layout></AntApp></ConfigProvider> }

import { useEffect, useMemo, useState } from 'react'
import { Alert, App as AntApp, Button, Card, Collapse, Descriptions, Drawer, Empty, Form, Input, InputNumber, List, Modal, Popconfirm, Progress, Segmented, Select, Space, Statistic, Table, Tag, Typography, message } from 'antd'
import { ArrowRightOutlined, CloudDownloadOutlined, PlayCircleOutlined, ReloadOutlined, SyncOutlined } from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  addSentimentWatch,
  generateSentimentReport,
  getFearIndexHistory,
  getPolymarketAssetSuggestions,
  getPolymarketSignals,
  getPolymarketSmartMoney,
  getSentimentAggregate,
  getSentimentDetail,
  getSentimentEvents,
  getSentimentReport,
  getSentimentReportFileUrl,
  getSentimentReportHistory,
  getSentimentReportStreamUrl,
  getSentimentWatchlistAlerts,
  listSentimentWatchlist,
  removeSentimentWatch,
  syncPolymarket,
} from './api/client'

type TabKey = 'micro' | 'macro' | 'theme' | 'watchlist'

const NODE_LABELS: Record<string, string> = {
  aggregate: '市场情绪聚合',
  events: '主题事件抽取',
  fear_index: '宏观恐慌指标',
  report: '综合舆情报告',
}

const sentimentColors: Record<string, string> = {
  positive: 'green',
  negative: 'red',
  neutral: 'blue',
  bullish: 'green',
  bearish: 'red',
}
const sentimentLabels: Record<string, string> = {
  positive: '正面',
  negative: '负面',
  neutral: '中性',
  bullish: '利好',
  bearish: '利空',
}
const signalColors: Record<string, string> = {
  关注: 'green',
  强烈关注: 'magenta',
  回避: 'orange',
  坚决回避: 'red',
}

function formatSentiment(value: unknown): string {
  if (value == null) return '-'
  return sentimentLabels[String(value)] || String(value)
}

export interface SentimentAnalystProps {
  initialStockCode?: string
  onNavigateToDiagnosis?: (stockCode: string) => void
}

export function SentimentAnalyst({ initialStockCode, onNavigateToDiagnosis }: SentimentAnalystProps) {
  const [activeTab, setActiveTab] = useState<TabKey>('micro')
  const [stockCode, setStockCode] = useState<string>(initialStockCode || '')
  useEffect(() => {
    if (initialStockCode) setStockCode(initialStockCode)
  }, [initialStockCode])
  return (
    <Space direction="vertical" size={16} className="sentiment-page" style={{ width: '100%' }}>
      <div className="sentiment-hero">
        <div>
          <Typography.Text className="eyebrow">NEWS & SENTIMENT</Typography.Text>
          <Typography.Title level={2} style={{ margin: 0 }}>舆情分析师</Typography.Title>
          <Typography.Text type="secondary">从微观新闻情绪、宏观恐慌指标到 Polymarket 预测市场，全景化跟踪 A 股与全球市场舆情</Typography.Text>
        </div>
        <Segmented
          value={activeTab}
          onChange={(value) => setActiveTab(value as TabKey)}
          options={[
            { label: '微观舆情', value: 'micro' },
            { label: '宏观风险', value: 'macro' },
            { label: '主题事件', value: 'theme' },
            { label: '监控列表', value: 'watchlist' },
          ]}
        />
      </div>
      {activeTab === 'micro' && (
        <MicroSentimentPanel
          stockCode={stockCode}
          onStockCodeChange={setStockCode}
          onNavigateToDiagnosis={onNavigateToDiagnosis}
        />
      )}
      {activeTab === 'macro' && <MacroRiskPanel />}
      {activeTab === 'theme' && <ThemeEventsPanel onNavigateToDiagnosis={onNavigateToDiagnosis} />}
      {activeTab === 'watchlist' && <WatchlistPanel onNavigateToDiagnosis={onNavigateToDiagnosis} />}
    </Space>
  )
}

// ============================================================ Tab 1 — 微观舆情
function MicroSentimentPanel({
  stockCode,
  onStockCodeChange,
  onNavigateToDiagnosis,
}: {
  stockCode: string
  onStockCodeChange: (code: string) => void
  onNavigateToDiagnosis?: (code: string) => void
}) {
  const code = stockCode.trim()
  const client = useQueryClient()
  const [reportId, setReportId] = useState<string | null>(null)
  const [reportStatus, setReportStatus] = useState<'idle' | 'running' | 'completed' | 'failed'>('idle')

  const aggregateQuery = useQuery({
    queryKey: ['sentiment-aggregate', code],
    queryFn: () => getSentimentAggregate(code, 20),
    enabled: code.length >= 4,
    refetchInterval: 60000,
  })
  const detailQuery = useQuery({
    queryKey: ['sentiment-detail', code],
    queryFn: () => getSentimentDetail(code, undefined, 50),
    enabled: code.length >= 4,
    refetchInterval: 60000,
  })
  const eventsQuery = useQuery({
    queryKey: ['sentiment-events', code],
    queryFn: () => getSentimentEvents(code, undefined, 50),
    enabled: code.length >= 4,
    refetchInterval: 60000,
  })
  const reportQuery = useQuery({
    queryKey: ['sentiment-report', code],
    queryFn: () => getSentimentReport(code),
    enabled: code.length >= 4 && reportStatus === 'completed',
  })
  const historyQuery = useQuery({
    queryKey: ['sentiment-report-history', code],
    queryFn: () => getSentimentReportHistory(code, 5),
    enabled: code.length >= 4,
  })

  const generateMutation = useMutation({
    mutationFn: (days: number) => generateSentimentReport(code, days),
    onSuccess: (data) => {
      setReportId(data.report_id)
      setReportStatus(data.status === 'completed' ? 'completed' : 'running')
      message.success(data.cache_hit ? '已命中缓存，无需重新生成' : '舆情报告已生成')
      client.invalidateQueries({ queryKey: ['sentiment-report', code] })
      client.invalidateQueries({ queryKey: ['sentiment-report-history', code] })
    },
    onError: (error: any) => message.error(error?.response?.data?.detail || '舆情报告生成失败'),
  })

  const aggregateRow = (aggregateQuery.data?.data || [])[0]
  const detailRows = detailQuery.data?.data || []
  const eventRows = eventsQuery.data?.data || []
  const report = reportQuery.data
  const topThemes: string[] = (() => {
    const themes = aggregateRow?.top_themes
    if (Array.isArray(themes)) return themes
    if (typeof themes === 'string') {
      try {
        return JSON.parse(themes)
      } catch {
        return []
      }
    }
    return []
  })()

  const riskAlerts: string[] = useMemo(() => {
    const raw = aggregateRow?.risk_alerts
    if (Array.isArray(raw)) return raw
    if (typeof raw === 'string') {
      try {
        return JSON.parse(raw)
      } catch {
        return []
      }
    }
    return []
  }, [aggregateRow])

  const detailColumns = [
    {
      title: '日期',
      dataIndex: 'news_date',
      width: 110,
      render: (value: string) => (value ? String(value).slice(0, 10) : '-'),
    },
    { title: '情感', dataIndex: 'sentiment', width: 80, render: (v: string) => <Tag color={sentimentColors[v] || 'default'}>{formatSentiment(v)}</Tag> },
    { title: '强度', dataIndex: 'strength', width: 70, render: (v: number) => (v == null ? '-' : `${v}/5`) },
    { title: '标题', dataIndex: 'news_title', ellipsis: true },
    { title: '来源', dataIndex: 'news_source', width: 110 },
  ]
  const eventColumns = [
    {
      title: '日期',
      dataIndex: 'news_date',
      width: 110,
      render: (value: string) => (value ? String(value).slice(0, 10) : '-'),
    },
    { title: '类型', dataIndex: 'event_type', width: 90 },
    { title: '子类型', dataIndex: 'event_subtype', width: 130 },
    { title: '信号', dataIndex: 'signal', width: 110, render: (v: string) => <Tag color={signalColors[v] || 'default'}>{v || '-'}</Tag> },
    { title: '描述', dataIndex: 'event_desc', ellipsis: true },
  ]

  return (
    <>
      <Card title="股票选择" className="sentiment-card">
        <Space wrap>
          <Input.Search
            value={stockCode}
            onChange={(event) => onStockCodeChange(event.target.value)}
            onSearch={(value) => onStockCodeChange(value.trim())}
            placeholder="输入股票代码，如 600519"
            enterButton
            style={{ width: 280 }}
            allowClear
          />
          <Button type="primary" icon={<PlayCircleOutlined />} loading={generateMutation.isPending} disabled={code.length < 4} onClick={() => generateMutation.mutate(7)}>
            生成 7 天舆情报告
          </Button>
          {reportId && <Tag color="blue">报告 ID：{reportId}</Tag>}
          {report?.data_as_of && <Tag color="cyan">数据截至 {report.data_as_of}</Tag>}
        </Space>
      </Card>

      {code.length < 4 && <Alert type="info" showIcon message="请先输入至少 4 位股票代码" />}

      {code.length >= 4 && aggregateQuery.isError && (
        <Alert type="error" showIcon message="情绪聚合查询失败" description="请先执行 sentiment 同步任务，或检查后端服务" />
      )}

      {code.length >= 4 && (
        <Card
          title="情绪聚合画像"
          className="sentiment-card"
          extra={aggregateRow ? <Tag color={sentimentColors[aggregateRow.overall_sentiment] || 'default'}>{formatSentiment(aggregateRow.overall_sentiment)}</Tag> : null}
        >
          {aggregateRow ? (
            <>
              <Descriptions size="small" column={{ xs: 1, sm: 2, md: 4 }}>
                <Descriptions.Item label="恐惧贪婪指数">
                  <strong>{aggregateRow.fear_greed_index ?? '-'}</strong>
                </Descriptions.Item>
                <Descriptions.Item label="新闻数">{aggregateRow.news_count ?? '-'}</Descriptions.Item>
                <Descriptions.Item label="正面 / 负面 / 中性">
                  {aggregateRow.positive_count ?? 0} / {aggregateRow.negative_count ?? 0} / {aggregateRow.neutral_count ?? 0}
                </Descriptions.Item>
                <Descriptions.Item label="分析时间">{aggregateRow.analyzed_at || '-'}</Descriptions.Item>
                <Descriptions.Item label="主题词" span={4}>
                  {topThemes.length ? topThemes.map((word) => <Tag key={word}>{word}</Tag>) : '-'}
                </Descriptions.Item>
                <Descriptions.Item label="摘要" span={4}>
                  {aggregateRow.summary || '-'}
                </Descriptions.Item>
              </Descriptions>
              {riskAlerts.length > 0 && <Alert style={{ marginTop: 12 }} type="warning" showIcon message="情绪聚合风险提示" description={riskAlerts.join('；')} />}
            </>
          ) : !aggregateQuery.isLoading ? (
            <Empty description="暂无情绪聚合数据，请先执行 sentiment 同步任务" />
          ) : null}
        </Card>
      )}

      {code.length >= 4 && (
        <Card title="新闻情绪明细" className="sentiment-card" extra={<Typography.Text type="secondary">近 50 条</Typography.Text>}>
          <Table rowKey={(row: any, idx?: number) => `${row.news_date}-${row.news_title}-${idx}`} size="small" loading={detailQuery.isLoading} dataSource={detailRows} columns={detailColumns} pagination={{ pageSize: 10 }} locale={{ emptyText: '暂无新闻明细，请先执行 sentiment 同步' }} />
        </Card>
      )}

      {code.length >= 4 && (
        <Card title="重大事件清单" className="sentiment-card">
          <Table rowKey={(row: any, idx?: number) => `${row.news_date}-${row.event_subtype}-${idx}`} size="small" loading={eventsQuery.isLoading} dataSource={eventRows} columns={eventColumns} pagination={{ pageSize: 10 }} locale={{ emptyText: '暂无事件' }} />
        </Card>
      )}

      <Card
        title="个股舆情研究报告"
        className="sentiment-card"
        extra={
          <Space>
            {historyQuery.data?.data?.length ? (
              <Select
                size="small"
                style={{ width: 220 }}
                placeholder="历史版本"
                value={reportId || undefined}
                onChange={(value) => {
                  setReportId(value)
                  setReportStatus('completed')
                }}
                options={(historyQuery.data?.data || []).map((row: any) => ({
                  value: row.report_id,
                  label: `${row.data_as_of || '-'} · ${row.created_at ? String(row.created_at).slice(0, 16) : ''}`,
                }))}
                allowClear
              />
            ) : null}
            <Button size="small" icon={<ReloadOutlined />} onClick={() => reportQuery.refetch()} disabled={!reportId}>刷新报告</Button>
            {onNavigateToDiagnosis && code.length >= 4 && (
              <Button size="small" icon={<ArrowRightOutlined />} onClick={() => onNavigateToDiagnosis(code)}>查看个股诊断</Button>
            )}
          </Space>
        }
      >
        {generateMutation.isPending && (
          <div>
            <Progress percent={50} status="active" showInfo={false} />
            <Typography.Text type="secondary">正在收集证据并生成报告，预计 5-30 秒...</Typography.Text>
          </div>
        )}
        {!generateMutation.isPending && report && (
          <div className="diagnosis-markdown">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{report.content_markdown || ''}</ReactMarkdown>
          </div>
        )}
        {!generateMutation.isPending && !report && (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未生成个股舆情报告，点击右上角按钮可立即生成" />
        )}
        {generateMutation.isError && (
          <Alert type="error" showIcon message="舆情报告生成失败" description={(generateMutation.error as any)?.response?.data?.detail || '请检查 DASHSCOPE_API_KEY 或后端服务日志'} />
        )}
      </Card>
    </>
  )
}

// ============================================================ Tab 2 — 宏观风险
function MacroRiskPanel() {
  const [running, setRunning] = useState(false)
  const [progress, setProgress] = useState<Record<string, 'pending' | 'active' | 'done' | 'failed'>>({})
  const [error, setError] = useState<string | null>(null)
  const [donePayload, setDonePayload] = useState<any>(null)
  const fearQuery = useQuery({ queryKey: ['fear-index', 60], queryFn: () => getFearIndexHistory(60), refetchInterval: 30000 })

  const runStream = () => {
    if (running) return
    setRunning(true)
    setError(null)
    setDonePayload(null)
    setProgress({ aggregate: 'pending', events: 'pending', fear_index: 'pending', report: 'pending' })
    const url = getSentimentReportStreamUrl({ days_aggregate: 3, days_events: 7, limit_events: 20 })
    const source = new EventSource(url)
    const setNode = (name: string, state: 'active' | 'done' | 'failed') => {
      setProgress((prev) => ({ ...prev, [name]: state }))
    }
    source.addEventListener('connected', () => {
      // 全部置为 active
      setProgress({ aggregate: 'active', events: 'active', fear_index: 'active', report: 'active' })
    })
    source.addEventListener('node_done', (event) => {
      try {
        const payload = JSON.parse((event as MessageEvent).data)
        const nodeName = payload?.node as string
        if (nodeName) setNode(nodeName, 'done')
      } catch (error) {
        console.error('node_done parse failed', error)
      }
    })
    source.addEventListener('done', (event) => {
      try {
        const payload = JSON.parse((event as MessageEvent).data)
        setDonePayload(payload)
        setProgress((prev) => {
          const next: Record<string, 'pending' | 'active' | 'done' | 'failed'> = { ...prev }
          for (const key of Object.keys(next)) if (next[key] === 'active') next[key] = 'done'
          return next
        })
      } catch (error) {
        console.error('done parse failed', error)
      } finally {
        source.close()
        setRunning(false)
      }
    })
    source.addEventListener('error_event', (event) => {
      try {
        const payload = JSON.parse((event as MessageEvent).data)
        setError(payload?.message || '宏观舆情简报生成失败')
      } catch {
        setError('宏观舆情简报生成失败')
      } finally {
        source.close()
        setRunning(false)
      }
    })
    source.onerror = () => {
      setError('SSE 连接异常，请检查后端服务')
      source.close()
      setRunning(false)
    }
  }

  const fearRows = (fearQuery.data?.data || []).slice().reverse()
  const latest = fearRows[fearRows.length - 1]
  const chartOption = {
    animation: false,
    tooltip: { trigger: 'axis' },
    grid: { left: 60, right: 24, top: 24, bottom: 40 },
    xAxis: { type: 'category', data: fearRows.map((row: any) => String(row.recorded_at || '').slice(0, 10)), axisLabel: { color: '#8fa2c7' } },
    yAxis: { type: 'value', min: 0, max: 100, axisLabel: { color: '#8fa2c7' }, splitLine: { lineStyle: { color: '#263244' } } },
    series: [{
      name: '综合恐慌贪婪指数',
      type: 'line',
      smooth: true,
      data: fearRows.map((row: any) => row.composite_score ?? null),
      areaStyle: { color: 'rgba(82,196,26,.18)' },
      itemStyle: { color: '#52c41a' },
    }],
  }

  const nodeStateColor = (state: string | undefined): string => {
    if (state === 'done') return '#52c41a'
    if (state === 'active') return '#1677ff'
    if (state === 'failed') return '#ff4d4f'
    return '#d9d9d9'
  }

  return (
    <>
      <Card className="sentiment-card" title="市场恐慌贪婪指数">
        <Space wrap size={24}>
          <Statistic
            title="当前综合评分"
            value={latest?.composite_score ?? '-'}
            valueStyle={{ color: latest && latest.composite_score < 30 ? '#ff4d4f' : latest && latest.composite_score > 75 ? '#faad14' : '#1677ff' }}
          />
          <Statistic title="VIX" value={latest?.vix ?? '-'} />
          <Statistic title="OVX" value={latest?.ovx ?? '-'} />
          <Statistic title="GVZ" value={latest?.gvz ?? '-'} />
          <Statistic title="美债10Y" value={latest?.us10y ?? '-'} suffix="%" />
          <Statistic title="风险等级" value={latest?.risk_level ?? '-'} />
        </Space>
        <div style={{ marginTop: 16 }}>
          {fearRows.length > 0 ? <ReactECharts option={chartOption} style={{ height: 240 }} notMerge /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无恐慌指数历史，请先执行 fear_index 同步任务" />}
        </div>
      </Card>

      <Card
        title="宏观舆情简报生成"
        className="sentiment-card"
        extra={
          <Button type="primary" icon={<PlayCircleOutlined />} loading={running} onClick={runStream} disabled={running}>
            生成宏观舆情简报
          </Button>
        }
      >
        <Space size={16} wrap>
          {['aggregate', 'events', 'fear_index', 'report'].map((node) => (
            <div key={node} className="sentiment-progress-node">
              <div className="dot" style={{ background: nodeStateColor(progress[node]) }} />
              <Typography.Text>{NODE_LABELS[node]}</Typography.Text>
            </div>
          ))}
        </Space>
        {error && <Alert style={{ marginTop: 16 }} type="error" showIcon message={error} />}
        {donePayload && (
          <Alert
            style={{ marginTop: 16 }}
            type="success"
            showIcon
            message="宏观舆情简报生成完成"
            description={
              <Space direction="vertical">
                <span>报告时间：{donePayload.data_as_of}</span>
                <span>覆盖股票：{donePayload.aggregate?.stocks ?? '-'}，新闻数：{donePayload.aggregate?.news ?? '-'}</span>
                <span>事件数：{donePayload.events_count ?? 0}</span>
                <Space>
                  <Button size="small" onClick={() => window.open(getSentimentReportFileUrl(donePayload.report_html_path, 'html'), '_blank')}>查看 HTML 报告</Button>
                  <Button size="small" onClick={() => window.open(getSentimentReportFileUrl(donePayload.report_markdown_path, 'markdown'), '_blank')}>查看 Markdown</Button>
                </Space>
              </Space>
            }
          />
        )}
      </Card>
    </>
  )
}

// ============================================================ Tab 3 — 主题事件
function ThemeEventsPanel({ onNavigateToDiagnosis }: { onNavigateToDiagnosis?: (code: string) => void }) {
  const client = useQueryClient()
  const signalsQuery = useQuery({ queryKey: ['polymarket-signals', 50], queryFn: () => getPolymarketSignals(undefined, 50) })
  const smartQuery = useQuery({ queryKey: ['polymarket-smart-money', 20], queryFn: () => getPolymarketSmartMoney(20) })
  const suggestionsQuery = useQuery({ queryKey: ['polymarket-suggestions', 20], queryFn: () => getPolymarketAssetSuggestions(20) })
  const syncMutation = useMutation({
    mutationFn: () => syncPolymarket(),
    onSuccess: (data) => {
      message.success(`同步完成，共 ${data.total_markets} 个市场`)
      client.invalidateQueries({ queryKey: ['polymarket-signals'] })
      client.invalidateQueries({ queryKey: ['polymarket-smart-money'] })
      client.invalidateQueries({ queryKey: ['polymarket-suggestions'] })
    },
    onError: (error: any) => message.error(error?.response?.data?.detail || 'Polymarket 同步失败（可能为网络原因）'),
  })

  const signals = signalsQuery.data?.data || []
  const smart = smartQuery.data?.data || []
  const suggestions = suggestionsQuery.data?.data || []
  const signalsColumns = [
    { title: '关键词', dataIndex: 'keyword', width: 100 },
    { title: '市场问题', dataIndex: 'question', ellipsis: true },
    { title: 'Yes 概率', dataIndex: 'yes_probability', width: 100, render: (v: number) => v == null ? '-' : `${v.toFixed(1)}%` },
    { title: '交易量(USD)', dataIndex: 'volume_usd', width: 140, render: (v: number) => v == null ? '-' : Number(v).toLocaleString('en-US', { maximumFractionDigits: 0 }) },
    { title: '信号强度', dataIndex: 'signal_strength', width: 130 },
    { title: '抓取时间', dataIndex: 'fetched_at', width: 160 },
  ]

  return (
    <>
      <Card className="sentiment-card" extra={
        <Button icon={<CloudDownloadOutlined />} loading={syncMutation.isPending} onClick={() => syncMutation.mutate()}>
          立即同步 Polymarket
        </Button>
      }>
        <Alert type="info" showIcon message="Polymarket 在国内网络可能不可达，同步失败时仅记录错误，不会中断其它任务" />
      </Card>
      <Card title="Polymarket 预测市场信号" className="sentiment-card">
        <Table rowKey={(row: any) => `${row.market_id}-${row.fetched_at}`} loading={signalsQuery.isLoading} dataSource={signals} columns={signalsColumns} pagination={{ pageSize: 10 }} locale={{ emptyText: '暂无 Polymarket 信号，请先点击右上角同步' }} />
      </Card>
      <Card title="聪明钱信号" className="sentiment-card">
        <Table
          rowKey={(row: any, idx?: number) => `${row.question}-${idx}`}
          loading={smartQuery.isLoading}
          dataSource={smart}
          pagination={{ pageSize: 10 }}
          columns={[
            { title: '市场', dataIndex: 'question', ellipsis: true },
            { title: '关键词', dataIndex: 'keyword', width: 100 },
            { title: 'Yes 概率', dataIndex: 'yes_probability', width: 100, render: (v: number) => v == null ? '-' : `${v.toFixed(1)}%` },
            { title: '交易量', dataIndex: 'volume_display', width: 120 },
            { title: '等级', dataIndex: 'alert_level', width: 80, render: (v: string) => <Tag color={v === '高' ? 'red' : 'orange'}>{v || '-'}</Tag> },
            { title: '信号原因', dataIndex: 'signal_reasons', render: (value: string[]) => (value || []).map((reason) => <Tag key={reason}>{reason}</Tag>) },
          ]}
          locale={{ emptyText: '暂无聪明钱信号' }}
        />
      </Card>
      <Card title="资产配置建议" className="sentiment-card">
        <List
          loading={suggestionsQuery.isLoading}
          dataSource={suggestions}
          locale={{ emptyText: '暂无资产配置建议' }}
          renderItem={(item: any) => (
            <List.Item>
              <List.Item.Meta
                title={<Space><Tag color="blue">{item.action}</Tag><Typography.Text type="secondary">{item.reason}</Typography.Text></Space>}
                description={<Space direction="vertical"><Typography.Text>{item.trigger}</Typography.Text><Typography.Text type="secondary">交易量：{item.volume}</Typography.Text></Space>}
              />
            </List.Item>
          )}
        />
      </Card>
    </>
  )
}

// ============================================================ Tab 4 — 监控列表
function WatchlistPanel({ onNavigateToDiagnosis }: { onNavigateToDiagnosis?: (code: string) => void }) {
  const client = useQueryClient()
  const [form] = Form.useForm()
  const [adding, setAdding] = useState(false)
  const watchlistQuery = useQuery({ queryKey: ['sentiment-watchlist', 'default'], queryFn: () => listSentimentWatchlist('default') })
  const alertsQuery = useQuery({ queryKey: ['sentiment-watchlist-alerts', 'default'], queryFn: () => getSentimentWatchlistAlerts('default'), refetchInterval: 60000 })

  const addMutation = useMutation({
    mutationFn: (values: any) => addSentimentWatch({
      group_name: 'default',
      stock_code: values.stock_code,
      stock_name: values.stock_name,
      threshold_fgi_low: values.threshold_fgi_low ?? null,
      threshold_fgi_high: values.threshold_fgi_high ?? null,
      threshold_negative_count: values.threshold_negative_count ?? null,
      note: values.note ?? null,
      enabled: true,
    }),
    onSuccess: () => {
      message.success('已加入监控列表')
      form.resetFields()
      setAdding(false)
      client.invalidateQueries({ queryKey: ['sentiment-watchlist'] })
      client.invalidateQueries({ queryKey: ['sentiment-watchlist-alerts'] })
    },
    onError: (error: any) => message.error(error?.response?.data?.detail || '添加监控失败'),
  })
  const removeMutation = useMutation({
    mutationFn: (row: any) => removeSentimentWatch(row.group_name, row.stock_code),
    onSuccess: () => {
      message.success('已移除监控')
      client.invalidateQueries({ queryKey: ['sentiment-watchlist'] })
      client.invalidateQueries({ queryKey: ['sentiment-watchlist-alerts'] })
    },
  })

  const watchRows = watchlistQuery.data?.data || []
  const alerts = alertsQuery.data
  const marketAlert = alerts?.market_alert
  const thresholdAlerts = alerts?.threshold_alerts || []
  const highEvents = alerts?.high_severity_events || []

  return (
    <>
      <Card className="sentiment-card" title="添加监控项" extra={<Button type="primary" icon={<SyncOutlined />} onClick={() => setAdding(true)}>添加股票</Button>}>
        <Typography.Text type="secondary">支持自定义 FGI 阈值与负面新闻阈值，超阈值自动触发告警</Typography.Text>
      </Card>
      <Card className="sentiment-card" title="监控列表">
        <Table
          rowKey="id"
          loading={watchlistQuery.isLoading}
          dataSource={watchRows}
          pagination={{ pageSize: 10 }}
          locale={{ emptyText: '暂无监控股票，点击右上角添加' }}
          columns={[
            { title: '股票', render: (_: any, row: any) => `${row.stock_name || '-'} (${row.stock_code})` },
            { title: 'FGI 阈值', render: (_: any, row: any) => `${row.threshold_fgi_low ?? '-'} ~ ${row.threshold_fgi_high ?? '-'}` },
            { title: '负面新闻阈值', dataIndex: 'threshold_negative_count', render: (v: number) => v ?? '-' },
            { title: '备注', dataIndex: 'note', ellipsis: true },
            {
              title: '操作',
              width: 200,
              render: (_: any, row: any) => (
                <Space>
                  {onNavigateToDiagnosis && (
                    <Button size="small" onClick={() => onNavigateToDiagnosis(row.stock_code)}>诊断</Button>
                  )}
                  <Popconfirm title={`确认移除 ${row.stock_code}?`} onConfirm={() => removeMutation.mutate(row)}>
                    <Button size="small" danger loading={removeMutation.isPending}>移除</Button>
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
      </Card>
      <Card className="sentiment-card" title="当前告警">
        {marketAlert && (
          <Alert
            style={{ marginBottom: 12 }}
            type={marketAlert.is_panic ? 'error' : marketAlert.is_greed ? 'warning' : 'info'}
            showIcon
            message={`市场整体：${marketAlert.risk_level || '-'}（${marketAlert.composite_score ?? '-'}）`}
            description={marketAlert.suggestion || '-'}
          />
        )}
        <List
          loading={alertsQuery.isLoading}
          dataSource={thresholdAlerts}
          locale={{ emptyText: '当前无阈值告警' }}
          renderItem={(item: any) => (
            <List.Item>
              <List.Item.Meta
                title={<Space><Tag color={item.level === 'danger' ? 'red' : item.level === 'warning' ? 'orange' : 'blue'}>{item.stock_name || item.stock_code}</Tag>{item.alert_type}</Space>}
                description={<Space direction="vertical"><Typography.Text>{item.message}</Typography.Text>{item.current && <Typography.Text type="secondary">当前：FGI={item.current.fear_greed_index} · 负面新闻 {item.current.negative_count} 条 · {item.current.analyzed_at}</Typography.Text>}</Space>}
              />
            </List.Item>
          )}
        />
      </Card>
      <Card className="sentiment-card" title="近期高严重度事件">
        <List
          dataSource={highEvents}
          locale={{ emptyText: '暂无事件' }}
          renderItem={(item: any) => (
            <List.Item>
              <Space>
                <Tag color={signalColors[item.signal] || 'default'}>{item.signal}</Tag>
                <Typography.Text strong>{item.stock_code}</Typography.Text>
                <Typography.Text>{item.event_type}/{item.event_subtype}</Typography.Text>
                <Typography.Text type="secondary">{item.event_desc}</Typography.Text>
                <Typography.Text type="secondary">{item.news_date}</Typography.Text>
              </Space>
            </List.Item>
          )}
        />
      </Card>
      <Modal title="添加舆情监控" open={adding} onCancel={() => setAdding(false)} onOk={() => form.submit()} confirmLoading={addMutation.isPending}>
        <Form form={form} layout="vertical">
          <Form.Item name="stock_code" label="股票代码" rules={[{ required: true }]}>
            <Input placeholder="如 600519" />
          </Form.Item>
          <Form.Item name="stock_name" label="股票名称">
            <Input placeholder="可选" />
          </Form.Item>
          <Form.Item name="threshold_fgi_low" label="FGI 下限阈值">
            <InputNumber min={0} max={100} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="threshold_fgi_high" label="FGI 上限阈值">
            <InputNumber min={0} max={100} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="threshold_negative_count" label="负面新闻阈值">
            <InputNumber min={0} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="note" label="备注">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}

// 包裹 AntApp 以便消费 message context
export function SentimentAnalystWithContext(props: SentimentAnalystProps) {
  return (
    <AntApp>
      <SentimentAnalyst {...props} />
    </AntApp>
  )
}
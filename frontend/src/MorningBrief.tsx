import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Col, Descriptions, Divider, InputNumber, Row, Space, Statistic, Switch, Table, Tag, Typography, message } from 'antd'
import { PlayCircleOutlined, ReloadOutlined, FileTextOutlined } from '@ant-design/icons'
import { getMorningCache, getMorningHistory, getMorningReportUrl, getMorningStreamUrl } from './api/client'

const nodeLabels: Record<string, string> = { industry: '板块强度', stock_picker: '多因子选股', report: '晨报生成', push: '推送' }
const phaseColors: Record<string, string> = { accel_up: 'red', decel_up: 'orange', decel_down: 'blue', accel_down: 'purple', neutral: 'default' }

export function MorningBrief() {
  const [data, setData] = useState<any>(null)
  const [history, setHistory] = useState<any[]>([])
  const [running, setRunning] = useState(false)
  const [node, setNode] = useState<string>('')
  const [messages, setMessages] = useState<string[]>([])
  const [params, setParams] = useState({ top_industries: 3, top_stocks: 5, sample_per_industry: 15, lookback: 90, industry_level: 2, enable_push: true })
  const [selectedStock, setSelectedStock] = useState<any>(null)

  const loadCache = async () => {
    try { setData(await getMorningCache()) } catch { message.info('暂无晨会缓存，请先运行晨会分析') }
    try { setHistory((await getMorningHistory(10)).data || []) } catch { setHistory([]) }
  }
  useEffect(() => { loadCache() }, [])

  const run = () => {
    if (running) return
    setRunning(true); setData(null); setMessages([]); setNode('')
    const source = new EventSource(getMorningStreamUrl(params))
    source.addEventListener('progress', (event) => { const payload = JSON.parse((event as MessageEvent).data); setNode(payload.current_node); setMessages((items) => [...items, payload.message]) })
    source.addEventListener('node_done', (event) => { const payload = JSON.parse((event as MessageEvent).data); setNode(payload.node); setMessages((items) => [...items, `${nodeLabels[payload.node] || payload.node}完成`]) })
    source.addEventListener('done', (event) => { setData(JSON.parse((event as MessageEvent).data)); setRunning(false); source.close(); loadCache(); message.success('晨会分析完成') })
    source.addEventListener('error_event', (event) => { const payload = JSON.parse((event as MessageEvent).data); setRunning(false); source.close(); message.error(payload.message || '晨会分析失败') })
    source.onerror = () => { if (running) { setRunning(false); source.close(); message.error('晨会连接中断，可读取最近缓存后重试') } }
  }

  const industries = data?.industry_rank || []
  const stocks = data?.picked_stocks || []
  const stockColumns = useMemo(() => [
    { title: '代码', dataIndex: 'code' }, { title: '名称', dataIndex: 'stock_name' }, { title: '板块', dataIndex: 'industry' },
    { title: 'Alpha', dataIndex: 'alpha', render: (value: number) => value == null ? '-' : value.toFixed(3) },
    { title: '1M动量', render: (_: unknown, row: any) => `${((row.raw_factors?.MOM_1M || 0) * 100).toFixed(2)}%` },
    { title: '3M动量', render: (_: unknown, row: any) => `${((row.raw_factors?.MOM_3M || 0) * 100).toFixed(2)}%` },
    { title: '信号', dataIndex: 'signal', render: (value: string) => <Tag color={value === '重点观察' ? 'red' : 'blue'}>{value || '观察'}</Tag> },
  ], [])
  return <Space direction="vertical" size={16} style={{ width: '100%' }}>
    <Space align="center" style={{ justifyContent: 'space-between', width: '100%' }}><div><Typography.Title level={3} style={{ margin: 0 }}>晨会分析</Typography.Title><Typography.Text type="secondary">板块轮动 · 多因子选股 · 晨报推送</Typography.Text></div><Space><Button icon={<ReloadOutlined />} onClick={loadCache}>读取缓存</Button><Button type="primary" icon={<PlayCircleOutlined />} loading={running} onClick={run}>运行晨会</Button></Space></Space>
    <Card size="small" title="运行参数"><Space wrap><span>Top板块 <InputNumber min={1} max={10} value={params.top_industries} onChange={(value) => setParams({ ...params, top_industries: value || 3 })} /></span><span>Top选股 <InputNumber min={1} max={20} value={params.top_stocks} onChange={(value) => setParams({ ...params, top_stocks: value || 5 })} /></span><span>回看天数 <InputNumber min={60} max={250} value={params.lookback} onChange={(value) => setParams({ ...params, lookback: value || 90 })} /></span><span>启用推送 <Switch checked={params.enable_push} onChange={(value) => setParams({ ...params, enable_push: value })} /></span></Space></Card>
    <Card title="工作流进度"><Row gutter={16}>{['industry', 'stock_picker', 'report', 'push'].map((item, index) => <Col xs={12} md={6} key={item}><Card size="small" bordered={false}><Statistic title={`${index + 1}. ${nodeLabels[item]}`} value={node === item ? '执行中' : messages.some((text) => text.includes(nodeLabels[item])) ? '已完成' : '待执行'} valueStyle={{ color: node === item ? '#1677ff' : messages.some((text) => text.includes(nodeLabels[item])) ? '#52c41a' : undefined }} /></Card></Col>)}</Row>{messages.length > 0 && <Typography.Text type="secondary">{messages[messages.length - 1]}</Typography.Text>}</Card>
    {data && <Alert type="info" message={data.summary || '晨会结果已生成'} description={<Space split={<Divider type="vertical" />}><span>数据日期：{data.data_as_of || '-'}</span><span>保存时间：{data.saved_at || '-'}</span><span>来源：{data.trigger_time ? '实时运行' : '缓存'}</span></Space>} />}
    <Row gutter={16}><Col xs={24} xl={12}><Card title="Top 强势板块" extra={<Tag>{industries.length} 个</Tag>}><Table rowKey="industry" size="small" pagination={false} dataSource={industries} columns={[{ title: '排名', dataIndex: 'rank' }, { title: '板块', dataIndex: 'industry' }, { title: '综合分', dataIndex: 'score', render: (value: number) => value == null ? '-' : value.toFixed(3) }, { title: '拐点', dataIndex: 'phase_desc', render: (value: string, row: any) => <Tag color={phaseColors[row.phase] || 'default'}>{value || '-'}</Tag> }, { title: '21日动量', dataIndex: 'MOM_21', render: (value: number) => value == null ? '-' : `${(value * 100).toFixed(2)}%` }, { title: '20日ROC', dataIndex: 'ROC_20', render: (value: number) => value == null ? '-' : `${value.toFixed(2)}%` }]} locale={{ emptyText: '暂无板块数据，请检查板块行情同步状态' }} /></Card></Col><Col xs={24} xl={12}><Card title="Top 选中标的" extra={<Tag>{stocks.length} 只</Tag>}><Table rowKey="code" size="small" pagination={false} dataSource={stocks} columns={stockColumns} onRow={(record) => ({ onClick: () => setSelectedStock(record), style: { cursor: 'pointer' } })} locale={{ emptyText: '暂无候选股票，请检查行情和行业数据' }} /></Card></Col></Row>
    {selectedStock && <Card title={`${selectedStock.code} · ${selectedStock.stock_name || ''}`} extra={<Button icon={<FileTextOutlined />} onClick={() => data?.report_html_path && window.open(getMorningReportUrl(data.report_html_path), '_blank')}>查看报告</Button>}><Descriptions column={{ xs: 1, sm: 2, md: 4 }} items={[['所属板块', selectedStock.industry], ['综合 Alpha', selectedStock.alpha], ['1M 动量', selectedStock.raw_factors?.MOM_1M], ['3M 动量', selectedStock.raw_factors?.MOM_3M], ['20D 波动率因子', selectedStock.raw_factors?.VOL_20], ['RSI 因子', selectedStock.raw_factors?.RSI_14], ['20D 乖离因子', selectedStock.raw_factors?.BIAS_20], ['盘中建议', selectedStock.intraday_advice]].map(([label, children]) => ({ label, children: children ?? '-' }))} /><Alert type="warning" message="因子分化提示" description={selectedStock.raw_factors?.MOM_3M < 0 ? '该标的短期动量可能修复，但中期动量为负，建议等待开盘方向确认，不宜仅凭板块强度追高。' : '请结合板块强度、成交量和开盘 30 分钟走势确认方向。'} /></Card>}
    {history.length > 0 && <Card title="最近运行记录"><Table rowKey="path" size="small" pagination={false} dataSource={history} columns={[{ title: '保存时间', dataIndex: 'saved_at' }, { title: '数据日期', dataIndex: 'data_as_of' }, { title: '状态', dataIndex: 'status' }, { title: '板块数', dataIndex: 'industry_count' }, { title: '选股数', dataIndex: 'stock_count' }]} /></Card>}
  </Space>
}

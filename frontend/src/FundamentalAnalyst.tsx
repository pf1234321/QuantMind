import { useState } from 'react'
import { Alert, Card, Descriptions, Empty, Input, Progress, Space, Statistic, Table, Tag, Typography } from 'antd'
import { SearchOutlined } from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import { useQuery } from '@tanstack/react-query'
import { getFundamentalAnalysis } from './api/client'

const ratingColors: Record<string, string> = {
  优秀: 'green',
  良好: 'blue',
  中等: 'cyan',
  一般: 'orange',
  较差: 'red',
  无数据: 'default',
}

export interface FundamentalAnalystProps {
  initialStockCode?: string
}

export function FundamentalAnalyst({ initialStockCode }: FundamentalAnalystProps) {
  const [stockCode, setStockCode] = useState<string>(initialStockCode || '')
  const code = stockCode.trim()

  const analysisQuery = useQuery({
    queryKey: ['fundamental-analysis', code],
    queryFn: () => getFundamentalAnalysis(code),
    enabled: code.length >= 4,
    retry: false,
  })

  const data = analysisQuery.data
  const stock = data?.stock
  const fundamentals = data?.fundamentals
  const comparison = data?.industry_comparison
  const ratings = data?.ratings
  const history = data?.history || []
  const peers = data?.industry_peers || []

  // 历史趋势图表配置
  const historyChart = {
    tooltip: { trigger: 'axis' },
    legend: {
      bottom: 0,
      textStyle: { color: '#9fb3d8' },
      data: ['ROE', 'ROA', '毛利率', '净利率']
    },
    grid: { left: 60, right: 24, top: 24, bottom: 60 },
    xAxis: {
      type: 'category',
      data: history.map((row: any) => row.report_date?.slice(0, 7) || '-'),
      axisLabel: { color: '#8fa2c7' },
    },
    yAxis: {
      type: 'value',
      name: '百分比 (%)',
      axisLabel: { color: '#8fa2c7', formatter: '{value}%' },
      splitLine: { lineStyle: { color: '#263244' } },
    },
    series: [
      {
        name: 'ROE',
        type: 'line',
        data: history.map((row: any) => row.roe || null),
        smooth: true,
        itemStyle: { color: '#52c41a' },
      },
      {
        name: 'ROA',
        type: 'line',
        data: history.map((row: any) => row.roa || null),
        smooth: true,
        itemStyle: { color: '#1677ff' },
      },
      {
        name: '毛利率',
        type: 'line',
        data: history.map((row: any) => row.gross_margin || null),
        smooth: true,
        itemStyle: { color: '#faad14' },
      },
      {
        name: '净利率',
        type: 'line',
        data: history.map((row: any) => row.net_margin || null),
        smooth: true,
        itemStyle: { color: '#722ed1' },
      },
    ],
  }

  // 行业对比柱状图
  const industryChart = comparison ? {
    tooltip: { trigger: 'axis' },
    legend: {
      bottom: 0,
      textStyle: { color: '#9fb3d8' },
      data: ['个股', '行业均值', '行业中位数']
    },
    grid: { left: 60, right: 24, top: 24, bottom: 60 },
    xAxis: {
      type: 'category',
      data: ['ROE', 'ROA', '毛利率', '净利率'],
      axisLabel: { color: '#8fa2c7' },
    },
    yAxis: {
      type: 'value',
      name: '百分比 (%)',
      axisLabel: { color: '#8fa2c7', formatter: '{value}%' },
      splitLine: { lineStyle: { color: '#263244' } },
    },
    series: [
      {
        name: '个股',
        type: 'bar',
        data: [
          fundamentals?.roe || 0,
          fundamentals?.roa || 0,
          fundamentals?.gross_margin || 0,
          fundamentals?.net_margin || 0,
        ],
        itemStyle: { color: '#52c41a' },
      },
      {
        name: '行业均值',
        type: 'bar',
        data: [
          comparison.roe?.avg || 0,
          comparison.roa?.avg || 0,
          comparison.gross_margin?.avg || 0,
          comparison.net_margin?.avg || 0,
        ],
        itemStyle: { color: '#1677ff' },
      },
      {
        name: '行业中位数',
        type: 'bar',
        data: [
          comparison.roe?.median || 0,
          comparison.roa?.median || 0,
          comparison.gross_margin?.median || 0,
          comparison.net_margin?.median || 0,
        ],
        itemStyle: { color: '#faad14' },
      },
    ],
  } : null

  // 同行公司对比表格
  const peerColumns = [
    { title: '股票代码', dataIndex: 'stock_code', width: 100 },
    { title: '股票名称', dataIndex: 'stock_name', width: 120 },
    {
      title: 'ROE (%)',
      dataIndex: 'roe',
      width: 100,
      render: (v: number) => v?.toFixed(2) || '-',
      sorter: (a: any, b: any) => (a.roe || 0) - (b.roe || 0),
    },
    {
      title: 'ROA (%)',
      dataIndex: 'roa',
      width: 100,
      render: (v: number) => v?.toFixed(2) || '-',
      sorter: (a: any, b: any) => (a.roa || 0) - (b.roa || 0),
    },
    {
      title: '毛利率 (%)',
      dataIndex: 'gross_margin',
      width: 110,
      render: (v: number) => v?.toFixed(2) || '-',
      sorter: (a: any, b: any) => (a.gross_margin || 0) - (b.gross_margin || 0),
    },
    {
      title: '净利率 (%)',
      dataIndex: 'net_margin',
      width: 110,
      render: (v: number) => v?.toFixed(2) || '-',
      sorter: (a: any, b: any) => (a.net_margin || 0) - (b.net_margin || 0),
    },
    {
      title: '营收 (亿元)',
      dataIndex: 'revenue',
      width: 120,
      render: (v: number) => v ? (v / 100000000).toFixed(2) : '-',
      sorter: (a: any, b: any) => (a.revenue || 0) - (b.revenue || 0),
    },
  ]

  return (
    <Space direction="vertical" size={16} className="fundamental-page" style={{ width: '100%' }}>
      <div className="fundamental-hero">
        <div>
          <Typography.Text className="eyebrow">FUNDAMENTAL ANALYSIS</Typography.Text>
          <Typography.Title level={2} style={{ margin: 0 }}>基本面分析师</Typography.Title>
          <Typography.Text type="secondary">分析股票的 ROE、ROA、毛利率等基本面指标，并与同行业公司对比</Typography.Text>
        </div>
      </div>

      <Card title="股票选择" className="fundamental-card">
        <Input.Search
          value={stockCode}
          onChange={(e) => setStockCode(e.target.value)}
          onSearch={(value) => setStockCode(value.trim())}
          placeholder="输入股票代码，如 600519"
          enterButton={<SearchOutlined />}
          style={{ width: 320 }}
          allowClear
        />
      </Card>

      {code.length < 4 && (
        <Alert type="info" showIcon message="请先输入至少 4 位股票代码" />
      )}

      {analysisQuery.isError && (
        <Alert
          type="error"
          showIcon
          message="查询失败"
          description={(analysisQuery.error as any)?.response?.data?.detail || '未找到该股票的财务数据，请先执行财务数据同步'}
        />
      )}

      {code.length >= 4 && data && (
        <>
          {/* 股票基本信息 */}
          <Card title="股票信息" className="fundamental-card">
            <Descriptions size="small" column={{ xs: 1, sm: 2, md: 4 }}>
              <Descriptions.Item label="股票代码">{stock?.code}</Descriptions.Item>
              <Descriptions.Item label="股票名称">{stock?.name}</Descriptions.Item>
              <Descriptions.Item label="所属行业">{stock?.sector_2 || '-'}</Descriptions.Item>
              <Descriptions.Item label="报告期">{stock?.report_date || '-'}</Descriptions.Item>
            </Descriptions>
          </Card>

          {/* 核心指标与评级 */}
          <Card title="核心财务指标" className="fundamental-card">
            <Space size={24} wrap>
              <div>
                <Statistic
                  title="ROE (净资产收益率)"
                  value={fundamentals?.roe?.toFixed(2) || '-'}
                  suffix="%"
                  valueStyle={{ color: '#52c41a' }}
                />
                <Tag color={ratingColors[ratings?.roe || '无数据']}>{ratings?.roe || '无数据'}</Tag>
                {comparison?.roe && (
                  <Typography.Text type="secondary">
                    行业排名: {comparison.roe.rank}/{comparison.roe.total} (前 {comparison.roe.percentile?.toFixed(0)}%)
                  </Typography.Text>
                )}
              </div>

              <div>
                <Statistic
                  title="ROA (总资产收益率)"
                  value={fundamentals?.roa?.toFixed(2) || '-'}
                  suffix="%"
                  valueStyle={{ color: '#1677ff' }}
                />
                <Tag color={ratingColors[ratings?.roa || '无数据']}>{ratings?.roa || '无数据'}</Tag>
                {comparison?.roa && (
                  <Typography.Text type="secondary">
                    行业排名: {comparison.roa.rank}/{comparison.roa.total} (前 {comparison.roa.percentile?.toFixed(0)}%)
                  </Typography.Text>
                )}
              </div>

              <div>
                <Statistic
                  title="毛利率"
                  value={fundamentals?.gross_margin?.toFixed(2) || '-'}
                  suffix="%"
                  valueStyle={{ color: '#faad14' }}
                />
                <Tag color={ratingColors[ratings?.gross_margin || '无数据']}>{ratings?.gross_margin || '无数据'}</Tag>
                {comparison?.gross_margin && (
                  <Typography.Text type="secondary">
                    行业排名: {comparison.gross_margin.rank}/{comparison.gross_margin.total} (前 {comparison.gross_margin.percentile?.toFixed(0)}%)
                  </Typography.Text>
                )}
              </div>

              <div>
                <Statistic
                  title="净利率"
                  value={fundamentals?.net_margin?.toFixed(2) || '-'}
                  suffix="%"
                  valueStyle={{ color: '#722ed1' }}
                />
                <Tag color={ratingColors[ratings?.net_margin || '无数据']}>{ratings?.net_margin || '无数据'}</Tag>
                {comparison?.net_margin && (
                  <Typography.Text type="secondary">
                    行业排名: {comparison.net_margin.rank}/{comparison.net_margin.total} (前 {comparison.net_margin.percentile?.toFixed(0)}%)
                  </Typography.Text>
                )}
              </div>

              <div>
                <Statistic
                  title="资产负债率"
                  value={fundamentals?.debt_ratio?.toFixed(2) || '-'}
                  suffix="%"
                  valueStyle={{ color: fundamentals?.debt_ratio && fundamentals.debt_ratio > 60 ? '#ff4d4f' : '#52c41a' }}
                />
                <Tag color={ratingColors[ratings?.debt_ratio || '无数据']}>{ratings?.debt_ratio || '无数据'}</Tag>
                <Typography.Text type="secondary">越低越好</Typography.Text>
              </div>
            </Space>
          </Card>

          {/* 其他财务指标 */}
          <Card title="其他财务指标" className="fundamental-card">
            <Descriptions size="small" column={{ xs: 1, sm: 2, md: 4 }}>
              <Descriptions.Item label="EPS (每股收益)">{fundamentals?.eps?.toFixed(2) || '-'} 元</Descriptions.Item>
              <Descriptions.Item label="流动比率">{fundamentals?.current_ratio?.toFixed(2) || '-'}</Descriptions.Item>
              <Descriptions.Item label="营业收入">{fundamentals?.revenue ? (fundamentals.revenue / 100000000).toFixed(2) : '-'} 亿元</Descriptions.Item>
              <Descriptions.Item label="净利润">{fundamentals?.net_profit ? (fundamentals.net_profit / 100000000).toFixed(2) : '-'} 亿元</Descriptions.Item>
            </Descriptions>
          </Card>

          {/* 历史趋势图 */}
          {history.length > 0 && (
            <Card title="历史趋势（最近4个季度）" className="fundamental-card">
              <ReactECharts option={historyChart} style={{ height: 300 }} notMerge />
            </Card>
          )}

          {/* 行业对比图 */}
          {industryChart && (
            <Card title={`行业对比 (${stock?.sector_2 || '同行业'})`} className="fundamental-card">
              <ReactECharts option={industryChart} style={{ height: 300 }} notMerge />
            </Card>
          )}

          {/* 同行业公司对比表 */}
          {peers.length > 0 && (
            <Card title="同行业公司对比（前20名）" className="fundamental-card">
              <Table
                rowKey="stock_code"
                size="small"
                dataSource={peers}
                columns={peerColumns}
                pagination={{ pageSize: 10 }}
                scroll={{ x: 800 }}
              />
            </Card>
          )}
        </>
      )}

      {code.length >= 4 && !analysisQuery.isLoading && !data && !analysisQuery.isError && (
        <Empty description="暂无数据" />
      )}
    </Space>
  )
}

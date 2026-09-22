import React, { useState } from 'react';
import {
  Card,
  Input,
  Button,
  Table,
  Tabs,
  Space,
  Tag,
  Statistic,
  Row,
  Col,
  Select,
  DatePicker,
  message,
  Modal,
  Alert,
  Progress,
  Divider,
  Spin,
  Empty,
  Badge,
} from 'antd';
import {
  LineChartOutlined,
  RiseOutlined,
  FallOutlined,
  SearchOutlined,
  ThunderboltOutlined,
  TrophyOutlined,
  FileTextOutlined,
  SyncOutlined,
  BarChartOutlined,
} from '@ant-design/icons';
import ReactECharts from 'echarts-for-react';
import ReactMarkdown from 'react-markdown';
import { api } from './api/client';

const { Search } = Input;
const { TabPane } = Tabs;
const { Option } = Select;
const { RangePicker } = DatePicker;

interface TechnicalIndicator {
  trade_date: string;
  ma5: number;
  ma20: number;
  ma60: number;
  rsi14: number;
  macd_dif: number;
  macd_dea: number;
  macd_bar: number;
  kdj_k: number;
  kdj_d: number;
  kdj_j: number;
  atr14: number;
  volume_ratio: number;
}

interface Pattern {
  stock_code: string;
  pattern_type: string;
  pattern_status: string;
  target_price: number;
  stop_loss: number;
  confidence: number;
  key_points_json: any;
  start_date: string;
  confirm_date: string;
}

interface BacktestResult {
  backtest_id?: string;
  stock_code: string;
  strategy_type: string;
  annualized_return: number;
  sharpe_ratio: number;
  max_drawdown: number;
  win_rate: number;
  trade_count: number;
}

interface TradeDetail {
  entry_date: string;
  exit_date: string;
  entry_price: number;
  exit_price: number;
  return_pct: number;
  profit_loss: number;
  holding_days: number;
  exit_reason: string;
}

interface TechnicalReport {
  report_id: string;
  stock_code: string;
  stock_name: string;
  report_date: string;
  technical_score: number;
  trend_direction: string;
  signal_strength: string;
  trend_analysis: string;
  pattern_analysis: string;
  indicator_analysis: string;
  volume_analysis: string;
  support_resistance: string;
  trading_suggestion: string;
  risk_warning: string;
}

export default function TechnicalAnalyst() {
  const [stockCode, setStockCode] = useState('600519');
  const [period, setPeriod] = useState('daily');
  const [backtestYears, setBacktestYears] = useState(3); // 回测年限
  const [loading, setLoading] = useState(false);

  // 数据状态
  const [indicators, setIndicators] = useState<TechnicalIndicator[]>([]);
  const [patterns, setPatterns] = useState<Pattern[]>([]);
  const [backtestResults, setBacktestResults] = useState<BacktestResult[]>([]);
  const [report, setReport] = useState<TechnicalReport | null>(null);
  const [tradeDetails, setTradeDetails] = useState<TradeDetail[]>([]);

  // 模态框状态
  const [reportModalVisible, setReportModalVisible] = useState(false);
  const [backtestModalVisible, setBacktestModalVisible] = useState(false);
  const [tradeDetailModalVisible, setTradeDetailModalVisible] = useState(false);
  const [selectedStrategy, setSelectedStrategy] = useState<BacktestResult | null>(null);

  // 查询技术指标
  const fetchIndicators = async () => {
    setLoading(true);
    try {
      const response = await api.get('/technical/indicators', {
        params: { code: stockCode, period, limit: 60 }
      });
      setIndicators(response.data.data || []);
      message.success('技术指标加载成功');
    } catch (error: any) {
      message.error(error.response?.data?.detail || '加载失败');
    } finally {
      setLoading(false);
    }
  };

  // 查询技术形态
  const fetchPatterns = async () => {
    setLoading(true);
    try {
      const response = await api.get('/technical/patterns', {
        params: { code: stockCode }
      });
      setPatterns(response.data.data || []);
      message.success('技术形态加载成功');
    } catch (error: any) {
      message.error(error.response?.data?.detail || '加载失败');
    } finally {
      setLoading(false);
    }
  };

  // 策略回测
  const runBacktest = async () => {
    setLoading(true);
    setBacktestModalVisible(true);
    try {
      // 动态计算日期范围
      const endDate = new Date();
      const startDate = new Date();
      startDate.setFullYear(endDate.getFullYear() - backtestYears);

      // 格式化为 YYYY-MM-DD
      const formatDate = (date: Date) => {
        return date.toISOString().split('T')[0];
      };

      const response = await api.post('/technical/backtest/batch', null, {
        params: {
          codes: stockCode,
          strategies: 'ma_cross,macd,rsi,kdj,ma_macd_combined,triple_combined',
          start_date: formatDate(startDate),
          end_date: formatDate(endDate),
          period: period,
          top_n: 10
        }
      });
      setBacktestResults(response.data.top_strategies || []);
      message.success('策略回测完成');
    } catch (error: any) {
      message.error(error.response?.data?.detail || '回测失败');
    } finally {
      setLoading(false);
    }
  };

  // 生成LLM报告
  const generateReport = async () => {
    setLoading(true);
    setReportModalVisible(true);
    try {
      const response = await api.post('/technical/report/generate', null, {
        params: { code: stockCode, period, llm_model: 'gpt-3.5-turbo' }
      });
      setReport(response.data);
      message.success('技术分析报告生成成功');
    } catch (error: any) {
      message.error(error.response?.data?.detail || '报告生成失败');
      setReportModalVisible(false);
    } finally {
      setLoading(false);
    }
  };

  // 同步计算指标
  const syncIndicators = async () => {
    setLoading(true);
    try {
      await api.post('/technical/sync/indicators', null, {
        params: { codes: stockCode, period }
      });
      message.success('技术指标计算完成');
      fetchIndicators();
    } catch (error: any) {
      message.error(error.response?.data?.detail || '计算失败');
      setLoading(false);
    }
  };

  // 识别形态
  const syncPatterns = async () => {
    setLoading(true);
    try {
      await api.post('/technical/sync/patterns', null, {
        params: { codes: stockCode }
      });
      message.success('技术形态识别完成');
      fetchPatterns();
    } catch (error: any) {
      message.error(error.response?.data?.detail || '识别失败');
      setLoading(false);
    }
  };

  // 查询交易明细
  const fetchTradeDetails = async (result: BacktestResult) => {
    if (!result.backtest_id) {
      message.error('回测ID不存在');
      return;
    }

    setLoading(true);
    setSelectedStrategy(result);
    try {
      const response = await api.get('/technical/backtest/trades', {
        params: {
          backtest_id: result.backtest_id,
          code: result.stock_code,
          strategy: result.strategy_type,
          period: period
        }
      });
      setTradeDetails(response.data.trades || []);
      setTradeDetailModalVisible(true);
    } catch (error: any) {
      message.error(error.response?.data?.detail || '加载交易明细失败');
    } finally {
      setLoading(false);
    }
  };

  // 渲染指标图表
  const renderIndicatorChart = () => {
    if (indicators.length === 0) return null;

    const dates = indicators.map(item => item.trade_date).reverse();
    const ma5 = indicators.map(item => item.ma5).reverse();
    const ma20 = indicators.map(item => item.ma20).reverse();
    const ma60 = indicators.map(item => item.ma60).reverse();

    const option = {
      title: { text: '均线走势', left: 'center' },
      tooltip: { trigger: 'axis' },
      legend: { data: ['MA5', 'MA20', 'MA60'], top: 30 },
      grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
      xAxis: { type: 'category', data: dates, boundaryGap: false },
      yAxis: { type: 'value' },
      series: [
        { name: 'MA5', type: 'line', data: ma5, smooth: true, lineStyle: { color: '#1890ff' } },
        { name: 'MA20', type: 'line', data: ma20, smooth: true, lineStyle: { color: '#52c41a' } },
        { name: 'MA60', type: 'line', data: ma60, smooth: true, lineStyle: { color: '#faad14' } },
      ]
    };

    return <ReactECharts option={option} style={{ height: '400px' }} />;
  };

  // 渲染MACD图表
  const renderMACDChart = () => {
    if (indicators.length === 0) return null;

    const dates = indicators.map(item => item.trade_date).reverse();
    const dif = indicators.map(item => item.macd_dif).reverse();
    const dea = indicators.map(item => item.macd_dea).reverse();
    const bar = indicators.map(item => item.macd_bar).reverse();

    const option = {
      title: { text: 'MACD 指标', left: 'center' },
      tooltip: { trigger: 'axis' },
      legend: { data: ['DIF', 'DEA', 'MACD'], top: 30 },
      grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
      xAxis: { type: 'category', data: dates, boundaryGap: false },
      yAxis: { type: 'value' },
      series: [
        { name: 'DIF', type: 'line', data: dif, lineStyle: { color: '#1890ff' } },
        { name: 'DEA', type: 'line', data: dea, lineStyle: { color: '#52c41a' } },
        {
          name: 'MACD',
          type: 'bar',
          data: bar,
          itemStyle: {
            color: (params: any) => params.value >= 0 ? '#ff4d4f' : '#52c41a'
          }
        }
      ]
    };

    return <ReactECharts option={option} style={{ height: '350px' }} />;
  };

  // 渲染RSI和KDJ图表
  const renderOscillatorChart = () => {
    if (indicators.length === 0) return null;

    const dates = indicators.map(item => item.trade_date).reverse();
    const rsi = indicators.map(item => item.rsi14).reverse();
    const kdjK = indicators.map(item => item.kdj_k).reverse();
    const kdjD = indicators.map(item => item.kdj_d).reverse();
    const kdjJ = indicators.map(item => item.kdj_j).reverse();

    const option = {
      title: { text: 'RSI & KDJ 指标', left: 'center' },
      tooltip: { trigger: 'axis' },
      legend: { data: ['RSI14', 'KDJ-K', 'KDJ-D', 'KDJ-J'], top: 30 },
      grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
      xAxis: { type: 'category', data: dates, boundaryGap: false },
      yAxis: { type: 'value', min: 0, max: 100 },
      series: [
        { name: 'RSI14', type: 'line', data: rsi, smooth: true, lineStyle: { color: '#722ed1' } },
        { name: 'KDJ-K', type: 'line', data: kdjK, smooth: true, lineStyle: { color: '#1890ff' } },
        { name: 'KDJ-D', type: 'line', data: kdjD, smooth: true, lineStyle: { color: '#52c41a' } },
        { name: 'KDJ-J', type: 'line', data: kdjJ, smooth: true, lineStyle: { color: '#faad14' } },
      ],
      markLine: {
        silent: true,
        data: [
          { yAxis: 20, lineStyle: { color: '#52c41a', type: 'dashed' } },
          { yAxis: 30, lineStyle: { color: '#52c41a', type: 'dashed' } },
          { yAxis: 70, lineStyle: { color: '#ff4d4f', type: 'dashed' } },
          { yAxis: 80, lineStyle: { color: '#ff4d4f', type: 'dashed' } },
        ]
      }
    };

    return <ReactECharts option={option} style={{ height: '350px' }} />;
  };

  // 形态类型中文映射
  const patternTypeMap: any = {
    'head_shoulders_top': '头肩顶',
    'double_bottom': '双底',
    'double_top': '双顶',
    'ascending_triangle': '上升三角形',
    'descending_triangle': '下降三角形'
  };

  // 形态状态颜色
  const patternStatusColor: any = {
    'forming': 'warning',
    'confirmed': 'success',
    'broken': 'error'
  };

  // 策略类型中文映射
  const strategyTypeMap: any = {
    'ma_cross': '均线交叉',
    'macd': 'MACD金叉',
    'rsi': 'RSI超买超卖',
    'kdj': 'KDJ超买超卖',
    'boll': '布林带突破',
    'ma_macd_combined': '均线+MACD组合',
    'triple_combined': '三重组合策略'
  };

  // 趋势方向图标
  const trendIcon: any = {
    'bullish': <RiseOutlined style={{ color: '#52c41a', fontSize: 20 }} />,
    'bearish': <FallOutlined style={{ color: '#ff4d4f', fontSize: 20 }} />,
    'neutral': <LineChartOutlined style={{ color: '#faad14', fontSize: 20 }} />
  };

  const trendText: any = {
    'bullish': '看涨',
    'bearish': '看跌',
    'neutral': '震荡'
  };

  return (
    <div style={{ padding: '24px' }}>
      {/* 顶部搜索栏 */}
      <Card style={{ marginBottom: 16 }}>
        <Space size="large" style={{ width: '100%', justifyContent: 'space-between' }}>
          <Space size="middle">
            <Search
              placeholder="请输入股票代码"
              value={stockCode}
              onChange={e => setStockCode(e.target.value)}
              onSearch={fetchIndicators}
              style={{ width: 200 }}
              enterButton={<SearchOutlined />}
            />
            <Select value={period} onChange={setPeriod} style={{ width: 120 }}>
              <Option value="daily">日线</Option>
              <Option value="weekly">周线</Option>
              <Option value="monthly">月线</Option>
            </Select>
          </Space>
          <Space>
            <Button
              type="primary"
              icon={<SyncOutlined />}
              onClick={syncIndicators}
              loading={loading}
            >
              计算指标
            </Button>
            <Button
              icon={<ThunderboltOutlined />}
              onClick={syncPatterns}
              loading={loading}
            >
              识别形态
            </Button>
            <Button
              icon={<BarChartOutlined />}
              onClick={runBacktest}
              loading={loading}
            >
              策略回测
            </Button>
            <Button
              type="primary"
              icon={<FileTextOutlined />}
              onClick={generateReport}
              loading={loading}
              style={{ background: '#722ed1' }}
            >
              生成报告
            </Button>
          </Space>
        </Space>
      </Card>

      {/* 主内容区 */}
      <Tabs defaultActiveKey="1">
        {/* Tab 1: 技术指标 */}
        <TabPane tab={<span><LineChartOutlined />技术指标</span>} key="1">
          {loading && <Spin tip="加载中..." style={{ display: 'block', margin: '50px auto' }} />}

          {!loading && indicators.length === 0 && (
            <Empty
              description="暂无数据，请输入股票代码并点击「计算指标」"
              style={{ marginTop: 50 }}
            />
          )}

          {indicators.length > 0 && (
            <>
              {/* 最新指标卡片 */}
              <Card title="最新技术指标" style={{ marginBottom: 16 }}>
                <Row gutter={16}>
                  <Col span={3}>
                    <Statistic
                      title="MA5"
                      value={indicators[0]?.ma5}
                      precision={2}
                      valueStyle={{ color: '#1890ff' }}
                    />
                  </Col>
                  <Col span={3}>
                    <Statistic
                      title="MA20"
                      value={indicators[0]?.ma20}
                      precision={2}
                      valueStyle={{ color: '#52c41a' }}
                    />
                  </Col>
                  <Col span={3}>
                    <Statistic
                      title="MA60"
                      value={indicators[0]?.ma60}
                      precision={2}
                      valueStyle={{ color: '#faad14' }}
                    />
                  </Col>
                  <Col span={3}>
                    <Statistic
                      title="RSI14"
                      value={indicators[0]?.rsi14}
                      precision={2}
                      suffix={
                        indicators[0]?.rsi14 < 30 ? <Tag color="green">超卖</Tag> :
                        indicators[0]?.rsi14 > 70 ? <Tag color="red">超买</Tag> :
                        <Tag>正常</Tag>
                      }
                    />
                  </Col>
                  <Col span={4}>
                    <Statistic
                      title="MACD"
                      value={indicators[0]?.macd_dif}
                      precision={4}
                      suffix={
                        indicators[0]?.macd_dif > indicators[0]?.macd_dea ?
                        <Tag color="red">金叉</Tag> : <Tag color="green">死叉</Tag>
                      }
                    />
                  </Col>
                  <Col span={3}>
                    <Statistic
                      title="KDJ-J"
                      value={indicators[0]?.kdj_j}
                      precision={2}
                      suffix={
                        indicators[0]?.kdj_j < 20 ? <Tag color="green">超卖</Tag> :
                        indicators[0]?.kdj_j > 80 ? <Tag color="red">超买</Tag> :
                        <Tag>正常</Tag>
                      }
                    />
                  </Col>
                  <Col span={3}>
                    <Statistic
                      title="ATR14"
                      value={indicators[0]?.atr14}
                      precision={2}
                    />
                  </Col>
                  <Col span={2}>
                    <Statistic
                      title="量比"
                      value={indicators[0]?.volume_ratio}
                      precision={2}
                    />
                  </Col>
                </Row>
              </Card>

              {/* 图表区域 */}
              <Row gutter={16}>
                <Col span={24}>
                  <Card style={{ marginBottom: 16 }}>
                    {renderIndicatorChart()}
                  </Card>
                </Col>
                <Col span={12}>
                  <Card style={{ marginBottom: 16 }}>
                    {renderMACDChart()}
                  </Card>
                </Col>
                <Col span={12}>
                  <Card style={{ marginBottom: 16 }}>
                    {renderOscillatorChart()}
                  </Card>
                </Col>
              </Row>
            </>
          )}
        </TabPane>

        {/* Tab 2: 技术形态 */}
        <TabPane tab={<span><ThunderboltOutlined />技术形态</span>} key="2">
          {loading && <Spin tip="识别中..." style={{ display: 'block', margin: '50px auto' }} />}

          {!loading && patterns.length === 0 && (
            <Empty
              description="暂无识别到的技术形态，请点击「识别形态」"
              style={{ marginTop: 50 }}
            />
          )}

          {patterns.length > 0 && (
            <Table
              dataSource={patterns}
              rowKey="id"
              pagination={{ pageSize: 10 }}
              columns={[
                {
                  title: '形态类型',
                  dataIndex: 'pattern_type',
                  render: (text) => (
                    <Tag color="blue" style={{ fontSize: 14 }}>
                      {patternTypeMap[text] || text}
                    </Tag>
                  )
                },
                {
                  title: '状态',
                  dataIndex: 'pattern_status',
                  render: (text) => (
                    <Badge
                      status={text === 'confirmed' ? 'success' : text === 'forming' ? 'processing' : 'error'}
                      text={text === 'confirmed' ? '已确认' : text === 'forming' ? '形成中' : '已破坏'}
                    />
                  )
                },
                {
                  title: '开始日期',
                  dataIndex: 'start_date',
                  sorter: (a, b) => a.start_date.localeCompare(b.start_date)
                },
                {
                  title: '确认日期',
                  dataIndex: 'confirm_date',
                  render: (text) => text || '-'
                },
                {
                  title: '目标价',
                  dataIndex: 'target_price',
                  render: (text) => <span style={{ color: '#52c41a', fontWeight: 'bold' }}>¥{text?.toFixed(2)}</span>
                },
                {
                  title: '止损位',
                  dataIndex: 'stop_loss',
                  render: (text) => <span style={{ color: '#ff4d4f' }}>¥{text?.toFixed(2)}</span>
                },
                {
                  title: '置信度',
                  dataIndex: 'confidence',
                  render: (text) => (
                    <Progress
                      percent={parseFloat((text * 100).toFixed(0))}
                      size="small"
                      status={text >= 0.8 ? 'success' : text >= 0.6 ? 'normal' : 'exception'}
                    />
                  )
                }
              ]}
            />
          )}
        </TabPane>

        {/* Tab 3: 策略回测 */}
        <TabPane tab={<span><TrophyOutlined />策略回测</span>} key="3">
          {!loading && backtestResults.length === 0 && (
            <>
              <Space direction="vertical" size="large" style={{ width: '100%' }}>
                <Card size="small">
                  <Space>
                    <span>回测周期：</span>
                    <Select value={backtestYears} onChange={setBacktestYears} style={{ width: 120 }}>
                      <Option value={1}>最近1年</Option>
                      <Option value={2}>最近2年</Option>
                      <Option value={3}>最近3年</Option>
                      <Option value={5}>最近5年</Option>
                    </Select>
                    <span style={{ color: '#999', fontSize: 12 }}>
                      截止时间：今天
                    </span>
                  </Space>
                </Card>
                <Empty
                  description="点击「策略回测」查看历史表现"
                  style={{ marginTop: 20 }}
                />
              </Space>
            </>
          )}

          {backtestResults.length > 0 && (
            <>
              <Alert
                message="回测说明"
                description={`回测区间: 最近${backtestYears}年 | 周期: ${period === 'daily' ? '日线' : period === 'weekly' ? '周线' : '月线'} | 已测试 ${backtestResults.length} 个策略`}
                type="info"
                showIcon
                style={{ marginBottom: 16 }}
              />

              <Table
                dataSource={backtestResults}
                rowKey={(record) => `${record.stock_code}-${record.strategy_type}`}
                pagination={false}
                columns={[
                  {
                    title: '排名',
                    render: (_, __, index) => (
                      index === 0 ? <TrophyOutlined style={{ color: '#faad14', fontSize: 18 }} /> :
                      index === 1 ? <TrophyOutlined style={{ color: '#bfbfbf', fontSize: 16 }} /> :
                      index === 2 ? <TrophyOutlined style={{ color: '#d48806', fontSize: 14 }} /> :
                      <span>{index + 1}</span>
                    )
                  },
                  {
                    title: '策略类型',
                    dataIndex: 'strategy_type',
                    render: (text) => (
                      <Tag color="cyan" style={{ fontSize: 14 }}>
                        {strategyTypeMap[text] || text}
                      </Tag>
                    )
                  },
                  {
                    title: '年化收益',
                    dataIndex: 'annualized_return',
                    render: (text) => (
                      <span style={{
                        color: text >= 0 ? '#52c41a' : '#ff4d4f',
                        fontWeight: 'bold',
                        fontSize: 16
                      }}>
                        {(text * 100).toFixed(2)}%
                      </span>
                    ),
                    sorter: (a, b) => a.annualized_return - b.annualized_return,
                    defaultSortOrder: 'descend'
                  },
                  {
                    title: '夏普比率',
                    dataIndex: 'sharpe_ratio',
                    render: (text) => text?.toFixed(2) || '-',
                    sorter: (a, b) => (a.sharpe_ratio || 0) - (b.sharpe_ratio || 0)
                  },
                  {
                    title: '最大回撤',
                    dataIndex: 'max_drawdown',
                    render: (text) => (
                      <span style={{ color: '#ff4d4f' }}>
                        {(text * 100).toFixed(2)}%
                      </span>
                    )
                  },
                  {
                    title: '胜率',
                    dataIndex: 'win_rate',
                    render: (text) => (
                      <Progress
                        percent={parseFloat((text * 100).toFixed(0))}
                        size="small"
                        status={text >= 0.6 ? 'success' : 'normal'}
                      />
                    )
                  },
                  {
                    title: '交易次数',
                    dataIndex: 'trade_count',
                    render: (count: number, record: BacktestResult) => (
                      <a onClick={() => fetchTradeDetails(record)} style={{ color: '#1890ff' }}>
                        {count} 笔
                      </a>
                    )
                  }
                ]}
              />
            </>
          )}
        </TabPane>
      </Tabs>

      {/* 回测结果模态框 */}
      <Modal
        title="策略回测结果"
        open={backtestModalVisible}
        onCancel={() => setBacktestModalVisible(false)}
        footer={null}
        width={1000}
      >
        {loading ? (
          <Spin tip="回测中，请稍候..." style={{ display: 'block', margin: '50px auto' }} />
        ) : backtestResults.length > 0 ? (
          <>
            <Alert
              message={`最佳策略: ${strategyTypeMap[backtestResults[0]?.strategy_type]} | 年化收益: ${(backtestResults[0]?.annualized_return * 100).toFixed(2)}%`}
              type="success"
              showIcon
              style={{ marginBottom: 16 }}
            />
            <Table
              dataSource={backtestResults}
              rowKey={(record) => record.strategy_type}
              pagination={false}
              size="small"
              columns={[
                { title: '策略', dataIndex: 'strategy_type', render: (text) => strategyTypeMap[text] },
                { title: '年化收益', dataIndex: 'annualized_return', render: (text) => `${(text * 100).toFixed(2)}%` },
                { title: '夏普', dataIndex: 'sharpe_ratio', render: (text) => text?.toFixed(2) },
                { title: '回撤', dataIndex: 'max_drawdown', render: (text) => `${(text * 100).toFixed(2)}%` },
                { title: '胜率', dataIndex: 'win_rate', render: (text) => `${(text * 100).toFixed(0)}%` },
                {
                  title: '交易次数',
                  dataIndex: 'trade_count',
                  render: (count: number, record: BacktestResult) => (
                    <a onClick={() => fetchTradeDetails(record)} style={{ color: '#1890ff' }}>
                      {count} 笔
                    </a>
                  )
                },
              ]}
            />
          </>
        ) : null}
      </Modal>

      {/* LLM 报告模态框 */}
      <Modal
        title={
          <Space>
            <FileTextOutlined style={{ color: '#722ed1' }} />
            <span>技术分析报告</span>
            {report && (
              <Tag color={report.trend_direction === 'bullish' ? 'green' : report.trend_direction === 'bearish' ? 'red' : 'orange'}>
                {trendText[report.trend_direction]}
              </Tag>
            )}
          </Space>
        }
        open={reportModalVisible}
        onCancel={() => setReportModalVisible(false)}
        footer={null}
        width={900}
      >
        {loading ? (
          <Spin tip="正在生成分析报告..." style={{ display: 'block', margin: '50px auto' }} />
        ) : report ? (
          <>
            {/* 报告头部 */}
            <Card style={{ marginBottom: 16, background: '#f0f2f5' }}>
              <Row gutter={16}>
                <Col span={6}>
                  <Statistic
                    title="股票"
                    value={`${report.stock_name}(${report.stock_code})`}
                    valueStyle={{ fontSize: 16 }}
                  />
                </Col>
                <Col span={6}>
                  <Statistic
                    title="技术评分"
                    value={report.technical_score}
                    suffix="/ 100"
                    valueStyle={{
                      color: report.technical_score >= 80 ? '#52c41a' : report.technical_score >= 60 ? '#faad14' : '#ff4d4f'
                    }}
                  />
                </Col>
                <Col span={6}>
                  <div style={{ textAlign: 'center' }}>
                    <div style={{ color: '#8c8c8c', fontSize: 14, marginBottom: 8 }}>趋势方向</div>
                    <div>{trendIcon[report.trend_direction]} <span style={{ marginLeft: 8, fontSize: 16 }}>{trendText[report.trend_direction]}</span></div>
                  </div>
                </Col>
                <Col span={6}>
                  <Statistic
                    title="信号强度"
                    value={report.signal_strength === 'strong' ? '强' : report.signal_strength === 'medium' ? '中' : '弱'}
                    valueStyle={{
                      color: report.signal_strength === 'strong' ? '#52c41a' : report.signal_strength === 'medium' ? '#faad14' : '#ff4d4f'
                    }}
                  />
                </Col>
              </Row>
            </Card>

            {/* 报告内容 */}
            <div style={{ maxHeight: '600px', overflowY: 'auto' }}>
              <Divider orientation="left">趋势分析</Divider>
              <div style={{ padding: '0 16px', lineHeight: 1.8 }}>
                <ReactMarkdown>{report.trend_analysis}</ReactMarkdown>
              </div>

              <Divider orientation="left">形态分析</Divider>
              <div style={{ padding: '0 16px', lineHeight: 1.8 }}>
                <ReactMarkdown>{report.pattern_analysis}</ReactMarkdown>
              </div>

              <Divider orientation="left">指标分析</Divider>
              <div style={{ padding: '0 16px', lineHeight: 1.8 }}>
                <ReactMarkdown>{report.indicator_analysis}</ReactMarkdown>
              </div>

              <Divider orientation="left">成交量分析</Divider>
              <div style={{ padding: '0 16px', lineHeight: 1.8 }}>
                <ReactMarkdown>{report.volume_analysis}</ReactMarkdown>
              </div>

              <Divider orientation="left">支撑与阻力</Divider>
              <div style={{ padding: '0 16px', lineHeight: 1.8 }}>
                <ReactMarkdown>{report.support_resistance}</ReactMarkdown>
              </div>

              <Divider orientation="left">交易建议</Divider>
              <Alert
                message={<ReactMarkdown>{report.trading_suggestion}</ReactMarkdown>}
                type="success"
                showIcon
                style={{ marginBottom: 16 }}
              />

              <Divider orientation="left">风险提示</Divider>
              <Alert
                message={<ReactMarkdown>{report.risk_warning}</ReactMarkdown>}
                type="warning"
                showIcon
              />
            </div>
          </>
        ) : null}
      </Modal>

      {/* 交易明细模态框 */}
      <Modal
        title={
          selectedStrategy
            ? `${strategyTypeMap[selectedStrategy.strategy_type]} - 交易明细 (${selectedStrategy.stock_code})`
            : '交易明细'
        }
        open={tradeDetailModalVisible}
        onCancel={() => setTradeDetailModalVisible(false)}
        footer={null}
        width={1200}
      >
        {tradeDetails.length > 0 ? (
          <>
            {/* 交易统计 */}
            <Row gutter={16} style={{ marginBottom: 24 }}>
              <Col span={6}>
                <Statistic
                  title="总交易次数"
                  value={tradeDetails.length}
                  suffix="笔"
                />
              </Col>
              <Col span={6}>
                <Statistic
                  title="盈利次数"
                  value={tradeDetails.filter(t => t.return_pct > 0).length}
                  suffix="笔"
                  valueStyle={{ color: '#cf1322' }}
                />
              </Col>
              <Col span={6}>
                <Statistic
                  title="亏损次数"
                  value={tradeDetails.filter(t => t.return_pct < 0).length}
                  suffix="笔"
                  valueStyle={{ color: '#3f8600' }}
                />
              </Col>
              <Col span={6}>
                <Statistic
                  title="总盈亏"
                  value={tradeDetails.reduce((sum, t) => sum + t.profit_loss, 0).toFixed(2)}
                  prefix="¥"
                  valueStyle={{
                    color: tradeDetails.reduce((sum, t) => sum + t.profit_loss, 0) >= 0 ? '#cf1322' : '#3f8600'
                  }}
                />
              </Col>
            </Row>

            {/* 收益率分布图 */}
            <ReactECharts
              option={{
                title: { text: '交易收益率分布', left: 'center' },
                tooltip: {
                  trigger: 'axis',
                  axisPointer: { type: 'shadow' },
                  formatter: (params: any) => {
                    const data = params[0];
                    const trade = tradeDetails[data.dataIndex];
                    return `
                      <b>${trade.entry_date} → ${trade.exit_date}</b><br/>
                      收益率: ${(trade.return_pct * 100).toFixed(2)}%<br/>
                      盈亏: ¥${trade.profit_loss.toFixed(2)}<br/>
                      持仓: ${trade.holding_days}天
                    `;
                  }
                },
                xAxis: {
                  type: 'category',
                  data: tradeDetails.map((_, i) => `T${i + 1}`),
                  axisLabel: { rotate: 45 }
                },
                yAxis: {
                  type: 'value',
                  name: '收益率 (%)',
                  axisLabel: { formatter: '{value}%' }
                },
                series: [
                  {
                    type: 'bar',
                    data: tradeDetails.map(t => (t.return_pct * 100).toFixed(2)),
                    itemStyle: {
                      color: (params: any) => {
                        return tradeDetails[params.dataIndex].return_pct >= 0 ? '#cf1322' : '#3f8600';
                      }
                    }
                  }
                ],
                grid: { left: '3%', right: '4%', bottom: '15%', containLabel: true }
              }}
              style={{ height: '350px', marginBottom: 24 }}
            />

            {/* 交易明细表格 */}
            <Table
              dataSource={tradeDetails}
              rowKey={(record, index) => `${index}`}
              pagination={{ pageSize: 10 }}
              size="small"
              columns={[
                {
                  title: '序号',
                  render: (_: any, __: any, index: number) => index + 1,
                  width: 60
                },
                {
                  title: '买入日期',
                  dataIndex: 'entry_date',
                  width: 110
                },
                {
                  title: '买入价',
                  dataIndex: 'entry_price',
                  render: (val: number) => `¥${val.toFixed(2)}`,
                  width: 90
                },
                {
                  title: '卖出日期',
                  dataIndex: 'exit_date',
                  width: 110
                },
                {
                  title: '卖出价',
                  dataIndex: 'exit_price',
                  render: (val: number) => `¥${val.toFixed(2)}`,
                  width: 90
                },
                {
                  title: '持仓天数',
                  dataIndex: 'holding_days',
                  render: (val: number) => `${val}天`,
                  width: 90
                },
                {
                  title: '收益率',
                  dataIndex: 'return_pct',
                  render: (val: number) => (
                    <span style={{ color: val >= 0 ? '#cf1322' : '#3f8600', fontWeight: 'bold' }}>
                      {val >= 0 ? '+' : ''}{(val * 100).toFixed(2)}%
                    </span>
                  ),
                  sorter: (a, b) => a.return_pct - b.return_pct,
                  width: 100
                },
                {
                  title: '盈亏金额',
                  dataIndex: 'profit_loss',
                  render: (val: number) => (
                    <span style={{ color: val >= 0 ? '#cf1322' : '#3f8600' }}>
                      ¥{val >= 0 ? '+' : ''}{val.toFixed(2)}
                    </span>
                  ),
                  sorter: (a, b) => a.profit_loss - b.profit_loss,
                  width: 100
                },
                {
                  title: '退出原因',
                  dataIndex: 'exit_reason',
                  render: (val: string) => {
                    const reasonMap: any = {
                      signal_exit: '信号退出',
                      stop_loss: '止损',
                      take_profit: '止盈',
                      manual_or_other: '其他'
                    };
                    return <Tag>{reasonMap[val] || val}</Tag>;
                  }
                }
              ]}
            />
          </>
        ) : (
          <Empty description="暂无交易明细" />
        )}
      </Modal>
    </div>
  );
}

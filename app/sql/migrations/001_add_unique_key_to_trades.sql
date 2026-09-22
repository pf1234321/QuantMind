-- 为交易明细表添加唯一索引，防止重复插入
-- 执行前先清理已有的重复数据

-- 1. 删除重复记录（保留最早的那条）
DELETE t1 FROM trade_technical_trades t1
INNER JOIN trade_technical_trades t2
WHERE t1.id > t2.id
  AND t1.backtest_id = t2.backtest_id
  AND t1.stock_code = t2.stock_code
  AND t1.strategy_type = t2.strategy_type
  AND t1.period = t2.period
  AND t1.entry_date = t2.entry_date
  AND t1.exit_date = t2.exit_date;

-- 2. 添加唯一索引
ALTER TABLE trade_technical_trades
ADD UNIQUE KEY `uk_trade_unique` (
  `backtest_id`,
  `stock_code`,
  `strategy_type`,
  `period`,
  `entry_date`,
  `exit_date`
);

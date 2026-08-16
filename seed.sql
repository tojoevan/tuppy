-- Tuppy v0.1 种子规则
-- 原则：预置常见家庭规则，没数据的安静躺着（匹配不到 = 沉默），
--       录到什么数据，什么规则自然激活。全触发也有限额 3 条/班兜底。
-- gap(缺测)：激活前提 = 该域+分类有 ≥1 条数据，且从首条录入日起算（冷启动保护）。

INSERT INTO rules (kind, domain, category, template, params, priority) VALUES
-- 冲突：日程域时间重叠
('detection', '日程', '', 'overlap',
 '{"check_between":"same_person","min_overlap_min":0}', 5),
-- 突变：金额环比
('detection', '账本', '电费', 'surge',
 '{"compare":"prev_month","ratio":1.3,"min_history_days":30,"min_amount":50}', 5),
-- 到期：非周期性（录一次提醒一次）
('detection', '物品', '', 'expiry',
 '{"days_before":2,"recurring":false}', 4),
('detection', '信用卡', '', 'expiry',
 '{"days_before":2,"recurring":false}', 5),
('detection', '证件', '', 'expiry',
 '{"days_before":30,"recurring":false}', 4),
('detection', '孩子', '疫苗', 'expiry',
 '{"days_before":7,"recurring":false}', 5),
-- 到期：周期性缴费/事务（到期自动顺延周期）
('detection', '缴费', '水费', 'expiry',
 '{"days_before":3,"recurring":true,"period_days":30}', 5),
('detection', '缴费', '燃气', 'expiry',
 '{"days_before":3,"recurring":true,"period_days":60}', 5),
('detection', '缴费', '物业', 'expiry',
 '{"days_before":7,"recurring":true,"period_days":90}', 5),
('detection', '车辆', '保养', 'expiry',
 '{"days_before":14,"recurring":true,"period_days":180}', 4),
('detection', '车辆', '保险', 'expiry',
 '{"days_before":14,"recurring":true,"period_days":365}', 4),
('detection', '车辆', '年检', 'expiry',
 '{"days_before":14,"recurring":true,"period_days":365}', 4),
('detection', '宠物', '驱虫', 'expiry',
 '{"days_before":3,"recurring":true,"period_days":30}', 4),
-- 缺测：规律记录断了提醒
('habit', '健康', '体重', 'gap',
 '{"frequency":"weekly","max_gap":1}', 4),
('habit', '健康', '吃药', 'gap',
 '{"frequency":"daily","max_gap":1}', 5);

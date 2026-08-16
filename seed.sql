-- Tuppy v0.1 种子规则：覆盖用户真实有的数据域
-- 冲突(日程) / 突变(电费) / 到期(物品/信用卡)
-- 缺测(gap) 模板已实现但暂不激活——需等用户有真实规律数据源再建

INSERT INTO rules (kind, domain, category, template, params, priority) VALUES
('detection', '日程', '', 'overlap',
 '{"check_between":"same_person","min_overlap_min":0}', 5),
('detection', '账本', '电费', 'surge',
 '{"compare":"prev_month","ratio":1.3,"min_history_days":30,"min_amount":50}', 5),
('detection', '物品', '', 'expiry',
 '{"days_before":2,"recurring":false}', 4),
('detection', '信用卡', '', 'expiry',
 '{"days_before":2,"recurring":false}', 5);

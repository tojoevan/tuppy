-- 生成物：由 scripts/sync_rules.py 从 tuppy-rules/rules.json 生成
-- 不要手改本文件。改规则去 tuppy-rules 仓库，跑 sync_rules.py 重新生成。

INSERT INTO rules (kind, domain, category, template, params, priority) VALUES
('detection', '日程', '', 'overlap', '{"check_between": "same_person", "min_overlap_min": 0}', 5),
('detection', '账本', '电费', 'surge', '{"compare": "prev_month", "ratio": 1.3, "min_history_days": 30, "min_amount": 50}', 5),
('detection', '物品', '', 'expiry', '{"days_before": 2, "recurring": false}', 4),
('detection', '信用卡', '', 'expiry', '{"days_before": 2, "recurring": false}', 5),
('detection', '证件', '', 'expiry', '{"days_before": 30, "recurring": false}', 4),
('detection', '孩子', '疫苗', 'expiry', '{"days_before": 7, "recurring": false}', 5),
('detection', '缴费', '水费', 'expiry', '{"days_before": 3, "recurring": true, "period_days": 30}', 5),
('detection', '缴费', '燃气', 'expiry', '{"days_before": 3, "recurring": true, "period_days": 60}', 5),
('detection', '缴费', '物业', 'expiry', '{"days_before": 7, "recurring": true, "period_days": 90}', 5),
('detection', '车辆', '保养', 'expiry', '{"days_before": 14, "recurring": true, "period_days": 180}', 4),
('detection', '车辆', '保险', 'expiry', '{"days_before": 14, "recurring": true, "period_days": 365}', 4),
('detection', '车辆', '年检', 'expiry', '{"days_before": 14, "recurring": true, "period_days": 365}', 4),
('detection', '宠物', '驱虫', 'expiry', '{"days_before": 3, "recurring": true, "period_days": 30}', 4),
('habit', '健康', '体重', 'gap', '{"frequency": "weekly", "max_gap": 1}', 4),
('habit', '健康', '吃药', 'gap', '{"frequency": "daily", "max_gap": 1}', 5),
('habit', '健康', '胰岛素', 'gap', '{"frequency": "weekly", "max_gap": 1}', 5);

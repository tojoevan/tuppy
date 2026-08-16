-- Tuppy v0.1 schema
-- 参照 docs/v0.1-design.md §3。六张主表 + rule_log + import_staging。

CREATE TABLE IF NOT EXISTS entries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  domain TEXT NOT NULL,               -- 自由文本：健康/日程/账本/物品/疫苗/...
  category TEXT NOT NULL DEFAULT '',  -- 域内分类：血压/电费/食品/...
  person TEXT NOT NULL DEFAULT '',
  happened_at TEXT NOT NULL,          -- 事件时间（支出日/开始/测量时/到期日）
  ended_at TEXT,
  amount REAL,
  value TEXT,                         -- 统一 TEXT，解析方式由 habit 规则声明
  title TEXT NOT NULL DEFAULT '',
  note TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'open',   -- open/notified/done/cancelled
  source TEXT NOT NULL DEFAULT 'manual', -- manual/import
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS rules (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,                 -- habit | detection
  domain TEXT NOT NULL,
  category TEXT NOT NULL DEFAULT '',
  template TEXT NOT NULL,             -- gap | overlap | surge | expiry
  params TEXT NOT NULL DEFAULT '{}',  -- JSON
  priority INTEGER NOT NULL DEFAULT 5,
  status TEXT NOT NULL DEFAULT 'propose'  -- propose | observe | archive
);

CREATE TABLE IF NOT EXISTS proposals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  rule_id INTEGER NOT NULL,
  text TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',  -- pending | kept | rejected | expired
  shift TEXT NOT NULL DEFAULT 'morning',
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS todos (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  proposal_id INTEGER NOT NULL,
  text TEXT NOT NULL,
  done INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  done_at TEXT
);

CREATE TABLE IF NOT EXISTS shadow (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date TEXT NOT NULL,
  item_text TEXT NOT NULL,
  rule_hint TEXT NOT NULL,
  source_type TEXT NOT NULL,  -- 挤掉 | 低于阈值 | 基线不足 | 未决
  rule_id INTEGER
);

CREATE TABLE IF NOT EXISTS health (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date TEXT NOT NULL,
  shift TEXT NOT NULL,         -- morning | evening
  status TEXT NOT NULL,        -- ok | error
  error TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- 规则状态变更日志：周报"我学到的"数据源
CREATE TABLE IF NOT EXISTS rule_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  rule_id INTEGER NOT NULL,
  action TEXT NOT NULL,        -- downgrade | upgrade
  reason TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- 导入暂存：预览确认后落库
CREATE TABLE IF NOT EXISTS import_staging (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  batch TEXT NOT NULL,
  row_json TEXT NOT NULL,
  valid INTEGER NOT NULL DEFAULT 1,
  reason TEXT
);

-- 索引：查询热路径（周报聚合、规则扫描、命中率）
CREATE INDEX IF NOT EXISTS idx_proposals_rule ON proposals(rule_id, created_at);
CREATE INDEX IF NOT EXISTS idx_entries_scan ON entries(domain, category, happened_at);
CREATE INDEX IF NOT EXISTS idx_shadow_date ON shadow(date);

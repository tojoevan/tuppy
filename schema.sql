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
  status TEXT NOT NULL DEFAULT 'propose',  -- propose | observe | archive
  anchor_date TEXT                        -- recurring 冷启动锚点（如车险每年 X 月 X 日）
);

CREATE TABLE IF NOT EXISTS proposals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  rule_id INTEGER NOT NULL,
  entry_id INTEGER,             -- 关联 entries（expiry 模板触发时），keep 后带截止
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
  due TEXT,                     -- 截止日（YYYY-MM-DD），来自关联 entry 的到期日
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

-- 迁移版本记录（migrations.py 按此推进存量库）
CREATE TABLE IF NOT EXISTS schema_version (
  name TEXT PRIMARY KEY,
  applied_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- 打扰预算：配额变更记录（当前配额 = 最后一条的 quota）
CREATE TABLE IF NOT EXISTS budget_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date TEXT NOT NULL,
  action TEXT NOT NULL,       -- adjust_down | adjust_up
  quota INTEGER NOT NULL,     -- 变更后的每日配额
  reason TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- 打扰预算：实际推送记录（responded 由晚班回填）
CREATE TABLE IF NOT EXISTS push_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date TEXT NOT NULL,
  shift TEXT NOT NULL,        -- morning | evening | weekly
  text TEXT NOT NULL,
  responded INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- 微问答去重状态：同一题答过/跳过即不再问（答过即停）。
CREATE TABLE IF NOT EXISTS qa_state (
  key TEXT PRIMARY KEY,                 -- 稳定题号：qa:{template}:{domain}:{category}
  answered_at TEXT,                     -- 答过时间；NULL=未答
  skipped_at TEXT,                      -- 跳过时间；NULL=未跳
  kind TEXT NOT NULL DEFAULT 'choice',  -- choice | fill
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

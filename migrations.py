"""幂等迁移。

schema.sql 永远是全新库的最新形态。生产库的存量表差异靠这里的迁移补。
每条迁移必须幂等（重跑无害）——因为老库可能已手动 ALTER 过。

用法：engine.init_db() 里自动调用 migrate(conn)。
"""

import sqlite3


def _has_column(conn, table, column):
    cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(c["name"] == column for c in cols)


def _migration_0001_budget(conn):
    """打扰预算：budget_log + push_log。"""
    conn.executescript("""
CREATE TABLE IF NOT EXISTS budget_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date TEXT NOT NULL,
  action TEXT NOT NULL,
  quota INTEGER NOT NULL,
  reason TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS push_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date TEXT NOT NULL,
  shift TEXT NOT NULL,
  text TEXT NOT NULL,
  responded INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
""")


def _migration_0002_todo_due(conn):
    """待办截止：proposals.entry_id + todos.due。"""
    if not _has_column(conn, "proposals", "entry_id"):
        conn.execute("ALTER TABLE proposals ADD COLUMN entry_id INTEGER")
    if not _has_column(conn, "todos", "due"):
        conn.execute("ALTER TABLE todos ADD COLUMN due TEXT")


def _migration_0003_anchor_date(conn):
    """recurring 规则冷启动锚点：rules.anchor_date。

    周期类规则（水费/物业/车险/年检…）此前必须依赖一条历史 entry 才能
    推算下次到期，导致全新库永远 0 待办。加 anchor_date 后，规则可凭
    「锚点 + N×period_days」直接生成下一个未来到期提醒。
    用户通过微问答补的「上次 X 哪天」也回写此字段，作为 fallback。
    """
    if not _has_column(conn, "rules", "anchor_date"):
        conn.execute("ALTER TABLE rules ADD COLUMN anchor_date TEXT")


MIGRATIONS = [
    ("0001_budget", _migration_0001_budget),
    ("0002_todo_due", _migration_0002_todo_due),
    ("0003_anchor_date", _migration_0003_anchor_date),
]


def migrate(conn):
    """跑未应用的迁移。schema.sql 已建好基础表（含 schema_version）。"""
    applied = {
        r["name"] for r in conn.execute("SELECT name FROM schema_version")
    }
    for name, fn in MIGRATIONS:
        if name in applied:
            continue
        fn(conn)
        conn.execute(
            "INSERT INTO schema_version (name) VALUES (?)", (name,)
        )
        print(f"migration applied: {name}")
    conn.commit()

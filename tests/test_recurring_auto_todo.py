"""recurring 周期规则自动落待办 + anchor 行内编辑测试。"""

import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import engine

TODAY = dt.date(2026, 8, 23)


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(engine, "today", lambda: TODAY)
    monkeypatch.setattr(engine, "now", lambda: dt.datetime(2026, 8, 23, 8, 30))
    engine.init_db()
    return engine.get_db()


def recurring_rule(db, domain, category, anchor, period_days=30, days_before=3):
    db.execute(
        "INSERT INTO rules (kind, domain, category, template, params, status,"
        " anchor_date) VALUES ('detection',?,?,'expiry',?, 'propose', ?)",
        (domain, category,
         '{"days_before":%d,"recurring":true,"period_days":%d}'
         % (days_before, period_days), anchor),
    )
    db.commit()
    return db.execute(
        "SELECT * FROM rules WHERE domain=? AND category=? ORDER BY id DESC LIMIT 1",
        (domain, category),
    ).fetchone()


# ---------- recurring 冷启动自动落待办 ----------

def test_recurring_coldstart_auto_todo_real(db):
    r = recurring_rule(db, "缴费", "水费2", "2026-07-30", period_days=30,
                       days_before=10)
    engine.run_shift("morning")
    props = db.execute(
        "SELECT * FROM proposals WHERE rule_id=?", (r["id"],)
    ).fetchall()
    assert len(props) == 1 and props[0]["status"] == "kept"
    todos = db.execute(
        "SELECT * FROM todos WHERE proposal_id=?", (props[0]["id"],)
    ).fetchall()
    assert len(todos) == 1
    assert todos[0]["due"] == "2026-08-29"


def test_recurring_no_double_todo(db):
    """同一 anchor 当天重复跑班次，不重复生成 todo。"""
    r = recurring_rule(db, "缴费", "燃气2", "2026-07-30", period_days=30,
                       days_before=10)
    engine.run_shift("morning")
    engine.run_shift("evening")  # evening 也能扫描
    todos = db.execute(
        "SELECT COUNT(*) c FROM todos t JOIN proposals p ON p.id=t.proposal_id"
        " WHERE p.rule_id=?", (r["id"],)
    ).fetchone()["c"]
    assert todos == 1


def test_non_recurring_stays_pending(db):
    """非 recurring 命中仍 pending，不自动落待办。"""
    db.execute(
        "INSERT INTO rules (kind, domain, category, template, params, status)"
        " VALUES ('detection','证件','','expiry',"
        "'{\"days_before\":2,\"recurring\":false}', 'propose')"
    )
    db.commit()
    rid = db.execute("SELECT last_insert_rowid() id").fetchone()["id"]
    db.execute(
        "INSERT INTO entries (domain, category, title, happened_at, status)"
        " VALUES ('证件','','护照', '2026-08-24 00:00:00', 'open')"
    )
    db.commit()
    engine.run_shift("morning")
    props = db.execute(
        "SELECT * FROM proposals WHERE rule_id=?", (rid,)
    ).fetchall()
    assert len(props) == 1 and props[0]["status"] == "pending"
    todos = db.execute(
        "SELECT COUNT(*) c FROM todos t JOIN proposals p ON p.id=t.proposal_id"
        " WHERE p.rule_id=?", (rid,)
    ).fetchone()["c"]
    assert todos == 0

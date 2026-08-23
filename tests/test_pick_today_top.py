"""Tuppy 早班推送挑选：pick_today_top 规则测试。"""

import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import engine

TODAY = dt.date(2026, 8, 15)


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(engine, "today", lambda: TODAY)
    monkeypatch.setattr(
        engine, "now", lambda: dt.datetime(2026, 8, 15, 6, 30)
    )
    engine.init_db()
    return engine.get_db()


def _todo(db, text, due=None, done=0):
    db.execute(
        "INSERT INTO proposals (rule_id, text, status, shift)"
        " VALUES (1,?,?,?)",
        (text, "pending", "morning"),
    )
    pid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.execute(
        "INSERT INTO todos (proposal_id, text, due, done) VALUES (?,?,?,?)",
        (pid, text, due, done),
    )
    db.commit()


def _proposal(db, text, priority=5, status="pending"):
    # priority 来自关联 rule，这里建一个带 priority 的 rule
    db.execute(
        "INSERT INTO rules (kind, domain, category, template, params, priority)"
        " VALUES ('detection','测试','x','expiry','{}',?)",
        (priority,),
    )
    rid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.execute(
        "INSERT INTO proposals (rule_id, text, status, shift)"
        " VALUES (?,?,?,?)",
        (rid, text, status, "morning"),
    )
    db.commit()


def test_picks_nearest_unexpired_todo(db):
    _todo(db, "车险 8-28 到期", "2026-08-28")
    _todo(db, "牛奶临期", "2026-08-20")
    top = engine.pick_today_top(db)
    assert top["text"] == "牛奶临期"  # 更近的优先
    assert top["url"] == "/todos"


def test_expired_todo_skipped(db):
    _todo(db, "已过期的水费", "2026-08-10")  # 早于今天 8-15
    _proposal(db, "信用卡快到期", priority=9)
    top = engine.pick_today_top(db)
    # 过期 todo 被跳过，退回 proposals
    assert top["text"] == "信用卡快到期"


def test_falls_back_to_highest_priority_proposal(db):
    _proposal(db, "牛奶临期", priority=3)
    _proposal(db, "车险提醒", priority=8)
    top = engine.pick_today_top(db)
    assert top["text"] == "车险提醒"  # priority 高优先
    assert top["url"] == "/"


def test_returns_none_when_empty(db):
    assert engine.pick_today_top(db) is None


def test_done_todo_not_picked(db):
    _todo(db, "已完成的事", "2026-08-20", done=1)
    _proposal(db, "待处理的提议", priority=5)
    top = engine.pick_today_top(db)
    assert top["text"] == "待处理的提议"

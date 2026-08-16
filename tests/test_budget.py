"""打扰预算器回归测试。"""

import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import engine

TODAY = dt.date(2026, 8, 16)


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(engine, "today", lambda: TODAY)
    engine.init_db()
    return engine.get_db()


def test_default_quota(db):
    assert engine.current_quota(db) == 2


def test_pushed_today_counts_non_weekly(db):
    for shift in ("morning", "evening", "weekly"):
        db.execute(
            "INSERT INTO push_log (date, shift, text) VALUES (?,?,?)",
            (TODAY.isoformat(), shift, "t"),
        )
    db.commit()
    assert engine.pushed_today(db) == 2  # weekly 不计


def test_auto_adjust_down_after_3_silent_days(db):
    for i in range(3):
        day = TODAY - dt.timedelta(days=3 - i)
        db.execute(
            "INSERT INTO push_log (date, shift, text, responded) VALUES (?,?,?,0)",
            (day.isoformat(), "morning", "t"),
        )
    db.commit()
    engine.auto_adjust_quota(db)
    assert engine.current_quota(db) == 1
    log = db.execute(
        "SELECT * FROM budget_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert log["action"] == "adjust_down"


def test_auto_adjust_up_after_5_responded_days(db):
    for i in range(5):
        day = TODAY - dt.timedelta(days=5 - i)
        db.execute(
            "INSERT INTO push_log (date, shift, text, responded) VALUES (?,?,?,1)",
            (day.isoformat(), "morning", "t"),
        )
    # 先降到 1
    db.execute(
        "INSERT INTO budget_log (date, action, quota, reason) VALUES (?,?,?,?)",
        (TODAY.isoformat(), "adjust_down", 1, "x"),
    )
    db.commit()
    engine.auto_adjust_quota(db)
    assert engine.current_quota(db) == 2


def test_quota_floor_is_one(db):
    for _ in range(6):
        db.execute(
            "INSERT INTO push_log (date, shift, text, responded)"
            " VALUES (?,?,?,0)",
            ((TODAY - dt.timedelta(days=1)).isoformat(), "morning", "t"),
        )
    db.execute(
        "INSERT INTO budget_log (date, action, quota, reason) VALUES (?,?,?,?)",
        (TODAY.isoformat(), "adjust_down", 1, "x"),
    )
    db.commit()
    engine.auto_adjust_quota(db)
    assert engine.current_quota(db) == 1  # 已最低，不再降


def test_fill_push_response_morning(db):
    db.execute(
        "INSERT INTO push_log (date, shift, text) VALUES (?,?,?)",
        (TODAY.isoformat(), "morning", "t"),
    )
    db.execute(
        "INSERT INTO proposals (rule_id, text, status, shift) VALUES (1,'t','kept','morning')"
    )
    db.commit()
    engine.fill_push_response(db)
    r = db.execute("SELECT responded FROM push_log").fetchone()
    assert r["responded"] == 1

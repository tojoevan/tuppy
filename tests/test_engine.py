"""Tuppy v0.1 引擎测试：四模板边界 + 限额 + 降权。"""

import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import engine

TODAY = dt.date(2026, 8, 15)  # 固定"今天"，可控


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(engine, "today", lambda: TODAY)
    monkeypatch.setattr(
        engine, "now", lambda: dt.datetime(2026, 8, 15, 6, 30)
    )
    engine.init_db()
    return engine.get_db()


def add_entry(db, domain, category="", person="", happened_at="",
              ended_at=None, amount=None, value=None, title="", status="open",
              created_at=None):
    # created_at 缺省 = 录入时间与 happened_at 同一天（常规使用场景）。
    # 传 None 时显式用 happened_at 日期，避免 SQLite 实时钟干扰 fixture 假时钟。
    ca = created_at or (happened_at[:10] + " 09:00" if happened_at else None)
    db.execute(
        "INSERT INTO entries (domain, category, person, happened_at, ended_at,"
        " amount, value, title, status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (domain, category, person, happened_at, ended_at, amount, value,
         title, status, ca),
    )
    db.commit()


def rule(db, template):
    return db.execute(
        "SELECT * FROM rules WHERE template=?", (template,)
    ).fetchone()


def gap_rule(db, category="血压"):
    """gap 测试自插 daily 规则，不依赖 seed 内容。"""
    db.execute(
        "INSERT INTO rules (kind, domain, category, template, params)"
        " VALUES ('habit','健康',?,'gap','{\"frequency\":\"daily\",\"max_gap\":1}')",
        (category,),
    )
    db.commit()
    return db.execute(
        "SELECT * FROM rules WHERE category=? AND template='gap'", (category,)
    ).fetchone()


# ---------- 模板 1：缺测 gap ----------

def test_gap_morning_triggers_when_yesterday_missed(db):
    add_entry(db, "健康", "血压", "妈", "2026-08-13 08:00")
    hits = engine.scan_gap(db, gap_rule(db), {"frequency": "daily", "max_gap": 1}, "morning")
    assert hits and "1 天没记" in hits["text"]


def test_gap_morning_silent_when_recorded_yesterday(db):
    add_entry(db, "健康", "血压", "妈", "2026-08-14 08:00")
    assert engine.scan_gap(db, gap_rule(db), {"frequency": "daily", "max_gap": 1}, "morning") is None


def test_gap_evening_triggers_two_days_missed(db):
    add_entry(db, "健康", "血压", "妈", "2026-08-13 08:00")
    hits = engine.scan_gap(db, gap_rule(db), {"frequency": "daily", "max_gap": 1}, "evening")
    assert hits and "连续 2 天" in hits["text"]


def test_gap_evening_silent_for_single_missed_day(db):
    add_entry(db, "健康", "血压", "妈", "2026-08-14 08:00")
    assert engine.scan_gap(db, gap_rule(db), {"frequency": "daily", "max_gap": 1}, "evening") is None


def test_gap_coldstart_history_import_silent(db):
    """冷启动：历史导入的最后一条 3 天前，但今天才录入——不算缺测。

    回归：曾因缺测从 happened_at 起算，刚导入历史就被轰炸。
    """
    db.execute(
        "INSERT INTO entries (domain, category, person, happened_at,"
        " created_at) VALUES ('健康','血压','妈妈','2026-08-12 08:00',"
        " '2026-08-15 10:00')"
    )
    db.commit()
    assert engine.scan_gap(db, rule(db, "gap"),
                           {"frequency": "daily", "max_gap": 1},
                           "morning") is None


# ---------- 模板 2：冲突 overlap ----------

def test_overlap_point_in_interval_same_person(db):
    add_entry(db, "日程", "", "我", "2026-08-20 15:00", title="疫苗乙脑")
    add_entry(db, "日程", "", "我", "2026-08-20 14:00", "2026-08-20 16:00", title="季度评审会")
    hits = engine.scan_overlap(db, rule(db, "overlap"), {"check_between": "same_person"})
    assert any("疫苗乙脑" in h["text"] for h in hits)


def test_overlap_skips_different_person(db):
    add_entry(db, "日程", "", "女儿", "2026-08-20 15:00", title="疫苗乙脑")
    add_entry(db, "日程", "", "我", "2026-08-20 14:00", "2026-08-20 16:00", title="季度评审会")
    hits = engine.scan_overlap(db, rule(db, "overlap"), {"check_between": "same_person"})
    assert hits == []


def test_overlap_allday_vs_timed(db):
    add_entry(db, "日程", "", "我", "2026-08-20", title="体检")
    add_entry(db, "日程", "", "我", "2026-08-20 09:00", "2026-08-20 10:00", title="会")
    hits = engine.scan_overlap(db, rule(db, "overlap"), {"check_between": "same_person"})
    assert any("体检" in h["text"] for h in hits)


# ---------- 模板 3：突变 surge ----------

def test_surge_baseline_insufficient_shadow(db):
    add_entry(db, "账本", "电费", "", "2026-07-20", amount=287)
    add_entry(db, "账本", "电费", "", "2026-08-12", amount=396)
    hits = engine.scan_surge(db, rule(db, "surge"),
                             {"ratio": 1.3, "min_history_days": 30, "min_amount": 50})
    assert hits and not hits["is_candidate"] and hits["shadow_type"] == "基线不足"


def test_surge_candidate_after_history(db):
    for day in (1, 10, 20):
        add_entry(db, "账本", "电费", "", f"2026-07-{day:02d}", amount=95)
    add_entry(db, "账本", "电费", "", "2026-08-05", amount=396)
    hits = engine.scan_surge(db, rule(db, "surge"),
                             {"ratio": 1.3, "min_history_days": 30, "min_amount": 50})
    assert hits and hits["is_candidate"] and "上月 285" in hits["text"]


def test_surge_below_threshold_shadow(db):
    for day in (1, 10, 20):
        add_entry(db, "账本", "电费", "", f"2026-07-{day:02d}", amount=95)
    add_entry(db, "账本", "电费", "", "2026-08-05", amount=314)  # +10%
    hits = engine.scan_surge(db, rule(db, "surge"),
                             {"ratio": 1.3, "min_history_days": 30, "min_amount": 50})
    assert hits and not hits["is_candidate"] and hits["shadow_type"] == "低于阈值"


def test_surge_min_amount_blocked(db):
    for day in (1, 10, 20):
        add_entry(db, "账本", "电费", "", f"2026-07-{day:02d}", amount=10)
    add_entry(db, "账本", "电费", "", "2026-08-05", amount=42)  # +40% 但差额 12 元
    hits = engine.scan_surge(db, rule(db, "surge"),
                             {"ratio": 1.3, "min_history_days": 30, "min_amount": 50})
    assert hits and not hits["is_candidate"]


# ---------- 模板 4：到期 expiry ----------

def test_expiry_within_days_before(db):
    add_entry(db, "物品", "食品", "", "2026-08-17", title="牛奶")
    hits = engine.scan_expiry(db, rule(db, "expiry"), {"days_before": 2})
    assert hits and "还有 2 天到期" in hits[0]["text"]


def test_expiry_outside_window_silent(db):
    add_entry(db, "物品", "食品", "", "2026-08-25", title="牛奶")
    assert engine.scan_expiry(db, rule(db, "expiry"), {"days_before": 2}) == []


def test_expiry_recurring_rolls_forward(db):
    add_entry(db, "物品", "缴费", "", "2026-08-01", title="物业费")
    engine.scan_expiry(db, rule(db, "expiry"),
                       {"days_before": 3, "recurring": True, "period_days": 30})
    row = db.execute(
        "SELECT happened_at FROM entries WHERE title='物业费'"
    ).fetchone()
    assert row["happened_at"] >= "2026-08-15"


# ---------- 限额与降权 ----------

def test_cap_three_candidates_crowd_out(db):
    for i in range(4):
        db.execute(
            "INSERT INTO rules (kind, domain, category, template, params)"
            " VALUES ('habit',?,?,'gap','{\"frequency\":\"daily\",\"max_gap\":1}')",
            ("健康", f"指标{i}"),
        )
        add_entry(db, "健康", f"指标{i}", "妈", "2026-08-13 08:00")
    db.commit()
    engine.run_shift("morning")
    n = db.execute("SELECT COUNT(*) c FROM proposals").fetchone()["c"]
    n_shadow = db.execute(
        "SELECT COUNT(*) c FROM shadow WHERE source_type='挤掉'"
    ).fetchone()["c"]
    assert n == 3 and n_shadow == 1


def test_downgrade_four_expired(db):
    r = rule(db, "expiry")
    for _ in range(4):
        db.execute(
            "INSERT INTO proposals (rule_id, text, status, shift)"
            " VALUES (?,?,?,?)", (r["id"], "t", "expired", "morning")
        )
    db.commit()
    engine.apply_feedback(db)
    status = db.execute(
        "SELECT status FROM rules WHERE id=?", (r["id"],)
    ).fetchone()["status"]
    n_log = db.execute("SELECT COUNT(*) c FROM rule_log").fetchone()["c"]
    assert status == "observe" and n_log == 1


def test_downgrade_three_rejected(db):
    r = rule(db, "expiry")
    for _ in range(3):
        db.execute(
            "INSERT INTO proposals (rule_id, text, status, shift)"
            " VALUES (?,?,?,?)", (r["id"], "t", "rejected", "morning")
        )
    db.commit()
    engine.apply_feedback(db)
    status = db.execute(
        "SELECT status FROM rules WHERE id=?", (r["id"],)
    ).fetchone()["status"]
    assert status == "observe"


def test_expire_pending_after_24h(db):
    r = rule(db, "expiry")
    # created_at 用假时钟推算（08-13），不依赖 SQLite 实时钟（曾 flaky）
    db.execute(
        "INSERT INTO proposals (rule_id, text, status, shift, created_at)"
        " VALUES (?,?,?,?, '2026-08-13 06:00')",
        (r["id"], "t", "pending", "morning"),
    )
    db.commit()
    engine.apply_feedback(db)
    status = db.execute(
        "SELECT status FROM proposals WHERE rule_id=?", (r["id"],)
    ).fetchone()["status"]
    assert status == "expired"

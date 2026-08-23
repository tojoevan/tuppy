"""Tuppy 微问答测试：规则派生 + 去重 + 写入 entries。"""

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
    monkeypatch.setattr(engine, "now", lambda: dt.datetime(2026, 8, 15, 9, 0))
    engine.init_db()
    # 插三条不同模板的启用规则
    db = engine.get_db()
    db.execute(
        "INSERT INTO rules (kind,domain,category,template,params,status)"
        " VALUES ('habit','健康','血压','gap','{\"frequency\":\"daily\"}','propose')"
    )
    db.execute(
        "INSERT INTO rules (kind,domain,category,template,params,status)"
        " VALUES ('detection','账本','电费','surge','{\"ratio\":1.3}','propose')"
    )
    db.execute(
        "INSERT INTO rules (kind,domain,category,template,params,status)"
        " VALUES ('detection','证件','','expiry','{\"days_before\":30}','propose')"
    )
    db.execute(
        "INSERT INTO rules (kind,domain,category,template,params,status)"
        " VALUES ('detection','日程','','overlap','{}','propose')"
    )
    db.commit()
    db.close()
    return engine.get_db()


def test_derive_questions_excludes_overlap(db):
    qs = engine.derive_questions(db)
    kinds = {q["kind"] for q in qs}
    keys = {q["key"] for q in qs}
    assert "qa:overlap:日程:" not in keys  # overlap 不派生
    assert "qa:gap:健康:血压" in keys
    assert "qa:surge:账本:电费" in keys
    assert "qa:expiry:证件:" in keys
    assert "fill" in kinds and "choice" in kinds


def test_next_question_returns_one(db):
    q = engine.next_question(db)
    assert q is not None
    assert q["key"].startswith("qa:")


def test_answered_question_disappears(db):
    q = engine.next_question(db)
    assert q is not None
    engine.apply_qa_answer(db, q, "yes" if q["kind"] == "choice" else "1")
    q2 = engine.next_question(db)
    if q2:
        assert q2["key"] != q["key"]


def test_expiry_fill_writes_entry_date(db):
    q = next(x for x in engine.derive_questions(db) if x["key"] == "qa:expiry:证件:")
    eid = engine.apply_qa_answer(db, q, "2026-09-01")
    assert eid
    row = db.execute("SELECT * FROM entries WHERE id=?", (eid,)).fetchone()
    assert row["source"] == "qa"
    assert row["happened_at"].startswith("2026-09-01")
    assert row["domain"] == "证件"


def test_surge_fill_writes_amount(db):
    q = next(x for x in engine.derive_questions(db) if x["key"] == "qa:surge:账本:电费")
    eid = engine.apply_qa_answer(db, q, "230.5")
    assert eid
    row = db.execute("SELECT amount FROM entries WHERE id=?", (eid,)).fetchone()
    assert abs(row["amount"] - 230.5) < 1e-6


def test_choice_yes_writes_entry(db):
    q = next(item for item in engine.derive_questions(db) if item["key"] == "qa:gap:健康:血压")
    eid = engine.apply_qa_answer(db, q, "yes")
    assert eid
    row = db.execute("SELECT source,domain FROM entries WHERE id=?", (eid,)).fetchone()
    assert row["source"] == "qa"


def test_choice_no_writes_no_entry(db):
    q = next(item for item in engine.derive_questions(db) if item["key"] == "qa:gap:健康:血压")
    before = db.execute("SELECT COUNT(*) c FROM entries").fetchone()["c"]
    eid = engine.apply_qa_answer(db, q, "no")
    after = db.execute("SELECT COUNT(*) c FROM entries").fetchone()["c"]
    assert eid is None
    assert after == before  # 不写 entries
    # 但仍记 qa_state（答过即停）
    st = db.execute(
        "SELECT answered_at FROM qa_state WHERE key=?", (q["key"],)
    ).fetchone()
    assert st and st["answered_at"]


def test_skip_records_state(db):
    q = engine.next_question(db)
    engine.record_qa_skip(db, q["key"])
    st = db.execute(
        "SELECT skipped_at FROM qa_state WHERE key=?", (q["key"],)
    ).fetchone()
    assert st and st["skipped_at"]
    # 跳过后再 next_question 不再返回它
    q2 = engine.next_question(db)
    if q2:
        assert q2["key"] != q["key"]


def test_invalid_amount_not_written(db):
    q = next(item for item in engine.derive_questions(db) if item["key"] == "qa:surge:账本:电费")
    before = db.execute("SELECT COUNT(*) c FROM entries").fetchone()["c"]
    eid = engine.apply_qa_answer(db, q, "不是数字")
    after = db.execute("SELECT COUNT(*) c FROM entries").fetchone()["c"]
    assert eid is None
    assert after == before


def test_empty_category_expiry_softened(db):
    """category 为空的 expiry 规则用「你的X」软化问法，不派生病句。"""
    db.execute(
        "INSERT INTO rules (kind,domain,category,template,params,status)"
        " VALUES ('detection','物品','','expiry','{\"days_before\":2}','propose')"
    )
    db.execute(
        "INSERT INTO rules (kind,domain,category,template,params,status)"
        " VALUES ('detection','信用卡','','expiry','{\"days_before\":2}','propose')"
    )
    qs = {q["key"]: q for q in engine.derive_questions(db)}
    # 空 category 仍派生，且问法软化
    assert "qa:expiry:物品:" in qs
    assert qs["qa:expiry:物品:"]["q"] == "你的物品 的到期日是什么时候？"
    assert "qa:expiry:信用卡:" in qs
    # 证件的 category 在 seed 中也为空 → 同样软化
    assert qs["qa:expiry:证件:"]["q"] == "你的证件 的到期日是什么时候？"


def test_question_label_no_stray_dot(db):
    """有 category 的题，问句主语不带多余点号且为合法主语。"""
    qs = {q["key"]: q for q in engine.derive_questions(db)}
    assert qs["qa:expiry:证件:"]["q"] == "你的证件 的到期日是什么时候？"
    assert "·" not in qs["qa:expiry:证件:"]["q"]

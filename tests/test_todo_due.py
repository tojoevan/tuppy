"""待办截止与到期提醒回归测试。"""

import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import engine

TODAY = dt.date(2026, 8, 16)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(engine, "today", lambda: TODAY)
    engine.init_db()
    import app as a

    monkeypatch.setattr(a, "TUPPY_PASSWORD", "secret-pw")
    a.app.config["TESTING"] = True
    c = a.app.test_client()
    c.post("/login", data={"password": "secret-pw"})
    return c


def _make_proposal_with_entry(conn, happened_at="2026-08-20 09:00"):
    conn.execute(
        "INSERT INTO entries (domain, category, happened_at, title)"
        " VALUES ('信用卡','','2026-08-20 09:00','还款')"
    )
    conn.execute(
        "INSERT INTO rules (kind, domain, category, template, params)"
        " VALUES ('detection','信用卡','','expiry',"
        " '{\"days_before\":2,\"recurring\":false}')"
    )
    rule_id = conn.execute(
        "SELECT id FROM rules WHERE domain='信用卡'"
    ).fetchone()["id"]
    conn.execute(
        "INSERT INTO proposals (rule_id, entry_id, text, status, shift)"
        " VALUES (?, 1, '信用卡还有 4 天到期', 'pending', 'morning')",
        (rule_id,),
    )
    conn.commit()
    return conn.execute(
        "SELECT id FROM proposals ORDER BY id DESC LIMIT 1"
    ).fetchone()["id"]


def test_keep_stores_due_from_entry(client):
    conn = engine.get_db()
    pid = _make_proposal_with_entry(conn)
    client.post(f"/proposal/{pid}/keep")
    t = conn.execute("SELECT * FROM todos").fetchone()
    assert t["due"] == "2026-08-20"


def test_keep_without_entry_no_due(client):
    conn = engine.get_db()
    conn.execute(
        "INSERT INTO proposals (rule_id, text, status, shift)"
        " VALUES (1, 't', 'pending', 'morning')"
    )
    conn.commit()
    pid = conn.execute(
        "SELECT id FROM proposals ORDER BY id DESC LIMIT 1"
    ).fetchone()["id"]
    client.post(f"/proposal/{pid}/keep")
    t = conn.execute("SELECT * FROM todos").fetchone()
    assert t["due"] is None


def test_todo_page_shows_due_and_overdue(client):
    conn = engine.get_db()
    pid = _make_proposal_with_entry(conn)
    client.post(f"/proposal/{pid}/keep")
    conn.execute("UPDATE todos SET due='2026-08-10'")  # 已过期
    conn.commit()
    html = client.get("/todos").get_data(as_text=True)
    assert "截止 2026-08-10" in html
    assert "已到期" in html

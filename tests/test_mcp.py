"""MCP 工具回归测试：直接调工具函数（不经过 HTTP 层）。"""

import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import engine

TODAY = dt.date(2026, 8, 16)


@pytest.fixture
def mcp_mod(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(engine, "today", lambda: TODAY)
    engine.init_db()
    import mcp_server as m

    return m


def test_add_entry_voice_source(mcp_mod):
    result = mcp_mod.add_entry(
        domain="账本", category="电费", happened_at="2026-08-01",
        amount=396.0,
    )
    assert "记下了" in result
    conn = engine.get_db()
    row = conn.execute("SELECT * FROM entries").fetchone()
    assert row["source"] == "voice"
    assert row["amount"] == 396.0


def test_add_entry_bad_date(mcp_mod):
    result = mcp_mod.add_entry(domain="账本", happened_at="昨天")
    assert "日期格式不对" in result


def test_list_proposals_empty(mcp_mod):
    assert "没有提议" in mcp_mod.list_proposals()


def test_list_proposals_with_status(mcp_mod):
    conn = engine.get_db()
    conn.execute(
        "INSERT INTO proposals (rule_id, text, status, shift)"
        " VALUES (1, '信用卡还有 2 天到期', 'pending', 'morning')"
    )
    conn.commit()
    result = mcp_mod.list_proposals()
    assert "信用卡还有 2 天到期" in result
    assert "还没处理" in result


def test_list_todos_overdue(mcp_mod):
    conn = engine.get_db()
    conn.execute(
        "INSERT INTO todos (proposal_id, text, due) VALUES (1, 't', '2026-08-10')"
    )
    conn.commit()
    result = mcp_mod.list_todos()
    assert "已到期" in result


def test_query_entries(mcp_mod):
    mcp_mod.add_entry(domain="账本", category="电费",
                      happened_at="2026-08-01", amount=396.0)
    result = mcp_mod.query_entries(domain="账本")
    assert "396元" in result


def test_weekly_stats(mcp_mod):
    conn = engine.get_db()
    conn.execute(
        "INSERT INTO proposals (rule_id, text, status, shift)"
        " VALUES (1, 't', 'kept', 'morning')"
    )
    conn.commit()
    result = mcp_mod.weekly_stats()
    assert "说了 1 次" in result and "听进去 1 次" in result

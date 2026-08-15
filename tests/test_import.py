"""CSV 导入流程回归测试：预览、确认、去重。"""

import io
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import engine

CSV = (
    "domain,person,happened_at,category,amount,value,title\n"
    "健康,妈妈,2026-08-13 08:00,血压,,140/88,\n"
    "账本,,2026-08-01,电费,396,,\n"
)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "DB_PATH", tmp_path / "t.db")
    engine.init_db()
    import app as a

    monkeypatch.setattr(a, "TUPPY_PASSWORD", "secret-pw")
    a.app.config["TESTING"] = True
    c = a.app.test_client()
    c.post("/login", data={"password": "secret-pw"})
    return c


def _import_csv(client, content):
    r = client.post(
        "/import/csv",
        data={"file": (io.BytesIO(content.encode()), "t.csv")},
        content_type="multipart/form-data",
    )
    m = re.search(r'name="batch" value="(\w+)"', r.get_data(as_text=True))
    assert m, "preview 页应含 batch"
    return client.post("/import/confirm", data={"batch": m.group(1)})


def test_import_preview_counts(client):
    r = client.post(
        "/import/csv",
        data={"file": (io.BytesIO(CSV.encode()), "t.csv")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "2 条" in html


def test_import_bad_date_reported(client):
    bad = "domain,happened_at\n健康,不是日期\n"
    r = client.post(
        "/import/csv",
        data={"file": (io.BytesIO(bad.encode()), "t.csv")},
        content_type="multipart/form-data",
    )
    assert "日期解析失败" in r.get_data(as_text=True)


def test_import_dedup_amount_and_null(client, monkeypatch):
    """两次导入同一 CSV：无论 amount 有值(396)还是空(NULL)，都不重复插入。

    回归：曾因 CSV 空字段为 ''（非 None）且金额为 TEXT（非 REAL）
    导致 COALESCE 比较失配，两次导入翻倍。
    """
    conn = engine.get_db()

    def count():
        return conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]

    _import_csv(client, CSV)
    n1 = count()
    _import_csv(client, CSV)
    n2 = count()
    assert n1 == 2 and n2 == 2, f"去重失败: {n1} -> {n2}"


def test_import_ics_timed_and_allday(client):
    """ICS 导入：定时事件带结束时间+备注，全天事件 date-only。"""
    from datetime import datetime

    from icalendar import Calendar, Event

    cal = Calendar()
    e1 = Event()
    e1.add("summary", "季度评审会")
    e1.add("dtstart", datetime(2026, 8, 20, 14, 0))
    e1.add("dtend", datetime(2026, 8, 20, 16, 0))
    e1.add("description", "带上季度数据")
    cal.add_component(e1)
    e2 = Event()
    e2.add("summary", "体检")
    e2.add("dtstart", datetime(2026, 8, 25).date())
    cal.add_component(e2)

    r = client.post(
        "/import/ics",
        data={"file": (io.BytesIO(cal.to_ical()), "t.ics"), "person": "我"},
        content_type="multipart/form-data",
    )
    m = re.search(r'name="batch" value="(\w+)"', r.get_data(as_text=True))
    assert m
    client.post("/import/confirm", data={"batch": m.group(1)})

    conn = engine.get_db()
    rows = conn.execute(
        "SELECT title, happened_at, ended_at, note, person FROM entries"
        " ORDER BY id"
    ).fetchall()
    assert len(rows) == 2
    timed_row = rows[0]
    assert timed_row["title"] == "季度评审会"
    assert timed_row["ended_at"] == "2026-08-20 16:00:00"
    assert timed_row["note"] == "带上季度数据"
    assert timed_row["person"] == "我"
    allday = rows[1]
    assert allday["title"] == "体检"
    assert allday["ended_at"] is None
    assert allday["happened_at"] == "2026-08-25"


def test_import_ics_then_overlap_detected(client):
    """ICS 导入的日程能与手动录入的事件产生冲突提议。"""
    from datetime import datetime

    from icalendar import Calendar, Event

    cal = Calendar()
    e1 = Event()
    e1.add("summary", "季度评审会")
    e1.add("dtstart", datetime(2026, 8, 20, 14, 0))
    e1.add("dtend", datetime(2026, 8, 20, 16, 0))
    cal.add_component(e1)
    r = client.post(
        "/import/ics",
        data={"file": (io.BytesIO(cal.to_ical()), "t.ics"), "person": "我"},
        content_type="multipart/form-data",
    )
    m = re.search(r'name="batch" value="(\w+)"', r.get_data(as_text=True))
    client.post("/import/confirm", data={"batch": m.group(1)})

    client.post(
        "/entry/add",
        data={"domain": "日程", "person": "我",
              "happened_date": "2026-08-20", "happened_time": "15:00",
              "title": "疫苗乙脑"},
    )
    conn = engine.get_db()
    rule = conn.execute(
        "SELECT * FROM rules WHERE domain='日程' AND template='overlap'"
    ).fetchone()
    hits = engine.scan_overlap(conn, rule, {"check_between": "same_person"})
    assert any("季度评审会" in h["text"] for h in hits)

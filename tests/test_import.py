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

    a.app.config["TESTING"] = True
    return a.app.test_client()


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

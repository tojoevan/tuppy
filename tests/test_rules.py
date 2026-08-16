"""规则导入/导出回归测试。"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import engine


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


def rule_count():
    conn = engine.get_db()
    n = conn.execute("SELECT COUNT(*) FROM rules").fetchone()[0]
    conn.close()
    return n


def test_export_roundtrip(client):
    r = client.get("/rules/export")
    assert r.status_code == 200
    payload = json.loads(r.get_data(as_text=True))
    assert payload["format"] == "tuppy-rules"
    assert payload["version"] == 1
    assert len(payload["rules"]) >= 4  # seed 全集


def test_import_new_rule(client):
    body = json.dumps({
        "rules": [{
            "kind": "detection", "domain": "测试域", "category": "测试类",
            "template": "expiry",
            "params": {"days_before": 1, "recurring": False},
            "priority": 5,
        }]
    })
    n_before = rule_count()
    r = client.post("/rules/import", data={"json": body})
    assert r.status_code == 302
    assert rule_count() == n_before + 1


def test_import_duplicate_skipped(client):
    body = json.dumps({
        "rules": [{
            "kind": "detection", "domain": "日程", "category": "",
            "template": "overlap",
            "params": {"check_between": "same_person"}, "priority": 5,
        }]
    })
    n_before = rule_count()
    client.post("/rules/import", data={"json": body})
    assert rule_count() == n_before  # 已存在，跳过


def test_import_invalid_template_rejected(client):
    body = json.dumps({
        "rules": [{
            "kind": "detection", "domain": "X", "category": "",
            "template": "hack", "params": {}, "priority": 5,
        }]
    })
    n_before = rule_count()
    client.post("/rules/import", data={"json": body})
    assert rule_count() == n_before


def test_import_bad_json_rejected(client):
    n_before = rule_count()
    r = client.post("/rules/import", data={"json": "not json{"})
    assert r.status_code == 302
    assert rule_count() == n_before


def test_import_bad_params_type_rejected(client):
    body = json.dumps({
        "rules": [{
            "kind": "detection", "domain": "X", "category": "",
            "template": "expiry", "params": "not-a-dict", "priority": 5,
        }]
    })
    n_before = rule_count()
    client.post("/rules/import", data={"json": body})
    assert rule_count() == n_before

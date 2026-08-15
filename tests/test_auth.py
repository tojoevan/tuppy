"""登录鉴权回归测试。"""

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
    return a.app.test_client()


def test_unauthed_redirects_to_login(client):
    r = client.get("/")
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


def test_login_page_reachable(client):
    r = client.get("/login")
    assert r.status_code == 200
    assert "密码" in r.get_data(as_text=True)


def test_wrong_password_rejected(client):
    r = client.post("/login", data={"password": "wrong"})
    assert "密码不对" in r.get_data(as_text=True)
    # 仍不可访问
    r2 = client.get("/")
    assert r2.status_code == 302


def test_correct_password_login_and_pages(client):
    r = client.post("/login", data={"password": "secret-pw"})
    assert r.status_code == 302
    assert "/login" not in r.headers["Location"]
    for path in ("/", "/todos", "/entries", "/shadow", "/weekly",
                 "/static/manifest.json"):
        r = client.get(path)
        assert r.status_code == 200, f"{path} 应 200, got {r.status_code}"


def test_logout(client):
    client.post("/login", data={"password": "secret-pw"})
    r = client.post("/logout")
    assert r.status_code == 302
    r2 = client.get("/")
    assert r2.status_code == 302  # 又锁了


def test_static_reachable_without_login(client):
    r = client.get("/static/manifest.json")
    assert r.status_code == 200

"""推送通知：自建 ntfy（主）。

.env 配置（与 TUPPY_SECRET 同文件）：
    TUPPY_NTFY_URL=http://127.0.0.1:2586   ntfy 服务地址（默认本机）
    TUPPY_NTFY_TOPIC=tuppy                 topic（默认 tuppy）
    TUPPY_NTFY_USER=tuppy                  ntfy 用户名
    TUPPY_NTFY_PASS=xxx                    ntfy 密码
无事不推——只在有话可说时调用。
"""

import os
import urllib.parse
import urllib.request
from pathlib import Path

BASE = Path(__file__).parent


def load_env():
    """读进程环境 + .env 文件（cron 不继承 systemd 环境，需自读）。"""
    env = os.environ.copy()
    f = BASE / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env.setdefault(k.strip(), v.strip())
    return env


def send(title, body, click_url=None):
    env = load_env()
    url = env.get("TUPPY_NTFY_URL", "http://127.0.0.1:2586").rstrip("/")
    topic = env.get("TUPPY_NTFY_TOPIC", "tuppy")
    user = env.get("TUPPY_NTFY_USER", "")
    password = env.get("TUPPY_NTFY_PASS", "")
    text = f"{title}：{body}"
    full = f"{url}/{urllib.parse.quote(topic)}"
    try:
        req = urllib.request.Request(
            full, data=text.encode("utf-8"), method="POST"
        )
        if user:
            import base64

            token = base64.b64encode(f"{user}:{password}".encode()).decode()
            req.add_header("Authorization", f"Basic {token}")
        if click_url:
            # 点通知跳转，不填则默认打开 ntfy web
            req.add_header("Click", click_url)
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"notify ntfy failed: {e}")


def mqtt_status(json_payload: str):
    """发布 Tuppy 状态到本地 mosquitto（ESP32 固件订阅 tuppy/status）。

    用 mosquitto_pub CLI——VPS 已装，免 python 依赖。
    失败静默：固件链路是增强通道，断不影响主功能。
    """
    import subprocess

    try:
        subprocess.run(
            ["mosquitto_pub", "-h", "127.0.0.1",
             "-t", "tuppy/status", "-m", json_payload],
            timeout=5, capture_output=True,
        )
    except Exception as e:
        print(f"mqtt_status failed: {e}")

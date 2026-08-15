"""推送通知：PushDeer（安卓+iOS）/ Bark（iOS）。

.env 配置（与 TUPPY_SECRET 同文件）：
    TUPPY_PUSHDEER_KEY=xxx   PushDeer pushkey，安卓+iOS 通用
    TUPPY_BARK_KEY=xxx        Bark key，仅 iOS
至少一个生效。无事不推——只在有话可说时调用。
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


def send(title, body):
    env = load_env()
    key = env.get("TUPPY_PUSHDEER_KEY", "").strip()
    if key:
        text = f"{title}\n{body}"
        url = ("https://api2.pushdeer.com/message/push?pushkey="
               + urllib.parse.quote(key) + "&text=" + urllib.parse.quote(text))
        _get(url, "pushdeer")
    bark = env.get("TUPPY_BARK_KEY", "").strip()
    if bark:
        url = (f"https://api.day.app/{urllib.parse.quote(bark)}/"
               f"{urllib.parse.quote(title)}/{urllib.parse.quote(body)}")
        _get(url, "bark")


def _get(url, channel):
    try:
        urllib.request.urlopen(url, timeout=10)
    except Exception as e:
        print(f"notify {channel} failed: {e}")

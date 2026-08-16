"""Tuppy 看板响应器：订阅 tuppy/query，查 SQLite，回复 tuppy/reply。

固件按键（BOOT 单击 / 电源键双击）发 tuppy/query {"view":"todos"} 等，
这里查库返回文本，发回 tuppy/reply {"view":"...","data":"..."}，固件主屏显示。

views:
  todos  今日待办（todos 未完成）
  expiry 到期提醒（entries 有 happened_at 且近 7 天到期的）
  health 健康缺测（健康域最近记录）
  status Tuppy 状态（提议数/待办数/心跳）
  pickup 随机解压语录

运行：python3 scripts/tuppy_responder.py（需 paho-mqtt，或 systemd）
"""

import datetime as dt
import json
import random
import sqlite3
import sys
from pathlib import Path

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("需要 paho-mqtt：pip install paho-mqtt")
    sys.exit(1)

BASE = Path(__file__).parent.parent
DB_PATH = BASE / "tuppy.db"
BROKER = "127.0.0.1"
PORT = 1883

PICKUPS = [
    "深呼吸，世界不会因为少做一件事就停下来。",
    "你已经做得很好了，剩下的明天再说。",
    "放空三秒，想想窗外有什么。",
    "今天的小目标：完成一件小事，奖励自己一下。",
    "焦虑解决不了问题，但行动可以。",
    "你已经连续工作很久了，起来喝口水吧。",
    "记住：你不是机器，允许自己慢一点。",
    "此刻最值得做的事：什么都不做。",
    "给自己泡杯茶，看看远处的风景。",
    "压力是暂时的，你是一直在进步的。",
]


def _db():
    return sqlite3.connect(DB_PATH)


def _today():
    return dt.date.today().isoformat()


def view_todos():
    conn = _db()
    rows = conn.execute(
        "SELECT text, due FROM todos WHERE done=0 ORDER BY id DESC LIMIT 8"
    ).fetchall()
    conn.close()
    if not rows:
        return "待办是空的，今天很轻松。"
    parts = []
    for text, due in rows:
        line = f"- {text}"
        if due:
            line += f"（{due}）" if due > _today() else "（已到期）"
        parts.append(line)
    return "今日待办：\n" + "\n".join(parts)


def view_expiry():
    conn = _db()
    rows = conn.execute(
        "SELECT domain, category, title, happened_at, note FROM entries"
        " WHERE happened_at >= ? AND happened_at <= ?"
        " ORDER BY happened_at LIMIT 8",
        (_today(), (dt.date.today() + dt.timedelta(days=14)).isoformat()),
    ).fetchall()
    conn.close()
    if not rows:
        return "近两周没有到期事项。"
    parts = []
    for domain, category, title, happened_at, note in rows:
        # happened_at 可能带时间（如 "2026-08-23 09:00"），只取日期部分
        date_part = happened_at.split(" ")[0]
        days = (dt.date.fromisoformat(date_part) - dt.date.today()).days
        name = title or note or f"{domain}/{category}"
        parts.append(f"- {name} {days}天后到期（{date_part}）")
    return "到期提醒：\n" + "\n".join(parts)


def view_health():
    conn = _db()
    rows = conn.execute(
        "SELECT category, title, happened_at, value FROM entries"
        " WHERE domain='健康' ORDER BY happened_at DESC LIMIT 5"
    ).fetchall()
    conn.close()
    if not rows:
        return "健康没有记录。用\"帮我记一下\"录入。"
    parts = []
    for category, title, happened_at, value in rows:
        name = title or category
        parts.append(f"- {name} {happened_at}" + (f" {value}" if value else ""))
    return "健康记录：\n" + "\n".join(parts)


def view_status():
    conn = _db()
    proposals = conn.execute(
        "SELECT COUNT(*) FROM proposals WHERE status='pending'"
    ).fetchone()[0]
    todos = conn.execute(
        "SELECT COUNT(*) FROM todos WHERE done=0"
    ).fetchone()[0]
    entries = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    conn.close()
    return f"提议 {proposals} 件 | 待办 {todos} 件 | 已录 {entries} 条"


def view_pickup():
    return random.choice(PICKUPS)


HANDLERS = {
    "todos": view_todos,
    "expiry": view_expiry,
    "health": view_health,
    "status": view_status,
    "pickup": view_pickup,
}


def on_connect(client, userdata, flags, reason_code, properties=None):
    print(f"connected rc={reason_code}, subscribing tuppy/query")
    client.subscribe("tuppy/query")


def on_message(client, userdata, msg):
    try:
        req = json.loads(msg.payload.decode())
        view = req.get("view", "status")
    except Exception:
        view = "status"
    handler = HANDLERS.get(view, view_status)
    try:
        data = handler()
    except Exception as e:
        data = f"查询失败: {e}"
    reply = json.dumps({"view": view, "data": data}, ensure_ascii=False)
    client.publish("tuppy/reply", reply, qos=0)
    print(f"reply[{view}]: {data[:60]}...")


def main():
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id="tuppy_responder",
    )
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(BROKER, PORT, 60)
    client.loop_forever()


if __name__ == "__main__":
    main()

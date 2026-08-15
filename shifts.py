"""Tuppy 两班入口。

用法：
    python shifts.py morning   # 早班（cron 06:30）
    python shifts.py evening   # 晚班（cron 22:00）
"""

import sys

import engine
import notify


def after_shift(shift):
    """班后推送：有话说才推，无事闭嘴。最多一天两条（天然打扰预算）。"""
    site = notify.load_env().get(
        "TUPPY_SITE_URL", "https://tuppy.oahubs.com"
    )
    conn = engine.get_db()
    if shift == "morning":
        n = conn.execute(
            "SELECT COUNT(*) FROM proposals WHERE status='pending'"
        ).fetchone()[0]
        if n:
            notify.send("Tuppy 早班", f"{n} 件想跟你说", click_url=site)
    else:
        n = conn.execute(
            "SELECT COUNT(*) FROM todos WHERE done=0"
        ).fetchone()[0]
        if n:
            notify.send(
                "Tuppy 晚班", f"{n} 件记下的事还没处理", click_url=site + "/todos"
            )
    conn.close()


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("morning", "evening"):
        print("usage: python shifts.py morning|evening")
        sys.exit(1)
    engine.init_db()
    engine.run_shift(sys.argv[1])
    after_shift(sys.argv[1])


if __name__ == "__main__":
    main()

"""Tuppy 两班入口。

用法：
    python shifts.py morning   # 早班（cron 06:30）
    python shifts.py evening   # 晚班（cron 22:00）
"""

import sys

import engine
import notify


def after_shift(shift):
    """班后推送：有话说才推，无事闭嘴。最多一天两条（天然打扰预算）。

    周日例外：晚班后必推周报摘要——每周一次的存活心跳。
    """
    import datetime as dt

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
        # 周日心跳：本周数字，不管有事没事
        if dt.date.today().weekday() == 6:
            monday = dt.date.today() - dt.timedelta(days=6)
            stats = conn.execute(
                "SELECT status, COUNT(*) c FROM proposals"
                " WHERE created_at >= ? GROUP BY status",
                (monday.isoformat(),),
            ).fetchall()
            counts = {s["status"]: s["c"] for s in stats}
            total = sum(counts.values())
            kept = counts.get("kept", 0)
            notify.send(
                "Tuppy 周报",
                f"这周我说了 {total} 次，你听进去 {kept} 次",
                click_url=site + "/weekly",
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

"""Tuppy 两班入口。

用法：
    python shifts.py morning   # 早班（cron 08:30）
    python shifts.py evening   # 晚班（cron 22:00）
"""

import datetime as dt
import sys

import engine
import notify


def _record_push(conn, shift, text):
    conn.execute(
        "INSERT INTO push_log (date, shift, text) VALUES (?,?,?)",
        (engine.today().isoformat(), shift, text),
    )
    conn.commit()


def _budget_silence(conn, shift, text):
    """超预算：不推，静默进影子。"""
    conn.execute(
        "INSERT INTO shadow (date, item_text, rule_hint, source_type, rule_id)"
        " VALUES (?,?,?,?, NULL)",
        (engine.today().isoformat(), text, "打扰预算", "超预算"),
    )
    conn.commit()
    print(f"budget exceeded ({shift}), silent to shadow")


def publish_device_status(conn):
    """班后发布固件状态：提议数/待办数/健康。ESP32 屏显数据源。"""
    import json

    proposals = conn.execute(
        "SELECT COUNT(*) c FROM proposals WHERE status='pending'"
    ).fetchone()["c"]
    todos = conn.execute(
        "SELECT COUNT(*) c FROM todos WHERE done=0"
    ).fetchone()["c"]
    health = conn.execute(
        "SELECT status FROM health ORDER BY id DESC LIMIT 1"
    ).fetchone()
    notify.mqtt_status(json.dumps({
        "proposals": proposals,
        "todos": todos,
        "health": health["status"] if health else "unknown",
    }, ensure_ascii=False))


def after_shift(shift):
    """班后推送：有话说才推，无事闭嘴。预算闸门在前。

    周日例外：晚班后必推周报心跳——独立通道，不占预算。
    """
    site = notify.load_env().get(
        "TUPPY_SITE_URL", "https://tuppy.oahubs.com"
    )
    conn = engine.get_db()
    publish_device_status(conn)
    quota = engine.current_quota(conn)
    used = engine.pushed_today(conn)
    if shift == "morning":
        top = engine.pick_today_top(conn)
        if top:
            text = f"今天最该办：{top['text']}"
            if used >= quota:
                _budget_silence(
                    conn, shift,
                    f"今天有想跟你说的事，但预算已用完（{used}/{quota}）",
                )
            else:
                notify.send("Tuppy 早班", text, click_url=site + top["url"])
                _record_push(conn, shift, text)
    else:
        n = conn.execute(
            "SELECT COUNT(*) FROM todos WHERE done=0"
        ).fetchone()[0]
        overdue = conn.execute(
            "SELECT COUNT(*) FROM todos WHERE done=0 AND due IS NOT NULL"
            " AND due <= ?",
            (engine.today().isoformat(),),
        ).fetchone()[0]
        if overdue:
            text = f"Tuppy 晚班：{overdue} 件待办到期了还没处理"
            if used >= quota:
                _budget_silence(
                    conn, shift,
                    f"{overdue} 件待办到期了，但今天预算已用完（{used}/{quota}）",
                )
            else:
                notify.send(
                    "Tuppy 晚班", f"{overdue} 件待办到期了还没处理",
                    click_url=site + "/todos",
                )
                _record_push(conn, shift, text)
        elif n:
            text = f"Tuppy 晚班：{n} 件记下的事还没处理"
            if used >= quota:
                _budget_silence(
                    conn, shift,
                    f"有 {n} 件待办还没处理，但今天预算已用完（{used}/{quota}）",
                )
            else:
                notify.send(
                    "Tuppy 晚班", f"{n} 件记下的事还没处理",
                    click_url=site + "/todos",
                )
                _record_push(conn, shift, text)
        # 周日心跳：本周数字，独立通道不占预算
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
            _record_push(conn, "weekly", f"周报心跳：说了 {total} 次")
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

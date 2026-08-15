"""Tuppy 两班入口。

用法：
    python shifts.py morning   # 早班（cron 06:30）
    python shifts.py evening   # 晚班（cron 22:00）
"""

import sys

import engine


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("morning", "evening"):
        print("usage: python shifts.py morning|evening")
        sys.exit(1)
    engine.init_db()
    engine.run_shift(sys.argv[1])


if __name__ == "__main__":
    main()

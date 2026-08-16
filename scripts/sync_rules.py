"""从 tuppy-rules/rules.json 生成 seed.sql。

用法：python scripts/sync_rules.py [rules.json 路径]
缺省找 ../tuppy-rules/rules.json（本地仓库并排布局）。

seed.sql 是生成物，不要手改。改规则去 tuppy-rules 仓库，
改完跑本脚本再提交 Tuppy。
"""

import json
import sys
from pathlib import Path

BASE = Path(__file__).parent.parent
DEFAULT_RULES = BASE.parent / "tuppy-rules" / "rules.json"


def load_rules(path):
    payload = json.loads(path.read_text())
    if payload.get("format") != "tuppy-rules":
        raise ValueError(f"{path}: 不是 tuppy-rules 格式")
    return payload["rules"]


def render_seed(rules):
    lines = [
        "-- 生成物：由 scripts/sync_rules.py 从 tuppy-rules/rules.json 生成",
        "-- 不要手改本文件。改规则去 tuppy-rules 仓库，跑 sync_rules.py 重新生成。",
        "",
        "INSERT INTO rules (kind, domain, category, template, params, priority)"
        " VALUES",
    ]
    values = []
    for r in rules:
        params = json.dumps(r["params"], ensure_ascii=False)
        values.append(
            f"('{r['kind']}', '{r['domain']}', '{r['category']}',"
            f" '{r['template']}', '{params}', {r['priority']})"
        )
    lines.append(",\n".join(values) + ";")
    return "\n".join(lines) + "\n"


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_RULES
    if not path.exists():
        print(f"{path} 不存在。tuppy-rules 仓库应放在 {DEFAULT_RULES.parent}")
        sys.exit(1)
    seed = render_seed(load_rules(path))
    out = BASE / "seed.sql"
    out.write_text(seed)
    print(f"{path} -> {out}：{len(load_rules(path))} 条规则")


if __name__ == "__main__":
    main()

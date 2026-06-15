#!/usr/bin/env bash
# Онлайн-бекап SQLite-бази SplitDaddy. Безпечний на живій базі (sqlite backup API
# робить узгоджений знімок без зупинки бота). Тримає останні 14 копій.
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$APP_DIR"
mkdir -p backups

STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="backups/splitdaddy-$STAMP.db"

.venv/bin/python - "$OUT" <<'PY'
import sqlite3, sys
out = sys.argv[1]
src = sqlite3.connect("splitdaddy.db")
dst = sqlite3.connect(out)
with dst:
    src.backup(dst)          # узгоджений онлайн-знімок
dst.close(); src.close()
print("backup ->", out)
PY

# Прибрати все, старше за останні 14 копій.
ls -1t backups/splitdaddy-*.db 2>/dev/null | tail -n +15 | xargs -r rm -f

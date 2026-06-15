#!/usr/bin/env bash
# Деплой на сервері: підтягнути main, оновити залежності, перезапустити сервіс.
# Викликається GitHub Actions через SSH (forced command у authorized_keys).
set -euo pipefail

cd /opt/splitdaddy
git fetch --quiet origin main
git reset --hard --quiet origin/main      # сервер дзеркалить origin/main (.env/.db не чіпаються — вони git-ignored)
.venv/bin/pip install -q -r requirements.txt
systemctl restart splitdaddy

echo "deployed $(git rev-parse --short HEAD) at $(date -u +%FT%TZ)"

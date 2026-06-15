#!/usr/bin/env bash
# Деплой на сервері: підтягнути main, оновити залежності, перезапустити сервіс.
# Викликається GitHub Actions через SSH (forced command у authorized_keys).
set -euo pipefail

cd /opt/splitdaddy
git fetch --quiet origin main
git reset --hard --quiet origin/main      # сервер дзеркалить origin/main (.env/.db не чіпаються — вони git-ignored)
.venv/bin/pip install -q -r requirements.txt
systemctl restart splitdaddy

REV="$(git rev-parse --short HEAD)"
echo "deployed $REV at $(date -u +%FT%TZ)"

# Опційне сповіщення в Telegram (якщо в .env задано NOTIFY_CHAT_ID).
set -a; . ./.env; set +a
if [ -n "${NOTIFY_CHAT_ID:-}" ] && [ -n "${BOT_TOKEN:-}" ]; then
  SUBJ="$(git log -1 --pretty=%s)"
  curl -s -m 10 "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${NOTIFY_CHAT_ID}" \
    --data-urlencode "text=🚀 SplitDaddy задеплоєно: ${REV} — ${SUBJ}" >/dev/null || true
fi

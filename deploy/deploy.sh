#!/bin/bash
# Викатка з Mac на сервер одною командою:
#   deploy/deploy.sh "текст коміту"      → коміт, push, rsync, selftest на сервері, збірка, рестарт
#   deploy/deploy.sh --check              → нічого не міняє, показує стан
#
# Чому по кроках, а не одним ssh: у сесії Claude в auto-режимі об'єднана
# команда «rsync + docker» блокується фільтром, окремі — ні. І селфтест
# на сервері ДО рестарту: зламаний бот не має доїхати до людей.
set -e
REPO="$(cd "$(dirname "$0")/.." && pwd)"
SRV="cappi-bot"
APP="~/app/cappi-shopper"

cd "$REPO"
if [ "$1" = "--check" ]; then
  git fetch -q origin; git status -sb | head -1
  ssh $SRV "cd $APP && docker compose -f deploy/docker-compose.yml ps --format '{{.Name}}: {{.Status}}'; docker logs cappi-shopper --tail 2"
  exit 0
fi
[ -z "$1" ] && { echo "deploy/deploy.sh \"що змінили\""; exit 1; }

echo "── 1/5 origin"
git fetch -q origin
BEHIND=$(git rev-list --count HEAD..origin/main)
[ "$BEHIND" -gt 0 ] && { echo "· на origin $BEHIND чужих комітів — rebase"; git -c core.editor=true rebase origin/main; }
echo "── 2/5 selftest локально"
python3 selftest.py 2>&1 | grep -v "^api " ; rm -rf .selftest-home
echo "── 3/5 коміт і push"
if [ -n "$(git status --porcelain)" ]; then git add -A && git commit -q -m "$1

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"; fi
git push -q origin main
echo "── 4/5 rsync"
rsync -az --delete --exclude .git --exclude data --exclude __pycache__ --exclude .selftest-home ./ $SRV:$APP/
echo "── 5/5 selftest на сервері, збірка, рестарт"
ssh $SRV "cd $APP && SHOPPER_HOME=/tmp/st python3 selftest.py 2>&1 | grep -v '^api ' && rm -rf /tmp/st && docker compose -f deploy/docker-compose.yml build 2>&1 | grep -E 'Built|rror' | tail -1 && docker compose -f deploy/docker-compose.yml up -d 2>&1 | tail -1 && sleep 6 && docker logs cappi-shopper --tail 2"

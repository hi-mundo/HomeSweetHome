#!/usr/bin/env bash
# Atualiza o Home Sweet Home instalado com systemd (ver DEPLOY.md).
#
#   cd ~/HomeSweetHome && ./deploy/update.sh
#
# 1. sai sem mexer em nada se já está na última versão
# 2. backup do banco em data/backups/ (mantém os últimos KEEP)
# 3. git pull --ff-only
# 4. roda os testes; se falharem, volta ao commit anterior
# 5. reinicia o serviço e confere se responde; se não, volta versão e banco
set -euo pipefail

SERVICE="${SERVICE:-homesweethome}"
KEEP="${KEEP:-10}"
cd "${APP_DIR:-$(dirname "$0")/..}"
DB="${LAR_DB:-$PWD/data/lar.db}"
BACKUPS="$PWD/data/backups"

say() { printf '\033[1m%s\033[0m\n' "$*"; }
fail() { printf '\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

# Porta que o serviço usa (Environment=PORT=... na unit); padrão 424.
PORT="$(systemctl show -p Environment "$SERVICE" 2>/dev/null | grep -o 'PORT=[0-9]*' | cut -d= -f2 || true)"
PORT="${PORT:-424}"

healthy() {
  for _ in $(seq 1 15); do
    if python3 -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:$PORT/api/items', timeout=2)" 2>/dev/null; then
      return 0
    fi
    sleep 1
  done
  return 1
}

# 1. Tem versão nova?
git fetch --quiet origin
OLD="$(git rev-parse HEAD)"
NEW="$(git rev-parse '@{u}')"
if [ "$OLD" = "$NEW" ]; then
  say "Já está na última versão ($(git log -1 --format='%h %s'))."
  exit 0
fi
[ -z "$(git status --porcelain --untracked-files=no)" ] || fail "Há mudanças locais nos arquivos do app. Resolva (git status) antes de atualizar."

# 2. Backup consistente, mesmo com o app rodando (API de backup do SQLite).
mkdir -p "$BACKUPS"
BACKUP=""
if [ -f "$DB" ]; then
  BACKUP="$BACKUPS/lar-$(date +%Y-%m-%d-%H%M%S).db"
  python3 -c "import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()" "$DB" "$BACKUP"
  say "Backup: $BACKUP"
  ls -1t "$BACKUPS"/lar-*.db | tail -n +"$((KEEP + 1))" | xargs -r rm --
fi

# 3. Atualiza.
say "Atualizando ${OLD:0:7} → ${NEW:0:7}"
git log --oneline "$OLD..$NEW"
git pull --ff-only --quiet

# 4. Testes antes de reiniciar.
if ! python3 -m unittest -q test_cardapio.py; then
  git reset --quiet --hard "$OLD"
  fail "Testes falharam: voltei para ${OLD:0:7}. O serviço não foi reiniciado."
fi

# 5. Reinicia e confere.
sudo systemctl restart "$SERVICE"
if healthy; then
  say "Pronto: $(git log -1 --format='%h %s') em http://$(hostname -I | awk '{print $1}'):$PORT"
  exit 0
fi

printf '\033[31m%s\033[0m\n' "O app não respondeu depois de reiniciar. Voltando versão e banco…" >&2
journalctl -u "$SERVICE" -n 20 --no-pager >&2 || true
sudo systemctl stop "$SERVICE"
git reset --quiet --hard "$OLD"
[ -n "$BACKUP" ] && cp "$BACKUP" "$DB"
sudo systemctl start "$SERVICE"
healthy && fail "Voltei para ${OLD:0:7} e o app respondeu. A versão nova ficou de fora." \
        || fail "Voltei para ${OLD:0:7}, mas o app ainda não responde: veja journalctl -u $SERVICE."

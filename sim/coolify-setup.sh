#!/bin/bash
# Instalação manual do Coolify (passos da doc oficial, sem o install.sh) dentro do sim-cp.
# Uso: docker compose cp coolify-src sim-cp:/root/ && docker compose exec -T sim-cp bash /root/coolify-setup.sh
# Gera segredos próprios em /data/coolify/source/.env (600, só dentro do container). Idempotente.
set -euo pipefail
VERSION=4.5.3
S=/data/coolify/source
mkdir -p $S /data/coolify/ssh/keys /data/coolify/ssh/mux /data/coolify/applications /data/coolify/databases \
         /data/coolify/backups /data/coolify/services /data/coolify/proxy/dynamic /data/coolify/webhooks-during-maintenance
cp /root/coolify-src/docker-compose.yml /root/coolify-src/docker-compose.prod.yml $S/
if [ ! -f $S/.env ]; then
  rnd() { openssl rand -hex "$1"; }
  umask 077
  sed -e "s|^APP_ID=.*|APP_ID=$(rnd 16)|" \
      -e "s|^APP_KEY=.*|APP_KEY=base64:$(openssl rand -base64 32)|" \
      -e "s|^DB_USERNAME=.*|DB_USERNAME=coolify|" \
      -e "s|^DB_PASSWORD=.*|DB_PASSWORD=$(rnd 24)|" \
      -e "s|^REDIS_PASSWORD=.*|REDIS_PASSWORD=$(rnd 24)|" \
      -e "s|^PUSHER_APP_ID=.*|PUSHER_APP_ID=$(rnd 16)|" \
      -e "s|^PUSHER_APP_KEY=.*|PUSHER_APP_KEY=$(rnd 16)|" \
      -e "s|^PUSHER_APP_SECRET=.*|PUSHER_APP_SECRET=$(rnd 16)|" \
      -e "s|^ROOT_USERNAME=.*|ROOT_USERNAME=operador|" \
      -e "s|^ROOT_USER_EMAIL=.*|ROOT_USER_EMAIL=operador@cp-sim.local|" \
      -e "s|^ROOT_USER_PASSWORD=.*|ROOT_USER_PASSWORD=$(rnd 16)Aa1!|" \
      /root/coolify-src/.env.production > $S/.env
  echo "[ok] .env gerado (600)"
fi
# Chave SSH do Coolify para o próprio host ("localhost" no painel).
K=/data/coolify/ssh/keys/id.root@host.docker.internal
[ -f $K ] || ssh-keygen -q -t ed25519 -N "" -C coolify -f $K
mkdir -p /root/.ssh && touch /root/.ssh/authorized_keys && chmod 600 /root/.ssh/authorized_keys
grep -qF "$(cat $K.pub)" /root/.ssh/authorized_keys || cat $K.pub >> /root/.ssh/authorized_keys
chown -R 9999:root /data/coolify && chmod -R 700 /data/coolify
docker network inspect coolify >/dev/null 2>&1 || docker network create --attachable coolify >/dev/null
cd $S
LATEST_IMAGE=$VERSION docker compose --env-file .env -f docker-compose.yml -f docker-compose.prod.yml \
  up -d --pull always --remove-orphans --force-recreate --wait
echo "[ok] Coolify $VERSION no ar"

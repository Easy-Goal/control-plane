#!/bin/bash
# Laboratório do control plane (ADR 064, fase A). Mesmo roteiro da VPS real, com a rede do Docker no papel
# da tailnet. Rodar da raiz do control-plane:
#   sim/lab.sh up       sobe as máquinas e instala tudo (idempotente: rodar de novo só corrige)
#   sim/lab.sh verify   confere servidores, cofre do control plane, sync e o valor no container
#   sim/lab.sh restore-test [staging|prod]   backup → apaga o schema → restaura do S3 → confere dados e /health
#   sim/lab.sh down     APAGA o laboratório (volumes inclusive). O cofre principal (127.0.0.1:8200) não é tocado.
# Nunca imprime segredo: tokens e chaves vão de processo para processo.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
DC="docker compose -f sim/docker-compose.yml"
CP=cp-sim-sim-cp-1
CP_ADDR=172.30.50.10
PROVIDER=coolify-sim
SIM_BAO=(env CP_BAO_ADDR=https://127.0.0.1:8210 CP_BAO_CACERT="$ROOT/openbao/tls/sim-ca.crt"
         CP_BAO_RESTART_CMD="docker exec $CP docker restart cp-openbao-bao-1")
step() { printf '\n### %s\n' "$*"; }

wait_dockerd() {
  for _ in $(seq 60); do docker exec "$1" docker info >/dev/null 2>&1 && return; sleep 2; done
  echo "dockerd de $1 não subiu" >&2; exit 1
}

# Chaves do S3 do laboratório: geradas 1x, só em sim/.s3.json (600). Nunca impressas.
ensure_s3_keys() {
  [ -f sim/.s3.json ] && return
  ( umask 077; python3 - > sim/.s3.json <<'PY'
import json, secrets
print(json.dumps({"identities": [{"name": "coolify-backups", "credentials": [
    {"accessKey": "cp" + secrets.token_hex(9), "secretKey": secrets.token_urlsafe(30)}],
    "actions": ["Admin", "Read", "Write", "List", "Tagging"]}]}))
PY
  )
}
s3_env() {  # exporta CP_S3_KEY/CP_S3_SECRET só para o processo filho
  python3 -c 'import json; c=json.load(open("sim/.s3.json"))["identities"][0]["credentials"][0]; print(c["accessKey"], c["secretKey"])'
}
with_s3() { read -r k s < <(s3_env); CP_S3_KEY=$k CP_S3_SECRET=$s "$@"; }
aws_lab() { read -r k s < <(s3_env); docker run --rm --network cp-sim_sim -e AWS_ACCESS_KEY_ID=$k -e AWS_SECRET_ACCESS_KEY=$s \
  -e AWS_DEFAULT_REGION=us-east-1 amazon/aws-cli:2.27.50 --endpoint-url http://172.30.50.40:8333 "$@"; }
pg() {  # psql no Postgres gerenciado da VPS (dev|prd)
  local h=cp-sim-sim-vps-$1-1; shift
  local c; c=$(docker exec $h docker ps --filter ancestor=postgres:16-alpine --format '{{.Names}}' | head -1)
  docker exec $h docker exec $c sh -c "psql -v ON_ERROR_STOP=1 -U \"\$POSTGRES_USER\" -d healthstay -Atc \"$*\""
}
CC() { CP_COOLIFY_PROVIDER=$PROVIDER scripts/cp-coolify "$@"; }

up() {
  step "máquinas"
  ensure_s3_keys
  $DC up -d --build
  for h in $CP cp-sim-sim-vps-dev-1 cp-sim-sim-vps-prd-1; do wait_dockerd $h; done

  step "control plane (install/control-plane.sh, igual à VPS real com CP_SIM=1)"
  docker exec -e CP_SIM=1 -e CP_ADDR=$CP_ADDR -e CP_ADMIN_EMAIL=operador@cp-sim.local $CP \
    bash /opt/cp-install/control-plane.sh

  step "CA do cofre do control plane → openbao/tls/sim-ca.crt (pública)"
  mkdir -p openbao/tls && docker cp -q $CP:/data/cp/ca/ca.crt openbao/tls/sim-ca.crt

  step "token do sync (usuário de serviço) → cofre principal"
  if ! CP_COOLIFY_PROVIDER=$PROVIDER scripts/cp-coolify servers >/dev/null 2>&1 || [ "${ROTATE:-0}" = 1 ]; then
    # Validade calculada antes: num pipe, $(...) do lado direito roda junto com o esquerdo.
    exp=$(date -u -d "+90 days" +%F)
    docker exec -e DAYS=90 $CP bash /opt/cp-install/coolify-sync-token.sh 2>/dev/null \
      | scripts/cp-secrets provider set easygoal $PROVIDER url=http://127.0.0.1:8000 --stdin token --expires "$exp"
  else
    echo "  token atual ainda vale (ROTATE=1 para trocar)"
  fi

  step "cofre do control plane: ensaio da migração (snapshot do principal → restore → unseal com as chaves originais)"
  if "${SIM_BAO[@]}" scripts/cp-secrets status 2>/dev/null | grep -q 'inicializado=True'; then
    "${SIM_BAO[@]}" scripts/cp-secrets unseal
  else
    snap=$(scripts/cp-secrets backup | sed -n 's|^\[ok\] \(openbao/backups/[^ ]*\).*|\1|p')
    "${SIM_BAO[@]}" scripts/cp-secrets restore "$snap"
    rm -f "$snap"   # snapshot só do ensaio (os backups de verdade são os do cp-secrets backup)
  fi

  step "VPS de app (install/app-server.sh)"
  CP_COOLIFY_PROVIDER=$PROVIDER scripts/cp-coolify key > /dev/null   # garante a chave
  pub=$(CP_COOLIFY_PROVIDER=$PROVIDER scripts/cp-coolify key)
  for h in dev prd; do
    docker exec -e CP_SIM=1 -e COOLIFY_PUBKEY="$pub" -e SERVER_TAG=app-$h cp-sim-sim-vps-$h-1 bash /opt/cp-install/app-server.sh
  done
  CP_COOLIFY_PROVIDER=$PROVIDER scripts/cp-coolify server add sim-vps-dev 172.30.50.20 --proxy none --description "VPS dev compartilhada (lab)"
  CP_COOLIFY_PROVIDER=$PROVIDER scripts/cp-coolify server add sim-vps-prd 172.30.50.21 --proxy none --description "VPS prd do Health Stay (lab)"

  step "imagens do Health Stay → registry do laboratório (fase C troca por CI → GHCR)"
  for i in api migrate; do
    docker image inspect health-stay-backend-$i:latest >/dev/null 2>&1 \
      || (cd ~/projects/easy/health-stay-backend && docker compose build $i)
    docker tag health-stay-backend-$i:latest 127.0.0.1:5001/health-stay-$i:dev
    docker push -q 127.0.0.1:5001/health-stay-$i:dev >/dev/null
  done
  echo "  [ok] health-stay-api:dev, health-stay-migrate:dev"

  step "segredos de prd (só cria o que falta; AES_KEY nunca é trocada depois de existir)"
  P=easygoal/health-stay/prod
  echo production | scripts/cp-secrets secret set $P NODE_ENV --stdin --if-missing
  echo healthstay | scripts/cp-secrets secret set $P POSTGRES_USER --stdin --if-missing
  echo 15m | scripts/cp-secrets secret set $P JWT_EXPIRES_IN --stdin --if-missing
  echo 7d | scripts/cp-secrets secret set $P REFRESH_TOKEN_TTL --stdin --if-missing
  scripts/cp-secrets secret gen $P POSTGRES_PASSWORD --bytes 24 --if-missing
  scripts/cp-secrets secret gen $P JWT_SECRET --bytes 48 --if-missing
  scripts/cp-secrets secret gen $P AES_KEY --bytes 32 --if-missing

  step "S3 dos backups (SeaweedFS no lab; R2/Spaces na real)"
  for _ in $(seq 30); do aws_lab s3api list-buckets >/dev/null 2>&1 && break; sleep 2; done
  aws_lab s3api head-bucket --bucket cp-backups >/dev/null 2>&1 || aws_lab s3 mb s3://cp-backups >/dev/null
  # Só no lab: o Coolify recusa destino em IP privado (proteção SSRF); libera exatamente o S3 do laboratório.
  docker exec $CP docker exec coolify php artisan tinker --execute='$s=App\Models\InstanceSettings::get(); $s->webhook_allowed_internal_hosts=["172.30.50.40"]; $s->save(); echo "ok";' >/dev/null 2>&1
  with_s3 CC s3 ensure lab-s3 http://172.30.50.40:8333 cp-backups

  step "Health Stay: Postgres gerenciado + backup + API, por ambiente"
  for pair in staging:dev prod:prd; do
    env=${pair%%:*}; vps=${pair##*:}
    CC db ensure health-stay $env sim-vps-$vps health-stay-db-$env easygoal/health-stay/$env
    CC backup ensure health-stay-db-$env lab-s3
    CC service ensure health-stay $env sim-vps-$vps health-stay-api-$env sim/health-stay-api.compose.yml
  done
  scripts/cp-secrets sync apply easygoal/health-stay

  verify
}

verify() {
  step "verificação"
  CP_COOLIFY_PROVIDER=$PROVIDER scripts/cp-coolify servers
  "${SIM_BAO[@]}" scripts/cp-secrets status | sed -n '1,3p;/== easygoal/,$p'
  scripts/cp-secrets sync plan easygoal/health-stay
  curl -fsS -o /dev/null -w "  API staging (VPS dev) /health/ready → %{http_code}\n" http://127.0.0.1:3101/health/ready
  curl -fsS -o /dev/null -w "  API prod    (VPS prd) /health/ready → %{http_code}\n" http://127.0.0.1:3102/health/ready
  .venv/bin/python sim/check-fingerprint.py easygoal/health-stay/staging JWT_SECRET api dev
  .venv/bin/python sim/check-fingerprint.py easygoal/health-stay/prod JWT_SECRET api prd
  for vps in dev prd; do echo "  migrations aplicadas (VPS $vps): $(pg $vps 'select count(*) from _prisma_migrations')"; done
  for h in dev prd; do
    docker exec cp-sim-sim-vps-$h-1 sh -c 'docker logs --since 3m coolify-sentinel 2>&1 | grep -c "push operation failed" || true' \
      | xargs -I{} echo "  sentinel sim-vps-$h: {} falhas de push nos últimos 3 min (url: http://$CP_ADDR:8000)"
  done
}

restore_test() {
  local env=${1:-staging} vps; [ "$env" = prod ] && vps=prd || vps=dev
  local port; [ "$vps" = prd ] && port=3102 || port=3101
  step "teste de restauração: $env (VPS $vps)"
  local marker; marker=$(python3 -c 'import secrets; print(secrets.token_hex(8))')
  pg $vps "create table if not exists cp_restore_probe(token text, at timestamptz default now()); insert into cp_restore_probe(token) values ('$marker')" >/dev/null
  local before; before=$(pg $vps 'select count(*) from _prisma_migrations')
  echo "  antes: marcador gravado, $before migrations"
  local path; path=$(CC backup now health-stay-db-$env)
  echo "  [ok] backup no S3: $path"
  pg $vps 'drop schema public cascade; create schema public' >/dev/null
  echo "  [..] schema public APAGADO (perda simulada): $(pg $vps "select count(*) from information_schema.tables where table_schema='public'") tabelas"
  CC db restore health-stay-db-$env lab-s3 "$path"
  local got after; got=$(pg $vps "select count(*) from cp_restore_probe where token='$marker'"); after=$(pg $vps 'select count(*) from _prisma_migrations')
  echo "  depois: marcador $([ "$got" = 1 ] && echo encontrado || echo AUSENTE), $after migrations"
  curl -fsS -o /dev/null -w "  /health/ready → %{http_code}\n" http://127.0.0.1:$port/health/ready
  pg $vps 'drop table cp_restore_probe' >/dev/null
  [ "$got" = 1 ] && [ "$after" = "$before" ] && echo "  [ok] restauração do $env confere" || { echo "  [erro] restauração não confere"; exit 1; }
}

down() {
  $DC down -v
  echo "laboratório apagado (cofre principal intacto). Recriar: sim/lab.sh up"
}

case "${1:-}" in
  up) up ;;
  verify) verify ;;
  restore-test) restore_test "${2:-staging}" ;;
  down) down ;;
  *) sed -n '2,8p' "$0"; exit 2 ;;
esac

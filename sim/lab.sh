#!/bin/bash
# Laboratório do control plane (ADR 064, fase A). Mesmo roteiro da VPS real, com a rede do Docker no papel
# da tailnet. Rodar da raiz do control-plane:
#   sim/lab.sh up       sobe as máquinas e instala tudo (idempotente: rodar de novo só corrige)
#   sim/lab.sh verify   confere servidores, cofre do control plane, sync e o valor no container
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

up() {
  step "máquinas"
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

  step "Health Stay staging na VPS dev + variáveis pelo sync"
  CP_COOLIFY_PROVIDER=$PROVIDER scripts/cp-coolify service ensure health-stay staging sim-vps-dev \
    health-stay-api-staging sim/health-stay-staging.compose.yml
  scripts/cp-secrets sync apply easygoal/health-stay

  verify
}

verify() {
  step "verificação"
  CP_COOLIFY_PROVIDER=$PROVIDER scripts/cp-coolify servers
  "${SIM_BAO[@]}" scripts/cp-secrets status | sed -n '1,3p;/== easygoal/,$p'
  scripts/cp-secrets sync plan easygoal/health-stay
  curl -fsS -o /dev/null -w "  API staging (VPS dev) /health/ready → %{http_code}\n" http://127.0.0.1:3101/health/ready
  .venv/bin/python sim/check-fingerprint.py easygoal/health-stay/staging JWT_SECRET api dev
  for h in dev prd; do
    docker exec cp-sim-sim-vps-$h-1 sh -c 'docker logs --since 3m coolify-sentinel 2>&1 | grep -c "push operation failed" || true' \
      | xargs -I{} echo "  sentinel sim-vps-$h: {} falhas de push nos últimos 3 min (url: http://$CP_ADDR:8000)"
  done
}

down() {
  $DC down -v
  echo "laboratório apagado (cofre principal intacto). Recriar: sim/lab.sh up"
}

case "${1:-}" in
  up) up ;;
  verify) verify ;;
  down) down ;;
  *) sed -n '2,8p' "$0"; exit 2 ;;
esac

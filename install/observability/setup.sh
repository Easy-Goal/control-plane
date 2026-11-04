#!/bin/bash
# Sobe a observabilidade (OpenObserve + Umami + gateway de ingestão) e troca a senha padrão do Umami. Idempotente.
# Um único caminho de código para a VPS, o laboratório (via install/control-plane.sh) e a stack local (scripts/cp-local).
#
#   CP_ADMIN_EMAIL     e-mail do admin do OpenObserve
#   OBS_BIND           onde o OpenObserve e o Umami publicam as portas (IP da tailnet; ver compose.yml)
#   GW_BIND            onde o gateway de ingestão escuta
#   OBS_DIR            (opcional) pasta de trabalho; padrão /data/cp/observability
#   OBS_COMPOSE_EXTRA  (opcional) compose extra (stack local: troca as portas)
#   OBS_OO_URL, OBS_UMAMI_URL, OBS_GW_URL  (opcionais) como alcançar cada serviço a partir desta máquina
#
# Nunca imprime segredo. As senhas ficam em $OBS_DIR/.env (600).
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/../lib.sh"
. "$HERE/images.env"
: "${CP_ADMIN_EMAIL:?defina CP_ADMIN_EMAIL}" "${OBS_BIND:?defina OBS_BIND}" "${GW_BIND:?defina GW_BIND}"

O=${OBS_DIR:-/data/cp/observability}
OO_URL=${OBS_OO_URL:-http://127.0.0.1:5080}
UMAMI_URL=${OBS_UMAMI_URL:-http://127.0.0.1:3300}
GW_URL=${OBS_GW_URL:-http://$GW_BIND:8280}

mkdir -p "$O" && chmod 700 "$O"
GW_SUM=$(sha256sum "$O/Caddyfile" 2>/dev/null | cut -d' ' -f1 || true)
cp "$HERE/compose.yml" "$HERE/Caddyfile" "$O/"
if [ ! -f "$O/.env" ]; then
  ( umask 077; rnd() { openssl rand -hex "$1"; }
    printf '%s\n' "ZO_ROOT_USER_EMAIL=$CP_ADMIN_EMAIL" "ZO_ROOT_USER_PASSWORD=Zo9-$(rnd 24)" \
      "UMAMI_DB_PASSWORD=$(rnd 24)" "UMAMI_APP_SECRET=$(rnd 32)" "UMAMI_ADMIN_PASSWORD=$(rnd 24)" > "$O/.env" )
  ok ".env da observabilidade gerado (600; senhas de admin → cofre)"
fi

DC=(docker compose --project-directory "$O" --env-file "$O/.env" -f "$O/compose.yml")
[ -n "${OBS_COMPOSE_EXTRA:-}" ] && DC+=(-f "$OBS_COMPOSE_EXTRA")
OPENOBSERVE_IMAGE=$OPENOBSERVE_IMAGE UMAMI_IMAGE=$UMAMI_IMAGE CADDY_IMAGE=$CADDY_IMAGE OBS_BIND="$OBS_BIND" GW_BIND="$GW_BIND" \
  "${DC[@]}" up -d --quiet-pull --remove-orphans >/dev/null 2>&1 || die "observabilidade não subiu"

# Caddyfile é montado como arquivo: mudança de regra só vale depois de reiniciar o gateway.
if [ -n "$GW_SUM" ] && [ "$GW_SUM" != "$(sha256sum "$O/Caddyfile" | cut -d' ' -f1)" ]; then
  docker restart cp-observability-ingest-1 >/dev/null && ok "gateway reiniciado (regras novas)"
fi

wait_url() { for _ in $(seq 90); do curl -fsS -o /dev/null "$1" 2>/dev/null && return; sleep 2; done; die "$1 não respondeu"; }
wait_url "$OO_URL/healthz"
wait_url "$UMAMI_URL/api/heartbeat"
wait_url "$GW_URL/healthz"

# Umami nasce com admin/umami: troca pela senha do .env. Falha fechada: 200 = troca; 401 = já trocada (confirma
# que a do .env entra); qualquer outra resposta para aqui. No fim, sempre loga com a senha do .env.
umami_login() {  # $1 = senha; imprime "<status> <token>"
  jq -n --arg p "$1" '{username:"admin",password:$p}' | curl -s -o "$O/.umami-login.json" -w '%{http_code}' \
    -X POST -H 'content-type: application/json' --data @- "$UMAMI_URL/api/auth/login"
  printf ' %s\n' "$(jq -r '.token // empty' "$O/.umami-login.json" 2>/dev/null)"; rm -f "$O/.umami-login.json"
}
UPASS=$(. "$O/.env"; printf %s "$UMAMI_ADMIN_PASSWORD")
read -r UCODE UTOK < <(umami_login umami)
case "$UCODE" in
  200)
    jq -n --arg n "$UPASS" '{currentPassword:"umami",newPassword:$n}' \
      | curl -fsS -o /dev/null -X POST -H "authorization: Bearer $UTOK" -H 'content-type: application/json' \
        --data @- "$UMAMI_URL/api/me/password" || die "não consegui trocar a senha padrão do Umami"
    ok "Umami: senha padrão do admin trocada" ;;
  401) ;;
  *) die "Umami: login de verificação respondeu $UCODE (esperado 200 ou 401)" ;;
esac
read -r UCODE _ < <(umami_login "$UPASS")
[ "$UCODE" = 200 ] || die "Umami: a senha do .env não entra (status $UCODE) — conferir antes de expor o gateway"
unset UPASS UTOK
ok "OpenObserve $OO_URL · Umami $UMAMI_URL · ingestão $GW_URL"

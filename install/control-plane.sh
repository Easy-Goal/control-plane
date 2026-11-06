#!/bin/bash
# Instala/atualiza o control plane numa máquina Ubuntu 24.04 (ADR 064, fase A). Idempotente: rodar de novo
# só corrige o que falta. Roda NA máquina, como root:
#   CP_ADDR=<ip da tailnet> CP_ADMIN_EMAIL=<seu e-mail> bash control-plane.sh
#
#   CP_ADDR          endereço pelo qual as VPS de app alcançam o control plane (IP da tailnet; na sim 172.30.50.10).
#                    Vira o IP da instância no Coolify → URL do Sentinel de todo servidor novo.
#   CP_ADMIN_EMAIL   e-mail do usuário root do Coolify (senha: root:reset-password, nunca gerada aqui em claro)
#   CP_SIM=1         ensaio em container: pula firewall, unattended-upgrades e Tailscale
#   TS_AUTHKEY       (opcional, VPS real) entra na tailnet com tag:control-plane
#   BAO_TLS_SANS     (opcional) SANs extras do certificado do OpenBao, ex.: "DNS:cp.tail1234.ts.net"
#   GW_BIND          (opcional) onde o gateway de ingestão escuta; padrão 127.0.0.1 (o Funnel publica). Sim: CP_ADDR
#
# Nunca imprime segredo. O token do sync é gerado à parte (install/coolify-sync-token.sh) direto para o cofre.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/lib.sh"

: "${CP_ADDR:?defina CP_ADDR (IP da tailnet do control plane)}"
: "${CP_ADMIN_EMAIL:?defina CP_ADMIN_EMAIL}"
COOLIFY_VERSION=4.5.3
declare -A COOLIFY_SHA256=(
  [docker-compose.yml]=2532ee9258e10ad4e86cb3c2b46c29fe9329f5a0dace0f7da410744feec279bd
  [docker-compose.prod.yml]=f8b104aadfca48d0033fdee6cb87fea13c68bc5c67c63ba18b1934e9f901ff5d
  [.env.production]=7895e54f7c9d40063e76afec9b35839048d91e5c3b5107d64ea49ef6987c304a
)
need_root

step "1/7 sistema base"
ensure_packages ca-certificates curl jq openssl openssh-server
harden_ssh
ensure_docker
if [ "${CP_SIM:-0}" != 1 ]; then
  ensure_unattended_upgrades
  ensure_tailscale control-plane
  # Painel, API e cofre só pela tailnet. Docker publica portas por fora do ufw: tudo que o Coolify/OpenBao
  # publicam vai em CP_ADDR (tailnet), nunca em 0.0.0.0.
  ensure_ufw_tailnet_only
fi

step "2/7 Coolify $COOLIFY_VERSION (arquivos fixados por sha256)"
S=/data/coolify/source
mkdir -p $S /data/coolify/{ssh/keys,ssh/mux,applications,databases,backups,services,proxy/dynamic,webhooks-during-maintenance}
for f in "${!COOLIFY_SHA256[@]}"; do
  dest="$S/$f"; [ "$f" = .env.production ] && dest="$S/.env.production.dist"
  if [ ! -f "$dest" ] || ! echo "${COOLIFY_SHA256[$f]}  $dest" | sha256sum -c --quiet - 2>/dev/null; then
    curl -fsSL -o "$dest.tmp" "https://raw.githubusercontent.com/coollabsio/coolify/v$COOLIFY_VERSION/$f"
    echo "${COOLIFY_SHA256[$f]}  $dest.tmp" | sha256sum -c --quiet - || die "sha256 de $f não confere"
    mv "$dest.tmp" "$dest"
  fi
done
if [ ! -f $S/.env ]; then
  rnd() { openssl rand -hex "$1"; }
  ( umask 077
    sed -e "s|^APP_ID=.*|APP_ID=$(rnd 16)|" \
        -e "s|^APP_KEY=.*|APP_KEY=base64:$(openssl rand -base64 32)|" \
        -e "s|^DB_USERNAME=.*|DB_USERNAME=coolify|" \
        -e "s|^DB_PASSWORD=.*|DB_PASSWORD=$(rnd 24)|" \
        -e "s|^REDIS_PASSWORD=.*|REDIS_PASSWORD=$(rnd 24)|" \
        -e "s|^PUSHER_APP_ID=.*|PUSHER_APP_ID=$(rnd 16)|" \
        -e "s|^PUSHER_APP_KEY=.*|PUSHER_APP_KEY=$(rnd 16)|" \
        -e "s|^PUSHER_APP_SECRET=.*|PUSHER_APP_SECRET=$(rnd 16)|" \
        -e "s|^ROOT_USER_EMAIL=.*|ROOT_USER_EMAIL=|" -e "s|^ROOT_USER_PASSWORD=.*|ROOT_USER_PASSWORD=|" \
        $S/.env.production.dist > $S/.env )
  ok ".env do Coolify gerado (600; segredos próprios, ficam só nesta máquina)"
fi
# Chave do Coolify para o próprio host ("localhost" no painel).
K=/data/coolify/ssh/keys/id.root@host.docker.internal
[ -f $K ] || ssh-keygen -q -t ed25519 -N "" -C coolify-localhost -f $K
authorize_key "$(cat $K.pub)"
chown -R 9999:root /data/coolify && chmod -R 700 /data/coolify
docker network inspect coolify >/dev/null 2>&1 || docker network create --attachable coolify >/dev/null
# O painel escuta em 8000 em todas as interfaces do container; na VPS real o ufw/tailnet restringe.
(cd $S && LATEST_IMAGE=$COOLIFY_VERSION docker compose --env-file .env -f docker-compose.yml -f docker-compose.prod.yml \
  up -d --pull missing --quiet-pull --remove-orphans --wait >/dev/null 2>&1) || die "Coolify não subiu"
ok "Coolify $COOLIFY_VERSION no ar"

step "3/7 Coolify: pós-instalação (os 4 ajustes do ensaio)"
for _ in $(seq 60); do docker exec coolify php artisan tinker --execute='echo App\Models\Team::find(0) ? "ok" : "";' 2>/dev/null | grep -q ok && break; sleep 3; done
docker exec -e CP_ADDR="$CP_ADDR" -e CP_ADMIN_EMAIL="$CP_ADMIN_EMAIL" coolify \
  php artisan tinker --execute="$(cat "$HERE/coolify-post.php")" 2>/dev/null | grep '^\[' || die "pós-instalação do Coolify falhou"

step "4/7 OpenBao (TLS)"
B=/data/cp/openbao
mkdir -p $B/tls /data/cp/ca && chmod 700 /data/cp /data/cp/ca $B
cp "$HERE/openbao/compose.yml" "$HERE/openbao/config.hcl" $B/
C=/data/cp/ca   # chave da CA fora do volume montado no container
if [ ! -f $C/ca.crt ]; then
  # CA própria do control plane (na VPS real dá para trocar por `tailscale cert`).
  ( umask 077; cd $C
    openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -days 3650 -subj "/CN=cp-openbao-ca" \
      -keyout ca.key -out ca.crt 2>/dev/null )
  ok "CA do OpenBao criada"
fi
SANS="IP:$CP_ADDR,IP:127.0.0.1,DNS:localhost${BAO_TLS_SANS:+,$BAO_TLS_SANS}"
if [ ! -f $B/tls/server.crt ] || ! openssl x509 -in $B/tls/server.crt -noout -ext subjectAltName 2>/dev/null | grep -q "$CP_ADDR"; then
  ( umask 077; cd $C
    openssl req -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -subj "/CN=cp-openbao" -keyout $B/tls/server.key -out server.csr 2>/dev/null
    printf 'subjectAltName=%s\nextendedKeyUsage=serverAuth\n' "$SANS" > ext.cnf
    openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -days 825 -extfile ext.cnf -out $B/tls/server.crt 2>/dev/null
    rm -f server.csr ext.cnf )
  cp $C/ca.crt $B/tls/ca.crt
  chown -R 100:1000 $B/tls && chmod 600 $B/tls/server.key && chmod 644 $B/tls/server.crt $B/tls/ca.crt  # uid do openbao
  ok "certificado do OpenBao ($SANS)"
fi
(cd $B && BAO_BIND="${BAO_BIND:-$CP_ADDR}" CP_ADDR="$CP_ADDR" docker compose up -d --quiet-pull --wait >/dev/null 2>&1) || die "OpenBao não subiu"
ok "OpenBao no ar em https://$CP_ADDR:8200 (vazio ou selado: restaurar/abrir com cp-secrets restore|unseal)"

step "5/7 observabilidade (OpenObserve + Umami + gateway de ingestão)"
GW_BIND=${GW_BIND:-$([ "${CP_SIM:-0}" = 1 ] && echo "$CP_ADDR" || echo 127.0.0.1)}
CP_ADMIN_EMAIL="$CP_ADMIN_EMAIL" OBS_BIND="$CP_ADDR" GW_BIND="$GW_BIND" bash "$HERE/observability/setup.sh"
ok "painéis na tailnet: OpenObserve http://$CP_ADDR:5080 · Umami http://$CP_ADDR:3300"

step "6/7 conferência"
docker exec coolify php artisan tinker --execute='$s=App\Models\InstanceSettings::get(); echo "api=",json_encode($s->is_api_enabled)," registro=",json_encode($s->is_registration_enabled)," ip=",$s->public_ipv4,PHP_EOL;' 2>/dev/null | tail -1
curl -s --cacert $B/tls/ca.crt "https://127.0.0.1:8200/v1/sys/seal-status" | jq -r '"openbao: inicializado=\(.initialized) selado=\(.sealed)"'

step "7/7 próximos passos (na máquina do operador)"
cat <<EOF
  - CA do cofre:   copiar $C/ca.crt → control-plane/openbao/tls/<ambiente>-ca.crt (público)
  - cofre:         CP_BAO_ADDR=https://$CP_ADDR:8200 CP_BAO_CACERT=... scripts/cp-secrets restore <snapshot> | unseal
  - token do sync: bash install/coolify-sync-token.sh (aqui) | scripts/cp-secrets provider set <cli> <coolify> --stdin token --expires ...
  - senha do root: docker exec -it coolify php artisan root:reset-password
  - observabilidade (ADR 066):
      ssh root@<cp> bash -s openobserve < install/observability-cred.sh \\
        | scripts/cp-secrets provider set <conta> openobserve url=http://$CP_ADDR:5080 email=$CP_ADMIN_EMAIL ingest_url=https://<cp>.<tailnet>.ts.net --stdin password
      ssh root@<cp> bash -s umami < install/observability-cred.sh \\
        | scripts/cp-secrets provider set <conta> umami url=http://$CP_ADDR:3300 username=admin ingest_url=https://<cp>.<tailnet>.ts.net --stdin password
      ingestão pública: liberar funnel na ACL da tailnet → tailscale funnel --bg --https=443 http://127.0.0.1:8280
EOF

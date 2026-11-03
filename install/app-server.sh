#!/bin/bash
# Prepara uma VPS de app (dev compartilhada ou prd de projeto) para ser servidor remoto do Coolify central
# (ADR 064, fase A). Idempotente. Roda NA VPS, como root:
#   COOLIFY_PUBKEY="ssh-ed25519 AAAA... coolify-cp" SERVER_TAG=app-prd bash app-server.sh
#
#   COOLIFY_PUBKEY   chave pública que o Coolify usa para entrar (scripts/cp-coolify key)
#   SERVER_TAG       tag na tailnet (app-dev, app-prd, cliente-<x>) — a ACL decide quem fala com quem
#   PUBLIC_PORTS     portas abertas para a internet (ex.: "80 443" se a VPS serve tráfego público via proxy)
#   CP_SIM=1         ensaio em container: pula firewall, unattended-upgrades e Tailscale
#   TS_AUTHKEY       (opcional, VPS real) entra na tailnet
# O resto (proxy, redes, Sentinel) o próprio Coolify instala ao validar o servidor.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/lib.sh"
: "${COOLIFY_PUBKEY:?defina COOLIFY_PUBKEY (scripts/cp-coolify key)}"
need_root

step "VPS de app ($(hostname))"
ensure_packages ca-certificates curl openssh-server
harden_ssh
ensure_docker
authorize_key "$COOLIFY_PUBKEY"
# Rede padrão do destino no Coolify: bancos gerenciados e services "ligados à rede do servidor" entram nela.
# O Coolify só a cria ao instalar o proxy; sem proxy (ou antes dele) o start do banco falha.
docker network inspect coolify >/dev/null 2>&1 || { docker network create --attachable coolify >/dev/null; ok "rede docker coolify"; }
if [ "${CP_SIM:-0}" != 1 ]; then
  ensure_unattended_upgrades
  ensure_tailscale "${SERVER_TAG:-app}"
  ensure_ufw_tailnet_only
fi
ok "pronta: scripts/cp-coolify server add $(hostname) <ip na tailnet>"

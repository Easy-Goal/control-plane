#!/bin/bash
# Escreve SÓ a senha de admin da observabilidade no stdout, para ligar direto no cofre (nunca na tela):
#   ssh root@<cp> bash -s openobserve < install/observability-cred.sh | scripts/cp-secrets provider set ... --stdin password
#   ssh root@<cp> bash -s umami < install/observability-cred.sh | ...
set -euo pipefail
. /data/cp/observability/.env
case "${1:-}" in
  openobserve) printf '%s\n' "$ZO_ROOT_USER_PASSWORD" ;;
  umami) printf '%s\n' "$UMAMI_ADMIN_PASSWORD" ;;
  *) echo "uso: observability-cred.sh openobserve|umami" >&2; exit 2 ;;
esac

#!/usr/bin/env bash
# Gera o .env de bootstrap de um serviço do control plane, uma única vez, sem imprimir valores.
set -euo pipefail
service="${1:?uso: scripts/bootstrap-env.sh <servico>}"
dir="$(cd "$(dirname "$0")/.." && pwd)/$service"
env_file="$dir/.env"
[ -d "$dir" ] || { echo "serviço desconhecido: $service" >&2; exit 1; }
[ -e "$env_file" ] && { echo "$env_file já existe — não sobrescrevo (segredos em uso)." >&2; exit 1; }
umask 077
case "$service" in
  infisical)
    {
      echo "ENCRYPTION_KEY=$(openssl rand -hex 16)"
      echo "AUTH_SECRET=$(openssl rand -base64 32)"
      echo "POSTGRES_PASSWORD=$(openssl rand -hex 24)"
      echo "SITE_URL=http://localhost:8080"
    } > "$env_file"
    ;;
  *) echo "sem bootstrap definido para $service" >&2; exit 1 ;;
esac
echo "Gerado $env_file (permissão 600). Faça AGORA o backup offline dele (ENCRYPTION_KEY)."

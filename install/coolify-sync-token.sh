#!/bin/bash
# Gera um token novo do usuário de serviço cp-sync e revoga os anteriores (= rotação do token do sync).
# Roda NO control plane e escreve SÓ o token no stdout — ligar direto no cofre, nunca na tela:
#   ssh root@<cp> bash -s < install/coolify-sync-token.sh \
#     | scripts/cp-secrets provider set <cliente> <coolify> url=http://<cp>:8000 --stdin token --expires <data>
# DAYS (padrão 90) = validade do token; a data de vencimento sai no stderr.
set -euo pipefail
DAYS=${DAYS:-90}
docker exec -e DAYS="$DAYS" coolify php artisan tinker --execute='
$u = App\Models\User::where("email", "cp-sync@service.invalid")->firstOrFail();
$t = $u->createToken("cp-sync", ["read", "read:sensitive", "write", "deploy"], now()->addDays((int) env("DAYS")), 0);
$u->tokens()->where("name", "cp-sync")->where("id", "!=", $t->accessToken->id)->delete();
echo "TOKEN=", $t->plainTextToken, PHP_EOL;' 2>/dev/null | sed -n 's/^TOKEN=//p'
date -u -d "+$DAYS days" +%F >&2

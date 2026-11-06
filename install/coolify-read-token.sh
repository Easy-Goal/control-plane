#!/bin/bash
# Gera o token SÓ DE LEITURA do painel e revoga o anterior (ADR 067). Sem read:sensitive, write nem deploy.
# Roda NO control plane e escreve SÓ o token no stdout: ligar direto no cofre, nunca na tela.
#   ssh root@<cp> bash -s < install/coolify-read-token.sh \
#     | scripts/cp-secrets provider set easygoal coolify-read url=http://<cp>:8000 --stdin token --expires <data>
# Com CP_CLIENT=<cliente>: usa o usuário de serviço e o time do cliente, que precisam existir (coolify-sync-token.sh).
# Não mexe no token do sync. DAYS (padrão 90) = validade; a data de vencimento sai no stderr.
set -euo pipefail
DAYS=${DAYS:-90}
CP_CLIENT=${CP_CLIENT:-}
case "$CP_CLIENT" in
  easygoal) echo "easygoal usa o time 0: rode sem CP_CLIENT" >&2; exit 2 ;;
  "") ;;
  *[!a-z0-9-]*) echo "CP_CLIENT inválido: use o slug do cliente (a-z, 0-9 e hífen)" >&2; exit 2 ;;
esac
docker exec -e DAYS="$DAYS" -e CP_CLIENT="$CP_CLIENT" coolify php artisan tinker --execute='
$client = env("CP_CLIENT");
$teamId = 0;
$email = "cp-sync@service.invalid";
if ($client) {
    $teamId = App\Models\Team::where("name", $client)->where("personal_team", false)->firstOrFail()->id;
    $email = "cp-sync-$client@service.invalid";
}
$u = App\Models\User::where("email", $email)->firstOrFail();
$t = $u->createToken("cp-panel", ["read"], now()->addDays((int) env("DAYS")), $teamId);
$u->tokens()->where("name", "cp-panel")->where("id", "!=", $t->accessToken->id)->delete();
echo "TOKEN=", $t->plainTextToken, PHP_EOL;' 2>/dev/null | sed -n 's/^TOKEN=//p'
date -u -d "+$DAYS days" +%F >&2

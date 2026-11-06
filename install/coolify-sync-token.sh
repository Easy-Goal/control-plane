#!/bin/bash
# Gera um token novo do usuário de serviço do sync e revoga os anteriores dele (= rotação do token do sync).
# Roda NO control plane e escreve SÓ o token no stdout — ligar direto no cofre, nunca na tela:
#   ssh root@<cp> bash -s < install/coolify-sync-token.sh \
#     | scripts/cp-secrets provider set <cliente> <coolify> url=http://<cp>:8000 --stdin token --expires <data>
# Sem CP_CLIENT: time 0 (conta principal), usuário cp-sync.
# Com CP_CLIENT=<cliente>: time do cliente e usuário cp-sync-<cliente>, criados se faltarem (ADR 067). O token só enxerga
# esse time, e a rotação não afeta os outros clientes. Sempre passe CP_CLIENT para cliente: sem ele, o token é da conta principal.
#   ssh root@<cp> CP_CLIENT=<cliente> bash -s < install/coolify-sync-token.sh | scripts/cp-secrets provider set <cliente> coolify ...
# DAYS (padrão 90) = validade do token; a data de vencimento sai no stderr.
set -euo pipefail
DAYS=${DAYS:-90}
CP_CLIENT=${CP_CLIENT:-}
if [ -n "$CP_CLIENT" ] && [ "$CP_CLIENT" = "${CP_HOME_CLIENT:-}" ]; then echo "a conta principal usa o time 0: rode sem CP_CLIENT" >&2; exit 2; fi
case "$CP_CLIENT" in
  "") ;;
  *[!a-z0-9-]*) echo "CP_CLIENT inválido: use o slug do cliente (a-z, 0-9 e hífen)" >&2; exit 2 ;;
esac
docker exec -e DAYS="$DAYS" -e CP_CLIENT="$CP_CLIENT" coolify php artisan tinker --execute='
$client = env("CP_CLIENT");
$teamId = 0;
if ($client) {
    $team = App\Models\Team::where("name", $client)->where("personal_team", false)->first();
    if (! $team) {
        $team = new App\Models\Team;
        $team->forceFill(["name" => $client, "personal_team" => false, "show_boarding" => false])->save();
    }
    $teamId = $team->id;
    // O operador (usuário 0) também entra no time, para ver o cliente pelo seletor do painel do Coolify.
    App\Models\User::find(0)?->teams()->syncWithoutDetaching([$teamId => ["role" => "owner"]]);
    $email = "cp-sync-$client@service.invalid";
    $u = App\Models\User::where("email", $email)->first();
    if (! $u) {
        $u = App\Models\User::create(["email" => $email, "name" => "cp-sync $client (servico)",
            "password" => Illuminate\Support\Facades\Hash::make(Illuminate\Support\Str::random(64))]);
        $u->forceFill(["email_verified_at" => now()])->save();
        // O Coolify cria um time pessoal para cada usuário novo. O de serviço fica só no time do cliente.
        $personal = $u->teams()->pluck("teams.id");
        $u->teams()->detach();
        App\Models\Team::whereIn("id", $personal)->get()->each->delete();
        $u->teams()->attach($teamId, ["role" => "admin"]);
    }
} else {
    $u = App\Models\User::where("email", "cp-sync@service.invalid")->firstOrFail();
}
$t = $u->createToken("cp-sync", ["read", "read:sensitive", "write", "deploy"], now()->addDays((int) env("DAYS")), $teamId);
$u->tokens()->where("name", "cp-sync")->where("id", "!=", $t->accessToken->id)->delete();
echo "TOKEN=", $t->plainTextToken, PHP_EOL;' 2>/dev/null | sed -n 's/^TOKEN=//p'
date -u -d "+$DAYS days" +%F >&2

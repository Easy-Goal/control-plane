// Pós-instalação do Coolify (rodado por control-plane.sh via `php artisan tinker --execute`). Idempotente.
// Os 4 ajustes descobertos no ensaio (ADR 064 §2) + API ligada. Saída: linhas "[..]" sem segredo.
use App\Models\{InstanceSettings, Team, User};
use Illuminate\Support\Facades\{Cache, Hash};
use Illuminate\Support\Str;

$addr = env('CP_ADDR');
$email = env('CP_ADMIN_EMAIL');

// Root (id 0, dono do time 0). O seeder valida e-mail por DNS e falha sem rede/MX: criar direto.
// Senha aleatória descartada: o operador define com `php artisan root:reset-password`.
$root = User::find(0);
if (! $root) {
    $root = (new User)->forceFill(['id' => 0, 'name' => 'operador', 'email' => $email,
        'password' => Hash::make(Str::random(64))]);
    $root->save();
    echo "[ok] usuário root criado ($email) — definir senha: root:reset-password\n";
}
if (! $root->teams()->where('team_id', 0)->exists()) {
    $root->teams()->attach(0, ['role' => 'owner']);
}
// (2) e-mail verificado: sem SMTP o painel prenderia o login na tela de verificação.
if (! $root->email_verified_at) {
    $root->forceFill(['email_verified_at' => now()])->save();
}

// (1) Usuário de serviço do sync: trocar a senha de uma pessoa revoga TODOS os tokens de API dela
// (DeletesUserSessions). O token em si sai por coolify-sync-token.sh, direto para o cofre.
$svc = User::firstOrCreate(['email' => 'cp-sync@service.invalid'],
    ['name' => 'cp-sync (servico)', 'password' => Hash::make(Str::random(64))]);
$svc->forceFill(['email_verified_at' => $svc->email_verified_at ?? now()])->save();
if (! $svc->teams()->where('team_id', 0)->exists()) {
    $svc->teams()->attach(0, ['role' => 'admin']);
}

// (3) Assistente de primeira configuração desligado (servidores entram pela API). O time fica em cache 1h.
$team = Team::find(0);
if ($team->show_boarding) {
    $team->show_boarding = false;
    $team->save();
}
foreach ([0, $svc->id] as $uid) {
    Cache::forget("user:$uid:team:0");
}

// (4) IP da instância = endereço na tailnet: vira a URL do Sentinel de todo servidor remoto
// (sem isso o Coolify usa o IP público detectado, que as VPS não alcançam pela tailnet).
$s = InstanceSettings::get();
$s->is_api_enabled = true;
$s->is_registration_enabled = false;
$s->public_ipv4 = $addr;
$s->save();

echo "[ok] root verificado, cp-sync (admin), onboarding off, registro off, API on, IP da instância $addr\n";

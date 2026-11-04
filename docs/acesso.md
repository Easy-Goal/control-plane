# Acesso a cada ferramenta

Como entrar em cada painel, no laboratório e na VPS real, e de qualquer device.

## Sumário

- [Regra geral](#regra-geral)
- [Tabela de endereços](#tabela-de-endereços)
- [OpenBao (cofre)](#openbao-cofre)
- [Coolify](#coolify)
- [OpenObserve (logs)](#openobserve-logs)
- [Umami (analytics)](#umami-analytics)
- [Gateway de ingestão](#gateway-de-ingestão)
- [Uptime Kuma](#uptime-kuma)
- [Tailscale (admin)](#tailscale-admin)
- [Painéis externos: Vercel, Railway, Supabase, GitHub](#painéis-externos-vercel-railway-supabase-github)
- [Ver uma senha do cofre sem imprimir no chat](#ver-uma-senha-do-cofre-sem-imprimir-no-chat)
- [Acesso de qualquer device](#acesso-de-qualquer-device)

## Regra geral

- **Nenhum painel do control plane é público.** Na VPS real, tudo só pela **tailnet** (rede privada do Tailscale).
- O **único** ponto público é o gateway de ingestão, pelo **Tailscale Funnel**. Ele só aceita envio de logs e
  eventos do Umami. Login, consulta e painéis dão 404 por ele.
- No laboratório, tudo escuta em `127.0.0.1` da sua máquina.
- Senhas de admin ficam no cofre (`kv/easygoal/_providers/...`) ou no Bitwarden da Easy Goal. Nunca no chat.

## Tabela de endereços

`<cp>` = IP do control plane na tailnet (ex.: `100.x.y.z`, veja com `tailscale ip -4` na VPS) ou o nome MagicDNS
(`cp.<tailnet>.ts.net`).

| Ferramenta | Laboratório | VPS real (só tailnet) | Login |
|---|---|---|---|
| OpenBao, cofre principal local | `http://127.0.0.1:8200/ui/` | — (desligado depois do go-live) | token do operador |
| OpenBao, cofre do control plane | `https://127.0.0.1:8210/ui/` | `https://<cp>:8200/ui/` | token do operador |
| Coolify | `http://127.0.0.1:8000` | `http://<cp>:8000` | root (e-mail) + senha |
| OpenObserve | `http://127.0.0.1:5080` | `http://<cp>:5080` | e-mail do admin + senha do cofre |
| Umami | `http://127.0.0.1:3300` | `http://<cp>:3300` | `admin` + senha do cofre |
| Gateway de ingestão | `http://127.0.0.1:8280` | `https://<cp>.<tailnet>.ts.net` (Funnel, **público**) | sem login (token por app) |
| API staging do Health Stay (lab) | `http://127.0.0.1:3101/health/ready` | — | — |
| API prod do Health Stay (lab) | `http://127.0.0.1:3102/health/ready` | — | — |
| Registry do lab | `127.0.0.1:5001` | — | — |

## OpenBao (cofre)

**Para que serve:** fonte de verdade de todos os segredos, com audit de cada leitura. Ver [segredos.md](segredos.md).

**Como logar:** a UI não tem usuário e senha. O operador é uma AppRole; você gera um token de 1h e entra pelo
método **Token**.

```bash
scripts/cp-secrets ui-token              # cofre principal → http://127.0.0.1:8200/ui/
scripts/cp-lab cp-secrets ui-token       # cofre do lab   → https://127.0.0.1:8210/ui/
```

1. O token vai para a área de transferência (no WSL, `clip.exe`).
2. Abra a URL que o comando mostra, escolha **Method: Token** e cole.
3. Ao terminar: `scripts/cp-secrets ui-token --revoke`.

**Cuidados:**
- O token só vale no cofre que o emitiu (8200 ≠ 8210).
- O cofre do lab e o da VPS usam uma CA própria. O browser avisa "conexão não segura". Para tirar o aviso, importe
  `openbao/tls/sim-ca.crt` (lab) ou `openbao/tls/prod-ca.crt` (VPS) como autoridade confiável no browser.
- Diagnóstico de "permission denied": `scripts/cp-secrets audit 1`.

## Coolify

**Para que serve:** deploy das apps em todas as VPS (servidores remotos por SSH na tailnet), bancos gerenciados,
backups S3, logs por container e notificações (Discord).

**Como logar:** usuário root, com o e-mail do instalador (`CP_ADMIN_EMAIL`). O instalador **não** gera senha em
claro: você define uma com o `root:reset-password`.

```bash
# VPS real (e-mail: contato@easygoal.com.br)
ssh root@<cp> docker exec -it coolify php artisan root:reset-password

# laboratório (e-mail: operador@cp-sim.local)
docker exec -it cp-sim-sim-cp-1 docker exec -it coolify php artisan root:reset-password
```

Guarde a senha no Bitwarden da Easy Goal e ligue o 2FA no painel (Settings → Security).

**Cuidados:**
- **Nunca** use o token de API de um humano no sync. O sync usa o usuário de serviço `cp-sync`. Se você trocar a
  senha de um usuário, o Coolify revoga **todos** os tokens de API dele.
- O registro de novos usuários fica fechado pelo instalador.

## OpenObserve (logs)

**Para que serve:** logs, traces e métricas (OTLP) das apps. 1 org por cliente e ambiente (`easygoal_staging`,
`easygoal_prod`...), 1 stream por serviço. Painéis, alertas e SQL. Ver [observabilidade.md](observabilidade.md).

**Como logar:** e-mail do admin (`CP_ADMIN_EMAIL`; no lab, `operador@cp-sim.local`) + senha que está no cofre em
`kv/easygoal/_providers/openobserve` (lab: `openobserve-sim`), campo `password`. Para copiar sem mostrar, ver
[Ver uma senha do cofre](#ver-uma-senha-do-cofre-sem-imprimir-no-chat).

**Cuidados:**
- Na consulta SQL, stream com hífen vira underscore: `health-stay-api` → `health_stay_api`.
- No OSS todos os usuários têm acesso total (sem RBAC). Não crie usuário para terceiros.

## Umami (analytics)

**Para que serve:** analytics de produto sem cookie. 1 site por app/ambiente.

**Como logar:** usuário `admin` + senha do cofre em `kv/easygoal/_providers/umami` (lab: `umami-sim`), campo
`password`. O instalador já trocou a senha padrão (`admin/umami`).

## Gateway de ingestão

**Para que serve:** porta de entrada **pública** para as apps enviarem logs (`POST /api/<org>/v1/logs|traces|metrics`)
e para o tracker do Umami (`GET /script.js`, `POST /api/send`). Todo o resto responde 404.

**Como logar:** não tem login. Cada app usa o próprio token de ingestão (`OBS_OTLP_AUTHORIZATION`, gravado pelo
`cp-obs ingest`).

Teste rápido (lab):

```bash
curl -s http://127.0.0.1:8280/healthz        # → ok
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8280/web/   # → 404 (painel não passa)
```

Na VPS real, o Funnel publica o gateway (depois da ACL da tailnet, ver [observabilidade](observabilidade.md#contenção-do-token-de-ingestão)):

```bash
ssh root@<cp> tailscale funnel --bg --https=443 http://127.0.0.1:8280
```

## Uptime Kuma

**Ainda não existe.** Está previsto no ADR 064 (fase D) como serviço do Coolify para checar o `/health` de cada API e
de cada front, com alerta no Discord. Quando for instalado, entra por `http://<cp>:<porta>` só na tailnet, e a porta
precisa entrar na ACL do grupo de operadores. Esta seção será atualizada então.

## Tailscale (admin)

**Para que serve:** quem está na tailnet, tags (`tag:control-plane`, `tag:app-dev`, `tag:app-prd`,
`tag:cliente-<x>`), ACL (quem fala com quem), auth keys dos servidores, Funnel, MagicDNS e HTTPS.

**Como logar:** `https://login.tailscale.com/admin` com a conta da Easy Goal (SSO do provedor de identidade usado
na criação da tailnet). 2FA no provedor de identidade.

**Cuidados:**
- A auth key dos servidores deve ser reutilizável, de curta duração e pré-marcada com a tag.
- ACL mínima do control plane em [observabilidade](observabilidade.md#contenção-do-token-de-ingestão). Sem ela, não ligar o Funnel.
- Plano gratuito (Personal) é **não comercial**: ver [custos](custos.md#free-tier-com-limites).

## Painéis externos: Vercel, Railway, Supabase, GitHub

Esses painéis ficam nos provedores, não no control plane. Login humano (com 2FA) pelo Bitwarden da Easy Goal, ou o
do cliente quando a conta é dele (ver [conexões](conexoes.md#c-clientes-com-contas-próprias)).

| Painel | URL | Para quê | Credencial do control plane |
|---|---|---|---|
| Vercel | `https://vercel.com/dashboard` | fronts, env, domínios | token do time em `kv/<cliente>/_providers/vercel` (90 dias) |
| Railway | `https://railway.com/dashboard` | APIs até a migração | token de **workspace** em `kv/<cliente>/_providers/railway`; ids pelo Cmd/Ctrl+K |
| Supabase | `https://supabase.com/dashboard` | bancos/auth | ainda sem adaptador no sync (lacuna G4) |
| GitHub (org) | `https://github.com/Easy-Goal` | repos, Actions | GitHub App em `kv/<cliente>/_providers/github` |
| GitHub App | `https://github.com/organizations/Easy-Goal/settings/apps` | chave e instalação da App | ver [sync](sync.md#github-app-da-easy-goal) |

## Ver uma senha do cofre sem imprimir no chat

O `provider exec` põe cada campo do provedor no ambiente do comando como `CP_<CAMPO>`. Assim a senha vai direto para
a área de transferência, sem aparecer na tela.

```bash
# senha do OpenObserve do lab → área de transferência (WSL)
scripts/cp-secrets provider exec easygoal openobserve-sim -- sh -c 'printf %s "$CP_PASSWORD" | clip.exe'

# senha do Umami da VPS real
scripts/cp-secrets provider exec easygoal umami -- sh -c 'printf %s "$CP_PASSWORD" | clip.exe'
```

Fora do WSL, troque `clip.exe` por `wl-copy` (Linux) ou `pbcopy` (macOS). Cole no campo de senha do painel e limpe a
área de transferência depois. Para ver quais campos existem: `scripts/cp-secrets provider list easygoal`.

## Acesso de qualquer device

```
 notebook / celular / tablet                      VPS do control plane
 ┌──────────────────────────┐   tailnet (WireGuard)  ┌────────────────────────────┐
 │ app do Tailscale logado  │ ─────────────────────▶ │ Coolify :8000              │
 │ na tailnet da Easy Goal  │   só quem a ACL libera │ OpenObserve :5080          │
 │ (usuário em              │                        │ Umami :3300                │
 │  group:operadores)       │                        │ OpenBao :8200              │
 └──────────────────────────┘                        └─────────────┬──────────────┘
                                                                   │ :8280 (127.0.0.1)
 internet (qualquer um) ──▶ Funnel https://<cp>.<tailnet>.ts.net ──┘ só envio de logs/Umami
```

**Notebook (Windows, macOS, Linux):**
1. Instale o Tailscale e entre com a conta da tailnet da Easy Goal.
2. Seu usuário precisa estar no `group:operadores` da ACL.
3. Abra os endereços da coluna "VPS real" da [tabela](#tabela-de-endereços).
4. Para rodar os `scripts/` (cofre, sync), clone o `control-plane`, crie o `.venv`
   (`python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`) e copie o `openbao/.bootstrap.env`
   **por canal seguro**. Cada cópia do `.bootstrap.env` é uma credencial a mais: prefira uma só máquina de operador e
   rode `operator rotate` se uma cópia sair do seu controle.

**Celular ou tablet (iOS, Android):**
1. Instale o app do Tailscale e entre na mesma tailnet.
2. Abra no browser `http://<cp>:8000` (Coolify), `http://<cp>:5080` (OpenObserve) ou `http://<cp>:3300` (Umami).
3. O cofre (OpenBao) não tem como gerar token pelo celular: o `ui-token` roda só na máquina do operador. Use o celular
   para acompanhar deploys, logs e analytics; mudança de segredo, só no notebook.

**O que fica público (sem tailnet):** só o gateway, pelo Funnel. Webhooks futuros (`cp-events`, ADR 064) também
entrarão pelo Funnel, com assinatura conferida.

**Celular perdido:** remova o device em `https://login.tailscale.com/admin/machines`. Se ele tinha sessão aberta no
Coolify, troque a senha do root e revise o 2FA.

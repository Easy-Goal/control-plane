# Como cada tipo de app se conecta ao control plane

O control plane faz as mesmas ações (sync, rotate, logs, offboard) para qualquer app. O que muda é **de quem é a
conta** e **qual credencial** o cofre usa para falar com o provedor.

## Sumário

- [Visão geral](#visão-geral)
- [(a) Apps da Easy Goal no mesmo domínio](#a-apps-da-easy-goal-no-mesmo-domínio)
- [(b) Repos da mesma org do GitHub](#b-repos-da-mesma-org-do-github)
- [(c) Clientes com contas próprias](#c-clientes-com-contas-próprias)
- [(d) Logs e analytics de qualquer app](#d-logs-e-analytics-de-qualquer-app)
- [(e) Acesso de qualquer device](#e-acesso-de-qualquer-device)
- [Matriz: ação × provedor](#matriz-ação--provedor)

## Visão geral

- O cofre **empurra** (push) os segredos para cada plataforma e faz o redeploy. As apps **não** falam com o cofre
  para rodar: cofre selado não derruba nenhuma app.
- Cada plataforma é um **provedor** (`[[client.provider]]`) com uma credencial em `kv/<cliente>/_providers/<nome>`.
- Cada destino é um **target** (`[[client.project.target]]`) com uma allowlist `keys`: só essas chaves saem do cofre.

## (a) Apps da Easy Goal no mesmo domínio

Apps em `*.easygoal.com.br` (sso, app-front, api-backend, site-easygoal, LPs).

```
            navegador do usuário
                   │ cookie eg_session (domínio .easygoal.com.br)
     ┌─────────────┼──────────────┬────────────────┐
     ▼             ▼              ▼                ▼
   sso         app-front     api-backend      site/LPs
 (Vercel)      (Vercel)      (Railway → Coolify) (Vercel)
 assina        verifica      verifica + assina
     ▲             ▲              ▲
     └─────────────┴──────────────┘
           SSO_JWT_SECRET (grupo sso-global)
                   ▲
     cp-secrets rotate / sync  ◀── OpenBao (kv/easygoal/<projeto>/<ambiente>)
```

- **Login único:** o `sso` assina o cookie `eg_session` para `.easygoal.com.br`. sso, app-front, api-backend e
  `@easygoal/auth` verificam com o mesmo `SSO_JWT_SECRET`. O api-backend também assina (sessão, OAuth/refresh).
- **Segredo compartilhado:** `SSO_JWT_SECRET` é um `[[client.shared]]` (`sso-global`). Um `rotate` grava em todos os
  membros e sincroniza (verificadores primeiro, assinante por último). Ver [Rotacionar o SSO](comandos.md#rotacionar-o-sso).
- **Vercel:** provedor `vercel` (token do time, 90 dias). O sync grava as env como `sensitive` e faz redeploy da produção.
- **Coolify:** APIs que saírem da Railway viram services no Coolify; o sync grava e reinicia.

Exemplo (Vercel, com o target declarado no `secrets.toml`):

```bash
scripts/cp-secrets secret gen easygoal/app-front/prod CRON_SECRET
scripts/cp-secrets sync plan easygoal/app-front
scripts/cp-secrets sync apply easygoal/app-front
```

## (b) Repos da mesma org do GitHub

Repos em `github.com/Easy-Goal` que precisam de secret no **Actions** (ex.: `VERCEL_TOKEN` do CI).

```
 OpenBao ── kv/easygoal/_providers/github (app_id, installation_id, private_key)
    │
    │ cp-secrets sync: gera token de 1h restrito ao repo do target
    ▼
 GitHub App "control-plane-easy" ──▶ Easy-Goal/<repo> → Settings → Secrets (Actions ou environment)
                                      vale na próxima execução do workflow
```

- Sem PAT de pessoa: a GitHub App tem só **Secrets: Read and write** (+ Environments se usar `github_environment`).
- Segredo de **runtime** não vai para o GitHub (ADR 063). Só o que o CI precisa.
- Criar a App: [sync.md](sync.md#github-app-da-easy-goal).

```toml
[[client.project.target]]
name = "ci-secrets"
provider = "github"
environment = "prod"
repo = "Easy-Goal/site-easygoal"
keys = ["VERCEL_TOKEN", "VERCEL_ORG_ID", "VERCEL_PROJECT_ID"]
```

## (c) Clientes com contas próprias

ADR 063: **o cliente é dono das contas** (VPS, Vercel, GitHub, Supabase). A Easy Goal opera com tokens guardados no
cofre e entrega tudo no fim do contrato.

```
 Bitwarden do cliente ◀── credenciais humanas (login dos painéis, 2FA) + export no offboarding
                                         ▲
 OpenBao (Easy Goal)                     │ cp-secrets offboard <cliente>
 ├── kv/<cliente>/_providers/vercel   ───┼──▶ Vercel do cliente (time dele)
 ├── kv/<cliente>/_providers/github   ───┼──▶ GitHub App instalada na org dele
 ├── kv/<cliente>/_providers/coolify  ───┼──▶ Coolify central → VPS dele (tag:cliente-<x>)
 ├── kv/<cliente>/_providers/railway  ───┘──▶ Railway do cliente (até migrar)
 └── kv/<cliente>/<projeto>/<ambiente>       (segredos de runtime)
```

**Como declarar** (`openbao/secrets.toml`):

```toml
[[client]]
slug = "msm"

[[client.provider]]
name = "vercel"
kind = "vercel"          # token do time do cliente, com escopo e expiração

[[client.provider]]
name = "github"
kind = "github"          # mesma App da Easy Goal, installation_id da conta do cliente

[[client.project]]
slug = "frontend-app"
environments = ["dev", "prod"]
```

```bash
scripts/cp-secrets plan
scripts/cp-secrets apply
scripts/cp-secrets provider set msm vercel --stdin token --expires 2027-02-02
scripts/cp-secrets provider set msm github app_id=<id> installation_id=<id do cliente> --stdin private_key < app.pem
```

**As mesmas ações internas, para o cliente:**

| Ação | Comando | Como chega ao provedor do cliente |
|---|---|---|
| Sync | `scripts/cp-secrets sync apply msm` | API da Vercel/GitHub/Coolify/Railway com a credencial `kv/msm/_providers/*`, lida só pela identidade `cp-sync-msm` |
| Rotação | `scripts/cp-secrets rotate msm/<grupo> prod --apply` | igual, para cada membro do grupo |
| Logs | `scripts/cp-obs ingest msm/frontend-app/prod` | org `msm_prod` no OpenObserve da Easy Goal |
| Fim de contrato | `scripts/cp-secrets offboard msm --apply --yes msm` + `scripts/cp-obs revoke msm --apply` | export para o Bitwarden dele, revoga os tokens que o provedor permite, apaga `kv/msm/*` |

**Provedores com adaptador hoje:** `coolify`, `vercel`, `github`, `railway`. **Supabase ainda não tem adaptador**
(lacuna G4): chaves do Supabase do cliente são gravadas com `secret set` e propagadas para os outros destinos, mas a
geração e a revogação são no painel dele.

**VPS do cliente:** entra na tailnet com `tag:cliente-<x>` (`SERVER_TAG=cliente-msm` no `app-server.sh`). Pela ACL, só
o control plane fala com ela; VPS de clientes não se enxergam nem alcançam o cofre.

## (d) Logs e analytics de qualquer app

Qualquer app, em qualquer plataforma (Vercel, Coolify, Railway, outra nuvem do cliente), manda logs pela internet
para o gateway público. Ele só aceita **envio**.

```
 app (Vercel / Coolify / Railway / cliente)
   │ @easygoal/observability: OTLP/HTTP com OBS_OTLP_AUTHORIZATION (token por app/ambiente)
   ▼
 https://<cp>.<tailnet>.ts.net  (Tailscale Funnel, público)
   │ gateway Caddy: só POST /api/<org>/v1/{logs,traces,metrics}, GET /script.js, POST /api/send
   ▼
 OpenObserve: org <cliente>_<ambiente>  ─── consulta/painéis só na tailnet (:5080)
 Umami: site <cliente>/<projeto>/<ambiente> ─ painel só na tailnet (:3300)
```

- **1 org por cliente e ambiente** (`easygoal_staging`, `msm_prod`): token de dev vazado não lê prod.
- Os tokens vivem no cofre e chegam ao app pelo `sync`, como qualquer segredo. Ver [Ligar logs num app novo](comandos.md#ligar-logs-num-app-novo).
- Detalhes e contenção: [observabilidade.md](observabilidade.md).

## (e) Acesso de qualquer device

```
 notebook ┐                         ┌─▶ Coolify, OpenObserve, Umami, OpenBao (só tailnet, ACL group:operadores)
 celular  ┼── app do Tailscale ─────┤
 tablet   ┘   (tailnet Easy Goal)   └─▶ scripts/ (só na máquina do operador com o .bootstrap.env)

 qualquer um na internet ──▶ Funnel ──▶ só o gateway de envio
```

Passo a passo em [acesso.md](acesso.md#acesso-de-qualquer-device).

## Matriz: ação × provedor

| Provedor (`kind`) | Grava env | Redeploy | Lê o valor de volta | Revoga no offboard | Observação |
|---|---|---|---|---|---|
| `coolify` | sim (service/application) | sim, espera o `health_url` | sim | nada no provedor (o Coolify é da Easy Goal); manual: remover o servidor e a chave SSH | token de usuário de serviço, 90 dias |
| `vercel` | sim (`sensitive`) | sim, produção | não (compara por data) | automático: invalida o token | token do time, 90 dias (`team_id` opcional) |
| `github` | sim (Actions ou environment) | não (vale no próximo workflow) | não | automático: desinstala a App da conta | token de 1h por sync |
| `railway` | sim (`skipDeploys` + 1 redeploy) | sim, espera `SUCCESS` | sim | manual: Workspace Settings → Tokens (a API não expõe) | temporário até a migração; `NEEDS_APPROVAL` vira aviso |
| `supabase` | **sem adaptador** (G4) | — | — | — | painel do Supabase |
| `openobserve`, `umami` | não são destino | — | — | `cp-obs revoke` | credenciais do `cp-obs` |

# Go-live do control plane na VPS principal — audit e fases

> Audit de 2026-11-03 (s352), reorganizado em 2026-11-04 (s353). Objetivo: subir **Coolify + OpenBao +
> observabilidade** numa VPS real, que vira o lugar de onde todos os segredos do ecossistema são controlados e
> sincronizados. Com isso fica possível fazer a rotação geral de credenciais (Black October) e desligar a Railway.
> Os fronts continuam onde estão (Vercel) por enquanto. Base: ADRs 061–066 no `easy-labs` e o inventário dos repos
> locais em `~/projects/easy` e `~/projects/clients`.

## Sumário

1. [Resumo](#1-resumo)
2. [Como o control plane funciona](#2-como-o-control-plane-funciona)
3. [Decisões](#3-decisões)
4. [Inventário: o que precisa ir para o cofre](#4-inventário-o-que-precisa-ir-para-o-cofre)
5. [Lacunas no control-plane](#5-lacunas-no-control-plane)
6. [Fases do go-live](#fases-do-go-live)
   - [Fase 0 — Preparação](#fase-0--preparação)
   - [Fase 1 — VPS do control plane](#fase-1--vps-do-control-plane)
   - [Fase 2 — Cofre na VPS](#fase-2--cofre-na-vps)
   - [Fase 3 — Import de segredos](#fase-3--import-de-segredos)
   - [Fase 4 — Observabilidade](#fase-4--observabilidade)
   - [Fase 5 — PRs da chave dupla](#fase-5--prs-da-chave-dupla)
   - [Fase 6 — Rotação geral](#fase-6--rotação-geral)
   - [Fase 7 — Migração da Railway, serviço a serviço](#fase-7--migração-da-railway-serviço-a-serviço)
   - [Fase 8 — Alertas e painéis](#fase-8--alertas-e-painéis)
7. [Checklist de 1 página](#7-checklist-de-1-página)
8. [Limites deste audit](#limites-deste-audit)

Legenda: ✅ pronto · 🟡 em andamento ou parcial · ❌ não começou.

## 1. Resumo

| | Estado |
|---|---|
| Instaladores (`install/`) | ✅ prontos e idempotentes. A fase A reinstala o laboratório do zero em ~6 min com os mesmos scripts da VPS real |
| Cofre (OpenBao) + `cp-secrets` | ✅ pronto. Audit, policy por ambiente, AppRoles, `plan/apply`, `sync`, `rotate`, `offboard`, `backup/restore` |
| Operador do cofre principal | ✅ `operator rotate` rodado em 2026-11-04 (1 secret_id destruído, 6 tokens revogados); lab realinhado com `operator align` |
| Destinos do sync | ✅ Coolify, Vercel, GitHub Actions e **Railway** (G1, testado offline). ❌ **Supabase** sem adaptador |
| Banco + backup S3 + restore (fase B) | 🟡 codado. Staging ok; prod do laboratório em restart (`DEMO_USER_PASSWORD` vazio, G5) |
| Observabilidade (ADR 066, O1) | ✅ no lab e na [stack local](local.md): OpenObserve + Umami + gateway, com logs reais da API do Health Stay. ❌ na VPS real. Pacote `@easygoal/observability` no `main` do monorepo |
| Cofre cobre o ecossistema | ❌ só o **Health Stay** está no cofre. Os outros ~25 repos ainda vivem de `.env` local + painel de cada plataforma |
| Segredo compartilhado entre projetos | ✅ `[[client.shared]]` + `cp-secrets rotate` (G2, testado no laboratório) |
| Rotação sem derrubar sessões | 🟡 chave dupla codada nos 7 repos e **pushada** (G3, `feat/sso-jwt-chave-dupla`) — falta PR, merge e deploy |
| Chaves de unseal | 🟡 o `.init.json` saiu do disco ✅ e o unseal digitado já foi usado. Falta registrar o teste formal e copiar um snapshot para fora da máquina (G10) |
| Token da Vercel no cofre | ❌ venceu em 2026-10-30 |
| VPS real | ❌ não contratada (D1/D2 em aberto) |

**Ordem adotada em 2026-11-04 (s354):** operar localmente primeiro ([stack local](local.md)) → importar tudo para o
cofre local → contratar a VPS → levar o cofre por snapshot → rotacionar a partir dele → migrar a Railway serviço a
serviço. O cofre vai por snapshot, então a Fase 3 não depende da VPS e roda antes da Fase 1. CI (fase C do ADR 064) e
`cp report` (fase E) **não bloqueiam** o go-live. O Coolify faz deploy direto do GitHub pela App dele, e o mínimo de
alerta (Discord) entra junto com a VPS.

**Critério para contratar a VPS:**
- a stack sobe do zero, volta depois de reiniciar o Docker e abre com as chaves digitadas;
- todos os projetos estão no cofre, com o audit registrando as leituras;
- um restore do snapshot funciona, e há cópia fora da máquina;
- logs de uma app local chegam ao OpenObserve sem dado sensível, e o gateway devolve 404 para o painel;
- um evento chega ao Umami;
- o `sync plan` lista as divergências, e o `sync apply` só foi testado no laboratório ou em projeto descartável;
- logs e analytics abrem pelo celular, via `tailscale serve`.

## 2. Como o control plane funciona

O repo `control-plane` **não roda como um container**. Ele tem duas partes:

```
máquina do operador (WSL)                      VPS do control plane (tailnet, sem porta pública)
┌───────────────────────────┐   Tailscale   ┌──────────────────────────────────────────────┐
│ scripts/cp-secrets        │ ────────────▶ │ OpenBao (TLS, :8200)  ← fonte de verdade     │
│ scripts/cp-coolify        │ ────────────▶ │ Coolify (:8000)       ← deploy + env das VPS │
│ scripts/cp-obs            │ ────────────▶ │ OpenObserve (:5080), Umami (:3300)           │
│ openbao/secrets.toml (git)│               │ gateway :8280 ← único público (Funnel)       │
└───────────────────────────┘               └──────────┬───────────────────────────────────┘
                                                       │ SSH pela tailnet
            sync (push) ──▶ Vercel, GitHub Actions,    ▼
                            Railway, Supabase*       VPS de app (dev compartilhada, prd por projeto)
                            (* adaptador a criar)
```

- O script `install/control-plane.sh` **é** o "app": numa VPS Ubuntu limpa, ele instala e configura Coolify,
  OpenBao e a observabilidade, e rodar de novo só corrige.
- Os scripts `cp-*` rodam na sua máquina e falam com a VPS **só pela tailnet**. Os painéis também ficam só na tailnet
  (ver [acesso](acesso.md)).
- As apps **não dependem do cofre para rodar**. O `sync` grava as variáveis em cada plataforma e faz o redeploy. Se o
  cofre ficar selado, nenhuma app cai; você só não consegue mudar segredos.

## 3. Decisões

**Tomadas em 2026-11-03 (ADR 065):** D4 = adaptador Railway; D5 = chave dupla, com `--maintenance` para
o corte imediato quando for incidente; D6 = MSM, VayGo e demais clientes como clientes próprios no cofre.

### Abertas

| # | Decisão | Recomendação |
|---|---|---|
| D1 | Provedor/região da VPS do control plane | **DigitalOcean, Droplet Basic 2 vCPU / 4 GB, Ubuntu 24.04** (US$ 24/mês, conferido em 2026-11-04). Latência não importa para o CP, e a DO tem API, firewall e Spaces. Coolify + OpenBao + observabilidade cabem (ver [RAM medida](vps.md#o-que-roda-no-control-plane-e-quanta-ram)) |
| D2 | Onde ficam as **APIs** que saem da Railway | A DO **não tem região no Brasil**. Para APIs com usuário brasileiro e dado sensível (LGPD, saúde no Health Stay), prefira São Paulo: **Vultr SP**, **AWS Lightsail sa-east-1**, **Magalu Cloud** ou **Oracle SP** (Always Free ARM, mas pode recuperar instância ociosa). O Coolify gerencia qualquer uma delas. A VPS do CP pode ficar na DO mesmo assim |
| D3 | Backup S3 | **Cloudflare R2** (10 GB grátis, sem custo de download) |
| D4 | Railway durante a transição | **Adaptador Railway no `cp-secrets`** (seção 5, G1). Sem ele, a rotação dos serviços da Railway é manual no painel, sem audit |
| D5 | Rotação do SSO | **Implementar chave dupla antes** (G3). Sem isso, a rotação do `SSO_JWT_SECRET` é um corte: todo mundo deslogado e 6 deploys no mesmo minuto |
| D6 | Clientes no cofre | MSM e VayGo como **clientes próprios** (`[[client]] slug = "msm"` / `"vaygo"`), seguindo o ADR 063: offboarding limpo, e o Bitwarden do cliente guarda as credenciais humanas |
| D7 | Domínio dos painéis | Nenhum público. Acesso pela tailnet (`http://<cp>:<porta>`, ver [acesso](acesso.md)). O nome `https://<cp>.<tailnet>.ts.net` na porta 443 fica com o Funnel do gateway (Serve e Funnel não dividem porta); HTTPS nos painéis, se quiser, por `tailscale serve` em 8443 ou 10000. Webhooks, quando existirem, entram pelo Funnel |

## 4. Inventário: o que precisa ir para o cofre

Levantado do código (`process.env`, `os.getenv`, `.env.example`, compose). Mostra **só nomes**: nenhum `.env`
real foi lido. A plataforma vem de arquivos do repo e do contexto no `easy-labs`. O que tem ⚠ precisa ser
confirmado no painel.

### 4.1 Onde cada repo roda hoje

| Repo | Org GitHub | Hoje | Destino alvo |
|---|---|---|---|
| `api-backend` (prod + `api-dev`) | Easy-Goal | **Railway** | Coolify: prd na VPS da EG, dev na VPS dev |
| `vaygo-api` | VayGO-App | **Railway** (deploy com aprovação manual) | Coolify (VPS prd VayGo) |
| Evolution API (WhatsApp do `easyai-crm`) | — | **Railway** (template) | Coolify. ⚠ tem estado (sessões do WhatsApp): volume + banco |
| `speaches` (Whisper do VayGo), `ollama-translation` | — | **Railway** | Coolify (VPS dev ou prd VayGo; o Ollama precisa de RAM) |
| Redis (`REDIS_URL` de `api-backend`/`vaygo-api`) | — | **Railway** ⚠ | Coolify (Redis gerenciado) |
| `health-stay-backend` | Easy-Goal | local (piloto) | Coolify (já no cofre) |
| `sso`, `app-front`, `site-easygoal`, `easyai-crm`, `easy-ia`, LPs da EG | Easy-Goal | Vercel ⚠ | Vercel (sync) |
| `vaygo-web` | VayGO-App | Vercel | Vercel (sync) |
| `health-stay-frontend` | Easy-Goal | local | Vercel ou Coolify (decidir no go-live dele) |
| MSM `frontend-app`, `frontend-adm-app`, LPs | Msm-Editora (`lp-metodo-lucro-ativo`: **msmeditora-dev**) | Vercel ⚠ | Vercel (sync, cliente `msm`) |
| MSM `backend-api` (FastAPI + Celery + RabbitMQ) | Msm-Editora | **VPS própria** (Portainer/nginx), deploy por **SSH com senha** (`sshpass`) | Coolify gerenciando a VPS que já existe (`app-server.sh` nela) |

### 4.2 Credenciais por origem

> **Dois níveis de segredo do SSO** (confirmado no código):
> - **global** (`SSO_JWT_SECRET` do sso): assina o cookie `eg_session` de `.easygoal.com.br`. Quem verifica:
>   sso, app-front, api-backend e `@easygoal/auth`. O api-backend também **assina** (sessão e tokens OAuth/refresh).
> - **por app** (`api_apps.jwt_secret` no banco do SSO): o token é reassinado para o app externo. Na env dele,
>   `SSO_JWT_SECRET` é esse segredo do app: easyai-crm (produto Easy AI CRM) e vaygo-api + vaygo-web (o mesmo app).
>   Quem assina fica fora do cofre (é uma linha no banco): o `rotate` usa `signer = ""` e avisa o passo manual. (uma rotação na origem → N repos recebem pelo sync)

| Credencial (onde se gira) | Repos que consomem | Observação |
|---|---|---|
| `SSO_JWT_SECRET` global (gerada) | sso, app-front, api-backend (+ `@easygoal/auth`) | grupo `sso-global`, `rotate` gradual |
| `SSO_JWT_SECRET` por app (`api_apps.jwt_secret`) | easyai-crm · vaygo-api + vaygo-web | 1 grupo por app, `signer = ""` (salvar no SSO depois do sync) |
| `SSO_APP_SECRET` (app no SSO) | msm frontend-app, msm backend-api | gira no cadastro do app no SSO |
| `SECRET_KEY`, `WEBHOOK_SECRET` / `SSO_WEBHOOK_SECRET` (geradas) | sso ↔ app-front | o par precisa trocar junto |
| Supabase **EG PRD/DEV** (`SUPABASE_URL`, anon, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET`, `DATABASE_URL`) | sso, app-front, api-backend, lp-easy-club (anon), easyai-crm (`DATABASE_URL`) | ver G4: o JWT secret legado derruba todas as sessões |
| `SUPABASE_MANAGEMENT_TOKEN` (PAT da conta Supabase) | app-front | **alcance de conta inteira** → girar primeiro e avaliar se precisa existir |
| Supabase **VayGo** | vaygo-api | dev e prod compartilham o projeto (memória s303) |
| Supabase **MSM** | msm frontend-app (anon), frontend-adm-app (service role), backend-api (service key) | projeto do cliente |
| `INTERNAL_API_KEY` / `EASYGOAL_API_KEY` (geradas) | api-backend, vaygo-api | chamada serviço→serviço |
| `NEXT_PUBLIC_EASY_API_KEY` | app-front, easy-ia, easyai-crm, lp-easy-club, site-easygoal, vaygo-web, msm frontend-app | **pública por design** (vai no bundle). Girar é barato, mas é coordenado |
| `CRM_CAPTURE_API_KEY` / `_EMPRESA_ID` / `_URL` | lp-easy-demo, lp-easy-ia, 4 LPs da MSM | chave de captura do Easy CRM |
| Resend | sso, app-front, api-backend, vaygo-api, easyai-crm, lp-easy-ia (EG) · frontend-adm-app, lp-metodo-lucro-ativo (MSM ⚠ conta própria?) | 1 chave por app (Resend permite N chaves) |
| Mercado Pago (`ACCESS_TOKEN`, `_SANDBOX`, `WEBHOOK_SECRET`, comprador de teste) | api-backend | |
| AbacatePay (`API_KEY`, `WEBHOOK_SECRET`) | api-backend, app-front, vaygo-api | |
| Upstash (`UPSTASH_REDIS_REST_*`) | app-front, site-easygoal | |
| `REDIS_URL` | api-backend, vaygo-api | muda de qualquer jeito na migração |
| Discord (`BOT_TOKEN`, `CLIENT_SECRET`) | app-front | |
| Google service account (`GOOGLE_SERVICE_ACCOUNT_JSON`, `GOOGLE_CREDENTIALS_JSON_BASE64`, `GOOGLE_PRIVATE_KEY`) | app-front (GA4/GTM), vaygo-api, easyai-crm (Sheets) | nova chave na SA → apagar a antiga |
| HubSpot (`HUBSPOT_TOKEN`) | site-easygoal | |
| Anthropic, Gemini, RapidAPI, YMove, YouTube, VAPID | vaygo-api | VAPID trocado invalida as inscrições de push |
| Evolution (`EVOLUTION_API_KEY`, `EVOLUTION_WEBHOOK_TOKEN`) | easyai-crm | gira junto com a migração da Evolution |
| `CRON_SECRET` (gerada) | app-front, easyai-crm | |
| `PLAYWRIGHT_AUDIT_SECRET` (gerada) | vaygo-web | |
| Kiwify (`CLIENT_SECRET`), Meta CAPI (`ACCESS_TOKEN`) | msm frontend-adm-app, msm lp-calculadora-juridica | contas do cliente |
| RabbitMQ, Grafana (`*_PASS`), `DEV_SSH_*` do Actions | msm backend-api | o SSH com senha vira chave (G8) |
| Health Stay (`JWT_SECRET`, `AES_KEY`, `POSTGRES_PASSWORD`…) | health-stay-backend | ✅ já no cofre. `AES_KEY` **nunca** troca direto |
| Contas de plataforma: Railway, Vercel, Supabase PAT, GitHub App, DigitalOcean, Tailscale, R2 | operador (`kv/<cliente>/_providers/*`) | entram pelo `provider set ... --expires` |

### 4.3 Achados de segurança do inventário

1. **`sso/.env.example` documenta `NEXT_PUBLIC_SUPABASE_JWT_SECRET_KEY`.** O código não lê essa variável, então
   ela não vai para o bundle. Mas se estiver cadastrada na Vercel com esse prefixo, basta alguém referenciá-la
   uma vez para o segredo vazar no browser. **Apagar da Vercel e do `.env.example`.**
2. **`vaygo-web` lê `NEXT_PUBLIC_DEV_BYPASS_USER_ID` e `NEXT_PUBLIC_SKIP_SUBSCRIPTION_PAYWALL`**
   (`src/lib/auth-dev.ts`, `src/lib/api.ts`). Confirmar que **não existem** em Production na Vercel. O sync
   pode garantir isso: a allowlist de prod simplesmente não inclui essas chaves.
3. **MSM `backend-api` faz deploy com senha SSH** (`sshpass`, `StrictHostKeyChecking=no`). Trocar por chave (e,
   depois, pelo Coolify) e girar a senha da VPS.
4. Nenhum `.env` real está versionado nos repos inventariados ✅. Mesmo assim, rodar **gitleaks no histórico** de
   todos antes de declarar a rotação concluída: segredo antigo no histórico também é exposição.
5. A GitHub App `control-plane-easy` está em "all" com `organization_secrets: write` (risco já registrado no
   ADR 064). Na rotação, gerar uma private key nova e **remover `organization_secrets`** se não houver uso.


## 5. Lacunas no control-plane

O que falta codar ou configurar.

| # | Lacuna | Bloqueia | Tamanho |
|---|---|---|---|
| G1 ✅ | **Adaptador `railway`** em `cp_providers.py`: GraphQL público (`variableCollectionUpsert` + redeploy da instância), token de workspace | rotação com audit nos serviços da Railway | pequeno (o molde é o Vercel) |
| G2 ✅ | **Segredo compartilhado** no `cp-secrets`: `[[client.shared]]` + `cp-secrets rotate <cli>/<grupo> <env>`, que grava o valor novo no caminho de cada membro e sincroniza (assinante por último). Implementado assim no lugar do desenho original (`kv/<cliente>/_shared/<nome>` + `sync apply --shared`) | rotação do SSO/CRM/API key | médio |
| G3 🟡 | **Chave dupla no SSO**: os verificadores aceitam `SSO_JWT_SECRET` **ou** `SSO_JWT_SECRET_PREVIOUS`, e o emissor assina só com a atual. Codada nos 7 repos (`feat/sso-jwt-chave-dupla`), **pushada em s352**; falta PR, merge e deploy | rotação sem deslogar ninguém | médio |
| G4 | **Adaptador `supabase`** (Management API): migrar das chaves legadas (anon/service_role, ligadas ao JWT secret) para as **chaves novas** (`sb_publishable_…` / `sb_secret_…`), que se criam e revogam uma a uma sem derrubar sessão | rotação do Supabase sem corte | médio (a migração de chave toca o código de cada app) |
| G5 🟡 | Fase B: o compose de prod não pode passar `DEMO_USER_PASSWORD` vazio. O compose do backend foi corrigido e mergeado (Fase 2.4); falta revalidar no laboratório | fechar a fase B | pequeno |
| G6 | Import inicial: `import_env` dos `.env` locais de cada repo + **import da Vercel** (valores atuais → cofre, 1x). O adaptador Vercel hoje lê só nomes e datas, nunca valores. `.env` local costuma ter valor de dev: não rodar `sync apply` em produção antes de conferir | cofre como fonte de verdade | médio |
| G7 | `secrets.toml` com os clientes `msm` e `vaygo`, os projetos, ambientes, targets e allowlists de todos os repos da 4.1 | tudo acima | médio (só declarativo) |
| G8 | Deploy do MSM `backend-api`: chave SSH no lugar da senha → depois `app-server.sh` na VPS dele + Coolify | rotação da VPS MSM | pequeno |
| G9 | Alerta mínimo: notificação do Coolify → Discord (deploy falhou, container parado, backup, disco) | operar sem estar olhando | pequeno (configuração) |
| G10 🟡 | Teste de **unseal com as chaves digitadas** (sem `.init.json`) + `backup` copiado para fora da máquina. O `.init.json` já saiu do disco e o unseal digitado foi usado em s353 (correção `45f3a9a`); falta registrar o teste formal e o snapshot fora da máquina | migrar o cofre com segurança | manual, 15 min |


## Fases do go-live

Cada fase tem objetivo, estado, o que falta, passos **manuais** do fundador (separados), comandos e critério de
pronto. Os comandos rodam na raiz do `control-plane`, na sua máquina, salvo quando dizem "na VPS".
`<cp>` = IP ou nome do control plane na tailnet (ver [placeholders](comandos.md#placeholders)).

| Fase | O quê | Estado |
|---|---|---|
| 0 | Preparação: chaves, backup, contas | 🟡 |
| 1 | VPS do control plane | ❌ |
| 2 | Cofre na VPS | ❌ (ensaiado no lab ✅) |
| 3 | Import de segredos do ecossistema | ❌ |
| 4 | Observabilidade na VPS | 🟡 (O1 ✅ no lab) |
| 5 | PRs da chave dupla | 🟡 (7 branches pushadas) |
| 6 | Rotação geral | ❌ |
| 7 | Migração da Railway, serviço a serviço | ❌ (adaptador Railway ✅) |
| 8 | Alertas e painéis | ❌ |

### Fase 0 — Preparação

**Objetivo:** garantir que o cofre pode ser aberto e migrado, e que as contas existem.

**Estado:** 🟡. O `.init.json` saiu do disco e o unseal digitado já foi usado (s353). O operador do principal foi
rotacionado em 2026-11-04. Token da Vercel vencido desde 2026-10-30.

**O que falta:** registrar o teste de unseal (G10), snapshot fora da máquina, contas, decisões D1/D2.

**Passos manuais (fundador):**
1. Decidir D1 e D2 (comparação de preço e região em [vps.md](vps.md)).
2. Criar as contas, com 2FA:
   - provedor da VPS escolhido;
   - Tailscale: tailnet da Easy Goal, ACL com `tag:control-plane`, `tag:app-dev`, `tag:app-prd`, `group:operadores`
     e uma **auth key** reutilizável de curta duração para os servidores. Atenção ao plano: o Personal é não
     comercial ([custos](custos.md#pontos-de-atenção));
   - Cloudflare R2: bucket `cp-backups` e token S3 só desse bucket;
   - um webhook do Discord num canal `#alertas`.
3. Vercel: gerar token novo do time (90 dias).
4. Railway: gerar token de **workspace** (Account → Tokens). **Não** apagar nada ainda.
5. Se o `.bootstrap.env` estiver no Bitwarden, atualizar (o de antes do rotate de 2026-11-04 não vale).

**Comandos:**

```bash
# G10: unseal digitando 2 das 3 chaves do Bitwarden
docker restart cp-openbao-bao-1
scripts/cp-secrets unseal
scripts/cp-secrets status

# snapshot (copiar o .snap para o R2. No Bitwarden ficam só as chaves, como notas de texto: o plano grátis
# não mostra opção de anexar arquivo, e snapshot e chaves separados protegem melhor)
scripts/cp-secrets backup

# token novo da Vercel
scripts/cp-secrets provider set easygoal vercel --stdin token --expires "$(date -u -d '+90 days' +%F)"
```

Se o unseal falhar, **pare tudo**: sem essas chaves, o snapshot não abre na VPS.

**Pronto quando:** o unseal digitado funcionar, o snapshot estiver fora da máquina, as contas existirem e o
`status` mostrar o provedor `vercel` com validade.

### Fase 1 — VPS do control plane

**Objetivo:** VPS real com Coolify, OpenBao (vazio, TLS) e observabilidade, acessível só pela tailnet.

**Estado:** ❌. Instalador pronto e ensaiado no lab (fase A ✅).

**O que falta:** contratar e instalar.

**Passos manuais (fundador):**
1. Criar a VPS: Ubuntu 24.04, sua chave SSH, firewall do provedor **só com 22/tcp do seu IP** (temporário).
2. Depois do Tailscale ativo: **remover a regra 22/tcp** do firewall do provedor. A partir daqui, tudo pela tailnet.
3. Definir a senha do root do Coolify, guardar no Bitwarden e ligar o 2FA no painel.
4. Coolify → Notifications → Discord. Coolify → S3 Storages → R2.

**Comandos:**

```bash
# sua máquina: copiar os instaladores
scp -r install root@<ip público>:/opt/cp-install
```

```bash
# na VPS, como root: entrar na tailnet e instalar
curl -fsSL https://tailscale.com/install.sh | sh
tailscale up --authkey=<auth key> --advertise-tags=tag:control-plane
CP_ADDR=$(tailscale ip -4) CP_ADMIN_EMAIL=contato@easygoal.com.br TS_AUTHKEY=<auth key> \
  BAO_TLS_SANS="DNS:<nome>.<tailnet>.ts.net" bash /opt/cp-install/control-plane.sh
```

```bash
# sua máquina, pela tailnet: senha do root do Coolify (interativo)
ssh root@<cp> docker exec -it coolify php artisan root:reset-password
```

O instalador instala Docker, endurece o SSH (só chave), confirma a tailnet, liga o ufw só para a tailnet, instala o
Coolify 4.5.3 (arquivos conferidos por sha256), o OpenBao com TLS (CA em `/data/cp/ca`) e a observabilidade. No fim
imprime os próximos passos.

**Pronto quando:** `http://<cp>:8000` abre pela tailnet e não abre pelo IP público, e a etapa 6/7 do instalador
mostra `openbao: inicializado=false selado=true` (vazio, à espera do restore).

### Fase 2 — Cofre na VPS

**Objetivo:** o cofre principal passa a ser o da VPS, com os mesmos segredos e as mesmas chaves de unseal.

**Estado:** ❌ na VPS. ✅ ensaiado no lab (`sim/lab.sh up` restaura o snapshot do principal e abre com as chaves
originais).

**O que falta:** restore na VPS, token do sync, desligar o cofre local.

**Passos manuais (fundador):** digitar as chaves de unseal no `restore`.

**Comandos:**

```bash
scp root@<cp>:/data/cp/ca/ca.crt openbao/tls/prod-ca.crt
scripts/cp-secrets backup
CP_BAO_ADDR=https://<cp>:8200 CP_BAO_CACERT=openbao/tls/prod-ca.crt \
  scripts/cp-secrets restore openbao/backups/<snap>
```

```bash
# fixar o cofre da VPS no shell (ou no ~/.bashrc: os scripts só leem variáveis de ambiente)
export CP_BAO_ADDR=https://<cp>:8200
export CP_BAO_CACERT=$HOME/projects/easy/control-plane/openbao/tls/prod-ca.crt
scripts/cp-secrets status
```

```bash
# token do sync para o Coolify real
ssh root@<cp> bash -s < install/coolify-sync-token.sh \
  | scripts/cp-secrets provider set easygoal coolify url=http://<cp>:8000 --stdin token --expires "$(date -u -d '+90 days' +%F)"
scripts/cp-coolify servers
```

```bash
# desligar o cofre local (para não haver duas verdades)
cd openbao && docker compose down && cd ..
```

**Pronto quando:** `scripts/cp-secrets status` mostra `selado=False` e audit ativo contra a VPS,
`scripts/cp-coolify servers` lista o `localhost` usable e o cofre local está desligado.

### Fase 3 — Import de segredos

**Objetivo:** o cofre vira a fonte de verdade de **todo** o ecossistema (hoje só o Health Stay).

**Estado:** ❌. Lacunas G6 (import) e G7 (`secrets.toml` completo).

**O que falta:** declarar clientes, projetos, provedores e targets; importar `.env` locais e valores da Vercel.

**Passos manuais (fundador):**
1. Decidir, a cada divergência entre painel e cofre, qual valor vence **antes** de girar qualquer coisa.
2. Apagar os `.env` locais importados.
3. Conferir os itens ⚠ do inventário (4.1) no painel de cada plataforma.

**Comandos:**

```bash
# 1. editar openbao/secrets.toml: clientes easygoal, msm, vaygo; um [[client.project]] por repo da 4.1;
#    providers railway/vercel/github/coolify; um [[client.project.target]] por destino com a allowlist keys
scripts/cp-secrets plan
scripts/cp-secrets apply

# 2. credenciais de cada provedor de cada cliente
scripts/cp-secrets provider set easygoal railway --stdin token --expires <data>
scripts/cp-secrets provider set msm vercel --stdin token --expires <data>

# 3. conferir
scripts/cp-secrets sync plan
```

**Pronto quando:** o `sync plan` mostra **iguais** em todos os destinos e nenhum `.env` de prod está em disco. Dev local
passa a usar `cp-secrets run <identidade> -- <cmd>`.

### Fase 4 — Observabilidade

**Objetivo:** logs e analytics das apps chegando ao control plane real, com o gateway público só de envio.

**Estado:** 🟡. O1 ✅ no lab (stack, gateway, `cp-obs`, pacote). Na VPS sobe junto com a fase 1, mas falta ligar.

**O que falta:** credenciais de admin no cofre, ACL da tailnet, Funnel, push do pacote `@easygoal/observability`,
adoção nos apps (O2).

**Passos manuais (fundador):**
1. Na política da tailnet: a ACL de [contenção](observabilidade.md#contenção-do-token-de-ingestão), o atributo
   `funnel`, MagicDNS e HTTPS ligados. **Sem a ACL, não ligar o Funnel.**
2. Aprovar o push do monorepo (`feat/observability`).

**Comandos:**

```bash
ssh root@<cp> bash -s openobserve < install/observability-cred.sh \
  | scripts/cp-secrets provider set easygoal openobserve url=http://<cp>:5080 \
      email=contato@easygoal.com.br ingest_url=https://<cp>.<tailnet>.ts.net --stdin password
ssh root@<cp> bash -s umami < install/observability-cred.sh \
  | scripts/cp-secrets provider set easygoal umami url=http://<cp>:3300 \
      username=admin ingest_url=https://<cp>.<tailnet>.ts.net --stdin password
ssh root@<cp> tailscale funnel --bg --https=443 http://127.0.0.1:8280
scripts/cp-obs status
```

```bash
# primeiro app (piloto): Health Stay
scripts/cp-obs ingest easygoal/health-stay/staging
# OBS_* na allowlist do target no secrets.toml, depois:
scripts/cp-secrets sync apply easygoal/health-stay
```

**Pronto quando:** `cp-obs status` mostra OpenObserve, Umami e gateway ok; um `curl` de fora da tailnet em
`https://<cp>.<tailnet>.ts.net/web/` dá 404; e o Health Stay aparece com `docs > 0` no stream dele.

### Fase 5 — PRs da chave dupla

**Objetivo:** os verificadores do SSO aceitam a chave atual e a anterior em produção, para a rotação não deslogar
ninguém.

**Estado:** 🟡. Codado e **pushado** em 7 repos (`feat/sso-jwt-chave-dupla`, base `origin/main`): sso `bd95621`,
monorepo `7bd4887`, app-front `80b4261`, api-backend `8f87732`, easyai-crm `3b3fdbc`, vaygo-web `b8de29c`, vaygo-api
`9af8878`. Typecheck limpo e testes novos verdes.

**O que falta:** abrir os PRs, revisar, mergear e fazer deploy. O `@easygoal/auth` tem o `dist` versionado: quem o
consome precisa atualizar a dependência.

**Passos manuais (fundador):** revisar e mergear os PRs; aprovar o deploy da `vaygo-api` na Railway (aprovação manual).

**Comandos (por repo, na pasta dele):**

```bash
gh pr create --base main --head feat/sso-jwt-chave-dupla --title "feat(sso): chave dupla (SSO_JWT_SECRET_PREVIOUS)" --fill
```

Ordem de deploy: `@easygoal/auth` (monorepo) → app-front, api-backend, easyai-crm, vaygo-api, vaygo-web → sso por
último.

**Pronto quando:** os 7 estão em produção e um token assinado com o valor de `SSO_JWT_SECRET_PREVIOUS` é aceito em
cada verificador.

### Fase 6 — Rotação geral

**Objetivo:** cada credencial da [4.2](#42-credenciais-por-origem) com versão nova no cofre e a antiga revogada na origem
(Black October).

**Estado:** ❌. Depende das fases 2, 3 e 5 (e do G4 para o Supabase).

**Regra para cada item:** gerar o novo na origem → `secret set` ou `secret gen` no cofre → `sync apply` → conferir o
health → só então revogar o antigo na origem.

| Ordem | O quê | Como |
|---|---|---|
| 1 | Contas de plataforma: Railway, Vercel, Supabase PAT (`SUPABASE_MANAGEMENT_TOKEN`), GitHub App (private key nova), provedor da VPS, senha da VPS MSM | painel de cada uma → `provider set ... --expires` |
| 2 | Pagamentos: Mercado Pago, AbacatePay (+ webhook secrets) | painel → `secret set` → sync (api-backend, app-front, vaygo-api) |
| 3 | Supabase EG, VayGo e MSM: **chaves novas** (G4) e senha do banco (`DATABASE_URL`) | com o G4 pronto: criar `sb_secret_*`, sync, revogar a legada. **Sem o G4**, girar o JWT secret legado é corte (todas as sessões caem) |
| 4 | `SSO_JWT_SECRET` | **com a fase 5**: `rotate` gradual, e depois de ≥ 7 dias `--finish`. **Sem ela**: `--maintenance`, todo mundo loga de novo |
| 5 | Segredos internos: `INTERNAL_API_KEY`, `SECRET_KEY`, `WEBHOOK_SECRET`, `CRON_SECRET`, `CRM_CAPTURE_API_KEY`, `PLAYWRIGHT_AUDIT_SECRET`, `SSO_APP_SECRET` | `secret gen` → sync (o par/grupo junto) |
| 6 | Terceiros: Resend, Upstash, Discord, Google SA, HubSpot, Anthropic, Gemini, RapidAPI, YMove, YouTube, Evolution, Kiwify, Meta CAPI | painel → `secret set` → sync → revogar a antiga |
| 7 | `NEXT_PUBLIC_EASY_API_KEY` | pública: gira por último, coordenada com quem valida |
| — | **Não girar:** `AES_KEY` (Health Stay) e VAPID, salvo vazamento confirmado | `AES_KEY` exige recriptografar dados; trocar VAPID derruba as inscrições de push |

**Passos manuais (fundador):** gerar cada credencial nova no painel de origem e revogar a antiga depois do health ok;
resolver os achados da [4.3](#43-achados-de-segurança-do-inventário).

**Comandos (exemplos):**

```bash
scripts/cp-secrets backup
# projetos e chaves conforme declarados na fase 3 (nomes ilustrativos)
scripts/cp-secrets secret set easygoal/api-backend/prod MP_ACCESS_TOKEN
scripts/cp-secrets sync apply easygoal/api-backend
scripts/cp-secrets rotate easygoal/sso-global prod --apply
scripts/cp-secrets secret gen easygoal/app-front/prod CRON_SECRET
scripts/cp-secrets sync apply easygoal
scripts/cp-secrets audit 168
```

Depois: **gitleaks** no histórico de todos os repos.

**Pronto quando:** cada credencial da 4.2 tem versão nova no cofre, a antiga está revogada na origem, o `sync plan`
está limpo e o gitleaks não acha segredo vivo.

### Fase 7 — Migração da Railway, serviço a serviço

**Objetivo:** desligar a Railway.

**Estado:** ❌. Adaptador Railway ✅ (G1): durante a transição, o cofre já empurra para a Railway com audit.

**Pré-requisito:** VPS das APIs (D2) com `install/app-server.sh` e cadastrada no Coolify.

**Ordem, do menor risco ao maior:**
1. `speaches` (Whisper) e `ollama-translation`: sem estado, só troca a URL no cofre (`WHISPER_BASE_URL`,
   `OLLAMA_BASE_URL`).
2. Redis: Redis gerenciado do Coolify, novo `REDIS_URL` pelo cofre (cache e filas recomeçam vazios; avisar antes).
3. `api-backend` **dev** (`api-dev.easygoal.com.br`): ensaio completo de domínio + TLS pelo proxy do Coolify.
4. `vaygo-api` e `api-backend` **prod**: subir em paralelo, smoke test pela URL do Coolify, trocar o DNS, manter a
   Railway parada (não apagada) por uma semana.
5. Evolution API: tem as sessões do WhatsApp. Migrar volume e banco, ou reconectar os QR codes numa janela combinada
   com os corretores.

**Para cada serviço:** target novo no `secrets.toml` (provider `coolify`) → `sync apply` → DNS → remover o target
`railway` → apagar o serviço na Railway → revogar os tokens dele.

**Passos manuais (fundador):** contratar a VPS das APIs, trocar o DNS, combinar a janela da Evolution, apagar os
serviços e cancelar o plano da Railway.

**Comandos (exemplo com a api-backend dev):**

```bash
# na VPS das APIs, como root
COOLIFY_PUBKEY="<saída de scripts/cp-coolify key>" SERVER_TAG=app-prd TS_AUTHKEY=<auth key> \
  bash /opt/cp-install/app-server.sh
```

```bash
# sua máquina
scripts/cp-coolify server add vps-apis <ip tailnet>
scripts/cp-coolify service ensure api-backend dev vps-apis api-backend-dev <compose.yml>
scripts/cp-secrets sync plan easygoal/api-backend
scripts/cp-secrets sync apply easygoal/api-backend
```

**Pronto quando (Railway desligada):** nenhum target `railway` no `secrets.toml`, o token de workspace da Railway
revogado e a conta sem serviços (plano cancelado).

### Fase 8 — Alertas e painéis

**Objetivo:** operar sem estar olhando.

**Estado:** ❌. O mínimo (Coolify → Discord, G9) entra na fase 1.

**O que falta:**
- Uptime Kuma (ADR 064, fase D) no `/health` de cada API e front;
- O3 do ADR 066: painéis e alertas em código (4xx/5xx, `scan=true`, falha de login por `ip_hash`, bots → Discord),
  audit do OpenBao, `sync` e `rotate` no OpenObserve, rate limit no gateway;
- fase B fechada (G5) e o Health Stay na VPS prd dele;
- CI (fase C: Trivy bloqueante, gitleaks, SBOM) e `cp report`/`cp-events` (fase E), sem pressa.

**Passos manuais (fundador):** criar o canal `#alertas` e o e-mail de resumo (`contato@easygoal.com.br`).

**Comandos (revisão trimestral):**

```bash
scripts/cp-secrets status
scripts/cp-secrets audit 168
sim/lab.sh restore-test prod
```

**Pronto quando:** derrubar uma API de propósito gera alerta no Discord em minutos, e há painéis de tráfego e erros por
serviço no OpenObserve.

## 7. Checklist de 1 página

- [ ] Fase 0: unseal digitado registrado (G10) + snapshot fora da máquina · D1/D2 decididos
- [ ] Contas: VPS, Tailscale (tags + auth key + plano), R2, webhook do Discord, token Vercel novo, token Railway
- [ ] Fase 1: `control-plane.sh` → firewall só tailnet → senha + 2FA do Coolify → Discord + R2
- [ ] Fase 2: `restore` do cofre → token do sync → cofre local desligado; `CP_BAO_ADDR` aponta para a VPS
- [ ] Fase 3: G7 `secrets.toml` completo · G6 import → `sync plan` "iguais" em tudo
- [ ] Fase 4: credenciais de admin no cofre · ACL da tailnet · Funnel · Health Stay mandando logs
- [ ] Fase 5: 7 PRs da chave dupla mergeados e em produção
- [ ] Achados 4.3: variável `NEXT_PUBLIC_*SECRET*` apagada · flags de bypass fora de prod no vaygo-web · SSH com senha do MSM trocado
- [ ] G4 (Supabase chaves novas) feito — ou janela de manutenção aceita
- [ ] Fase 6: rotação na ordem da tabela, revogando a antiga só depois do health ok · gitleaks no histórico de todos os repos
- [ ] Fase 7: whisper/ollama → Redis → api-backend dev → vaygo-api/api-backend prod → Evolution → conta encerrada
- [ ] Fase 8: Uptime Kuma + alertas + painéis

## Limites deste audit

- A plataforma de cada repo vem do código e do contexto do `easy-labs`. Sem o CLI da Railway/Vercel e com o token
  da Vercel vencido, os itens ⚠ não foram conferidos no painel. O import da etapa 2 confirma tudo.
- `clients/msm-editora/backend-api` não entrou no inventário (o caminho não é um repo git acessível daqui).
- O inventário lista variáveis lidas pelo código. Uma variável que só existe no painel e nenhum código lê não
  aparece aqui, mas aparece no `sync plan` como "fora da allowlist".

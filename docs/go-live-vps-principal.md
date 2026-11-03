# Go-live do control plane na VPS principal — audit e roteiro

> Audit de 2026-11-03 (s352). Objetivo: subir **Coolify + OpenBao** numa VPS real, que vira o lugar de onde
> todos os segredos do ecossistema são controlados e sincronizados. Com isso fica possível fazer a rotação geral
> de credenciais (Black October) e desligar a Railway.
> Os fronts continuam onde estão (Vercel) por enquanto. Base: ADRs 061–064 no `easy-labs` e o inventário dos repos
> locais em `~/projects/easy` e `~/projects/clients`.

## 1. Resumo

| | Estado |
|---|---|
| Instaladores (`install/`) | ✅ prontos e idempotentes. A fase A reinstala o laboratório do zero em ~6 min com os mesmos scripts da VPS real |
| Cofre (OpenBao) + `cp-secrets` | ✅ pronto. Audit, policy por ambiente, AppRoles, `plan/apply`, `sync`, `offboard`, `backup/restore` |
| Destinos do sync | ✅ Coolify, Vercel e GitHub Actions. ❌ **Railway** e ❌ **Supabase** não têm adaptador |
| Banco + backup S3 + restore (fase B) | 🟡 codado. Staging ok; prod do laboratório em restart (`DEMO_USER_PASSWORD` vazio) |
| Cofre cobre o ecossistema | ❌ só o **Health Stay** está no cofre. Os outros ~25 repos ainda vivem de `.env` local + painel de cada plataforma |
| Segredo compartilhado entre projetos | ❌ o `cp-secrets` é por `projeto/ambiente`. O `SSO_JWT_SECRET` é o mesmo em 6 apps |
| Rotação sem derrubar sessões | ❌ o SSO só aceita **uma** chave. Trocar o `SSO_JWT_SECRET` desloga todo mundo e exige trocar os 6 apps ao mesmo tempo |
| Chaves de unseal | 🟡 o `.init.json` saiu do disco ✅. Ainda falta **testar** um unseal digitando as chaves do Bitwarden |
| Token da Vercel no cofre | ❌ venceu em 2026-10-30 |

**Caminho mais curto:** cofre na VPS → importar tudo para o cofre → rotacionar a partir dele → migrar a Railway
serviço a serviço. As fases C (CI), D (alertas) e E (`cp report`) do ADR 064 **não bloqueiam** o go-live. O
Coolify faz deploy direto do GitHub pela App dele, e o mínimo de alerta (Discord) entra junto.

## 2. Como o control plane funciona (o "app")

O repo `control-plane` **não roda como um container**. Ele tem duas partes:

```
máquina do operador (WSL)                      VPS do control plane (tailnet, sem porta pública)
┌───────────────────────────┐   Tailscale   ┌──────────────────────────────────────────────┐
│ scripts/cp-secrets        │ ────────────▶ │ OpenBao (TLS, :8200)  ← fonte de verdade     │
│ scripts/cp-coolify        │ ────────────▶ │ Coolify (:8000)       ← deploy + env das VPS  │
│ openbao/secrets.toml (git)│               │ Uptime Kuma, depois Loki/Grafana              │
└───────────────────────────┘               └──────────┬───────────────────────────────────┘
                                                       │ SSH pela tailnet
            sync (push) ──▶ Vercel, GitHub Actions,    ▼
                            Railway*, Supabase*      VPS de app (dev compartilhada, prd por projeto)
                            (* adaptador a criar)
```

- O script `install/control-plane.sh` **é** o "app": numa VPS Ubuntu limpa, ele instala e configura Coolify +
  OpenBao, e rodar de novo só corrige.
- Os scripts `cp-*` rodam na sua máquina e falam com a VPS **só pela tailnet**. O painel do Coolify e o do
  OpenBao também ficam acessíveis só pela tailnet.
- As apps **não dependem do cofre para rodar**. O `sync` grava as variáveis em cada plataforma e faz o
  redeploy. Se o cofre ficar selado, nenhuma app cai; você só não consegue mudar segredos.

## 3. Decisões que são suas (antes de começar)

| # | Decisão | Recomendação |
|---|---|---|
| D1 | Provedor/região da VPS do control plane | **DigitalOcean, Droplet Basic 2 vCPU / 4 GB, Ubuntu 24.04** (~US$ 24/mês, conferir). Latência não importa para o CP, e a DO tem API, firewall e Spaces. Coolify + OpenBao + Kuma cabem com folga |
| D2 | Onde ficam as **APIs** que saem da Railway | A DO **não tem região no Brasil**. Para APIs com usuário brasileiro e dado sensível (LGPD, saúde no Health Stay), prefira São Paulo: **Vultr SP**, **AWS Lightsail sa-east-1**, **Magalu Cloud** ou **Oracle SP** (Always Free ARM, mas pode recuperar instância ociosa). O Coolify gerencia qualquer uma delas. A VPS do CP pode ficar na DO mesmo assim |
| D3 | Backup S3 | **Cloudflare R2** (10 GB grátis, sem custo de download) |
| D4 | Railway durante a transição | **Adaptador Railway no `cp-secrets`** (seção 5, G1). Sem ele, a rotação dos serviços da Railway é manual no painel, sem audit |
| D5 | Rotação do SSO | **Implementar chave dupla antes** (G3). Sem isso, a rotação do `SSO_JWT_SECRET` é um corte: todo mundo deslogado e 6 deploys no mesmo minuto |
| D6 | Clientes no cofre | MSM e VayGo como **clientes próprios** (`[[client]] slug = "msm"` / `"vaygo"`), seguindo o ADR 063: offboarding limpo, e o Bitwarden do cliente guarda as credenciais humanas |
| D7 | Domínio dos painéis | Nenhum público. Acesso por `https://<cp>.<tailnet>.ts.net` (`tailscale cert`). Webhooks, quando existirem, entram pelo Tailscale Funnel |

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

### 4.2 Credenciais por origem (uma rotação na origem → N repos recebem pelo sync)

| Credencial (onde se gira) | Repos que consomem | Observação |
|---|---|---|
| `SSO_JWT_SECRET` (gerada) | sso, app-front, api-backend, easyai-crm, vaygo-api, vaygo-web (+ lib `easygoal-monorepo`) | **compartilhada** → G2/G3 |
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

## 5. Lacunas no control-plane (o que codar)

| # | Lacuna | Bloqueia | Tamanho |
|---|---|---|---|
| G1 | **Adaptador `railway`** em `cp_providers.py`: GraphQL público (`variableCollectionUpsert` + redeploy da instância), token de time | rotação com audit nos serviços da Railway | pequeno (o molde é o Vercel) |
| G2 | **Segredo compartilhado** no `cp-secrets`: `kv/<cliente>/_shared/<nome>` referenciado pelos targets (`shared = ["SSO_JWT_SECRET"]`) + `sync apply --shared <nome>` aplicando em todos os destinos de uma vez | rotação do SSO/CRM/API key | médio |
| G3 | **Chave dupla no SSO** (código de produto, precisa de aprovação): os verificadores aceitam `SSO_JWT_SECRET` **ou** `SSO_JWT_SECRET_PREVIOUS`, e o emissor assina só com a atual. Toca `sso`, `@easygoal/auth` (monorepo) e o verificador de cada app | rotação sem deslogar ninguém | médio |
| G4 | **Adaptador `supabase`** (Management API): migrar das chaves legadas (anon/service_role, ligadas ao JWT secret) para as **chaves novas** (`sb_publishable_…` / `sb_secret_…`), que se criam e revogam uma a uma sem derrubar sessão | rotação do Supabase sem corte | médio (a migração de chave toca o código de cada app) |
| G5 | Fase B: o compose de prod não pode passar `DEMO_USER_PASSWORD` vazio (compose por ambiente, ou o backend tratar vazio como ausente) | fechar a fase B | pequeno |
| G6 | Import inicial: `import_env` dos `.env` locais de cada repo + **import da Vercel** (valores atuais → cofre, 1x) | cofre como fonte de verdade | médio (o adaptador Vercel já lê) |
| G7 | `secrets.toml` com os clientes `msm` e `vaygo`, os projetos, ambientes, targets e allowlists de todos os repos da 4.1 | tudo acima | médio (só declarativo) |
| G8 | Deploy do MSM `backend-api`: chave SSH no lugar da senha → depois `app-server.sh` na VPS dele + Coolify | rotação da VPS MSM | pequeno |
| G9 | Alerta mínimo: notificação do Coolify → Discord (deploy falhou, container parado, backup, disco) | operar sem estar olhando | pequeno (configuração) |
| G10 | Teste de **unseal com as chaves digitadas** (sem `.init.json`) + `backup` copiado para fora da máquina | migrar o cofre com segurança | manual, 15 min |

## 6. Roteiro

Cada etapa termina com um critério de pronto. Os comandos rodam na raiz do `control-plane`, na sua máquina.

### Etapa 0 — Preparação (manual, ~1 dia)

1. **Chaves de unseal (G10).** Abra o cofre local digitando 2 das 3 chaves do Bitwarden:
   `docker restart cp-openbao-bao-1 && scripts/cp-secrets unseal`. Se falhar, **pare tudo**: sem essas chaves,
   o snapshot não abre na VPS.
2. **Backup:** `scripts/cp-secrets backup` → copiar o `.snap` de `openbao/backups/` para o Bitwarden (anexo) ou
   para o R2. Ele é cifrado e só abre com as chaves de unseal.
3. **Contas:**
   - DigitalOcean (D1), com 2FA;
   - Tailscale: tailnet da Easy Goal, ACL com `tag:control-plane`, `tag:app-dev`, `tag:app-prd` e uma **auth key**
     reutilizável de curta duração para os servidores;
   - Cloudflare R2: bucket `cp-backups` e token S3 só desse bucket;
   - um webhook do Discord num canal `#alertas`.
4. **Vercel:** token novo do time (90 dias) → `scripts/cp-secrets provider set easygoal vercel --stdin token --expires <+90d>`.
5. **Railway:** token de **time** (Account → Tokens) → guardar para o G1. **Não** apagar nada ainda.

✅ Pronto quando o unseal manual funcionar, o snapshot estiver fora da máquina e as contas existirem.

### Etapa 1 — Subir a VPS do control plane (~meio dia)

1. Criar o Droplet: Ubuntu 24.04, sua chave SSH, **Cloud Firewall da DO só com 22/tcp** do seu IP (temporário).
2. Na VPS, como root, com o repo copiado (`scp -r install root@<ip>:/opt/cp-install`). O instalador exige o
   `CP_ADDR` (IP da tailnet), então primeiro entre na tailnet para descobrir o IP:
   ```bash
   curl -fsSL https://tailscale.com/install.sh | sh
   tailscale up --authkey=<auth key> --advertise-tags=tag:control-plane
   CP_ADDR=$(tailscale ip -4) CP_ADMIN_EMAIL=contato@easygoal.com.br TS_AUTHKEY=<auth key> \
     BAO_TLS_SANS="DNS:<nome>.<tailnet>.ts.net" bash /opt/cp-install/control-plane.sh
   ```
   O script instala Docker, endurece o SSH (só chave), confirma a tailnet, liga o ufw só para a tailnet, instala o
   Coolify 4.5.3 (arquivos conferidos por sha256) e o OpenBao com TLS (CA em `/data/cp/ca`).
3. Com o Tailscale ativo: **remova a regra 22/tcp do Cloud Firewall**. A partir daqui, tudo passa pela tailnet.
4. Senha do root do Coolify: `ssh root@<cp> docker exec -it coolify php artisan root:reset-password`.
   Guarde no Bitwarden e ligue o 2FA no painel.
5. Migrar o cofre (o mesmo fluxo que a fase A ensaiou):
   ```bash
   scp root@<cp>:/data/cp/ca/ca.crt openbao/tls/prod-ca.crt
   scripts/cp-secrets backup
   CP_BAO_ADDR=https://<cp-tailnet>:8200 CP_BAO_CACERT=openbao/tls/prod-ca.crt \
     scripts/cp-secrets restore openbao/backups/<snap>      # pede as chaves de unseal digitadas
   ```
6. Token do sync para o Coolify real:
   ```bash
   ssh root@<cp> bash -s < install/coolify-sync-token.sh \
     | scripts/cp-secrets provider set easygoal coolify url=http://<cp-tailnet>:8000 --stdin token --expires <+90d>
   ```
7. Daqui em diante, **o cofre principal é o da VPS**. Exporte `CP_BAO_ADDR`/`CP_BAO_CACERT` no seu shell, ou em
   `~/.config/cp/env`. O cofre local (`127.0.0.1:8200`) fica desligado (`docker compose down` em `openbao/`)
   para não haver duas verdades.
8. Coolify → Notifications → Discord (G9). Coolify → S3 Storages → R2.

✅ Pronto quando `scripts/cp-secrets status` mostrar `selado=False` e audit ativo contra a VPS,
`scripts/cp-coolify servers` listar o `localhost` usable e o Discord receber a notificação de teste.

### Etapa 2 — Cofre como fonte de verdade do ecossistema (~2–3 dias, G1, G6, G7)

1. Codar o **G1** (adaptador Railway), validado contra um projeto descartável na Railway, do mesmo jeito que
   foi feito com a Vercel.
2. Declarar no `secrets.toml` (**G7**) os clientes `easygoal`, `msm` e `vaygo`, um `[[client.project]]` por repo
   da 4.1, os ambientes reais (`dev`/`prod` e `staging` onde existir), os providers (`railway`, `vercel`,
   `github`, `coolify`) e um `[[client.project.target]]` por destino com a allowlist `keys`.
3. **Import (G6):** `import_env` a partir dos `.env` locais (só cria o que falta) e import único da Vercel para o
   que só existe lá. Rodar `scripts/cp-secrets plan`, revisar e depois `apply`.
4. `scripts/cp-secrets sync plan` em tudo: precisa dar **"iguais"** em todos os destinos. Divergência aqui
   significa painel e cofre discordando, e você decide qual valor vence **antes** de girar qualquer coisa.
5. Apagar os `.env` locais que foram importados. Para dev local, use `cp-secrets run <identidade> -- <cmd>`.

✅ Pronto quando o `sync plan` mostrar todos os destinos sincronizados e nenhum `.env` de prod estiver em disco.

### Etapa 3 — Rotação geral (Black October)

Ordem por alcance: o que abre mais portas gira primeiro. Para cada item: **gerar o novo na origem → `secret set`
ou `secret gen` no cofre → `sync apply` → conferir o health → só então revogar o antigo na origem.**

| Ordem | O quê | Como |
|---|---|---|
| 1 | Contas de plataforma: Railway, Vercel, Supabase PAT (`SUPABASE_MANAGEMENT_TOKEN`), GitHub App (private key nova), DigitalOcean, senha da VPS MSM | painel de cada uma → `provider set ... --expires` |
| 2 | Pagamentos: Mercado Pago, AbacatePay (+ webhook secrets) | painel → `secret set` → sync (api-backend, app-front, vaygo-api) |
| 3 | Supabase EG, VayGo e MSM: **chaves novas** (G4) e senha do banco (`DATABASE_URL`) | com o G4 pronto: criar `sb_secret_*`, sync, revogar a legada. **Sem o G4**, girar o JWT secret legado é corte (todas as sessões caem) |
| 4 | `SSO_JWT_SECRET` | **com o G3**: `SSO_JWT_SECRET_PREVIOUS` ← atual, `SSO_JWT_SECRET` ← novo, sync shared (G2), e depois de 1 TTL de sessão apagar o `PREVIOUS`. **Sem o G3**: janela de manutenção, sync dos 6 apps em sequência, todo mundo loga de novo |
| 5 | Segredos internos: `INTERNAL_API_KEY`, `SECRET_KEY`, `WEBHOOK_SECRET`, `CRON_SECRET`, `CRM_CAPTURE_API_KEY`, `PLAYWRIGHT_AUDIT_SECRET`, `SSO_APP_SECRET` | `secret gen` → sync (o par/grupo junto) |
| 6 | Terceiros: Resend, Upstash, Discord, Google SA, HubSpot, Anthropic, Gemini, RapidAPI, YMove, YouTube, Evolution, Kiwify, Meta CAPI | painel → `secret set` → sync → revogar a antiga |
| 7 | `NEXT_PUBLIC_EASY_API_KEY` | pública: gira por último, coordenada com quem valida |
| — | **Não girar:** `AES_KEY` (Health Stay) e VAPID, salvo vazamento confirmado | `AES_KEY` exige recriptografar dados; trocar VAPID derruba as inscrições de push |

Depois: rodar **gitleaks** no histórico de todos os repos e conferir o `cp-secrets audit` (quem leu o quê).

✅ Pronto quando cada credencial da 4.2 tiver versão nova no cofre, a antiga estiver revogada na origem e o
`sync plan` estiver limpo.

### Etapa 4 — Sair da Railway, serviço a serviço (~1–2 semanas)

Pré-requisito: a VPS das APIs (D2) com `install/app-server.sh` e cadastrada no Coolify
(`scripts/cp-coolify server add`).

Ordem, do menor risco ao maior:
1. `speaches` (Whisper) e `ollama-translation`: sem estado, só troca a URL no cofre (`WHISPER_BASE_URL`,
   `OLLAMA_BASE_URL`).
2. Redis: Redis gerenciado do Coolify, novo `REDIS_URL` pelo cofre (cache e filas recomeçam vazios; avisar antes).
3. `api-backend` **dev** (`api-dev.easygoal.com.br`): ensaio completo de domínio + TLS pelo proxy do Coolify.
4. `vaygo-api` e `api-backend` **prod**: subir em paralelo, smoke test pela URL do Coolify, trocar o DNS, manter a
   Railway parada (não apagada) por uma semana.
5. Evolution API: tem as sessões do WhatsApp. Migrar volume e banco, ou reconectar os QR codes numa janela
   combinada com os corretores.

Para cada serviço: target novo no `secrets.toml` (provider `coolify`) → `sync apply` → DNS → remover o target
`railway` → apagar o serviço na Railway → revogar os tokens dele.

✅ Pronto (**Railway desligada**) quando nenhum target `railway` existir no `secrets.toml`, o token de time da
Railway tiver sido revogado e a conta estiver sem serviços (cancelar o plano).

### Etapa 5 — Depois do go-live

- Fechar a fase B (G5) e levar o Health Stay para a VPS prd dele.
- Fases C (CI com Trivy bloqueante), D (Loki/Alloy/Grafana) e E (`cp report`, `cp-events`) do ADR 064, sem pressa.
- Os fronts continuam na Vercel com sync. Mover para Coolify só se o custo da Vercel justificar.
- Revisão trimestral: `cp-secrets status` (validade dos tokens), teste de restore do cofre e de um banco.

## 7. Checklist de 1 página

- [ ] G10: unseal digitado ok + snapshot fora da máquina
- [ ] Contas: DigitalOcean, Tailscale (tags + auth key), R2, webhook do Discord, token Vercel novo, token Railway
- [ ] VPS CP: `control-plane.sh` → firewall só tailnet → senha + 2FA do Coolify → `restore` do cofre → token do sync → Discord + R2
- [ ] Cofre local desligado; `CP_BAO_ADDR` aponta para a VPS
- [ ] G1 Railway · G7 `secrets.toml` completo · G6 import → `sync plan` "iguais" em tudo
- [ ] Achados 4.3: variável `NEXT_PUBLIC_*SECRET*` apagada · flags de bypass fora de prod no vaygo-web · SSH com senha do MSM trocado
- [ ] G3 (SSO chave dupla) e G4 (Supabase chaves novas) aprovados e feitos — ou janela de manutenção aceita
- [ ] Rotação na ordem da etapa 3, revogando a antiga só depois do health ok
- [ ] gitleaks no histórico de todos os repos
- [ ] Railway: whisper/ollama → Redis → api-backend dev → vaygo-api/api-backend prod → Evolution → conta encerrada

## Limites deste audit

- A plataforma de cada repo vem do código e do contexto do `easy-labs`. Sem o CLI da Railway/Vercel e com o token
  da Vercel vencido, os itens ⚠ não foram conferidos no painel. O import da etapa 2 confirma tudo.
- `clients/msm-editora/backend-api` não entrou no inventário (o caminho não é um repo git acessível daqui).
- O inventário lista variáveis lidas pelo código. Uma variável que só existe no painel e nenhum código lê não
  aparece aqui, mas aparece no `sync plan` como "fora da allowlist".

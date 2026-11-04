# control-plane

Infra do control plane da Easy Goal (ADRs 061–064 no `easy-labs`): os serviços que vão rodar na VPS
(Coolify, segredos, observabilidade) e os instaladores. Hoje roda na máquina de dev (`10home`): cofre
principal local + laboratório `sim/` instalado pelos mesmos scripts que vão para a VPS real.
Só infra e estado desejado; nenhum segredo versionado.

> Roteiro para a VPS real e rotação geral: [`docs/go-live-vps-principal.md`](docs/go-live-vps-principal.md).

## Serviços

| Serviço | Pasta | Acesso | Estado |
|---|---|---|---|
| OpenBao (segredos + audit) | `openbao/` | `http://127.0.0.1:8200` (só local) | etapa 2 |
| Laboratório: control plane + VPS dev + VPS prd + registry | `sim/` | Coolify `127.0.0.1:8000`, cofre do CP `https://127.0.0.1:8210`, API staging `127.0.0.1:3101` | fase A (ADR 064) |
| Observabilidade: OpenObserve + Umami + gateway de ingestão | `install/observability/` | lab: OpenObserve `127.0.0.1:5080`, Umami `127.0.0.1:3300`, ingestão `127.0.0.1:8280` | ADR 066 |

## Segredos — OpenBao (`scripts/cp-secrets`)

Por que OpenBao (ADR 062): audit log de cada leitura e política por caminho (uma identidade lê
exatamente um projeto/ambiente) sem licença paga. O Infisical gratuito não tem nenhum dos dois.

```bash
cd openbao && docker compose up -d --wait && cd ..
scripts/cp-secrets init      # 1x: chaves de unseal → openbao/.init.json, operador → openbao/.bootstrap.env, revoga root
scripts/cp-secrets status    # selado? audit ativo? .init.json ainda em disco?
scripts/cp-secrets unseal    # depois de reiniciar o Docker (o cofre volta SELADO)
scripts/cp-secrets ui-token  # token do operador (1h) copiado para a área de transferência → UI, método Token
scripts/cp-lab cp-secrets ui-token   # o mesmo contra o cofre do laboratório (https://127.0.0.1:8210)
```

A UI do OpenBao não tem usuário e senha: o operador é uma AppRole, e o token só vale no cofre que o
emitiu. `scripts/cp-lab <script> ...` roda qualquer script contra o laboratório.

**Revogar acesso do operador** (o token da UI vence em 1h, renovável até 4h; o `secret_id` do
`.bootstrap.env` **não vence**):

```bash
scripts/cp-secrets ui-token --revoke    # revoga todos os tokens vivos do operador (UI e scripts em andamento)
scripts/cp-secrets operator rotate      # secret_id novo testado e gravado, destrói os outros, revoga os tokens
```

O `operator rotate` grava a credencial nova antes de destruir a antiga (se cair no meio, o arquivo já vale). Cofre
do lab é restaurado do principal e tem o mesmo operador: para ensaiar lá sem invalidar o principal, use
`CP_BAO_BOOTSTRAP=<cópia> scripts/cp-lab cp-secrets operator rotate`.

**Estado desejado** em `openbao/secrets.toml` (projetos, ambientes, repos com `.env` a importar,
identidades de runtime — só nomes):

```bash
scripts/cp-secrets plan      # o que mudaria (não altera nada)
scripts/cp-secrets apply     # policies <proj>-<env>-read, AppRoles de runtime, import de .env (idempotente)
scripts/cp-secrets audit 24  # leituras por identidade/ambiente, negados, todas as operações
scripts/cp-secrets backup    # snapshot do raft em openbao/backups/ (cifrado; copiar para fora da máquina)
```

**Rodar uma app sem `.env` em disco** (mesmo fluxo da VPS):

```bash
cd ~/projects/easy/health-stay-backend
~/projects/easy/control-plane/scripts/cp-secrets run health-stay-api-dev -- \
  docker compose --env-file /dev/null --profile full up -d --build --wait db migrate api
```

O `run` faz login com a AppRole (`openbao/runtime/<identidade>.env`), lê `kv/<projeto>/<ambiente>`,
revoga o token e executa o comando com as variáveis no ambiente do processo.

## Push para os destinos — `sync` (ADR 063)

Modelo principal em servidor: o cofre é a fonte de verdade e o `sync` **empurra** para cada destino
(Coolify das VPS, Vercel…) e faz o redeploy. As apps não dependem do cofre para rodar: cofre selado só
bloqueia mudanças. O `run` (pull) fica para dev local.

```bash
scripts/cp-secrets provider set easygoal coolify-sim url=http://127.0.0.1:8000   # token pedido oculto
scripts/cp-secrets provider list easygoal            # campos, sem valores
scripts/cp-secrets secret gen easygoal/health-stay/staging JWT_SECRET   # interna: gera nova versão
scripts/cp-secrets secret set easygoal/health-stay/prod MP_TOKEN        # de um painel: pede oculto
scripts/cp-secrets sync plan                         # diff por nome/versão (nunca valor) + divergências
scripts/cp-secrets sync apply easygoal/health-stay   # grava, redeploy, espera o health_url
```

- **Token do Coolify = usuário de serviço próprio** (`cp-sync`, membro admin do time, senha aleatória
  descartada, token com expiração), nunca o de um humano: o Coolify revoga **todos** os tokens de API do
  usuário quando a senha dele muda (`DeletesUserSessions`). Trocar a senha do operador derrubou o sync com 401.
- `[[client.project.target]]` define destino, ambiente e **allowlist `keys`** (obrigatória): o resto do
  ambiente nunca sai do cofre.
- A versão sincronizada fica no `custom_metadata` do caminho (`sync.<target>`) e só é anotada depois de um
  redeploy que deu certo; se falhou, o próximo `apply` refaz (`--redeploy` força).
- Divergência (alguém mudou no painel do destino): o `plan` avisa e o `apply` restaura o valor do cofre.
  Variáveis fora da allowlist não são tocadas.
- Identidade `cp-sync-<cliente>`: lê só `kv/<cliente>/*` e anota metadata; não escreve segredo.

- `cp-secrets status` mostra tudo numa tela por cliente: credenciais de operação com validade
  (`provider set ... --expires AAAA-MM-DD`, aviso a 15 dias) e cada destino com a versão do cofre ×
  sincronizada. Só lê o cofre; divergência no destino é com `sync plan`.

**Destinos** (`kind` do provedor): `coolify` (service/application, redeploy + health), `vercel` (env
`sensitive`, redeploy da produção), `github` (secrets do Actions do repo ou de um environment; sem redeploy,
vale na próxima execução), `railway` (temporário até a migração: variáveis de um service num environment,
token de **workspace**, ids `railway_project/environment/service` copiados com Cmd/Ctrl+K no painel; grava com
`skipDeploys`, faz um redeploy só e espera `SUCCESS`; service com aprovação manual para em `NEEDS_APPROVAL`
com aviso; referências `${{...}}` da Railway ficam fora da allowlist). O GitHub precisa do `.venv` (`python3 -m venv .venv && .venv/bin/pip install -r
requirements.txt`); o `cp-secrets` reexecuta nele sozinho.

**GitHub App da Easy Goal** (acesso aos secrets sem PAT de pessoa; criar 1x na org):
1. `github.com/organizations/Easy-Goal/settings/apps/new` — webhook **desligado**; permissões de repositório
   só **Secrets: Read and write** (+ **Environments: Read and write** se usar `github_environment`;
   Metadata: read é obrigatória). Instalação: "Only on this account" até o primeiro cliente precisar.
2. Anotar o **App ID**, gerar a **private key** (.pem) e instalar em **Only select repositories**. O id da
   instalação está na URL (`.../settings/installations/<id>`).
3. `scripts/cp-secrets provider set easygoal github app_id=<id> installation_id=<id> --stdin private_key < arquivo.pem`
   e `shred -u arquivo.pem`. Cada sync gera um token de 1h restrito ao repo do target e o descarta no fim.
   A chave da App não expira: trocar 1x/ano (gerar nova, `provider set`, apagar a antiga no GitHub).
4. Cliente com GitHub próprio: a App é instalada na conta dele (vira provedor `github` do cliente com o
   `installation_id` de lá); o `offboard` desinstala.

**Segredo compartilhado e rotação sem derrubar sessões** (`[[client.shared]]`, exemplo no `secrets.toml`):

```bash
scripts/cp-secrets rotate easygoal/sso-global prod            # plan: membros, assinante, modo
scripts/cp-secrets rotate easygoal/sso-global prod --apply    # gradual: novo em todos + _PREVIOUS = antigo
scripts/cp-secrets rotate easygoal/sso-global prod --finish --apply        # depois da janela (≥ 7 dias)
scripts/cp-secrets rotate easygoal/sso-global prod --maintenance --apply   # incidente: sem janela, todos deslogam
```

Os apps verificam com `SSO_JWT_SECRET` e, se a assinatura falhar, com `SSO_JWT_SECRET_PREVIOUS` (branches
`feat/sso-jwt-chave-dupla` em sso, `@easygoal/auth`, app-front, api-backend, easyai-crm, vaygo-api e vaygo-web).
Os verificadores sincronizam primeiro e o assinante por último. `_PREVIOUS` desligado = valor aleatório que
ninguém usa (nunca vazio). O `rotate` recusa membros com valores diferentes: igualar antes.

**Fim de contrato:** `scripts/cp-secrets offboard <cliente>` (plan) → `--apply --yes <cliente>`: backup,
export JSON para o Bitwarden do cliente (`openbao/exports/`, texto puro: importar e `shred -u`), revoga os
tokens de operação que o provedor permite, apaga AppRoles, policies e `kv/<cliente>/*`, e lista os passos
manuais (SSH, Coolify, tailnet, bloco do `secrets.toml`).

**Laboratório (`sim/lab.sh up | verify | down`)**: ver "Instalação" abaixo.

## Observabilidade — OpenObserve + Umami (`scripts/cp-obs`, ADR 066)

Sobe no control plane pelo `install/control-plane.sh` (passo 5), com limite de memória em tudo:

| Serviço | Para quê | Acesso |
|---|---|---|
| OpenObserve v1.1.2 | logs OTLP das apps (1 **org por cliente e ambiente**, 1 stream por serviço), painéis, alertas, SQL | UI/API só tailnet (`:5080`) |
| Umami 3.4.1 (+ Postgres) | analytics de produto sem cookie (1 site por app/ambiente) | painel só tailnet (`:3300`) |
| gateway (Caddy 2.11.7) | **único ponto público** (Tailscale Funnel → `:8280`): só `POST /api/<org>/v1/{logs,traces,metrics}`, `GET /script.js` e `POST /api/send`. Consulta, login e painéis dão 404 | público |

```bash
scripts/cp-obs status                                        # saúde, orgs, streams, service accounts, sites
scripts/cp-obs ingest easygoal/health-stay/staging           # org + service account + OBS_* no cofre
scripts/cp-obs ingest easygoal/health-stay/staging --rotate  # token novo (o antigo para na hora → sync)
scripts/cp-obs analytics easygoal/site-easygoal/prod --domain easygoal.com.br   # site no Umami
scripts/cp-obs revoke <cliente> [--apply]                    # offboarding: corta ingestão e apaga os sites
```

As apps usam o `@easygoal/observability` (monorepo): sem variáveis só escrevem JSON no stdout; com
`OBS_OTLP_*` enviam ao gateway. Ponha as chaves `OBS_*` na allowlist do target e rode `cp-secrets sync`.

O que o ensaio ensinou (OpenObserve OSS):
- O token de service account **só sai na criação ou na rotação**; a listagem devolve ele mascarado. Por isso o
  `ingest` reemite quando o cofre não tem o token.
- Sem RBAC no OSS, o token de ingestão também **lê** a própria org pela API direta. Contenção em 3 camadas:
  1. o gateway público só deixa passar envio;
  2. **1 org por cliente e ambiente** (`<cli>_<env>`): token de dev vazado não lê prod, e outra org responde 401;
  3. **ACL da tailnet**: só o operador alcança `:5080` e `:3300`. As VPS de app falam com o control plane só no
     que precisam (Sentinel `:8000`). Na política do Tailscale:
     ```json
     {"action": "accept", "src": ["group:operadores"], "dst": ["tag:control-plane:5080,3300,8000,8200"]},
     {"action": "accept", "src": ["tag:app-dev", "tag:app-prd"], "dst": ["tag:control-plane:8000"]}
     ```
     Sem essa ACL, não ligar o Funnel.
- O identificador da org é aleatório (com maiúsculas): o endpoint guardado no cofre já leva ele.
- Stream com hífen vira underscore (`health-stay-api` → `health_stay_api`) na consulta SQL.
- A senha do root precisa de maiúscula, minúscula, dígito e símbolo (senão o OpenObserve não sobe).
- Caddyfile é montado como arquivo: o instalador reinicia o gateway quando a regra muda.

## Instalação — control plane e VPS de app (ADR 064)

Os mesmos scripts no laboratório e na VPS real (Ubuntu 24.04, root). Idempotentes: rodar de novo só corrige.

| Script | Onde roda | O que faz |
|---|---|---|
| `install/control-plane.sh` | VPS do control plane | sshd só chave, docker (repo oficial), unattended-upgrades, Tailscale (`TS_AUTHKEY`), ufw só tailnet; Coolify 4.5.3 com arquivos fixados por sha256; pós-instalação (`coolify-post.php`); OpenBao com TLS (CA própria em `/data/cp/ca`) |
| `install/coolify-sync-token.sh` | VPS do control plane | token novo do usuário de serviço `cp-sync` (revoga os anteriores) **só no stdout** → `provider set ... --stdin token` |
| `install/observability-cred.sh` | VPS do control plane | senha de admin do OpenObserve ou do Umami **só no stdout** → `provider set easygoal openobserve\|umami ... --stdin password` |
| `install/app-server.sh` | cada VPS de app | sshd só chave, docker, chave do Coolify (`COOLIFY_PUBKEY`), Tailscale com tag, ufw |
| `scripts/cp-coolify` | máquina do operador | `key` (chave SSH do Coolify → pública), `server add`, `servers`, `service ensure` |
| `cp-secrets restore <snap>` | máquina do operador | migração do cofre: snapshot do principal → OpenBao novo → abre com as chaves originais |

Pós-instalação do Coolify (o que o ensaio ensinou): root criado direto (o seeder valida e-mail por DNS) e com
e-mail verificado; usuário de serviço `cp-sync` para o token do sync; onboarding desligado; registro fechado;
API ligada; **IP da instância = endereço na tailnet** (vira a URL do Sentinel de todo servidor remoto).

Roteiro na VPS real (fase F):
1. `CP_ADDR=<ip tailnet> CP_ADMIN_EMAIL=contato@easygoal.com.br TS_AUTHKEY=... bash install/control-plane.sh`
2. CA: copiar `/data/cp/ca/ca.crt` → `openbao/tls/prod-ca.crt`; `cp-secrets backup` aqui →
   `CP_BAO_ADDR=https://<cp>:8200 CP_BAO_CACERT=openbao/tls/prod-ca.crt cp-secrets restore <snap>`
3. `ssh root@<cp> bash -s < install/coolify-sync-token.sh | cp-secrets provider set easygoal coolify url=... --stdin token --expires <+90d>`
4. Para cada VPS de app: `COOLIFY_PUBKEY="$(scripts/cp-coolify key)" SERVER_TAG=app-prd bash install/app-server.sh`
   (na VPS) → `scripts/cp-coolify server add <nome> <ip tailnet>`
5. `scripts/cp-coolify service ensure ...` + `cp-secrets sync apply`
6. Observabilidade: `ssh root@<cp> bash -s openobserve < install/observability-cred.sh | cp-secrets provider set easygoal openobserve url=http://<cp>:5080 ingest_url=https://<cp>.<tailnet>.ts.net email=... --stdin password`
   (idem `umami`), liberar Funnel na ACL e `tailscale funnel --bg --https=443 http://127.0.0.1:8280`

Laboratório: `sim/lab.sh up` faz 1–5 com `CP_SIM=1` (sem firewall/Tailscale; a rede Docker 172.30.50.0/24
faz o papel da tailnet) e `verify` confere servidores, cofre do CP, sync, valor no container e Sentinel.
Gotchas: Docker publica portas **por fora do ufw** (publicar no IP da tailnet ou atrás do proxy); o ufw só é
aplicado com a tailnet ativa (senão trancaria o SSH pelo IP público).

### Arquivos sensíveis (fora do git, 600)

| Arquivo | O que é | Onde deve morar |
|---|---|---|
| `openbao/.init.json` | 3 chaves de unseal (2 abrem o cofre) | **gerenciador de senhas**, depois apagar daqui |
| `openbao/.bootstrap.env` | AppRole do operador `control-plane-bootstrap` (policy `cp-admin`) | esta máquina |
| `openbao/runtime/*.env` | AppRole de runtime (lê um ambiente) | o servidor que roda a app |
| `openbao/backups/*.snap` | snapshot cifrado | fora da máquina (sem as chaves não abre) |
| `openbao/exports/*.json` | export do offboard (texto puro) | Bitwarden do cliente, depois `shred -u` |

Sem `.init.json` em disco, o `unseal` pede as chaves digitadas (2 de 3).

### Regras

- Valores nunca aparecem em saída de script, log ou chat: só nomes, contagens e ids.
- Import de `.env` só cria chaves que faltam; depois do primeiro import o OpenBao é a fonte de verdade.
- Versão fixada por digest (`openbao/docker-compose.yml`): atualizar de propósito, com `backup` antes.
- Porta só em `127.0.0.1`, HTTP. Na VPS (etapa 3): acesso pela tailnet, com TLS.
- Audit em JSON no volume `bao_audit` (valores em HMAC) → OpenObserve (ADR 066, fase O3).

## Histórico

- Infisical v0.167.2 (etapa 2, 2026-10-28) substituído pelo OpenBao no mesmo dia: role por ambiente e
  audit log são Enterprise. Containers, volumes `cp-infisical_*` e credenciais removidos em 2026-10-29 (s351).

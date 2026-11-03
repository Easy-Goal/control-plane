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

## Segredos — OpenBao (`scripts/cp-secrets`)

Por que OpenBao (ADR 062): audit log de cada leitura e política por caminho (uma identidade lê
exatamente um projeto/ambiente) sem licença paga. O Infisical gratuito não tem nenhum dos dois.

```bash
cd openbao && docker compose up -d --wait && cd ..
scripts/cp-secrets init      # 1x: chaves de unseal → openbao/.init.json, operador → openbao/.bootstrap.env, revoga root
scripts/cp-secrets status    # selado? audit ativo? .init.json ainda em disco?
scripts/cp-secrets unseal    # depois de reiniciar o Docker (o cofre volta SELADO)
```

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
vale na próxima execução). O GitHub precisa do `.venv` (`python3 -m venv .venv && .venv/bin/pip install -r
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

**Fim de contrato:** `scripts/cp-secrets offboard <cliente>` (plan) → `--apply --yes <cliente>`: backup,
export JSON para o Bitwarden do cliente (`openbao/exports/`, texto puro: importar e `shred -u`), revoga os
tokens de operação que o provedor permite, apaga AppRoles, policies e `kv/<cliente>/*`, e lista os passos
manuais (SSH, Coolify, tailnet, bloco do `secrets.toml`).

**Laboratório (`sim/lab.sh up | verify | down`)**: ver "Instalação" abaixo.

## Instalação — control plane e VPS de app (ADR 064)

Os mesmos scripts no laboratório e na VPS real (Ubuntu 24.04, root). Idempotentes: rodar de novo só corrige.

| Script | Onde roda | O que faz |
|---|---|---|
| `install/control-plane.sh` | VPS do control plane | sshd só chave, docker (repo oficial), unattended-upgrades, Tailscale (`TS_AUTHKEY`), ufw só tailnet; Coolify 4.5.3 com arquivos fixados por sha256; pós-instalação (`coolify-post.php`); OpenBao com TLS (CA própria em `/data/cp/ca`) |
| `install/coolify-sync-token.sh` | VPS do control plane | token novo do usuário de serviço `cp-sync` (revoga os anteriores) **só no stdout** → `provider set ... --stdin token` |
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
- Audit em JSON no volume `bao_audit` (valores em HMAC) → coletor para Loki na etapa 5.

## Histórico

- Infisical v0.167.2 (etapa 2, 2026-10-28) substituído pelo OpenBao no mesmo dia: role por ambiente e
  audit log são Enterprise. Containers, volumes `cp-infisical_*` e credenciais removidos em 2026-10-29 (s351).

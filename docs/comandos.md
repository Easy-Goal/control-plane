# Comandos por situação

Cada seção diz **quando usar**, traz um bloco pronto para copiar, o que esperar na saída e o que fazer se falhar.
Os comandos rodam **na raiz do repositório `control-plane`**, na sua máquina. Instalado pelo pacote, use `cplane`:
`scripts/cp-secrets` vira `cplane secrets`, `scripts/cp-coolify` vira `cplane coolify` e `scripts/cp-obs` vira `cplane obs`.

Nenhum comando daqui imprime valor de segredo: só nomes, versões, contagens e ids.

## Placeholders

Quando um comando tem `<algo>`, troque pelo valor real (sem os sinais `<` `>`).

| Placeholder | O que é | Exemplo real |
|---|---|---|
| `<cliente>` | slug do cliente no `secrets.toml` | `minhaempresa` |
| `<projeto>` | slug do projeto dentro do cliente | `<projeto>` |
| `<ambiente>` | ambiente do projeto | `dev`, `staging`, `prod` |
| `<cliente>/<projeto>/<ambiente>` | um ambiente inteiro (= caminho `kv/...` no cofre) | `<cliente>/<projeto>/staging` |
| `<provedor>` | nome de uma credencial de plataforma (`[[client.provider]]`) | `coolify-sim`, `vercel`, `openobserve-sim` |
| `<grupo>` | segredo compartilhado (`[[client.shared]]`) | `sso-global` |
| `<identidade>` | AppRole de runtime (`[[client.project.runtime]]`) | `<aplicação>-dev` |
| `<cp>` | VPS do control plane na tailnet (nome ou IP) | `cp.tail1234.ts.net` |

## Qual cofre o comando usa

- Sem nada na frente: **cofre principal** (`CP_BAO_ADDR`, padrão `http://127.0.0.1:8200`).
- Com `scripts/cp-lab` na frente: **cofre do laboratório** (`https://127.0.0.1:8210`).
- Na VPS real (depois do go-live): exporte `CP_BAO_ADDR` e `CP_BAO_CACERT` uma vez no shell (ver
  [instalação](instalacao.md#roteiro-na-vps-real-fase-f)).

```bash
scripts/cp-secrets status            # cofre principal
scripts/cp-lab cp-secrets status     # cofre do laboratório
```

## Resumo

| Situação | Frequência |
|---|---|
| [Começar a sessão](#começar-a-sessão) | todo dia |
| [Depois de reiniciar o Docker ou a VPS](#depois-de-reiniciar-o-docker-ou-a-vps) | a cada reinício |
| [Entrar na UI do OpenBao](#entrar-na-ui-do-openbao) | quando precisar ver o cofre |
| [Ver o que existe num ambiente](#ver-o-que-existe-num-ambiente) | quando precisar |
| [Criar ou trocar um segredo](#criar-ou-trocar-um-segredo) | quando mudar uma variável |
| [Levar segredos para a Vercel, o Coolify, o GitHub ou a Railway](#levar-segredos-para-a-vercel-o-coolify-o-github-ou-a-railway) | depois de toda mudança |
| [Rodar uma app local sem .env](#rodar-uma-app-local-sem-env) | dev local |
| [Cadastrar ou renovar a credencial de uma plataforma](#cadastrar-ou-renovar-a-credencial-de-uma-plataforma) | 1x por plataforma + renovação |
| [Projeto, ambiente ou destino novo](#projeto-ambiente-ou-destino-novo) | quando criar algo |
| [Ligar logs num app novo](#ligar-logs-num-app-novo) | 1x por app/ambiente |
| [Ligar analytics (Umami) num front](#ligar-analytics-umami-num-front) | 1x por front |
| [Conferir a observabilidade](#conferir-a-observabilidade) | quando precisar |
| [Rotacionar o SSO](#rotacionar-o-sso) | rotina ou incidente |
| [Vazou um segredo](#vazou-um-segredo) | incidente |
| [Vazou o token de ingestão de logs](#vazou-o-token-de-ingestão-de-logs) | incidente |
| [Revogar acesso do operador](#revogar-acesso-do-operador) | fim de sessão na UI, suspeita, rotina |
| [Conferir quem leu o quê (audit)](#conferir-quem-leu-o-quê-audit) | semanal |
| [Backup do cofre](#backup-do-cofre) | antes de mudanças grandes |
| [VPS de app nova](#vps-de-app-nova) | 1x por VPS |
| [Banco, backup e restauração no Coolify](#banco-backup-e-restauração-no-coolify) | 1x por projeto/ambiente |
| [Renovar o token do sync do Coolify](#renovar-o-token-do-sync-do-coolify) | a cada 90 dias |
| [Cliente saiu](#cliente-saiu) | fim de contrato |
| [Laboratório](#laboratório) | ensaios |
| [Montar um cofre novo](#montar-um-cofre-novo) | 1x |

---

## Começar a sessão

Use no começo de todo dia de trabalho, antes de mexer em segredo.

```bash
cd <pasta do repositório control-plane>
scripts/cp-secrets status
scripts/cp-secrets sync plan
```

**O que esperar:**
- `status` → primeira linha `OpenBao 2.7.2 — inicializado=True selado=False`, `audit devices: file/`, e uma tela por
  cliente com cada provedor (`vence AAAA-MM-DD (Nd)`) e cada destino (`em dia`, `PENDENTE (cofre vN)` ou
  `nunca sincronizado`).
- `sync plan` → por destino: `cofre vN, sincronizado vN` e `iguais: N`. Nada muda.

**Se falhar:**
- `selado=True` → [Depois de reiniciar o Docker ou a VPS](#depois-de-reiniciar-o-docker-ou-a-vps).
- `← RENOVAR` ou `VENCEU` num provedor → [Cadastrar ou renovar](#cadastrar-ou-renovar-a-credencial-de-uma-plataforma).
- `PENDENTE` → rode o `sync apply` (ver [Levar segredos](#levar-segredos-para-a-vercel-o-coolify-o-github-ou-a-railway)).
- `ATENÇÃO: openbao/.init.json ainda está em disco` → mova as chaves para o Bitwarden e apague o arquivo.
- `Connection refused` → o container do cofre não está de pé: `cd openbao && docker compose up -d --wait && cd ..`.

## Depois de reiniciar o Docker ou a VPS

Todo reinício (Docker Desktop, WSL, VPS) **sela** o cofre. As apps continuam no ar; só não dá para mudar segredo.
Tenha à mão 2 das 3 chaves de unseal (gerenciador de senhas).

```bash
scripts/cp-secrets unseal
scripts/cp-lab cp-secrets unseal      # só se usar o laboratório
```

**O que esperar:** `chave de unseal 1/2:` e `2/2:` (digitação oculta) e depois `aberto`. Se já estava aberto: `já aberto`.

**Se falhar:**
- `(vazia — cole de novo)` → a colagem não chegou ao prompt oculto. Cole de novo (botão direito no terminal do WSL).
- `ainda selado (1/2)` → uma chave estava errada. Rode de novo.
- Lab em restart infinito depois de reiniciar o Docker Desktop: `sim/lab.sh up` conserta (idempotente).

## Entrar na UI do OpenBao

A UI não tem usuário e senha. Você entra com um token do operador, que vale 1h (renovável até 4h).

```bash
scripts/cp-secrets ui-token
```

**O que esperar:** `[ok] token copiado (vale 1h, renovável até 4h)` e a URL
`http://127.0.0.1:8200/ui/vault/auth?with=token`. Abra a URL, escolha **Method: Token** e cole.

Laboratório (o token só vale no cofre que o emitiu):

```bash
scripts/cp-lab cp-secrets ui-token     # UI em https://127.0.0.1:8210/ui/
```

Ao terminar, revogue: `scripts/cp-secrets ui-token --revoke`. Detalhes de cada ferramenta em [acesso.md](acesso.md).

**Se falhar:**
- `(sem área de transferência; imprimindo)` → não achou `clip.exe`/`wl-copy`/`pbcopy`/`xclip`. O token saiu na tela:
  não cole esse terminal em lugar nenhum e revogue ao terminar.
- "permission denied" na UI → o token é de outro cofre (8200 × 8210) ou venceu. Gere outro.

## Ver o que existe num ambiente

Mostra nomes e versão (nunca valores).

```bash
scripts/cp-secrets keys <cliente>/<projeto>/staging
scripts/cp-secrets provider list <conta>
```

**O que esperar:** `kv/<cliente>/<projeto>/staging — versão N, M chaves` e os nomes; para provedores, cada nome e os **campos** (ex.:
`url, token`), sem valores.

## Criar ou trocar um segredo

Use `gen` para segredo **interno** (gerado aqui, ex.: `JWT_SECRET`) e `set` para valor que vem de um **painel**
(ex.: token do Mercado Pago). Os dois criam uma nova versão no cofre. Depois, sempre propague com o `sync`.

```bash
# interno: gera um valor aleatório
scripts/cp-secrets secret gen <cliente>/<projeto>/staging JWT_SECRET

# de um painel: pede o valor oculto (cole e Enter)
scripts/cp-secrets secret set <cliente>/<projeto>/prod MP_TOKEN

# só cria se ainda não existir (não troca o atual)
scripts/cp-secrets secret gen <cliente>/<projeto>/prod AES_KEY --bytes 32 --if-missing

# propagar
scripts/cp-secrets sync plan <cliente>/<projeto>
scripts/cp-secrets sync apply <cliente>/<projeto>
```

**O que esperar:** `[ok] kv/<cliente>/<projeto>/staging: JWT_SECRET trocada → versão N (propagar: cp-secrets sync plan)` (`criada` se a chave não existia).

**Se falhar / cuidado:**
- A chave precisa estar na allowlist `keys` do target para chegar ao destino. Se não estiver, o `sync` não a leva.
- **Chave que cifra dados guardados nunca troca direto.** Trocar exige recifrar os dados.
- Valor vindo de painel: gere o novo no painel, `secret set`, `sync apply`, confira o health e **só então** revogue o
  antigo no painel.

## Levar segredos para a Vercel, o Coolify, o GitHub ou a Railway

Depois de qualquer `secret`, `rotate` ou `cp-obs`. O `plan` mostra o diff (só nomes); o `apply` grava, faz o
redeploy e espera o `health_url`. O filtro opcional é `<cliente>[/<projeto>[/<target>]]`.

```bash
scripts/cp-secrets sync plan
scripts/cp-secrets sync apply <cliente>/<projeto>
scripts/cp-secrets sync apply <cliente>/<projeto>/api-staging-sim     # um destino só
scripts/cp-secrets sync apply <cliente>/<projeto> --redeploy          # força o redeploy
```

**O que esperar (plan):**

```text
<cliente>/<projeto>/api-staging-sim: cofre v7, sincronizado v6
  atualizar: JWT_SECRET
  iguais: 8 | fora da allowlist (não mexo): FOO
```

No `apply`: `[ok] N variáveis gravadas`, `[ok] redeploy concluído` (ou `na fila`), `[ok] http://.../health/ready → 200`.
No GitHub não há redeploy: `vale na próxima execução`.

**Se falhar:**
- `[aviso] divergiu no destino (o cofre vence)` → alguém mudou no painel. O `apply` restaura o valor do cofre. Se o
  valor do painel é o certo, grave-o no cofre antes (`secret set`).
- `401` no Coolify → o token do sync venceu ou foi revogado: [Renovar o token do sync](#renovar-o-token-do-sync-do-coolify).
- Railway em `NEEDS_APPROVAL` → o serviço tem aprovação manual de deploy . Aprove no painel.
- Redeploy falhou → a versão **não** é anotada; o próximo `apply` refaz.
- Detalhes de cada destino em [sync.md](sync.md).

## Rodar uma app local sem .env

Injeta os segredos de **um** ambiente no processo, sem arquivo em disco. Só para dev local.

```bash
cd <pasta da aplicação>
<pasta do control-plane>/scripts/cp-secrets run <aplicação>-dev -- \
  docker compose --env-file /dev/null --profile full up -d --build --wait db migrate api
```

**O que esperar:** o comando roda normalmente. O `run` faz login com a AppRole (`openbao/runtime/<aplicação>-dev.env`),
lê `kv/<cliente>/<projeto>/dev`, revoga o token e executa.

**Se falhar:** arquivo de runtime ausente → rode `scripts/cp-secrets apply` (cria as AppRoles do `secrets.toml`).

## Cadastrar ou renovar a credencial de uma plataforma

Credenciais de operação (Coolify, Vercel, GitHub App, Railway, OpenObserve, Umami) ficam em
`kv/<cliente>/_providers/<provedor>`. Sempre com `--expires` quando a credencial vence: o `status` avisa 15 dias antes.

```bash
# Vercel: token do time, 90 dias (pede o token oculto)
scripts/cp-secrets provider set <conta> vercel --stdin token --expires 2027-02-02

# GitHub App: chave .pem por stdin, depois apagar o arquivo
scripts/cp-secrets provider set <conta> github app_id=<id> installation_id=<id> --stdin private_key < arquivo.pem
shred -u arquivo.pem

# conferir (só campos)
scripts/cp-secrets provider list <conta>
```

Data de 90 dias para frente: `date -u -d "+90 days" +%F`.

**O que esperar:** `[ok] kv/<conta>/_providers/vercel: token (vence 2027-02-02)`.

**Rodar um script com a credencial no ambiente** (variáveis `CP_<CAMPO>`, sem imprimir):

```bash
scripts/cp-secrets provider exec <conta> vercel -- python3 sim/bootstrap-vercel-probe.py
```

## Coolify de um cliente: um time por cliente

Cada cliente tem um time e um usuário de serviço próprios (ADR 067). O token só enxerga esse time. Sempre passe
`CP_CLIENT` e `--client`: sem eles, o token e a VPS vão para o time da conta principal.

```bash
# cria o time e o usuário de serviço, se faltarem, e grava o token no cofre. Rodar de novo faz a rotação
ssh root@<cp> CP_CLIENT=<cliente> bash -s < install/coolify-sync-token.sh \
  | scripts/cp-secrets provider set <cliente> coolify url=http://<cp>:8000 --stdin token --expires "$(date -u -d '+90 days' +%F)"

scripts/cp-coolify --client <cliente> key                          # chave SSH do time do cliente
scripts/cp-coolify --client <cliente> server add vps-<cliente> <ip na tailnet>
scripts/cp-coolify --client <cliente> servers
```

**O que esperar:** `servers` lista só os servidores desse cliente. O Coolify da conta principal não enxerga os recursos dele
pela API, e vice-versa. O painel do Coolify troca de time pelo seletor, com o login do operador.

## Projeto, ambiente ou destino novo

Edite `secrets.toml` (`[[client.project]]`, `[[client.project.target]]` com a allowlist `keys`,
`[[client.project.runtime]]`, `import_env`). Depois:

```bash
scripts/cp-secrets plan      # o que mudaria (não altera nada)
scripts/cp-secrets apply     # policies, AppRoles, import de .env (idempotente)
scripts/cp-secrets sync plan
```

**O que esperar:** o `plan` lista policies/AppRoles/chaves a criar; o `apply` repete com `[ok]`. O import de `.env`
só cria chaves que faltam (o cofre vence depois).

Para um destino novo no Coolify, crie antes o service: ver [Banco, backup e restauração](#banco-backup-e-restauração-no-coolify).
Formato completo em [sync.md](sync.md#estado-desejado-secretstoml).

## Ligar logs num app novo

1x por app/ambiente. Cria a org `<cliente>_<ambiente>` no OpenObserve, uma service account de ingestão e grava 5
variáveis `OBS_*` no ambiente do app.

```bash
# laboratório (credenciais -sim no cofre principal)
CP_OBS_PROVIDER=openobserve-sim CP_UMAMI_PROVIDER=umami-sim scripts/cp-obs ingest <cliente>/<projeto>/staging

# VPS real (provedores openobserve/umami)
scripts/cp-obs ingest <cliente>/<projeto>/staging
```

Depois, ponha as chaves na allowlist do target em `secrets.toml`:

```toml
keys = [..., "OBS_OTLP_ENDPOINT", "OBS_OTLP_AUTHORIZATION", "OBS_SERVICE", "OBS_ENV", "OBS_IP_SALT"]
```

e propague:

```bash
scripts/cp-secrets sync plan <cliente>/<projeto>
scripts/cp-secrets sync apply <cliente>/<projeto>
```

**O que esperar:** `[ok] org <cliente>_staging criada`, `[ok] service account ... criada`,
`[ok] kv/<cliente>/<projeto>/staging → versão N: OBS_...`. Rodar de novo: `nada a mudar`.

**Se falhar:** `kv/<conta>/_providers/openobserve vazio` → cadastre a senha de admin (ver
[observabilidade](observabilidade.md#credenciais-de-admin-no-cofre)). O app precisa usar o `o pacote de observabilidade`.

## Ligar analytics (Umami) num front

1x por front/ambiente. Cria o site no Umami e grava `NEXT_PUBLIC_UMAMI_WEBSITE_ID` e `NEXT_PUBLIC_UMAMI_SRC`
(públicos por natureza).

```bash
scripts/cp-obs analytics <cliente>/<projeto>/prod --domain seudominio.com.br
```

Ponha as duas chaves na allowlist do target e rode o `sync`. No layout do Next:
`<Script defer src={process.env.NEXT_PUBLIC_UMAMI_SRC} data-website-id={process.env.NEXT_PUBLIC_UMAMI_WEBSITE_ID} />`.

**O que esperar:** `[ok] site ... (seudominio.com.br) criado no Umami: <id>` (ou `já existe`).

## Conferir a observabilidade

```bash
scripts/cp-obs status                                                    # VPS real
CP_OBS_PROVIDER=openobserve-sim CP_UMAMI_PROVIDER=umami-sim scripts/cp-obs status   # laboratório
```

**O que esperar:** saúde do OpenObserve, do gateway e do Umami; cada org com streams (`docs=N`) e service accounts;
cada site do Umami.

## Rotacionar o SSO

Troca um segredo compartilhado (`[[client.shared]]`) em todos os projetos sem deslogar ninguém. Os verificadores
aceitam `SSO_JWT_SECRET` e, se falhar, `SSO_JWT_SECRET_PREVIOUS`.

**Pré-requisitos:**
- o bloco `[[client.shared]] name = "sso-global"` descomentado no `secrets.toml` (hoje é só exemplo);
- as 7 branches `feat/sso-jwt-chave-dupla` **em produção**. Sem elas, o gradual equivale a uma manutenção (todos deslogam);
- `SSO_JWT_SECRET_PREVIOUS` na allowlist de cada target membro.

```bash
scripts/cp-secrets rotate <cliente>/<grupo> prod                  # plan: membros, assinante, modo
scripts/cp-secrets rotate <cliente>/<grupo> prod --apply          # gradual: novo em todos + _PREVIOUS = antigo
# esperar a janela (≥ 7 dias = EG_SESSION_MAX_AGE)
scripts/cp-secrets rotate <cliente>/<grupo> prod --finish --apply # encerra a janela do valor antigo
```

**O que esperar:** o plan mostra membros, `signer` e modo. O apply grava em cada membro e sincroniza: os
verificadores primeiro, o assinante por último.

**Se falhar:** "membros com valores diferentes" → o `rotate` recusa. Iguale os valores antes (`secret set` em cada
membro). Grupo com `signer = ""` (segredo por app no SSO): salve o valor novo em `api_apps.jwt_secret` no painel
admin do SSO **depois** do sync.

## Vazou um segredo

Vazamento confirmado: troque **sem janela**. Todo mundo que depende dele é afetado na hora.

```bash
# segredo compartilhado (SSO): todos deslogam
scripts/cp-secrets rotate <cliente>/<grupo> prod --maintenance --apply

# segredo comum interno
scripts/cp-secrets secret gen <cliente>/<projeto>/prod JWT_SECRET
scripts/cp-secrets sync apply <cliente>/<projeto>

# segredo de painel: gere o novo no painel, grave e propague, depois revogue o antigo no painel
scripts/cp-secrets secret set <cliente>/<projeto>/prod MP_TOKEN
scripts/cp-secrets sync apply <cliente>/<projeto>

# depois: quem leu o quê nas últimas 72h
scripts/cp-secrets audit 72
```

Credencial de **plataforma** vazada (token Vercel, chave da GitHub App, token Railway): gere outra no painel,
`provider set ... --expires`, e revogue a antiga no painel. `AES_KEY` e VAPID só trocam com vazamento confirmado
(ver [segredos](segredos.md#o-que-nunca-girar-direto)).

## Vazou o token de ingestão de logs

O token antigo para de valer na hora. Rode o `sync` logo depois para o app não ficar sem enviar.

```bash
scripts/cp-obs ingest <cliente>/<projeto>/staging --rotate
scripts/cp-secrets sync apply <cliente>/<projeto>
```

**O que esperar:** `[ok] token de ... rotacionado — o anterior já não vale`.

## Revogar acesso do operador

O token da UI vence em 1h (renovável até 4h). O `secret_id` do `openbao/.bootstrap.env` **não vence**.

```bash
# fim de uma sessão na UI, ou token exposto (UI, terminal, log)
scripts/cp-secrets ui-token --revoke

# suspeita sobre o .bootstrap.env (cópia em outra máquina, backup exposto) ou rotina trimestral
cp openbao/.bootstrap.env /tmp/bootstrap.antigo       # só se existir cofre restaurado (lab)
scripts/cp-secrets operator rotate

# levar a credencial nova ao lab (restaurado do principal) e apagar a cópia
CP_BAO_BOOTSTRAP=/tmp/bootstrap.antigo scripts/cp-lab cp-secrets operator align
shred -u /tmp/bootstrap.antigo
```

**O que esperar:**
- `--revoke` → `[ok] N token(s) do operador revogado(s) em http://127.0.0.1:8200 (+ o desta execução)`.
- `operator rotate` → `[ok] secret_id novo testado e gravado`, `[ok] N secret_id antigo(s) destruído(s)`,
  `[ok] N token(s) vivo(s) do operador revogado(s)`.
- `operator align` → `[ok] https://127.0.0.1:8210: credencial do principal gravada, N antiga(s) destruída(s)`.

**Cuidados:**
- O `rotate` grava a credencial nova **antes** de destruir a antiga: se cair no meio, o arquivo já vale.
- Se o `.bootstrap.env` estiver guardado no Bitwarden, atualize lá (o antigo não vale mais).
- Ensaiar no lab sem invalidar o principal: `CP_BAO_BOOTSTRAP=<cópia> scripts/cp-lab cp-secrets operator rotate`.

## Conferir quem leu o quê (audit)

Rotina semanal, ou depois de qualquer suspeita.

```bash
scripts/cp-secrets audit 24     # últimas 24h
scripts/cp-secrets audit 168    # última semana
```

**O que esperar:** `audit log OpenBao — últimas 24h — N respostas`, com leituras por identidade/ambiente, negados
e todas as operações.

## Backup do cofre

Antes de atualizar o OpenBao, de um `rotate`, de um `offboard` ou de migrar o cofre.

```bash
scripts/cp-secrets backup
```

**O que esperar:** `[ok] openbao/backups/<arquivo>.snap (N bytes) — restaurar exige as chaves de unseal`.
Copie o `.snap` para fora da máquina (Google Drive ou R2). Ele é cifrado: sem as chaves de unseal, não abre. As chaves ficam no Bitwarden, em notas de texto, separadas do snapshot.

## VPS de app nova

1x por VPS (dev compartilhada, prd de um projeto ou VPS de cliente). Na sua máquina, pegue a chave pública do Coolify;
na VPS, rode o instalador; depois cadastre no Coolify.

```bash
# 1. sua máquina: chave pública do Coolify
scripts/cp-coolify key
```

```bash
# 2. na VPS, como root (com a pasta install/ copiada para /opt/cp-install)
COOLIFY_PUBKEY="ssh-ed25519 AAAA... coolify-cp" SERVER_TAG=app-prd TS_AUTHKEY=<auth key> \
  bash /opt/cp-install/app-server.sh
```

```bash
# 3. sua máquina: cadastrar e conferir
scripts/cp-coolify server add vps-prd-<projeto> <ip na tailnet>
scripts/cp-coolify servers
```

**O que esperar:** `app-server.sh` termina com `pronta: scripts/cp-coolify server add ...`. O `server add` espera o
servidor ficar `reachable/usable`. Detalhes em [instalação](instalacao.md).

## Banco, backup e restauração no Coolify

1x por projeto/ambiente. Exemplo do laboratório (staging na VPS dev):

```bash
export CP_COOLIFY_PROVIDER=coolify-sim     # na VPS real: coolify (padrão)

# destino S3 dos backups (chaves só no ambiente, nunca em argumento)
CP_S3_KEY=<key> CP_S3_SECRET=<secret> scripts/cp-coolify s3 ensure lab-s3 http://172.30.50.40:8333 cp-backups

# Postgres gerenciado (usuário/senha vêm do cofre; grava DB_HOST no cofre)
scripts/cp-coolify db ensure <projeto> staging sim-vps-dev <banco>-staging <cliente>/<projeto>/staging --db <banco>

# backup agendado (padrão 03:00, guarda 14)
scripts/cp-coolify backup ensure <banco>-staging lab-s3

# service da app a partir de um compose (as variáveis chegam pelo sync)
scripts/cp-coolify service ensure <projeto> staging sim-vps-dev <aplicação>-staging sim/minha-api.compose.yml
scripts/cp-secrets sync apply <cliente>/<projeto>
```

Backup avulso antes de uma migration arriscada e restauração:

```bash
scripts/cp-coolify backup now <banco>-staging                 # imprime o caminho no S3
scripts/cp-coolify db restore <banco>-staging lab-s3 <caminho>
```

**Se falhar:** "destino em IP privado" no S3 → é a proteção SSRF do Coolify; só o lab libera o IP do S3 dele.

## Renovar o token do sync do Coolify

A cada 90 dias (o `status` avisa) ou se o `sync` der 401. Gera um token novo do usuário de serviço `cp-sync` e
revoga os anteriores. O token vai direto para o cofre, sem passar pela tela.

```bash
# VPS real
ssh root@<cp> bash -s < install/coolify-sync-token.sh \
  | scripts/cp-secrets provider set <conta> coolify url=http://<cp>:8000 --stdin token --expires "$(date -u -d '+90 days' +%F)"

# laboratório
ROTATE=1 sim/lab.sh up
```

**Cuidado:** calcule a data **antes** do pipe ou use `$(...)` como acima. Num pipe, o `$(...)` do lado direito roda
junto com o esquerdo.

## Cliente saiu

Fim de contrato. Primeiro sempre o plan (não altera nada). O cliente `<conta>` nunca passa por offboard.

```bash
scripts/cp-secrets backup
scripts/cp-secrets offboard <cliente>                         # plan
scripts/cp-obs revoke <cliente>                               # plan: orgs, service accounts e sites

scripts/cp-secrets offboard <cliente> --apply --yes <cliente>
scripts/cp-obs revoke <cliente> --apply
```

`<cliente>` precisa estar declarado na configuração da conta.

**O que esperar:** `[ok] export → openbao/exports/<arquivo>.json (600, texto puro: importar e apagar)`, revogação
dos tokens que cada provedor permite, `[ok] AppRoles, policies e kv/<cliente>/* apagados`, e a lista de passos manuais.

**Depois (manual):**
1. Importe o JSON no Bitwarden do cliente e `shred -u openbao/exports/<arquivo>.json`.
2. Siga a lista impressa: SSH, servidor no Coolify, nó da tailnet, token da Railway (revogar no painel) e o bloco do
   cliente no `secrets.toml`. A GitHub App é desinstalada e o token da Vercel é invalidado pelo próprio `offboard`.
3. Logs antigos no OpenObserve expiram pela retenção (exporte antes pela UI, se ele pedir).

## Laboratório

O lab (`sim/`) simula control plane + VPS dev + VPS prd + registry + S3, instalados pelos **mesmos** `install/` da
VPS real. A rede Docker `172.30.50.0/24` faz o papel da tailnet.

```bash
sim/lab.sh up                        # monta ou conserta tudo (idempotente, ~6 min do zero)
sim/lab.sh verify                    # servidores, cofre do lab, sync, valor no container, Sentinel
sim/lab.sh restore-test staging      # backup → apaga o schema → restaura do S3 → confere
sim/lab.sh restore-test prod
sim/lab.sh down                      # APAGA o lab (volumes inclusive). O cofre principal não é tocado
```

Conferir que o container recebeu o valor do cofre (compara hashes, nunca valores):

```bash
.venv/bin/python sim/check-fingerprint.py <cliente>/<projeto>/staging JWT_SECRET api dev
```

Validar o adaptador Vercel num projeto descartável:

```bash
scripts/cp-secrets provider exec <conta> vercel -- python3 sim/bootstrap-vercel-probe.py
python3 sim/check-vercel-probe.py
```

Qualquer script contra o cofre do lab:

```bash
scripts/cp-lab cp-secrets status
scripts/cp-lab cp-secrets ui-token
```

**O que esperar no `verify`:** 3 servidores usable, `API staging (VPS dev) /health/ready → 200`,
`API prod (VPS prd) /health/ready → 200`, fingerprints iguais, `0 falhas de push` do Sentinel.

**Se falhar:** prod do lab em restart com `DEMO_USER_PASSWORD` vazio é conhecido (lacuna G5 do
roteiro de go-live da sua conta).

## Montar um cofre novo

1x por cofre vazio (máquina nova sem snapshot). Para **migrar** um cofre existente, use `restore` (ver
[instalação](instalacao.md#roteiro-na-vps-real-fase-f)).

```bash
cd openbao && docker compose up -d --wait && cd ..
scripts/cp-secrets init
scripts/cp-secrets status
scripts/cp-secrets apply
```

**O que esperar:** `[ok] inicializado (3 chaves, 2 para abrir) → openbao/.init.json (600)`, audit, KV, AppRole, operador
em `openbao/.bootstrap.env` e `[ok] token root revogado`.

**Depois (manual, obrigatório):** copie as 3 chaves do `.init.json` para o gerenciador de senhas e apague o arquivo
(`shred -u openbao/.init.json`). Perder 2 das 3 chaves = segredos irrecuperáveis.

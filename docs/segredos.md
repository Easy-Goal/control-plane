# Segredos: OpenBao e `scripts/cp-secrets`

Como o cofre funciona, quem acessa o quê e as regras. Os comandos do dia a dia estão em [comandos.md](comandos.md).

## Sumário

- [Por que OpenBao](#por-que-openbao)
- [Layout do cofre](#layout-do-cofre)
- [Subir o cofre local](#subir-o-cofre-local)
- [Operador: token da UI e secret_id](#operador-token-da-ui-e-secret_id)
- [Estado desejado e import de .env](#estado-desejado-e-import-de-env)
- [Rodar uma app sem .env (pull)](#rodar-uma-app-sem-env-pull)
- [Segredo compartilhado e rotação sem derrubar sessões](#segredo-compartilhado-e-rotação-sem-derrubar-sessões)
- [O que nunca girar direto](#o-que-nunca-girar-direto)
- [Fim de contrato (offboard)](#fim-de-contrato-offboard)
- [Arquivos sensíveis](#arquivos-sensíveis)
- [Regras](#regras)
- [Referência de subcomandos](#referência-de-subcomandos)
- [Histórico](#histórico)

## Por que OpenBao

ADR 062: audit log de cada leitura e policy por caminho (uma identidade lê exatamente um projeto/ambiente), sem
licença paga. O Infisical gratuito não tem nenhum dos dois.

- Imagem `openbao/openbao:2.7.2` fixada por digest, storage raft de nó único.
- Audit declarativo no `config.hcl` (JSON, valores em HMAC), volume `bao_audit`.
- Shamir 3/2: 3 chaves de unseal, 2 abrem o cofre. O `init` cria o operador e **revoga o root**.
- O cofre **volta selado** a cada reinício. As apps não caem (o modelo é push, ver [sync.md](sync.md)); só não dá para
  mudar segredo até o `unseal`.

## Layout do cofre

| Caminho | O que guarda | Quem lê |
|---|---|---|
| `kv/<cliente>/<projeto>/<ambiente>` | segredos de runtime de um ambiente | policy `<cliente>-<projeto>-<ambiente>-read` (uma AppRole de runtime) e o `cp-sync-<cliente>` |
| `kv/<cliente>/_providers/<provedor>` | credenciais de operação (Coolify, Vercel, GitHub App, Railway, OpenObserve, Umami) | só `cp-sync-<cliente>` e o operador |

- A própria Easy Goal é o cliente `easygoal` (nunca passa por offboard).
- Segredo compartilhado (`[[client.shared]]`) **não** tem caminho próprio: o `rotate` grava o mesmo valor no caminho
  de cada membro.
- Dev nunca lê prod: isolamento validado (leitura de prod, escrita e leitura de policies dão 403 e aparecem no audit).

## Subir o cofre local

```bash
cd openbao && docker compose up -d --wait && cd ..
scripts/cp-secrets init      # 1x: chaves → openbao/.init.json, operador → openbao/.bootstrap.env, revoga o root
scripts/cp-secrets status    # selado? audit ativo? .init.json ainda em disco?
scripts/cp-secrets unseal    # depois de reiniciar o Docker (o cofre volta SELADO)
```

Sem `.init.json` em disco, o `unseal` pede as chaves digitadas (2 de 3). Depois do `init`, as chaves vão para o
Bitwarden da Easy Goal e o arquivo sai do disco.

Destino dos scripts: `CP_BAO_ADDR` (padrão `http://127.0.0.1:8200`) e `CP_BAO_CACERT` (CA do cofre do control plane,
HTTPS). `scripts/cp-lab <script> ...` aponta para o laboratório (`https://127.0.0.1:8210`, CA `openbao/tls/sim-ca.crt`).

## Operador: token da UI e secret_id

A UI do OpenBao não tem usuário e senha. O operador é a AppRole `control-plane-bootstrap` (policy `cp-admin`), com
credencial em `openbao/.bootstrap.env`. O token gerado só vale no cofre que o emitiu.

| Credencial | Validade | Como revogar |
|---|---|---|
| token da UI / dos scripts | 1h, renovável até 4h | `scripts/cp-secrets ui-token --revoke` (revoga todos os tokens vivos do operador) |
| `secret_id` do `.bootstrap.env` | **não vence** | `scripts/cp-secrets operator rotate` |

- O `operator rotate` grava a credencial nova e testa o login **antes** de destruir as outras: se cair no meio, o
  arquivo já vale. Depois revoga os tokens vivos.
- Cofre restaurado do principal (lab) continua aceitando só a credencial antiga. Copie o `.bootstrap.env` **antes** do
  rotate e, depois, rode `CP_BAO_BOOTSTRAP=<cópia> scripts/cp-lab cp-secrets operator align` (grava no lab o
  secret_id novo do principal, destrói os outros) e `shred -u <cópia>`.
- Ensaiar no lab sem invalidar o principal: `CP_BAO_BOOTSTRAP=<cópia> scripts/cp-lab cp-secrets operator rotate`.
- Último `operator rotate` no cofre principal: **2026-11-04** (s353; 1 secret_id destruído, 6 tokens revogados, lab
  realinhado com `operator align`). Se houver cópia do `.bootstrap.env` no Bitwarden, ela precisa ser atualizada.

Passo a passo em [Revogar acesso do operador](comandos.md#revogar-acesso-do-operador).

## Estado desejado e import de .env

`openbao/secrets.toml` (versionado, **só nomes**) descreve clientes, projetos, ambientes, repos com `.env` a importar,
identidades de runtime, provedores e destinos.

```bash
scripts/cp-secrets plan      # o que mudaria (não altera nada)
scripts/cp-secrets apply     # policies <proj>-<env>-read, AppRoles de runtime e de sync, import de .env (idempotente)
scripts/cp-secrets audit 24  # leituras por identidade/ambiente, negados, todas as operações
scripts/cp-secrets backup    # snapshot do raft em openbao/backups/ (cifrado; copiar para fora da máquina)
```

- `import_env = { file = ".env", environment = "dev" }` num `[[client.project.repo]]`: só cria chaves que faltam.
  Depois do primeiro import, o OpenBao é a fonte de verdade.
- `legacy_path`: move 1x o layout antigo `kv/<projeto>/<env>` (ADR 062) para `kv/<cliente>/<projeto>/<env>`.
- Formato dos destinos: [sync.md](sync.md#estado-desejado-secretstoml).

## Rodar uma app sem .env (pull)

Mesmo fluxo que serviria numa VPS, mas hoje usado só para **dev local** (o modelo principal é push).

```bash
cd ~/projects/easy/health-stay-backend
~/projects/easy/control-plane/scripts/cp-secrets run health-stay-api-dev -- \
  docker compose --env-file /dev/null --profile full up -d --build --wait db migrate api
```

O `run` faz login com a AppRole (`openbao/runtime/<identidade>.env`), lê `kv/<cliente>/<projeto>/<ambiente>`, revoga o
token e executa o comando com as variáveis no ambiente do processo.

## Segredo compartilhado e rotação sem derrubar sessões

`[[client.shared]]` (exemplo comentado no `secrets.toml`): o mesmo valor em vários projetos do cliente.

```bash
scripts/cp-secrets rotate easygoal/sso-global prod                         # plan: membros, assinante, modo
scripts/cp-secrets rotate easygoal/sso-global prod --apply                 # gradual: novo em todos + _PREVIOUS = antigo
scripts/cp-secrets rotate easygoal/sso-global prod --finish --apply        # depois da janela (≥ 7 dias)
scripts/cp-secrets rotate easygoal/sso-global prod --maintenance --apply   # incidente: sem janela, todos deslogam
```

- Os apps verificam com `SSO_JWT_SECRET` e, se a assinatura falhar, com `SSO_JWT_SECRET_PREVIOUS`. Expirado ou com
  audience errado nunca passa pelo anterior. A assinatura usa só o atual.
- Branches `feat/sso-jwt-chave-dupla` em sso, `@easygoal/auth`, app-front, api-backend, easyai-crm, vaygo-api e
  vaygo-web: **pushadas (s352), aguardando PR e deploy**. Antes do deploy, o gradual equivale a uma manutenção.
- Os verificadores sincronizam primeiro e o assinante por último.
- `_PREVIOUS` desligado = valor aleatório que ninguém usa (nunca vazio: há destinos que recusam variável vazia).
- O `rotate` recusa membros com valores diferentes: igualar antes.
- Janela mínima: 7 dias (`EG_SESSION_MAX_AGE`). No api-backend vale o maior TTL emitido (sessão, refresh OAuth).
- **Dois níveis de SSO:** global (`eg_session`, grupo `sso-global`, `signer = "sso"`) e por app
  (`api_apps.jwt_secret` no banco do SSO: easyai-crm; vaygo-api + vaygo-web). No por app, `signer = ""`: salvar o
  valor novo no painel admin do SSO **depois** do sync.

## O que nunca girar direto

| Segredo | Por quê |
|---|---|
| `AES_KEY` (Health Stay) | cifra dado de saúde: trocar exige recifrar os dados (processo à parte) |
| chaves VAPID (vaygo-api) | trocar derruba todas as inscrições de push |

Só com vazamento confirmado, e com plano próprio.

## Fim de contrato (offboard)

```bash
scripts/cp-secrets offboard <cliente>                        # plan
scripts/cp-secrets offboard <cliente> --apply --yes <cliente>
```

Faz backup, exporta JSON para o Bitwarden do cliente (`openbao/exports/`, texto puro: importar e `shred -u`), revoga os
tokens de operação que o provedor permite (Vercel invalida o token; GitHub desinstala a App; Railway e Coolify ficam
como passo manual), apaga AppRoles, policies e `kv/<cliente>/*` e lista os passos manuais (SSH, Coolify, tailnet,
bloco do `secrets.toml`). Junto: `scripts/cp-obs revoke <cliente> --apply`.

## Arquivos sensíveis

Todos fora do git, permissão 600.

| Arquivo | O que é | Onde deve morar |
|---|---|---|
| `openbao/.init.json` | 3 chaves de unseal (2 abrem o cofre) | **gerenciador de senhas**, depois apagar daqui |
| `openbao/.bootstrap.env` | AppRole do operador `control-plane-bootstrap` (policy `cp-admin`) | esta máquina |
| `openbao/runtime/*.env` | AppRole de runtime (lê um ambiente) | o servidor que roda a app |
| `openbao/backups/*.snap` | snapshot cifrado | fora da máquina (sem as chaves não abre) |
| `openbao/exports/*.json` | export do offboard (texto puro) | Bitwarden do cliente, depois `shred -u` |
| `sim/.s3.json` | chaves do S3 do laboratório | só o lab |
| `/data/coolify/source/.env` (VPS) | segredos do próprio Coolify | só a VPS |
| `/data/cp/observability/.env` (VPS) | senhas de admin do OpenObserve e do Umami | só a VPS (cópia no cofre via `observability-cred.sh`) |
| `/data/cp/ca/ca.key` (VPS) | chave da CA do OpenBao | só a VPS |

Não são segredo, mas ficam fora do git (`openbao/tls/` no `.gitignore`; o install regenera): `openbao/tls/sim-ca.crt`,
`openbao/tls/prod-ca.crt`.

## Regras

- Valores nunca aparecem em saída de script, log ou chat: só nomes, contagens e ids.
- Import de `.env` só cria chaves que faltam; depois do primeiro import o OpenBao é a fonte de verdade.
- Versão fixada por digest (`openbao/docker-compose.yml`): atualizar de propósito, com `backup` antes.
- Cofre local: porta só em `127.0.0.1`, HTTP. Na VPS: acesso pela tailnet, com TLS.
- Audit em JSON no volume `bao_audit` (valores em HMAC) → OpenObserve (ADR 066, fase O3).
- Chaves de unseal e credenciais do control plane ficam no Bitwarden **da Easy Goal**, nunca no de um cliente.

## Referência de subcomandos

Do docstring de `scripts/cp-secrets` (rode `scripts/cp-secrets` sem argumentos para ver):

```text
status                                  selo e audit + painel: destinos, versão cofre × sincronizada, validade dos tokens
init                                    1x: inicializa, abre, liga audit/kv/approle, cria o operador e revoga o root
unseal                                  abre o cofre depois de reiniciar (chaves do .init.json ou digitadas)
plan | apply                            policies + AppRoles (runtime e sync) + import de .env + migração de layout
keys <cli>/<proj>/<env>                 nomes e versão (nunca valores)
secret gen|set <cli>/<proj>/<env> CHAVE [--if-missing] [--bytes N] [--stdin]
run <identidade> -- <cmd>               injeta os segredos do ambiente no processo (dev local)
provider set <cli> <prov> [campo=valor ...] [--stdin campo] [--expires AAAA-MM-DD]
provider list <cli>                     provedores e campos (sem valores)
provider exec <cli> <prov> -- <cmd>     roda o comando com CP_<CAMPO> no ambiente
sync plan | apply [<cli>[/<proj>[/<target>]]] [--redeploy]
rotate <cli>/<grupo> <env> [--maintenance | --finish] [--stdin] [--apply]
offboard <cli> [--apply --yes <cli>] [--out arquivo]
ui-token [--print] | ui-token --revoke
operator rotate | operator align        (align com CP_BAO_BOOTSTRAP=<cópia antiga>)
audit [horas]
backup
restore <snapshot>                      restaura num OpenBao novo (CP_BAO_ADDR) e abre com as chaves originais
```

## Histórico

- Infisical v0.167.2 (etapa 2, 2026-10-28) substituído pelo OpenBao no mesmo dia: role por ambiente e audit log são
  Enterprise. Containers, volumes `cp-infisical_*` e credenciais removidos em 2026-10-29 (s351).
- 2026-11-04 (s353): `ui-token --revoke`, `operator rotate` e `operator align`; `operator rotate` rodado no principal.

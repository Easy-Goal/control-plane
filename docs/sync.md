# Sync: do cofre para os destinos (ADR 063)

O cofre é a fonte de verdade. O `sync` **empurra** cada segredo para o destino (Coolify, Vercel, GitHub Actions,
Railway) e faz o redeploy. As apps não dependem do cofre para rodar: cofre selado só bloqueia mudanças.

## Sumário

- [Fluxo](#fluxo)
- [Comandos](#comandos)
- [Estado desejado (secrets.toml)](#estado-desejado-secretstoml)
- [Como o sync decide o que mudar](#como-o-sync-decide-o-que-mudar)
- [Destinos](#destinos)
- [Token do Coolify: usuário de serviço](#token-do-coolify-usuário-de-serviço)
- [GitHub App do operador](#github-app-do-operador)
- [Painel de status](#painel-de-status)

## Fluxo

```
 secret gen/set, rotate, cp-obs ──▶ OpenBao kv/<cli>/<proj>/<env> (nova versão)
                                         │
                       cp-secrets sync plan (diff por nome/versão, nunca valor)
                       cp-secrets sync apply
                                         │ identidade cp-sync-<cliente>
               ┌───────────────┬─────────┴─────┬──────────────┐
               ▼               ▼               ▼              ▼
           Coolify          Vercel          GitHub         Railway
        (grava + redeploy (sensitive +     (Actions;      (skipDeploys +
         + health_url)     redeploy prod)  sem redeploy)   1 redeploy)
```

## Comandos

```bash
scripts/cp-secrets provider set <conta> coolify-sim url=http://127.0.0.1:8000   # token pedido oculto
scripts/cp-secrets provider list <conta>                                        # campos, sem valores
scripts/cp-secrets secret gen <cliente>/<projeto>/staging JWT_SECRET            # interna: nova versão
scripts/cp-secrets secret set <cliente>/<projeto>/prod MP_TOKEN                 # de um painel: pede oculto
scripts/cp-secrets sync plan                                                     # diff + divergências
scripts/cp-secrets sync apply <cliente>/<projeto>                               # grava, redeploy, espera o health_url
```

Por situação: [comandos.md](comandos.md#levar-segredos-para-a-vercel-o-coolify-o-github-ou-a-railway).

## Estado desejado (secrets.toml)

```toml
[[client]]
slug = "<cliente>"

[[client.provider]]          # credencial em kv/<conta>/_providers/coolify-sim
name = "coolify-sim"
kind = "coolify"

[[client.project]]
slug = "<projeto>"
environments = ["dev", "staging", "prod"]

[[client.project.target]]
name = "api-staging-sim"
provider = "coolify-sim"
environment = "staging"
resource = "service"                         # ou "application"
resource_name = "<aplicação>-staging"    # service no Coolify (cp-coolify service ensure)
keys = ["NODE_ENV", "POSTGRES_USER", "POSTGRES_PASSWORD", "DB_HOST", "JWT_SECRET"]   # allowlist obrigatória
health_url = "http://127.0.0.1:3101/health/ready"
```

- `keys` é a **allowlist** (obrigatória): o resto do ambiente (ex.: `DATABASE_URL` local) nunca sai do cofre.
- Exemplos comentados no próprio `secrets.toml`: destino GitHub (`repo`, `github_environment`), Railway
  (`railway_project`, `railway_environment`, `railway_service`) e `[[client.shared]]`.
- Prod sem `DEMO_USER_PASSWORD`: usuário de demonstração não existe em produção.

## Como o sync decide o que mudar

- A versão sincronizada fica no `custom_metadata` do caminho (`sync.<target>`) e só é anotada **depois** de um redeploy
  que deu certo. Se falhou, o próximo `apply` refaz (`--redeploy` força).
- **Divergência** (alguém mudou no painel do destino): o `plan` avisa e o `apply` restaura o valor do cofre.
  Variáveis fora da allowlist não são tocadas.
- Destino que não devolve o valor (Vercel, GitHub): compara pela data de atualização.
- Valor vazio no destino é placeholder (o Coolify cria as variáveis do compose sem valor): preenche sem acusar
  divergência.
- Destino recriado (ex.: reinstalação) é detectado pelo id do recurso (`res=` na marca): vira sincronização inicial,
  sem falsa divergência.
- Identidade `cp-sync-<cliente>`: lê só `kv/<cliente>/*` e anota metadata; não escreve segredo.

## Destinos

| `kind` | O que faz | Credencial | Observação |
|---|---|---|---|
| `coolify` | grava env de um service ou application, redeploy, espera o `health_url` | token do usuário de serviço `cp-sync` (90 dias) | ver abaixo |
| `vercel` | env `sensitive`, redeploy da produção (espera o READY) | token do time com escopo e expiração (`team_id` opcional) | |
| `github` | secrets do Actions do repo ou de um environment | GitHub App (`app_id`, `installation_id`, `private_key`) | sem redeploy: vale na próxima execução |
| `railway` | variáveis de um service num environment, `skipDeploys`, 1 redeploy, espera `SUCCESS` | token de **workspace** | temporário até a migração. Ids pelo Cmd/Ctrl+K no painel. Service com aprovação manual para em `NEEDS_APPROVAL` com aviso. Referências `${{...}}` da Railway ficam fora da allowlist |
| `supabase` | — | — | **sem adaptador** (lacuna G4) |

O GitHub precisa do `.venv` (PyNaCl/PyJWT). O `cp-secrets` reexecuta nele sozinho:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

## Token do Coolify: usuário de serviço

- O token do sync é do usuário de serviço `cp-sync` (membro admin do time, senha aleatória descartada, token com
  expiração), **nunca** o de um humano.
- Motivo: o Coolify revoga **todos** os tokens de API de um usuário quando a senha dele muda (`DeletesUserSessions`).
  Trocar a senha do operador derrubou o sync com 401.
- Gerar/renovar: `install/coolify-sync-token.sh` (ver [comandos](comandos.md#renovar-o-token-do-sync-do-coolify)).

## GitHub App do operador

Acesso aos secrets sem PAT de pessoa. Criar 1x na org:

1. `https://github.com/organizations/<organização>/settings/apps/new`. Webhook **desligado**. Permissões de repositório:
   só **Secrets: Read and write** (+ **Environments: Read and write** se usar `github_environment`; Metadata: read é
   obrigatória). Instalação: "Only on this account" até o primeiro cliente precisar.
2. Anote o **App ID**, gere a **private key** (.pem) e instale em **Only select repositories**. O id da instalação
   está na URL (`.../settings/installations/<id>`).
3. Grave no cofre e apague o arquivo:

   ```bash
   scripts/cp-secrets provider set <conta> github app_id=<id> installation_id=<id> --stdin private_key < arquivo.pem
   shred -u arquivo.pem
   ```

   Cada sync gera um token de 1h restrito ao repo do target e o descarta no fim. A chave da App não expira: trocar
   1x/ano (gerar nova, `provider set`, apagar a antiga no GitHub).
4. Cliente com GitHub próprio: a App é instalada na conta dele (vira provedor `github` do cliente com o
   `installation_id` de lá); o `offboard` desinstala.

**Estado real** (ADR 064): a App `control-plane-easy` está instalada em **todos os repos** da org (decisão do
fundador) e tem `organization_secrets: write`. Risco: chave vazada alcança a org inteira. Na rotação geral, gerar
uma private key nova e remover `organization_secrets` se não houver uso.

## Painel de status

`scripts/cp-secrets status` mostra uma tela por cliente:

- cada provedor com a validade (`provider set ... --expires AAAA-MM-DD`; aviso `← RENOVAR` a 15 dias);
- cada destino com a versão do cofre × a sincronizada (`em dia`, `PENDENTE`, `nunca sincronizado`).

Só lê o cofre. Divergência no destino aparece no `sync plan`, que consulta os provedores.

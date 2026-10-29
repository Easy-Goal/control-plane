# control-plane

Infra do control plane da Easy Goal (ADR 061 e ADR 062 no `easy-labs`): os serviços que vão rodar na VPS
(Coolify, segredos, observabilidade). Hoje roda na máquina de dev que simula a VPS (`10home`).
Só infra e estado desejado; nenhum segredo versionado.

## Serviços

| Serviço | Pasta | Acesso | Estado |
|---|---|---|---|
| OpenBao (segredos + audit) | `openbao/` | `http://127.0.0.1:8200` (só local) | etapa 2 |

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

### Arquivos sensíveis (fora do git, 600)

| Arquivo | O que é | Onde deve morar |
|---|---|---|
| `openbao/.init.json` | 3 chaves de unseal (2 abrem o cofre) | **gerenciador de senhas**, depois apagar daqui |
| `openbao/.bootstrap.env` | AppRole do operador `control-plane-bootstrap` (policy `cp-admin`) | esta máquina |
| `openbao/runtime/*.env` | AppRole de runtime (lê um ambiente) | o servidor que roda a app |
| `openbao/backups/*.snap` | snapshot cifrado | fora da máquina (sem as chaves não abre) |

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

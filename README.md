# control-plane

Infra do control plane da Easy Goal (ADRs 061–066 no `easy-labs`).
- **Cofre** (OpenBao): fonte de verdade de todos os segredos, com audit de cada leitura.
- **Sync**: empurra os segredos para Coolify, Vercel, GitHub Actions e Railway e faz o redeploy.
- **Coolify**: deploy em todas as VPS. **OpenObserve + Umami**: logs e analytics das apps.
- Hoje roda na máquina de dev (`10home`): cofre principal local + laboratório `sim/` instalado pelos mesmos scripts
  que vão para a VPS real. Só infra e estado desejado; nenhum segredo versionado.

```
 sua máquina (scripts/cp-*)          VPS do control plane (só tailnet)          destinos
 ┌──────────────────────┐  tailnet  ┌──────────────────────────────┐  push  ┌──────────────────┐
 │ cp-secrets  cp-obs   │ ────────▶ │ OpenBao  Coolify             │ ─────▶ │ Vercel, GitHub,  │
 │ cp-coolify  cp-lab   │           │ OpenObserve  Umami  gateway ─┼─ Funnel│ Railway, VPS app │
 │ openbao/secrets.toml │           └──────────────┬───────────────┘ (logs) └──────────────────┘
 └──────────────────────┘                          │ SSH (Coolify)
                                     VPS dev compartilhada · VPS prd por projeto · VPS do cliente
```

## Sumário

| Documento | Para quê |
|---|---|
| [docs/comandos.md](docs/comandos.md) | **o que rodar em cada situação**, com exemplo real copiável |
| [docs/acesso.md](docs/acesso.md) | como entrar em cada ferramenta (lab e VPS), de qualquer device |
| [docs/go-live-vps-principal.md](docs/go-live-vps-principal.md) | audit, inventário e **fases do go-live** com estado e passos manuais |
| [docs/conexoes.md](docs/conexoes.md) | como apps da Easy Goal, da org GitHub e de clientes se conectam |
| [docs/custos.md](docs/custos.md) | o que é grátis, o que tem free tier e o que é pago (com fonte e data) |
| [docs/vps.md](docs/vps.md) | opções de VPS, preço, região, LGPD, RAM do control plane |
| [docs/segredos.md](docs/segredos.md) | OpenBao: layout, operador, rotação, offboard, arquivos sensíveis, regras |
| [docs/sync.md](docs/sync.md) | sync para os destinos, `secrets.toml`, GitHub App |
| [docs/observabilidade.md](docs/observabilidade.md) | OpenObserve, Umami, gateway, `cp-obs`, contenção |
| [docs/instalacao.md](docs/instalacao.md) | instaladores, roteiro na VPS real, laboratório, gotchas |

## Início rápido

Começo de toda sessão, na raiz do repo:

```bash
cd ~/projects/easy/control-plane
scripts/cp-secrets status            # selado? audit? tokens vencendo? destinos pendentes?
scripts/cp-secrets unseal            # só se o status disser selado=True (pede 2 das 3 chaves do Bitwarden)
scripts/cp-lab cp-secrets unseal     # idem para o cofre do laboratório, se for usar o lab
scripts/cp-secrets sync plan         # o que está diferente entre o cofre e os destinos (não muda nada)
scripts/cp-secrets ui-token          # se for usar a UI do OpenBao (token de 1h na área de transferência)
```

Mudou um segredo? `scripts/cp-secrets secret gen|set <cliente>/<projeto>/<ambiente> CHAVE` e depois
`scripts/cp-secrets sync apply <cliente>/<projeto>`. Todo o resto em [docs/comandos.md](docs/comandos.md).

Regras que valem sempre:
- Nenhum script imprime valor de segredo. Valores nunca vão para chat, log ou commit.
- `scripts/` rodam na sua máquina; `install/` rodam na VPS, como root.
- `scripts/cp-lab <script> ...` roda qualquer script contra o cofre do **laboratório** (`https://127.0.0.1:8210`).

## Mapa de pastas

| Pasta / arquivo | O que tem |
|---|---|
| `scripts/cp-secrets` | cofre: status, unseal, segredos, sync, rotate, offboard, operador, audit, backup/restore |
| `scripts/cp-coolify` | Coolify pela API: chave SSH, servidores, services, bancos, backups S3 |
| `scripts/cp-obs` | observabilidade: orgs/tokens de ingestão no OpenObserve, sites no Umami, revoke |
| `scripts/cp-lab` | wrapper: roda um script contra o cofre do laboratório |
| `scripts/cp_providers.py` | adaptadores dos destinos (Coolify, Vercel, GitHub, Railway) |
| `openbao/` | cofre local (compose, `config.hcl`) e `secrets.toml` (estado desejado, só nomes) |
| `install/` | instaladores da VPS: `control-plane.sh`, `app-server.sh`, token do sync, senhas da observabilidade |
| `install/observability/` | compose do OpenObserve + Umami + gateway e o `Caddyfile` (allowlist pública) |
| `install/openbao/` | compose e config do OpenBao com TLS para a VPS |
| `sim/` | laboratório: control plane + VPS dev + VPS prd + registry + S3 (`sim/lab.sh`) |
| `docs/` | esta documentação |
| `requirements.txt` | dependências do `.venv` (adaptador GitHub) |

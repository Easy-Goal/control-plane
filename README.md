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

## Como rodar

Comece pelo painel. Ele abre sem Docker, sem cofre e sem credencial, mostra o que falta nesta máquina e ensina o próximo
passo. Só instale o resto quando for usar.

```bash
git clone git@github.com:Easy-Goal/control-plane.git
cd control-plane
scripts/cp-panel          # http://127.0.0.1:4700 (Windows sem WSL: py scripts\cp-panel)
```

Depois de abrir, vá em **Configurar > Esta máquina** para ver o que falta aqui, com o comando de cada item, e em **Guias**
para o passo a passo de cada situação.

### O que dá para fazer em cada nível

Cada nível acrescenta algo ao anterior. Pare no que você precisa.

| Nível | O que você consegue | Precisa instalar | Como começar |
|---|---|---|---|
| **1. Só o painel** | Ver todas as telas com exemplos, ler os guias, ver o que falta nesta máquina, gerar os comandos de um cliente novo | Git e Python 3.11+ | `scripts/cp-panel` |
| **2. Stack local** | Guardar segredos no cofre, ver logs e analytics nesta máquina, importar `.env`, testar backup e restauração | Docker e `jq` | `scripts/cp-local up`, depois `scripts/cp-secrets init` ([local.md](docs/local.md)) |
| **3. Laboratório** | Simular VPS com Coolify, deploy e backup, ver dados reais no painel e agir por ele | Docker. O lab usou cerca de 2,1 GB de RAM em repouso; o cofre local precisa existir antes | `sim/lab.sh up`, depois `scripts/cp-lab cp-panel`, ou com `--acoes` para agir ([painel.md](docs/painel.md#agir-pelo-painel-no-laboratório)) |
| **4. Contas reais** | Levar segredos para Vercel, Railway e GitHub Actions | Tokens das contas; `.venv` para o GitHub | [plano-ate-a-vps.md](docs/plano-ate-a-vps.md) |
| **5. VPS** | Operar de qualquer device | Tailscale e a VPS contratada | [go-live-vps-principal.md](docs/go-live-vps-principal.md) |

### Para que serve cada ferramenta

| Ferramenta | Quem usa | Sem ela | Instalação |
|---|---|---|---|
| Python 3.11+ | Painel e todos os `scripts/cp-*` | Nada roda. Em versão menor, só o painel abre, sem ler `secrets.toml` | `sudo apt install -y python3` |
| Docker | Stack local e laboratório | O painel funciona e mostra Docker como opcional | Docker Desktop com integração WSL |
| `jq` | `scripts/cp-local` | Só a stack local para | `sudo apt install -y jq` |
| `ssh-keygen` | `scripts/cp-coolify key` | Não cria a chave das VPS | já vem no OpenSSH |
| `.venv` | Destino GitHub Actions | Os outros destinos funcionam | `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt` |
| Tailscale | Acesso à VPS | Stack local e laboratório funcionam | ver [acesso.md](docs/acesso.md) |

**Para abrir o painel em outro device, não copie `.init.json` nem `.bootstrap.env`.** Nenhum deles é necessário. Essa
credencial só vai para uma máquina que também vai operar o cofre.

## Sumário

| Documento | Para quê |
|---|---|
| [docs/painel.md](docs/painel.md) | **painel único**: abre em qualquer device com `scripts/cp-panel`, mostra o que falta e ensina a configurar |
| [docs/plano-ate-a-vps.md](docs/plano-ate-a-vps.md) | **seus passos manuais** e o que roda em paralelo até contratar a VPS |
| [docs/local.md](docs/local.md) | **stack local**: cofre, logs e analytics na sua máquina, antes da VPS |
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

## Rotina de quem já tem o cofre

Começo de toda sessão, na raiz do repo:

```bash
cd ~/projects/easy/control-plane
scripts/cp-secrets status            # selado? audit? tokens vencendo? destinos pendentes?
scripts/cp-secrets unseal            # só se o status disser selado=True (pede 2 das 3 chaves do Bitwarden)
scripts/cp-lab cp-secrets unseal     # idem para o cofre do laboratório, se for usar o lab
scripts/cp-secrets sync plan         # o que está diferente entre o cofre e os destinos (não muda nada)
scripts/cp-secrets ui-token          # se for usar a UI do OpenBao (token de 1h na área de transferência)
```

Depois de reiniciar a máquina ou o Docker, os cofres voltam selados: faça o unseal antes de abrir o resto.

Abra o painel e comece pela lista de atenção do **Quadro**:

```bash
scripts/cp-panel                  # só exemplos e o que existe nesta máquina
scripts/cp-lab cp-panel           # dados reais do laboratório, só leitura
scripts/cp-lab cp-panel --acoes   # também age no laboratório: abra o link que o terminal mostrar
```

### Como entrar em cada ferramenta

O painel traz o mesmo em **Ferramentas**, por ambiente, e o passo a passo em **Guias > Começar o dia**.

| Ferramenta | Stack local | Laboratório | VPS (só tailnet) | Usuário | Senha ou token |
|---|---|---|---|---|---|
| Painel | `127.0.0.1:4700` | `127.0.0.1:4700` | ainda não | sem login | no lab com `--acoes`, o link do terminal |
| Cofre (OpenBao) | `http://127.0.0.1:8200/ui/` | `https://127.0.0.1:8210/ui/` | `https://<cp>:8200/ui/` | sem usuário, **Method: Token** | `ui-token`, abaixo |
| Coolify | não existe | `http://127.0.0.1:8000` | `http://<cp>:8000` | lab: `operador@cp-sim.local`; VPS: `contato@easygoal.com.br` | a que você definiu, no Bitwarden |
| OpenObserve | `http://127.0.0.1:15080` | `http://127.0.0.1:5080` | `http://<cp>:5080` | local: `operador@cp-local.local`; lab: `operador@cp-sim.local`; VPS: `contato@easygoal.com.br` | cofre, abaixo |
| Umami | `http://127.0.0.1:13300` | `http://127.0.0.1:3300` | `http://<cp>:3300` | `admin` | cofre, abaixo |

Nenhum comando abaixo mostra o valor: ele vai para a área de transferência. Cole no login e limpe o histórico com Win+V.
Fora do WSL, troque `clip.exe` por `wl-copy` (Linux) ou `pbcopy` (macOS).

```bash
# Cofre: token de 1 h, que só vale no cofre que o emitiu
scripts/cp-secrets ui-token                  # local
scripts/cp-lab cp-secrets ui-token           # laboratório
scripts/cp-secrets ui-token --revoke         # ao terminar (no lab, com cp-lab)

# OpenObserve e Umami: senha guardada no cofre
scripts/cp-secrets provider exec easygoal openobserve-local -- sh -c 'printf %s "$CP_PASSWORD" | clip.exe'
scripts/cp-secrets provider exec easygoal umami-local -- sh -c 'printf %s "$CP_PASSWORD" | clip.exe'
scripts/cp-lab cp-secrets provider exec easygoal openobserve-sim -- sh -c 'printf %s "$CP_PASSWORD" | clip.exe'
scripts/cp-lab cp-secrets provider exec easygoal umami-sim -- sh -c 'printf %s "$CP_PASSWORD" | clip.exe'

# Coolify: só se não souber a senha. Define outra; guarde no Bitwarden
docker exec -it cp-sim-sim-cp-1 docker exec -it coolify php artisan root:reset-password   # laboratório
ssh root@<cp> docker exec -it coolify php artisan root:reset-password                     # VPS
```

O cofre do laboratório usa uma CA própria e o navegador avisa de conexão não segura. Para tirar o aviso, importe
`openbao/tls/sim-ca.crt` como autoridade confiável.

**Contas externas**, cada uma com o login da própria conta e 2FA: [Bitwarden](https://vault.bitwarden.com),
[Vercel](https://vercel.com/dashboard), [Railway](https://railway.com/dashboard), [GitHub](https://github.com/Easy-Goal),
[Supabase](https://supabase.com/dashboard) e [Tailscale](https://login.tailscale.com/admin). Em cada cliente, use a conta
dele. Detalhes, cuidados e acesso pelo celular em [docs/acesso.md](docs/acesso.md).

### Mudou um segredo?

`scripts/cp-secrets secret gen|set <cliente>/<projeto>/<ambiente> CHAVE` e depois
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
| `scripts/cp-local` | stack local: sobe, para e consulta cofre + observabilidade nesta máquina |
| `local/` | portas da stack local; `local/observability/` é gerado e fica fora do git |
| `scripts/cp-panel` e `panel/` | painel local, sem dependências; exemplos em `demo.json`, leitura real em `live.py`, ações em `actions.py`, cliente novo em `clients.py` |
| `scripts/cp_config.py` | leitura única do estado desejado: `secrets.toml` mais `openbao/clients/` |
| `scripts/cp_providers.py` | adaptadores dos destinos (Coolify, Vercel, GitHub, Railway) |
| `openbao/` | cofre local (compose, `config.hcl`), `secrets.toml` e `clients/<cliente>.toml` (estado desejado, só nomes) |
| `install/` | instaladores da VPS: `control-plane.sh`, `app-server.sh`, token do sync, senhas da observabilidade |
| `install/observability/` | compose do OpenObserve + Umami + gateway e o `Caddyfile` (allowlist pública) |
| `install/openbao/` | compose e config do OpenBao com TLS para a VPS |
| `sim/` | laboratório: control plane + VPS dev + VPS prd + registry + S3 (`sim/lab.sh`) |
| `docs/` | esta documentação |
| `requirements.txt` | dependências do `.venv` (adaptador GitHub) |

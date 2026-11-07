# control-plane

Um lugar só para operar as aplicações de vários clientes: segredos, deploy, logs, versões e o que falta fazer. O programa
não traz dados de nenhuma empresa: a conta (clientes, projetos, contas e destinos, só com nomes) vem de um repositório de
configuração seu, e os valores ficam no cofre.

- **Painel:** visão única, com primeira visita guiada. Roda só com Python.
- **Cofre** (OpenBao, opcional): fonte de verdade dos segredos, com audit de cada leitura.
- **Sync:** leva os segredos para Coolify, Vercel, GitHub Actions e Railway e faz o redeploy.
- **Coolify, OpenObserve e Umami** (opcionais): deploy nas VPS, logs e analytics.

## Para começar

**O mínimo é Python 3.9 ou mais novo.** Não precisa de root, Docker, cofre nem credencial.

Enquanto o repositório for privado, baixe com uma chave SSH que tenha acesso a ele:

```bash
git clone --depth 1 git@github.com:<organização>/control-plane.git
```

| Sistema | Instalar |
|---|---|
| Linux, macOS, WSL e outros Unix | `sh control-plane/install.sh` |
| Windows (PowerShell) | `powershell -ExecutionPolicy Bypass -File control-plane\install.ps1` |

Depois, rode `cplane`, ou o caminho completo que o instalador mostrar. O navegador abre com três caminhos: importar uma
conta, começar do zero ou ver com exemplos. Detalhes e onde cada coisa fica: [docs/instalar.md](docs/instalar.md).

### O que cada coisa exige

Instale só o que for usar. `cplane doctor` confere a máquina e mostra o comando do seu sistema.

| Para | Precisa | Comando |
|---|---|---|
| Organizar clientes e projetos, ver guias e exemplos | Python 3.9+ | `cplane` |
| Importar a conta de um repositório | git e chave SSH com acesso a ele | `cplane import <repositório>` |
| Importar a conta sem git | o arquivo gerado por `cplane export` | `cplane import <arquivo>` |
| Guardar segredos nesta máquina | Docker com Compose | `cplane vault up`, `cplane secrets init` |
| Destino GitHub Actions | `.venv` com `requirements.txt`, só no repositório | ver [docs/sync.md](docs/sync.md) |
| Subir tudo nesta máquina: cofre, logs, analytics e painel | Docker com Compose | `cplane up` ([local.md](docs/local.md)) |
| Laboratório com VPS simuladas | repositório, os mesmos da stack local e cerca de 2,1 GB de RAM | `sim/lab.sh up` |
| Criar a chave SSH das VPS | `ssh-keygen`, que vem com o OpenSSH | `cplane coolify --client <cliente> key` |
| Acessar uma VPS | Tailscale | [docs/acesso.md](docs/acesso.md) |

**Acesso de outras máquinas:** só com `cplane --remoto`, depois de criar a conta com autenticador e atrás do `tailscale serve`. Nova máquina precisa de aprovação por código: [docs/maquinas.md](docs/maquinas.md). Antes de usar em VPS, faça a revisão de segurança listada em [próximos passos](docs/proximos-passos.md).

**Para abrir o painel em outro device, não copie `.init.json` nem `.bootstrap.env`.** Valores do cofre e chaves de unseal
não viajam com a conta.

## A sua conta

| O quê | Onde fica |
|---|---|
| Programa | Este repositório ou o pacote instalado. Sem dados de empresa |
| Clientes, projetos, destinos, nome da conta | Repositório privado seu, só com nomes: `workspace.toml`, `secrets.toml`, `clients/` |
| Roteiros e documentos da sua operação | No mesmo repositório de configuração |
| Valores de segredo | No cofre |
| Chaves de unseal | No seu gerenciador de senhas, nunca junto do snapshot |

`workspace.toml` define o nome e a conta principal, que nunca passa por offboard:

```toml
name = "Minha Empresa"
home_client = "minhaempresa"

[[probe]]                      # opcional: aplicação a conferir nesta máquina, só endereço local
name = "API"
url = "http://127.0.0.1:3001/health"
```

## Trabalhar neste repositório

Em um clone, sem instalar, `scripts/cp-panel` abre o painel. Pasta com `openbao/secrets.toml` usa o layout antigo, sem
primeira visita. `CP_HOME=<pasta>` aponta os scripts para os dados dela.

```bash
python3 -m unittest panel/test_server.py panel/test_install.py panel/test_auth.py
python3 scripts/build_release.py    # lista de inclusão; falha com nome de negócio ou forma de segredo
```

**Regras:** o mesmo comando em toda plataforma, com as exceções listadas em [próximos passos](docs/proximos-passos.md).
Nome de empresa, cliente ou aplicação não entra no programa nem nas docs: um teste garante isso.

## Sumário

| Documento | Para quê |
|---|---|
| [docs/instalar.md](docs/instalar.md) | **instalar em qualquer sistema**, importar a conta e onde cada coisa fica |
| [docs/maquinas.md](docs/maquinas.md) | **máquinas e acesso remoto**: papéis, classes, aprovação, login e limites |
| [docs/proximos-passos.md](docs/proximos-passos.md) | o que falta construir, recomendações e exceções de plataforma |
| [docs/painel.md](docs/painel.md) | **painel único**: telas, segurança e o caminho do exemplo ao real |
| [docs/local.md](docs/local.md) | **stack local**: cofre, logs e analytics na sua máquina, antes da VPS |
| [docs/comandos.md](docs/comandos.md) | **o que rodar em cada situação**, com exemplo real copiável |
| [docs/acesso.md](docs/acesso.md) | como entrar em cada ferramenta (lab e VPS), de qualquer device |
| [docs/custos.md](docs/custos.md) | o que é grátis, o que tem free tier e o que é pago (com fonte e data) |
| [docs/vps.md](docs/vps.md) | opções de VPS, preço, região, LGPD, RAM do control plane |
| [docs/segredos.md](docs/segredos.md) | OpenBao: layout, operador, rotação, offboard, arquivos sensíveis, regras |
| [docs/sync.md](docs/sync.md) | sync para os destinos, `secrets.toml`, GitHub App |
| [docs/observabilidade.md](docs/observabilidade.md) | OpenObserve, Umami, gateway, `cp-obs`, contenção |
| [docs/instalacao.md](docs/instalacao.md) | instaladores da VPS, roteiro na VPS real, laboratório, gotchas |

## Rotina de quem já tem o cofre

Começo de toda sessão, na raiz do repositório. Instalado pelo pacote, use `cplane secrets` no lugar de `scripts/cp-secrets`:

```bash
scripts/cp-secrets status            # selado? audit? tokens vencendo? destinos pendentes?
scripts/cp-secrets unseal            # só se o status disser selado=True (pede 2 das 3 chaves de unseal)
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
| Painel | `127.0.0.1:4700` | `127.0.0.1:4700` | `https://<cp>` com `--remoto` | na VPS, usuário, senha e autenticador | no lab com `--acoes`, o link do terminal |
| Cofre (OpenBao) | `http://127.0.0.1:8200/ui/` | `https://127.0.0.1:8210/ui/` | `https://<cp>:8200/ui/` | sem usuário, **Method: Token** | `ui-token`, abaixo |
| Coolify | não existe | `http://127.0.0.1:8000` | `http://<cp>:8000` | lab: `operador@cp-sim.local`; VPS: o seu e-mail | a que você definiu, no gerenciador de senhas |
| OpenObserve | `http://127.0.0.1:15080` | `http://127.0.0.1:5080` | `http://<cp>:5080` | local: `operador@cp-local.local`; lab: `operador@cp-sim.local`; VPS: o seu e-mail | cofre, abaixo |
| Umami | `http://127.0.0.1:13300` | `http://127.0.0.1:3300` | `http://<cp>:3300` | `admin` | cofre, abaixo |

Nenhum comando abaixo mostra o valor: ele vai para a área de transferência. Cole no login e limpe o histórico com Win+V.
Fora do WSL, troque `clip.exe` por `wl-copy` (Linux) ou `pbcopy` (macOS).

```bash
# Cofre: token de 1 h, que só vale no cofre que o emitiu
scripts/cp-secrets ui-token                  # local
scripts/cp-lab cp-secrets ui-token           # laboratório
scripts/cp-secrets ui-token --revoke         # ao terminar (no lab, com cp-lab)

# OpenObserve e Umami: senha guardada no cofre
scripts/cp-secrets provider exec <conta> openobserve-local -- sh -c 'printf %s "$CP_PASSWORD" | clip.exe'
scripts/cp-secrets provider exec <conta> umami-local -- sh -c 'printf %s "$CP_PASSWORD" | clip.exe'
scripts/cp-lab cp-secrets provider exec <conta> openobserve-sim -- sh -c 'printf %s "$CP_PASSWORD" | clip.exe'
scripts/cp-lab cp-secrets provider exec <conta> umami-sim -- sh -c 'printf %s "$CP_PASSWORD" | clip.exe'

# Coolify: só se não souber a senha. Define outra; guarde no gerenciador de senhas
docker exec -it cp-sim-sim-cp-1 docker exec -it coolify php artisan root:reset-password   # laboratório
ssh root@<cp> docker exec -it coolify php artisan root:reset-password                     # VPS
```

O cofre do laboratório usa uma CA própria e o navegador avisa de conexão não segura. Para tirar o aviso, importe
`openbao/tls/sim-ca.crt` como autoridade confiável.

**Contas externas**, cada uma com o login da própria conta e 2FA: seu gerenciador de senhas,
[Vercel](https://vercel.com/dashboard), [Railway](https://railway.com/dashboard), [GitHub](https://github.com),
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
| `scripts/cplane.py` | o comando único: painel, doctor, importar, exportar, máquina, cofre, atualizar |
| `scripts/cp_install.py`, `install.sh`, `install.ps1` | instalador de toda plataforma |
| `scripts/build_release.py` | gera o release em `dist/`, por lista de inclusão |
| `scripts/cp_paths.py` | resposta única sobre onde ficam programa e dados, e qual é a conta principal |
| `scripts/cp_config.py` | leitura única do estado desejado: `secrets.toml` mais `clients/` |
| `scripts/cp_providers.py` | adaptadores dos destinos (Coolify, Vercel, GitHub, Railway) |
| `openbao/` | cofre local (compose, `config.hcl`). `secrets*.toml` daqui são transitórios: saem depois de validada a instalação |
| `install/` | instaladores da VPS: `control-plane.sh`, `app-server.sh`, token do sync, senhas da observabilidade |
| `install/observability/` | compose do OpenObserve + Umami + gateway e o `Caddyfile` (allowlist pública) |
| `install/openbao/` | compose e config do OpenBao com TLS para a VPS |
| `sim/` | laboratório: control plane + VPS dev + VPS prd + registry + S3 (`sim/lab.sh`). Fora do pacote |
| `docs/` | esta documentação |
| `requirements.txt` | dependências do `.venv` (adaptador GitHub) |

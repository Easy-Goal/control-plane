# Instalar o control plane

Precisa só de **Python 3.9 ou mais novo**. Não usa root nem administrador. Cofre, logs e Docker são opcionais e vêm depois.

## O que é necessário

| Para | Precisa |
|---|---|
| Instalar e abrir o painel | Python 3.9+ |
| Baixar por `git clone` ou importar a conta de um repositório | git e chave SSH com acesso ao repositório. Para testar: `ssh -T git@github.com` |
| Rodar o cofre nesta máquina | Docker com Compose |
| Acessar uma VPS | Tailscale |

Se faltar algo, `cplane doctor` e o instalador mostram o comando do seu sistema.

## Baixar

**Por `git clone`,** enquanto o repositório for privado:

```sh
git clone --depth 1 git@github.com:<organização>/control-plane.git
```

**Por release,** quando houver um publicado: baixe todos os arquivos para uma pasta vazia. O `SHA256SUMS` precisa estar ao lado do pacote.

```sh
gh release download --repo <organização>/control-plane --dir control-plane
```

## Instalar

Dentro do que foi baixado, ou com o caminho da pasta:

| Sistema | Comando |
|---|---|
| Linux, macOS, WSL e outros Unix | `sh control-plane/install.sh` |
| Windows (PowerShell) | `powershell -ExecutionPolicy Bypass -File control-plane\install.ps1` |

Só o programa é copiado, por lista de inclusão. Repetir é seguro e não mexe nos dados. A pasta baixada pode ser apagada depois.

- **Linux, macOS e WSL:** se `~/.local/bin` não estiver no PATH, o instalador mostra a linha a acrescentar e o caminho completo para abrir agora.
- **Windows:** o instalador acrescenta a pasta ao PATH do seu usuário, sem administrador. Só terminais novos enxergam a mudança.

## Abrir

```sh
cplane
```

O navegador abre com a primeira visita: importar uma conta, começar do zero ou ver com exemplos. Sem navegador, como em uma VPS por SSH, use `cplane --sem-navegador` e abra o link por um túnel.

## Importar uma conta

```sh
cplane import git@github.com:<organização>/<repositório-de-configuração>.git
```

Ou, sem repositório, com o arquivo gerado por `cplane export` em outra máquina:

```sh
cplane import control-plane-conta-AAAAMMDD.tar.gz
```

Vêm só nomes e estrutura. Valores do cofre e chaves de unseal nunca viajam com a conta. A importação recusa `.env`, chaves privadas, snapshots e textos com forma de segredo.

Para receber as mudanças depois: `cplane import`, sem argumentos.

## Onde ficam as coisas

| | Linux, macOS, WSL, Unix | Windows |
|---|---|---|
| Programa | `~/.local/share/control-plane` | `%LOCALAPPDATA%\control-plane` |
| Comando | `~/.local/bin/cplane` | `%LOCALAPPDATA%\control-plane\bin\cplane.cmd` |
| Dados | `~/.config/control-plane` | `%APPDATA%\control-plane` |

`CP_HOME` troca a pasta dos dados. WSL e Windows são máquinas diferentes: cada um tem sua instalação e seu registro.

## O que a conta contém

Um repositório de configuração tem `workspace.toml` (nome e conta principal), `secrets.toml` e `clients/<cliente>.toml`. Para criar um, comece do zero no painel e publique a pasta da configuração em um repositório privado. O caminho aparece em **Configurar > Esta máquina**.

## Dia a dia

| Comando | O que faz |
|---|---|
| `cplane doctor` | Confere a máquina e diz como resolver o que faltar |
| `cplane up` | Sobe tudo, pede as chaves do cofre se preciso, confere e abre o painel (precisa de Docker) |
| `cplane vault up` | Sobe só o cofre nesta máquina (precisa de Docker) |
| `cplane --cofre` | Abre o painel conectado ao cofre desta máquina |
| `cplane machine` | Mostra id, nome e papel desta máquina |
| `cplane machine promote` | Torna esta máquina a principal da conta, normalmente a VPS |
| `cplane --remoto` | Aceita outras máquinas, com aprovação e login: veja `docs/maquinas.md` |
| `cplane update <pacote>` | Instala outra versão sem mexer nos dados |
| `cplane rollback` | Volta para a versão anterior |
| `cplane uninstall` | Remove o programa e mantém os dados |
| `cplane secrets`, `cplane obs`, `cplane coolify` | Os mesmos `scripts/cp-secrets`, `cp-obs` e `cp-coolify` citados na documentação do repositório |

## Ainda não disponível

Logs e analytics pelo pacote e os instaladores de VPS. Veja `docs/proximos-passos.md`.

# Instalar o control plane

Precisa só de **Python 3.9 ou mais novo**. Não usa root nem administrador. Cofre, logs e Docker são opcionais e vêm depois.

## Baixar

Baixe todos os arquivos do release para uma pasta vazia: `install.sh`, `install.ps1`, `install.py`, o pacote e `SHA256SUMS`.

Com o GitHub CLI, em qualquer sistema:

```sh
gh release download --repo <organização>/control-plane --dir control-plane-release
cd control-plane-release
```

Sem o GitHub CLI, com acesso SSH ao repositório:

```sh
git clone --depth 1 git@github.com:<organização>/control-plane.git
cd control-plane
```

## Instalar

| Sistema | Comando |
|---|---|
| Linux, macOS, WSL e outros Unix | `sh install.sh` |
| Windows (PowerShell) | `powershell -ExecutionPolicy Bypass -File install.ps1` |

Se faltar algo, o instalador para e mostra o comando deste sistema. Repetir é seguro.

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

## Dia a dia

| Comando | O que faz |
|---|---|
| `cplane doctor` | Confere a máquina e diz como resolver o que faltar |
| `cplane vault up` | Sobe o cofre nesta máquina (precisa de Docker) |
| `cplane --cofre` | Abre o painel conectado ao cofre desta máquina |
| `cplane machine` | Mostra id, nome e papel desta máquina |
| `cplane machine promote` | Torna esta máquina a principal da conta, normalmente a VPS |
| `cplane update <pacote>` | Instala outra versão sem mexer nos dados |
| `cplane rollback` | Volta para a versão anterior |
| `cplane uninstall` | Remove o programa e mantém os dados |

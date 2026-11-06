#!/bin/sh
# Instala o control plane em Linux, macOS, WSL e outros Unix, sem root. Windows: install.ps1.
#   sh install.sh             usa o pacote desta pasta ou, em um clone do repositório, a própria pasta
#   sh install.sh <pacote>    usa esse pacote, com o SHA256SUMS ao lado
# Precisa só de Python 3.9 ou mais novo. Nada é baixado nem instalado além do próprio programa.
set -eu
here=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)

python=''
for candidate in python3 python3.13 python3.12 python3.11 python3.10 python3.9 python; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
    python=$candidate
    break
  fi
done

if [ -z "$python" ]; then
  echo "Falta o Python 3.9 ou mais novo."
  if command -v apt-get >/dev/null 2>&1; then echo "  Como resolver: sudo apt-get install -y python3"
  elif command -v dnf >/dev/null 2>&1; then echo "  Como resolver: sudo dnf install -y python3"
  elif command -v apk >/dev/null 2>&1; then echo "  Como resolver: sudo apk add python3"
  elif command -v pacman >/dev/null 2>&1; then echo "  Como resolver: sudo pacman -S python"
  elif command -v zypper >/dev/null 2>&1; then echo "  Como resolver: sudo zypper install python3"
  elif command -v brew >/dev/null 2>&1; then echo "  Como resolver: brew install python3"
  elif command -v pkg >/dev/null 2>&1; then echo "  Como resolver: sudo pkg install python3"
  else echo "  Como resolver: instale pelo gerenciador de pacotes do sistema, ou em https://www.python.org/downloads/"
  fi
  echo "Depois, rode este comando de novo."
  exit 1
fi

package=${1:-}
if [ -z "$package" ]; then
  for found in "$here"/control-plane-*.tar.gz; do
    [ -f "$found" ] && package=$found
  done
fi

if [ -n "$package" ]; then
  [ -f "$here/install.py" ] || { echo "Falta o install.py ao lado do install.sh. Baixe todos os arquivos do release."; exit 1; }
  exec "$python" -I -B "$here/install.py" --package "$package"
fi
if [ -f "$here/scripts/cp_install.py" ]; then
  exec "$python" -I -B "$here/scripts/cp_install.py" --from-dir "$here"
fi
echo "Não encontrei o pacote control-plane-<versão>.tar.gz nesta pasta."
exit 1

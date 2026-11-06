#!/usr/bin/env python3
"""Instala o control plane nesta máquina: Linux, macOS, WSL, BSD e Windows, com o mesmo código.

Regras: sem root, sem baixar nada, sem instalar dependência. O que faltar é mostrado com o comando deste sistema.
Dados ficam fora do programa: instalar de novo, atualizar ou desinstalar não mexe neles.
Só stdlib e sem importar nada do pacote: este arquivo roda sozinho, antes de existir instalação.
"""
import argparse
import fnmatch
import hashlib
import os
import platform
import re
import shutil
import socket
import stat
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

MIN_PYTHON = (3, 9)
PORT = 4700
# O pacote é uma lista de inclusão: documento interno, teste e laboratório ficam fora mesmo se alguém esquecer deles.
INCLUDE = [
    "VERSION", "requirements.txt",
    "panel/actions.py", "panel/auth.py", "panel/clients.py", "panel/live.py", "panel/server.py", "panel/workspace.py", "panel/demo.json", "panel/web/*",
    "scripts/cp-secrets", "scripts/cp-obs", "scripts/cp-coolify", "scripts/cp_config.py", "scripts/cp_paths.py", "scripts/cp_providers.py",
    "scripts/cp_toml.py", "scripts/cp_install.py", "scripts/cplane.py", "scripts/_vendor/*",
    "openbao/docker-compose.yml", "openbao/config.hcl",
    "docs/instalar.md", "docs/maquinas.md", "docs/proximos-passos.md",
]


def included(name):
    return "__pycache__" not in name and any(fnmatch.fnmatchcase(name, pattern) for pattern in INCLUDE)


def is_windows():
    return os.name == "nt"


def system_name():
    system = platform.system()
    if system == "Linux" and "microsoft" in platform.release().lower():
        return "wsl"
    return {"Windows": "windows", "Darwin": "macos", "Linux": "linux"}.get(system, "unix")


def program_root(env=None):
    env = os.environ if env is None else env
    if env.get("CP_PROGRAM_ROOT"):
        return Path(env["CP_PROGRAM_ROOT"])
    if is_windows():
        return Path(env.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "control-plane"
    return Path(env.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "control-plane"


def bin_dir(env=None):
    env = os.environ if env is None else env
    if env.get("CP_BIN_DIR"):
        return Path(env["CP_BIN_DIR"])
    return program_root(env) / "bin" if is_windows() else Path.home() / ".local" / "bin"


def launcher_path(env=None):
    return bin_dir(env) / ("cplane.cmd" if is_windows() else "cplane")


def _package_manager_hint(package):
    """Comando para instalar algo neste sistema. Só mostrado: nunca executado por aqui."""
    system = system_name()
    if system == "windows":
        return f"winget install {package}"
    if system == "macos":
        return f"brew install {package}"
    for tool, line in (("apt-get", f"sudo apt-get install -y {package}"), ("dnf", f"sudo dnf install -y {package}"), ("apk", f"sudo apk add {package}"),
                       ("pacman", f"sudo pacman -S {package}"), ("zypper", f"sudo zypper install {package}"), ("pkg", f"sudo pkg install {package}")):
        if shutil.which(tool):
            return line
    return f"Instale {package} pelo gerenciador de pacotes do sistema."


def _writable(path):
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return os.access(probe, os.W_OK)


def _port_free(port=PORT):
    with socket.socket() as sock:
        if not is_windows():  # no Windows, esta opção deixaria passar uma porta ocupada
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _on_path(folder):
    wanted = os.path.normcase(str(folder))
    return any(os.path.normcase(p.rstrip("/\\")) == wanted.rstrip("/\\") for p in os.environ.get("PATH", "").split(os.pathsep))


def checks(env=None):
    """Lista de (nome, estado, texto, como resolver). 'fail' impede de instalar ou abrir; 'warn' e 'off' só informam."""
    rows = []
    good = sys.version_info[:2] >= MIN_PYTHON
    rows.append(("Python", "ok" if good else "fail", f"{platform.python_version()} ({sys.executable})",
                 "" if good else _package_manager_hint("Python.Python.3.12" if is_windows() else "python3")))
    root = program_root(env)
    can_write = _writable(root) and _writable(bin_dir(env))
    rows.append(("Pasta do programa", "ok" if can_write else "fail", str(root), "" if can_write else "Sem permissão de escrita. Não use sudo: confira o dono da pasta."))
    rows.append(("Porta 4700", "ok" if _port_free() else "warn", "Livre" if _port_free() else "Em uso", "" if _port_free() else "O painel pode abrir em outra porta: cplane --port 4701"))
    git_fix = _package_manager_hint("Git.Git" if is_windows() else "git")
    rows.append(("git", "ok" if shutil.which("git") else "off", "Instalado" if shutil.which("git") else "Só é preciso para importar uma conta de um repositório", "" if shutil.which("git") else git_fix))
    docker_fix = "Instale o Docker Desktop: https://docs.docker.com/desktop/" if system_name() in ("windows", "macos", "wsl") else "https://docs.docker.com/engine/install/"
    rows.append(("Docker", "ok" if shutil.which("docker") else "off", "Instalado" if shutil.which("docker") else "Só é preciso para o cofre e os logs nesta máquina", "" if shutil.which("docker") else docker_fix))
    rows.append(("Tailscale", "ok" if shutil.which("tailscale") else "off", "Instalado" if shutil.which("tailscale") else "Só é preciso para o acesso remoto", "" if shutil.which("tailscale") else "https://tailscale.com/download"))
    return rows


def print_checks(rows):
    label = {"ok": "ok", "warn": "atenção", "off": "opcional", "fail": "falta"}
    for name, state, text, fix in rows:
        print(f"  [{label[state]}] {name}: {text}")
        if fix:
            print(f"      Como resolver: {fix}")


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for block in iter(lambda: source.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_package(package):
    """Detecta pacote corrompido ou trocado no caminho. A assinatura do release é evolução: docs/proximos-passos.md."""
    sums = package.parent / "SHA256SUMS"
    if not sums.exists():
        sys.exit(f"Falta o arquivo SHA256SUMS ao lado de {package.name}. Baixe todos os arquivos do release.")
    expected = {}
    for line in sums.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 2:
            expected[parts[1].lstrip("*")] = parts[0]
    if package.name not in expected:
        sys.exit(f"{package.name} não está no SHA256SUMS.")
    if sha256(package) != expected[package.name]:
        sys.exit(f"A soma de verificação de {package.name} não confere. Nada foi instalado. Baixe de novo.")


def extract_package(package, target):
    """Só arquivos comuns da lista de inclusão. Caminho absoluto, .. e link são recusados, em qualquer versão do Python."""
    with tarfile.open(package, "r:gz") as tar:
        members = tar.getmembers()
        tops = {m.name.split("/", 1)[0] for m in members}
        if len(tops) != 1:
            sys.exit("Pacote inválido: precisa ter uma única pasta.")
        for member in members:
            if member.isdir():
                continue
            parts = member.name.split("/")
            relative = "/".join(parts[1:])
            if not member.isfile() or member.name.startswith(("/", "\\")) or ".." in parts or "\\" in member.name or not included(relative):
                sys.exit(f"Pacote inválido: {member.name} não é permitido.")
            dest = target / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(member) as source, open(dest, "wb") as out:
                shutil.copyfileobj(source, out)


def copy_from_dir(source, target):
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source).as_posix()
        if path.is_file() and not path.is_symlink() and included(relative):
            dest = target / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, dest)


def _write_launcher(root, python, env=None):
    path = launcher_path(env)
    path.parent.mkdir(parents=True, exist_ok=True)
    if is_windows():
        path.write_text(
            "@echo off\r\nsetlocal\r\nset PYTHONUTF8=1\r\n"
            f'set /p CP_V=<"{root}\\current"\r\n'
            f'"{python}" -B "{root}\\versions\\%CP_V%\\scripts\\cplane.py" %*\r\n',
            encoding="utf-8",
        )
        return path
    quoted_root, quoted_python = _sh_quote(str(root)), _sh_quote(str(python))
    path.write_text(
        "#!/bin/sh\nexport PYTHONUTF8=1\n"
        f"root={quoted_root}\n"
        f'v=$(cat "$root/current") || exit 1\n'
        f'exec {quoted_python} -B "$root/versions/$v/scripts/cplane.py" "$@"\n',
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _sh_quote(text):
    return "'" + text.replace("'", "'\"'\"'") + "'"


def _windows_path(add, folder):
    """PATH do usuário, sem administrador. Fica no registro: só terminais novos enxergam a mudança."""
    import ctypes
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
        try:
            current, kind = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            current, kind = "", winreg.REG_EXPAND_SZ
        rest = [p for p in current.split(";") if p and os.path.normcase(p.rstrip("\\")) != os.path.normcase(str(folder).rstrip("\\"))]
        new = ";".join([*rest, str(folder)] if add else rest)
        if new != current:
            winreg.SetValueEx(key, "Path", 0, kind, new)
            ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "Environment", 2, 2000, None)


def _set_pointer(root, version):
    current = root / "current"
    old = current.read_text(encoding="utf-8").strip() if current.exists() else ""
    if old and old != version:
        (root / "previous").write_text(old, encoding="utf-8")
    temp = root / ".current.tmp"
    temp.write_text(version, encoding="utf-8")
    os.replace(temp, current)


def _prune(root, keep):
    for folder in (root / "versions").iterdir():
        if folder.name not in keep:
            shutil.rmtree(folder, ignore_errors=True)


def _read_version(folder):
    version = (folder / "VERSION").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z.+_-]{0,40}", version):
        sys.exit("Pacote inválido: versão ilegível.")
    return version


def install(package=None, from_dir=None, env=None):
    rows = checks(env)
    failed = [r for r in rows if r[1] == "fail"]
    if failed:
        print("Não dá para instalar ainda:")
        print_checks(failed)
        sys.exit(1)
    if package:
        verify_package(package)
    root = program_root(env)
    (root / "versions").mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root, prefix=".novo-") as temp:
        fresh = Path(temp) / "pacote"
        fresh.mkdir()
        if package:
            extract_package(package, fresh)
        else:
            copy_from_dir(from_dir, fresh)
        if not (fresh / "scripts" / "cplane.py").exists():
            sys.exit("Pacote inválido: falta o comando cplane.")
        version = _read_version(fresh)
        target = root / "versions" / version
        if target.exists():
            try:
                shutil.rmtree(target)
            except OSError:
                sys.exit("Não foi possível substituir esta versão. Feche o painel e rode de novo.")
        os.replace(fresh, target)
    _set_pointer(root, version)
    launcher = _write_launcher(root, sys.executable, env)
    previous = (root / "previous").read_text(encoding="utf-8").strip() if (root / "previous").exists() else ""
    _prune(root, {version, previous})
    return version, launcher


def finish_message(version, launcher, env=None):
    print(f"\nControl plane {version} instalado.")
    print(f"  Programa: {program_root(env)}")
    folder = launcher.parent
    if is_windows():
        if not (env or os.environ).get("CP_BIN_DIR"):  # pasta escolhida à mão: o PATH do usuário fica como está
            _windows_path(True, folder)
        print("\nFeche este terminal, abra outro e rode:\n  cplane")
        print(f"\nPara abrir agora, sem trocar de terminal:\n  & \"{launcher}\"")
    elif _on_path(folder):
        print("\nPara abrir:\n  cplane")
    else:
        print(f"\nPara abrir agora:\n  {launcher}")
        print(f"\nPara usar só cplane daqui em diante, acrescente esta linha ao arquivo de início do seu shell:\n  export PATH=\"{folder}:$PATH\"")


def uninstall_program(env=None):
    launcher = launcher_path(env)
    if is_windows() and not (env or os.environ).get("CP_BIN_DIR"):
        _windows_path(False, launcher.parent)
    shutil.rmtree(program_root(env), ignore_errors=True)
    if not launcher.exists():
        return
    if is_windows():
        # O cmd ainda está lendo este .cmd: apagar agora mostraria "The batch file cannot be found".
        subprocess.Popen(f'cmd /c ping -n 3 127.0.0.1 >nul & del "{launcher}"', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
    else:
        launcher.unlink()


def main():
    parser = argparse.ArgumentParser(description="Instala o control plane nesta máquina.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--package", type=Path, help="pacote control-plane-<versão>.tar.gz, com o SHA256SUMS ao lado")
    group.add_argument("--from-dir", type=Path, help="pasta de um clone do repositório")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    version, launcher = install(args.package.resolve() if args.package else None, args.from_dir.resolve() if args.from_dir else None)
    print("Conferido nesta máquina:")
    print_checks(checks())
    finish_message(version, launcher)


if __name__ == "__main__":
    main()

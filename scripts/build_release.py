#!/usr/bin/env python3
"""Gera o release em dist/<versão>/: pacote, instaladores e somas de verificação.

Falha se o pacote trouxer nome de negócio ou forma de segredo. Rodar no repositório: python3 scripts/build_release.py
Fica fora do pacote, assim como os nomes que ele procura.
"""
import gzip
import hashlib
import io
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import cp_install  # noqa: E402

BUSINESS = re.compile(r"easy[\s_-]?goal|msm|vaygo|health[\s_-]?stay|healthstay|malcon|editora|bxiebrbuvpllrvbfoznu", re.I)
SECRET = re.compile(
    r"ghp_[A-Za-z0-9]{20,}|github_pat_\w{20,}|-----BEGIN [A-Z ]*PRIVATE KEY|hvs\.[A-Za-z0-9_-]{20,}|sk_(?:live|test)_\w{10,}|APP_USR-[\w-]{10,}|"
    r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}|postgres(?:ql)?://[^\s\"'<:$]+:[^\s\"'<@$]+@"
)
BINARY = {".woff2"}


def tracked():
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return sorted(name for name in out.splitlines() if cp_install.included(name) and (ROOT / name).is_file())


def audit(names):
    """Devolve os problemas. Mostra arquivo e linha, nunca o valor encontrado."""
    problems = []
    for name in names:
        if Path(name).suffix in BINARY:
            continue
        for number, line in enumerate((ROOT / name).read_text(encoding="utf-8").splitlines(), 1):
            if BUSINESS.search(line):
                problems.append(f"{name}:{number}: nome de negócio")
            if SECRET.search(line):
                problems.append(f"{name}:{number}: forma de segredo")
    return problems


def build(names, version, out):
    data = io.BytesIO()
    top = f"control-plane-{version}"
    # Sem data, dono ou modo do autor: o mesmo código gera sempre o mesmo pacote.
    with gzip.GzipFile(filename="", fileobj=data, mode="wb", mtime=0) as packed, tarfile.open(fileobj=packed, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for name in names:
            raw = (ROOT / name).read_bytes()
            info = tarfile.TarInfo(f"{top}/{name}")
            info.size = len(raw)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(raw))
    (out / f"{top}.tar.gz").write_bytes(data.getvalue())


def main():
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    names = tracked()
    missing = [p for p in cp_install.INCLUDE if "*" not in p and p not in names]
    if missing:
        sys.exit("Faltam no pacote: " + ", ".join(missing))
    problems = audit(names)
    if problems:
        sys.exit(f"Release bloqueado, {len(problems)} problema(s):\n  " + "\n  ".join(problems))
    out = ROOT / "dist" / version
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    build(names, version, out)
    shutil.copyfile(ROOT / "install.sh", out / "install.sh")
    shutil.copyfile(ROOT / "install.ps1", out / "install.ps1")
    shutil.copyfile(ROOT / "scripts" / "cp_install.py", out / "install.py")
    lines = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}" for p in sorted(out.iterdir())]
    (out / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")
    size = (out / f"control-plane-{version}.tar.gz").stat().st_size
    print(f"dist/{version}: {len(names)} arquivos, pacote de {size / 1024:.0f} KB")


if __name__ == "__main__":
    main()

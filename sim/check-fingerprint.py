#!/usr/bin/env python3
"""Confere se o valor de uma chave no container da VPS simulada é o mesmo do cofre (só compara hashes).
Uso: python3 sim/check-fingerprint.py <cli>/<proj>/<env> CHAVE <servico-compose> [vps: dev|prd]"""
import hashlib, importlib.machinery, importlib.util, subprocess, sys
from pathlib import Path
loader = importlib.machinery.SourceFileLoader("cps", str(Path(__file__).resolve().parent.parent / "scripts" / "cp-secrets"))
spec = importlib.util.spec_from_loader("cps", loader)
cps = importlib.util.module_from_spec(spec)
loader.exec_module(cps)
path, key, svc = sys.argv[1:4]
host = f"cp-sim-sim-vps-{sys.argv[4] if len(sys.argv) > 4 else 'dev'}-1"
want = hashlib.sha256(cps.kv_read(cps.operator_token(), path)["data"][key].encode()).hexdigest()
name = subprocess.run(["docker", "exec", host, "docker", "ps", "--filter", f"name=^{svc}-", "--format", "{{.Names}}"],
                      capture_output=True, text=True, check=True).stdout.split()[0]
got = subprocess.run(["docker", "exec", host, "docker", "exec", name, "printenv", key],
                     capture_output=True, text=True, check=True).stdout.rstrip("\n")
same = hashlib.sha256(got.encode()).hexdigest() == want
print(f"{key} em {name}: {'IGUAL ao cofre' if same else 'DIFERENTE do cofre'} (sha256 {want[:8]}…)")
sys.exit(0 if same else 1)

#!/usr/bin/env python3
"""Compara o fingerprint de SYNC_PROBE servido pela Vercel com o do cofre (sem expor valores)."""
import hashlib, importlib.machinery, importlib.util, json, sys, urllib.request
from pathlib import Path
loader = importlib.machinery.SourceFileLoader("cps", str(Path(__file__).resolve().parent.parent / "scripts" / "cp-secrets"))
spec = importlib.util.spec_from_loader("cps", loader)
cps = importlib.util.module_from_spec(spec)
loader.exec_module(cps)
want = hashlib.sha256(cps.kv_read(cps.operator_token(), "easygoal/cp-probe/prod")["data"]["SYNC_PROBE"].encode()).hexdigest()[:8]
got = json.load(urllib.request.urlopen("https://cp-sync-probe.vercel.app/api/probe", timeout=20))
print(f"SYNC_PROBE na Vercel: {'IGUAL ao cofre' if got.get('sha8') == want else 'DIFERENTE do cofre'} ({got.get('sha8')} vs {want})")
sys.exit(0 if got.get("sha8") == want else 1)

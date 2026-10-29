#!/usr/bin/env python3
"""Bootstrap do Coolify simulado (etapa 4): registra a VPS do projeto e cria o service do Health Stay.
Rodar com a credencial do cofre, sem token na tela:
  scripts/cp-secrets provider exec easygoal coolify-sim -- python3 sim/bootstrap-coolify.py
Idempotente por nome. Imprime só uuids.
"""
import base64, json, os, subprocess, sys, tempfile, time, urllib.error, urllib.request
from pathlib import Path

URL, TOKEN = os.environ["CP_URL"].rstrip("/") + "/api/v1", os.environ["CP_TOKEN"]
HERE = Path(__file__).resolve().parent
VPS_IP, VPS_CONTAINER = "172.30.50.20", "cp-sim-sim-vps-hs-1"


def api(method, path, body=None):
    req = urllib.request.Request(URL + path, method=method, data=json.dumps(body).encode() if body else None,
                                 headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json",
                                          "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        sys.exit(f"{method} {path} → {e.code}: {e.read().decode()[:300]}")


def by_name(items, name):
    return next((i for i in items if i.get("name") == name), None)


# 1. Chave SSH control plane → VPS (privada só no Coolify; pública no authorized_keys da VPS)
key = by_name(api("GET", "/security/keys"), "cp-sim-vps")
if not key:
    with tempfile.TemporaryDirectory() as d:
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "coolify-cp-sim", "-f", f"{d}/k"], check=True)
        priv, pub = Path(f"{d}/k").read_text(), Path(f"{d}/k.pub").read_text().strip()
    key = api("POST", "/security/keys", {"name": "cp-sim-vps", "private_key": priv})
    subprocess.run(["docker", "exec", VPS_CONTAINER, "sh", "-c",
                    f"mkdir -p /root/.ssh && echo '{pub}' >> /root/.ssh/authorized_keys && chmod 600 /root/.ssh/authorized_keys"], check=True)
print(f"chave ssh: {key['uuid']}")

# 2. VPS do projeto como servidor remoto (sem proxy do Coolify: a porta da API é publicada direto)
srv = by_name(api("GET", "/servers"), "sim-vps-hs")
if not srv:
    srv = api("POST", "/servers", {"name": "sim-vps-hs", "description": "VPS simulada do Health Stay",
                                   "ip": VPS_IP, "port": 22, "user": "root", "private_key_uuid": key["uuid"],
                                   "proxy_type": "none", "instant_validate": True})
for _ in range(60):
    s = api("GET", f"/servers/{srv['uuid']}")
    st = s.get("settings") or {}
    if st.get("is_reachable") and st.get("is_usable"):
        break
    time.sleep(5)
else:
    sys.exit(f"servidor {srv['uuid']} não ficou reachable/usable")
print(f"servidor: {srv['uuid']} (reachable, usable)")

# 3. Projeto + ambiente staging
proj = by_name(api("GET", "/projects"), "health-stay") or api("POST", "/projects", {"name": "health-stay"})
envs = api("GET", f"/projects/{proj['uuid']}/environments")
if not by_name(envs, "staging"):
    api("POST", f"/projects/{proj['uuid']}/environments", {"name": "staging"})
print(f"projeto: {proj['uuid']} (ambiente staging)")

# 4. Service a partir do compose (sem instant_deploy: as variáveis chegam pelo sync)
svc = by_name(api("GET", "/services"), "health-stay-api-staging")
if not svc:
    raw = base64.b64encode((HERE / "health-stay-staging.compose.yml").read_bytes()).decode()
    svc = api("POST", "/services", {"name": "health-stay-api-staging", "project_uuid": proj["uuid"],
                                    "environment_name": "staging", "server_uuid": srv["uuid"],
                                    "docker_compose_raw": raw, "instant_deploy": False})
print(f"service: {svc['uuid']}  ← colocar em uuid do target api-staging-sim")

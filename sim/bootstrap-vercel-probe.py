#!/usr/bin/env python3
"""Projeto descartável na Vercel para validar o adaptador do `cp-secrets sync` (etapa 4, ADR 063).
Cria o projeto cp-sync-probe e faz o primeiro deploy de produção: uma função que devolve só o
fingerprint (sha256, 8 caracteres) de SYNC_PROBE — nunca o valor. Nenhuma app real envolvida.
  scripts/cp-secrets provider exec easygoal vercel -- python3 sim/bootstrap-vercel-probe.py
  scripts/cp-secrets provider exec easygoal vercel -- python3 sim/bootstrap-vercel-probe.py --delete
"""
import json, os, sys, time, urllib.error, urllib.parse, urllib.request

TOKEN, TEAM = os.environ["CP_TOKEN"], os.environ.get("CP_TEAM_ID", "")
NAME = "cp-sync-probe"
API = "https://api.vercel.com"
FN = """const { createHash } = require('node:crypto');
module.exports = (req, res) => {
  const v = process.env.SYNC_PROBE;
  res.setHeader('Cache-Control', 'no-store');
  res.json({ present: Boolean(v), sha8: v ? createHash('sha256').update(v).digest('hex').slice(0, 8) : null });
};
"""


def api(method, path, body=None, ok404=False, **q):
    if TEAM:
        q["teamId"] = TEAM
    url = API + path + ("?" + urllib.parse.urlencode(q) if q else "")
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        if ok404 and e.code == 404:
            return None
        sys.exit(f"{method} {path} → {e.code}: {e.read().decode()[:300]}")


if "--delete" in sys.argv:
    api("DELETE", f"/v9/projects/{NAME}", ok404=True)
    print(f"projeto {NAME} apagado")
    sys.exit()

proj = api("GET", f"/v9/projects/{NAME}", ok404=True) or api("POST", "/v11/projects", {"name": NAME, "framework": None})
print(f"projeto: {proj['id']} ({NAME})")
# Sem proteção de deploy: a função só expõe um fingerprint de um valor de teste.
api("PATCH", f"/v9/projects/{proj['id']}", {"ssoProtection": None})
dep = api("POST", "/v13/deployments", {"name": NAME, "project": proj["id"], "target": "production",
                                       "files": [{"file": "api/probe.js", "data": FN}],
                                       "projectSettings": {"framework": None}})
for _ in range(120):
    st = api("GET", f"/v13/deployments/{dep['id']}")
    if st["readyState"] in ("READY", "ERROR", "CANCELED"):
        break
    time.sleep(3)
print(f"deploy: {st['readyState']}")
print(f"health_url: https://{NAME}.vercel.app/api/probe")

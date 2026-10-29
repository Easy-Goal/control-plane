"""Adaptadores de destino do `cp-secrets sync` (ADR 063). Stdlib only.

Cada adaptador recebe os campos do provedor (kv/<cliente>/_providers/<nome>) e o bloco [[target]] do
secrets.toml, e implementa:

  list()            -> {nome: {"value": str|None, "updated_at": datetime|None}}   (value None = ilegível)
  upsert(dict)      grava as chaves (cria ou atualiza)
  redeploy()        aplica as variáveis novas (restart/deploy) e espera terminar
  revoke()          invalida a credencial de operação no provedor (offboarding), se o provedor permitir

Nunca imprimem valores.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone


class ProviderError(Exception):
    pass


def http(method, url, token, body=None, timeout=60):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        # Corpo de erro do provedor pode ecoar o payload: corta e não inclui valores enviados.
        detail = e.read().decode(errors="replace")[:200]
        raise ProviderError(f"{method} {url.split('?')[0]} → {e.code}: {detail}") from None
    except urllib.error.URLError as e:
        raise ProviderError(f"{method} {url.split('?')[0]} inacessível ({e.reason})") from None


def wait_http_ok(url, timeout=300):
    """Espera um GET 200 (health_url do target)."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                if r.status == 200:
                    return
                last = r.status
        except urllib.error.HTTPError as e:
            last = e.code
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            last = type(e).__name__
        time.sleep(3)
    raise ProviderError(f"health {url} não respondeu 200 em {timeout}s (último: {last})")


def wait_http_cycle(url, down_timeout=180, up_timeout=300):
    """Restart assíncrono (ex.: service do Coolify): espera a app sair do ar e voltar, senão um 200 do
    container antigo passaria como sucesso."""
    deadline = time.time() + down_timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                if r.status != 200:
                    break
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            break
        time.sleep(1)
    else:
        raise ProviderError(f"{url} não saiu do ar em {down_timeout}s: restart não confirmado")
    wait_http_ok(url, up_timeout)


def parse_ts(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):  # Vercel: epoch em ms
        return datetime.fromtimestamp(v / 1000, timezone.utc)
    return datetime.fromisoformat(str(v).replace("Z", "+00:00"))


class Coolify:
    """Coolify v4: service (compose) ou application. Token com abilities read, read:sensitive, write, deploy."""
    fields = {"url": False, "token": True}  # campo → é segredo?
    async_restart = False  # True para service: o restart entra numa fila e não devolve id para acompanhar

    def __init__(self, prov, target):
        self.base = prov["url"].rstrip("/") + "/api/v1"
        self.token = prov["token"]
        self.kind = target.get("resource", "service")
        if self.kind not in ("service", "application"):
            raise ProviderError(f"resource inválido: {self.kind} (service | application)")
        self.uuid = target.get("uuid") or ""
        if not self.uuid:
            raise ProviderError("target sem uuid do recurso no Coolify")
        self.coll = "services" if self.kind == "service" else "applications"
        self.async_restart = self.kind == "service"

    def list(self):
        envs = http("GET", f"{self.base}/{self.coll}/{self.uuid}/envs", self.token)
        out = {}
        for e in envs:
            if e.get("is_preview"):
                continue
            out[e["key"]] = {"value": e.get("value"), "updated_at": parse_ts(e.get("updated_at"))}
        return out

    def upsert(self, values):
        data = [{"key": k, "value": v, "is_literal": True} for k, v in values.items()]
        http("PATCH", f"{self.base}/{self.coll}/{self.uuid}/envs/bulk", self.token, {"data": data})

    def redeploy(self):
        if self.kind == "application":
            res = http("POST", f"{self.base}/deploy?uuid={self.uuid}&force=false", self.token)
            dep = (res.get("deployments") or [{}])[0].get("deployment_uuid")
            if dep:
                self._wait_deployment(dep)
        else:
            # Restart de service regenera o compose com as variáveis atuais e recria os containers.
            http("POST", f"{self.base}/services/{self.uuid}/restart", self.token)

    def _wait_deployment(self, dep, timeout=900):
        deadline = time.time() + timeout
        while time.time() < deadline:
            st = http("GET", f"{self.base}/deployments/{dep}", self.token).get("status")
            if st == "finished":
                return
            if st in ("failed", "cancelled-by-user"):
                raise ProviderError(f"deploy {dep} terminou em {st}")
            time.sleep(5)
        raise ProviderError(f"deploy {dep} não terminou em {timeout}s")

    def revoke(self):
        return "token do Coolify é da Easy Goal (não fica na conta do cliente): nada a revogar no provedor"


class Vercel:
    """Vercel: env vars de um projeto, por target (production/preview). Token com escopo do time + expiração."""
    fields = {"token": True, "team_id": False}
    API = "https://api.vercel.com"
    async_restart = False  # redeploy() já espera o READY (troca atômica)

    def __init__(self, prov, target):
        self.token = prov["token"]
        self.team = prov.get("team_id") or ""
        self.project = target.get("project") or ""
        if not self.project:
            raise ProviderError("target sem project (id ou nome do projeto na Vercel)")
        self.targets = target.get("vercel_targets", ["production"])
        self.type = target.get("vercel_type", "sensitive")  # sensitive: ilegível até no painel

    def _q(self, **params):
        if self.team:
            params["teamId"] = self.team
        return ("?" + urllib.parse.urlencode(params)) if params else ""

    def list(self):
        res = http("GET", f"{self.API}/v10/projects/{self.project}/env{self._q()}", self.token)
        out = {}
        for e in res.get("envs", []):
            if not set(self.targets) & set(e.get("target") or []):
                continue
            # Valores encrypted/sensitive não voltam em claro: a divergência é detectada por updatedAt.
            out[e["key"]] = {"value": None, "updated_at": parse_ts(e.get("updatedAt"))}
        return out

    def upsert(self, values):
        body = [{"key": k, "value": v, "type": self.type, "target": self.targets} for k, v in values.items()]
        res = http("POST", f"{self.API}/v10/projects/{self.project}/env{self._q(upsert='true')}", self.token, body)
        failed = res.get("failed") or []
        if failed:
            keys = [f.get("error", {}).get("envVarKey", "?") for f in failed]
            raise ProviderError(f"Vercel recusou: {', '.join(keys)}")

    def redeploy(self, timeout=600):
        if "production" not in self.targets:
            return
        res = http("GET", f"{self.API}/v6/deployments{self._q(projectId=self.project, target='production', limit=1)}", self.token)
        deps = res.get("deployments") or []
        if not deps:
            raise ProviderError("projeto sem deploy de produção para refazer (faça o primeiro deploy)")
        last = deps[0]
        body = {"name": last["name"], "deploymentId": last["uid"], "target": "production"}
        new = http("POST", f"{self.API}/v13/deployments{self._q()}", self.token, body)
        dep = new["id"]
        deadline = time.time() + timeout
        while time.time() < deadline:
            st = http("GET", f"{self.API}/v13/deployments/{dep}{self._q()}", self.token).get("readyState")
            if st == "READY":
                return
            if st in ("ERROR", "CANCELED"):
                raise ProviderError(f"redeploy {dep} terminou em {st}")
            time.sleep(5)
        raise ProviderError(f"redeploy {dep} não ficou READY em {timeout}s")

    def revoke(self):
        # "current" invalida o próprio token usado na requisição.
        http("DELETE", f"{self.API}/v3/user/tokens/current", self.token)
        return "token da Vercel invalidado"


KINDS = {"coolify": Coolify, "vercel": Vercel}

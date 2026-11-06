"""Adaptadores de destino do `cp-secrets sync` (ADR 063).

Cada adaptador recebe os campos do provedor (kv/<cliente>/_providers/<nome>) e o bloco [[target]] do
secrets.toml, e implementa:

  list()            -> {nome: {"value": str|None, "updated_at": datetime|None}}   (value None = ilegível)
  upsert(dict)      grava as chaves (cria ou atualiza)
  redeploy()        aplica as variáveis novas (restart/deploy) e espera terminar (redeploys=False: não há)
  revoke()          invalida a credencial de operação no provedor (offboarding), se o provedor permitir
  close()           (opcional) descarta credenciais temporárias do adaptador

Stdlib only, exceto o GitHub (PyNaCl + PyJWT: requirements.txt, carregados só quando usados).

Nunca imprimem valores.
"""
import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone


class ProviderError(Exception):
    pass


def http(method, url, token, body=None, timeout=60, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
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
    redeploys = True

    def __init__(self, prov, target):
        self.base = prov["url"].rstrip("/") + "/api/v1"
        self.token = prov["token"]
        self.kind = target.get("resource", "service")
        if self.kind not in ("service", "application"):
            raise ProviderError(f"resource inválido: {self.kind} (service | application)")
        self.coll = "services" if self.kind == "service" else "applications"
        self.async_restart = self.kind == "service"
        # resource_name (preferido) sobrevive a reinstalação; uuid fixo só para recurso criado à mão.
        self.uuid = target.get("uuid") or ""
        self.resource_name = target.get("resource_name") or ""
        if not (self.uuid or self.resource_name) and target.get("project") != "-":
            raise ProviderError("target sem resource_name (ou uuid) do recurso no Coolify")

    def _resolve(self):
        if not self.uuid:
            found = [r for r in http("GET", f"{self.base}/{self.coll}", self.token) if r.get("name") == self.resource_name]
            if len(found) != 1:
                raise ProviderError(f"{self.kind} '{self.resource_name}': {len(found)} no Coolify (esperado 1)")
            self.uuid = found[0]["uuid"]
        return self.uuid

    @property
    def resource_id(self):
        return self._resolve()

    def list(self):
        envs = http("GET", f"{self.base}/{self.coll}/{self._resolve()}/envs", self.token)
        out = {}
        for e in envs:
            if e.get("is_preview"):
                continue
            out[e["key"]] = {"value": e.get("value"), "updated_at": parse_ts(e.get("updated_at"))}
        return out

    def upsert(self, values):
        data = [{"key": k, "value": v, "is_literal": True} for k, v in values.items()]
        http("PATCH", f"{self.base}/{self.coll}/{self._resolve()}/envs/bulk", self.token, {"data": data})

    def redeploy(self):
        if self.kind == "application":
            res = http("POST", f"{self.base}/deploy?uuid={self._resolve()}&force=false", self.token)
            dep = (res.get("deployments") or [{}])[0].get("deployment_uuid")
            if dep:
                self._wait_deployment(dep)
        else:
            # Restart de service regenera o compose com as variáveis atuais e recria os containers.
            http("POST", f"{self.base}/services/{self._resolve()}/restart", self.token)

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
        return "o token do Coolify continua valendo até remover o usuário de serviço e o time do cliente no Coolify (passo manual)"


class Vercel:
    """Vercel: env vars de um projeto, por target (production/preview). Token com escopo do time + expiração."""
    fields = {"token": True, "team_id": False}
    API = "https://api.vercel.com"
    async_restart = False  # redeploy() já espera o READY (troca atômica)
    redeploys = True

    def __init__(self, prov, target):
        self.token = prov["token"]
        self.team = prov.get("team_id") or ""
        self.project = target.get("project") or ""
        if not self.project:
            raise ProviderError("target sem project (id ou nome do projeto na Vercel)")
        self.targets = target.get("vercel_targets", ["production"])
        self.resource_id = self.project
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


class GitHub:
    """Secrets do GitHub Actions (repo ou environment) via GitHub App da Easy Goal instalada na org/conta.
    Cada sync gera um token de instalação de 1h restrito ao repo do target e só às permissões necessárias.
    Não há redeploy: o valor novo vale na próxima execução do workflow."""
    fields = {"app_id": False, "installation_id": False, "private_key": True}
    API = "https://api.github.com"
    HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    async_restart = False
    redeploys = False

    def __init__(self, prov, target):
        self.app_id = str(prov.get("app_id") or "")
        self.installation = str(prov.get("installation_id") or "")
        self.key = prov.get("private_key") or ""
        if not (self.app_id and self.installation and self.key):
            raise ProviderError("provedor github sem app_id, installation_id ou private_key")
        self.repo = target.get("repo") or ""  # "org/nome"
        self.env = target.get("github_environment") or ""
        self.resource_id = f"{self.repo}#{self.env}" if self.env else self.repo
        self._token = None

    def _jwt(self):
        try:
            import jwt
        except ImportError:
            raise ProviderError("falta PyJWT/cryptography (python3 -m venv .venv && .venv/bin/pip install -r requirements.txt)") from None
        now = int(time.time())
        return jwt.encode({"iat": now - 60, "exp": now + 540, "iss": self.app_id}, self.key, algorithm="RS256")

    def _req(self, method, path, body=None, token=None):
        return http(method, f"{self.API}{path}", token or self._installation_token(), body, headers=self.HEADERS)

    def _installation_token(self):
        if self._token:
            return self._token
        if not self.repo or "/" not in self.repo:
            raise ProviderError("target sem repo (\"org/nome\")")
        perms = {"secrets": "write"}
        if self.env:
            perms["environments"] = "write"
        res = self._req("POST", f"/app/installations/{self.installation}/access_tokens",
                        {"repositories": [self.repo.split("/", 1)[1]], "permissions": perms}, token=self._jwt())
        self._token = res["token"]
        return self._token

    def _base(self):
        base = f"/repos/{self.repo}"
        return f"{base}/environments/{urllib.parse.quote(self.env, safe='')}/secrets" if self.env else f"{base}/actions/secrets"

    def list(self):
        out, page = {}, 1
        while True:
            res = self._req("GET", f"{self._base()}?per_page=100&page={page}")
            for s in res.get("secrets", []):
                # Secrets do Actions são só-escrita: a divergência é detectada por updated_at.
                out[s["name"]] = {"value": None, "updated_at": parse_ts(s.get("updated_at"))}
            if len(out) >= res.get("total_count", 0) or not res.get("secrets"):
                return out
            page += 1

    def upsert(self, values):
        try:
            from nacl import encoding, public
        except ImportError:
            raise ProviderError("falta PyNaCl (python3 -m venv .venv && .venv/bin/pip install -r requirements.txt)") from None
        pk = self._req("GET", f"{self._base()}/public-key")
        box = public.SealedBox(public.PublicKey(pk["key"].encode(), encoding.Base64Encoder()))
        for k, v in values.items():
            enc = base64.b64encode(box.encrypt(v.encode())).decode()
            self._req("PUT", f"{self._base()}/{k}", {"encrypted_value": enc, "key_id": pk["key_id"]})

    def redeploy(self):
        pass

    def close(self):
        if self._token:
            try:
                self._req("DELETE", "/installation/token")
            except ProviderError:
                pass  # expira sozinho em 1h
            self._token = None

    def revoke(self):
        # Desinstala a App da conta do cliente: some o acesso da Easy Goal a todos os repos dele.
        self._req("DELETE", f"/app/installations/{self.installation}", token=self._jwt())
        return "GitHub App da Easy Goal desinstalada da conta"


class Railway:
    """Railway (destino temporário até a migração, ADR 063 etapa 7): variáveis de um service num environment,
    pela API GraphQL pública. Token de workspace (Authorization: Bearer), nunca token de projeto.
    Ids do target: Cmd/Ctrl+K no painel copia project, environment e service."""
    fields = {"token": True}
    API = "https://backboard.railway.com/graphql/v2"
    async_restart = False  # redeploy() espera o deploy novo ficar SUCCESS
    redeploys = True

    def __init__(self, prov, target):
        self.token = prov["token"]
        self.ids = {k: target.get(f"railway_{k}") or "" for k in ("project", "environment", "service")}
        if target.get("project") != "-" and not all(self.ids.values()):
            raise ProviderError("target sem railway_project, railway_environment e railway_service (ids)")
        self.resource_id = self.ids["service"] + "@" + self.ids["environment"]

    def _gql(self, query, variables):
        res = http("POST", self.API, self.token, {"query": query, "variables": variables})
        if res.get("errors"):
            raise ProviderError("Railway: " + "; ".join(e.get("message", "?") for e in res["errors"])[:300])
        return res["data"]

    def _ids(self):
        return {"projectId": self.ids["project"], "environmentId": self.ids["environment"], "serviceId": self.ids["service"]}

    def list(self):
        # unrendered: referências (${{Redis.REDIS_URL}}) voltam como escritas, não resolvidas.
        q = ("query v($projectId: String!, $environmentId: String!, $serviceId: String) {"
             " variables(projectId: $projectId, environmentId: $environmentId, serviceId: $serviceId, unrendered: true) }")
        return {k: {"value": v, "updated_at": None} for k, v in (self._gql(q, self._ids())["variables"] or {}).items()}

    def upsert(self, values):
        # skipDeploys: o redeploy é um só, depois de gravar tudo, e acompanhado até o fim.
        q = "mutation u($input: VariableCollectionUpsertInput!) { variableCollectionUpsert(input: $input) }"
        self._gql(q, {"input": {**self._ids(), "variables": values, "replace": False, "skipDeploys": True}})

    def _last_success(self):
        q = ("query d($input: DeploymentListInput!) { deployments(input: $input, first: 1) {"
             " edges { node { id status } } } }")
        edges = self._gql(q, {"input": {**self._ids(), "status": {"in": ["SUCCESS"]}}})["deployments"]["edges"]
        return edges[0]["node"] if edges else None

    def redeploy(self, timeout=900):
        last = self._last_success()
        if not last:
            raise ProviderError("service sem deploy bem-sucedido para refazer (faça o primeiro deploy)")
        new = self._gql("mutation r($id: String!) { deploymentRedeploy(id: $id) { id status } }",
                        {"id": last["id"]})["deploymentRedeploy"]
        q = "query s($id: String!) { deployment(id: $id) { status } }"
        deadline = time.time() + timeout
        while time.time() < deadline:
            st = self._gql(q, {"id": new["id"]})["deployment"]["status"]
            if st == "SUCCESS":
                return
            if st == "NEEDS_APPROVAL":
                raise ProviderError(f"deploy {new['id']} aguarda aprovação manual no painel da Railway")
            if st in ("FAILED", "CRASHED", "REMOVED", "REMOVING", "SKIPPED"):
                raise ProviderError(f"deploy {new['id']} terminou em {st}")
            time.sleep(5)
        raise ProviderError(f"deploy {new['id']} não ficou SUCCESS em {timeout}s")

    def revoke(self):
        return "token de workspace da Railway: revogar no painel (Workspace Settings → Tokens); a API não expõe"


class _NotATarget:
    """Credencial de operação que não é destino de sync (ferramenta do control plane, usada pelo cp-obs)."""
    redeploys = False
    async_restart = False

    def __init__(self, prov, target):
        if target.get("project") != "-":
            raise ProviderError(f"{type(self).__name__} não é destino de sync (credencial do cp-obs)")

    def list(self):
        raise ProviderError("não é destino de sync")

    upsert = redeploy = list


class OpenObserve(_NotATarget):
    """OpenObserve do control plane (ADR 066): url = API/UI na tailnet; ingest_url = gateway público (Funnel)."""
    fields = {"url": False, "ingest_url": False, "email": False, "password": True}

    def revoke(self):
        return "OpenObserve: trocar ZO_ROOT_USER_PASSWORD no .env do control plane (offboard tira a org do cliente)"


class Umami(_NotATarget):
    """Umami do control plane (ADR 066): url = painel na tailnet; ingest_url = gateway público (script + coleta)."""
    fields = {"url": False, "ingest_url": False, "username": False, "password": True}

    def revoke(self):
        return "Umami: trocar a senha do admin no painel (offboard apaga os sites do cliente)"


def discover(kind, fields):
    """Projetos que a credencial enxerga: nome, id e um detalhe curto. Só leitura; nenhum valor de variável."""
    if kind == "coolify":
        base = fields["url"].rstrip("/") + "/api/v1"
        return [{"name": s["name"], "id": s["uuid"], "detail": coll}
                for coll in ("services", "applications", "databases") for s in http("GET", f"{base}/{coll}", fields["token"])]
    if kind == "vercel":
        team = f"?teamId={urllib.parse.quote(fields['team_id'])}" if fields.get("team_id") else ""
        res = http("GET", f"{Vercel.API}/v9/projects{team}", fields["token"])
        return [{"name": p["name"], "id": p["id"], "detail": p.get("framework") or ""} for p in res.get("projects", [])]
    if kind == "railway":
        query = "query { projects { edges { node { id name environments { edges { node { id name } } } services { edges { node { id name } } } } } } } }"
        res = http("POST", Railway.API, fields["token"], {"query": query})
        if res.get("errors"):
            raise ProviderError("Railway recusou o token")
        out = []
        for edge in res["data"]["projects"]["edges"]:
            project = edge["node"]
            envs = ", ".join(f"{e['node']['name']}={e['node']['id']}" for e in project["environments"]["edges"])
            for svc in project["services"]["edges"]:
                out.append({"name": f"{project['name']}/{svc['node']['name']}", "id": svc["node"]["id"], "detail": f"projeto={project['id']} {envs}"})
        return out
    raise ProviderError(f"sem descoberta para {kind}")


def test_credential(kind, fields):
    """Pedido só de leitura, com a credencial. Devolve o que foi conferido; ProviderError se a plataforma recusar."""
    if kind == "coolify":
        return f"Coolify aceitou: {len(http('GET', fields['url'].rstrip('/') + '/api/v1/servers', fields['token']))} servidor(es)"
    if kind == "vercel":
        http("GET", "https://api.vercel.com/v2/user", fields["token"])
        return "Vercel aceitou"
    if kind == "railway":
        res = http("POST", Railway.API, fields["token"], {"query": "query { projects { edges { node { id } } } }"})
        if res.get("errors"):
            raise ProviderError("Railway recusou o token")
        return "Railway aceitou"
    if kind == "github":
        app = GitHub({**fields}, {"repo": "x/y"})
        app._req("GET", "/app", token=app._jwt())
        return "GitHub aceitou"
    raise ProviderError(f"sem teste para {kind}")


KINDS = {"coolify": Coolify, "vercel": Vercel, "github": GitHub, "railway": Railway,
         "openobserve": OpenObserve, "umami": Umami}

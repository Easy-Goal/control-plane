"""Leitura real do painel (fase 1, ADR 067): Coolify, OpenObserve e metadados do cofre.

Regras:
  - Cada mapeador monta a saída campo a campo. O que não está escrito aqui não chega ao navegador.
  - O token da sessão e as credenciais de leitura ficam só na memória deste processo.
  - Erro de leitura vira "Não lido", com causa fixa e próximo passo. Nunca volta para o exemplo nem repete corpo de resposta.
"""
import concurrent.futures as futures
import json
import os
import re
import signal
import ssl
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import cp_paths  # noqa: E402
import cp_config  # noqa: E402

ENVS = ("dev", "staging", "prod")
LIVE_SECONDS = 30
TIMEOUT = 6
LOG_LIMIT = 100
LOG_WINDOW_DAYS = 7
EXPIRY_WARN_DAYS = 15
MOVING_TAGS = {"dev", "staging", "prod", "latest", "main", "master", "stable", ""}
ACCOUNT_KINDS = {"coolify", "vercel", "railway", "github"}  # OpenObserve e Umami são ferramentas nossas, não contas do cliente
LEVELS = {"debug": "info", "info": "info", "warn": "warn", "warning": "warn", "error": "error", "fatal": "error"}
EVENT = re.compile(r"[a-z]+(?:[._][a-z]+)+")  # nome de evento (http.request). Texto livre pode trazer valores
SAFE_NAME = re.compile(r"[A-Za-z0-9_-]{1,64}")
ROUTE_WORD = re.compile(r"v\d{1,2}|[A-Za-z._~-]{0,32}")  # sem dígito: id, token de link e afins viram :id


class ReadError(Exception):
    """Falha de leitura com causa segura para mostrar."""

    def __init__(self, status):
        super().__init__(str(status))
        self.status = status


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Nenhuma credencial segue um redirecionamento."""

    def redirect_request(self, *_a, **_k):
        return None


def request_json(method, url, headers, body=None, cacert=None, timeout=TIMEOUT):
    if not url.startswith(("http://", "https://")):
        raise ReadError("url")
    handlers = [NoRedirect()]
    if url.startswith("https:"):
        handlers.append(urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=cacert)))
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Accept": "application/json", "Content-Type": "application/json", **headers})
    try:
        with urllib.request.build_opener(*handlers).open(req, timeout=timeout) as resp:
            return json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as err:
        raise ReadError(err.code) from None
    except (OSError, ValueError):
        raise ReadError("rede") from None


def cause(name, err):
    status = getattr(err, "status", None)
    if status in (401, 403):
        return f"{name} recusou a credencial de leitura."
    if status == "rede":
        return f"{name} não respondeu."
    return f"{name} respondeu com erro." if status else f"Falha ao ler {name}."


# ---------- Formatação ----------
def parse_time(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def relative(value, now=None):
    moment = parse_time(value)
    if not moment:
        return "Sem registro"
    secs = int(((now or datetime.now(timezone.utc)) - moment).total_seconds())
    if secs < 60:
        return "agora"
    if secs < 3600:
        return f"há {secs // 60} min"
    if secs < 86400:
        return f"há {secs // 3600} h"
    days = secs // 86400
    return "há 1 dia" if days == 1 else f"há {days} dias"


def resolve_image(image, release):
    """O Coolify devolve o compose sem resolver. A tag vem do registro do release; sem ele, do valor padrão do compose."""
    text = str(image or "")
    match = re.fullmatch(r"(.+):\$\{IMAGE_TAG(?::-([^}]*))?\}", text)
    if not match:
        return text
    tag = (release or {}).get("tag") or match.group(2) or ""
    return f"{match.group(1)}:{tag}" if tag else match.group(1)


def image_version(image):
    """Última parte da imagem, sem registro. Tag móvel não identifica a versão."""
    if not image:
        return "Sem imagem", False
    last = str(image).rsplit("/", 1)[-1]
    if "@sha256:" in last:
        name, digest = last.split("@sha256:", 1)
        return f"{name}@{digest[:12]}", False
    tag = last.rsplit(":", 1)[1] if ":" in last else ""
    return last or "Sem imagem", tag in MOVING_TAGS


def image_tag(image):
    last = str(image or "").rsplit("/", 1)[-1]
    return last.rsplit(":", 1)[1] if ":" in last and "@" not in last else ""


def tag_commit(tag):
    match = re.fullmatch(r".+-([0-9a-f]{7,40})", tag)
    return match.group(1) if match else ""


def split_env(name):
    for env in ENVS:
        if str(name).endswith(f"-{env}"):
            return name[: -len(env) - 1], env
    return None, None


# ---------- Mapeadores: só o que está aqui sai para o navegador ----------
def env_state(status):
    head, _, tail = str(status or "").partition(":")
    if head == "running" and tail != "unhealthy":
        return "running", "Sem health check" if tail == "unknown" else "Saudável"
    if head in ("running", "degraded", "exited", "restarting", "unhealthy"):
        return "degraded", {"restarting": "Reiniciando", "exited": "Parado"}.get(head, "Falhando")
    return "waiting", "Sem estado informado"


def service_env(svc, now=None, release=None):
    parts = [a for a in svc.get("applications") or [] if isinstance(a, dict)]
    main = next((a for a in parts if not str(a.get("status", "")).startswith("exited")), parts[0] if parts else {})
    state, health = env_state(svc.get("status"))
    image = resolve_image(main.get("image"), release)
    version, moving = image_version(image)
    tag = image_tag(image)
    return {
        "state": state, "health": health, "version": version, "moving": moving, "commit": tag_commit(tag), "tag": "" if moving else tag,
        "when": relative((release or {}).get("at") or svc.get("updated_at"), now), "whenLabel": "Último release" if release else "Última mudança no Coolify",
        "where": (svc.get("server") or {}).get("name") or "Servidor não informado",
        "hostOk": bool(svc.get("server_status")),
    }


def database_env(db, now=None):
    state, health = env_state(db.get("status"))
    version, _ = image_version(db.get("image"))
    out = {
        "state": state, "health": health, "version": version, "moving": False, "commit": "",
        "when": relative(db.get("updated_at"), now), "whenLabel": "Última mudança no Coolify",
        "where": ((db.get("destination") or {}).get("server") or {}).get("name") or "Servidor não informado",
        "hostOk": bool(db.get("server_status")),
    }
    configs = db.get("backup_configs") or []
    log = (configs[0].get("latest_log") or {}) if configs and isinstance(configs[0], dict) else {}
    status = log.get("status")
    if status:
        failed = status == "failed"
        out["backup"] = f"{'Falhou' if failed else 'Sucesso' if status == 'success' else 'Em andamento'}, {relative(log.get('updated_at'), now)}"
        out["backupFailed"] = failed
    elif configs:
        out["backup"] = "Agendado, ainda sem execução"
    else:
        out["backup"] = "Sem backup agendado"
    return out


def sync_text(meta, target):
    """Versão do cofre x versão levada ao destino. Só v e at da marca: dest e res ficam de fora."""
    if not meta:
        return "todo", "Cofre sem valores para este ambiente"
    current = meta.get("current_version")
    mark = (meta.get("custom_metadata") or {}).get(f"sync.{target}") or ""
    fields = dict(p.split("=", 1) for p in mark.split() if "=" in p)
    if "v" not in fields:
        return "todo", f"Cofre na versão {current}, nunca levada ao destino"
    if fields["v"] != str(current):
        return "todo", f"Cofre na versão {current}, destino na {fields['v']}"
    return "ok", f"Em dia, versão {current}"


def tested_text(meta, updated):
    mark = str(((meta or {}).get("custom_metadata") or {}).get("tested") or "").split()
    if len(mark) == 2:
        return f"{'Aceita' if mark[0] == 'ok' else 'Recusada'} em {mark[1][:10]}"
    return f"Ainda não testada. Gravada em {updated}" if updated else "Ainda não testada"


def account_row(client, provider, meta, serves, today=None):
    state, expires = "missing", "Ainda sem credencial no cofre"
    updated = ""
    if meta:
        updated = str(meta.get("updated_time", ""))[:10]
        raw = (meta.get("custom_metadata") or {}).get("expires")
        if raw:
            try:
                left = (date.fromisoformat(raw) - (today or date.today())).days
            except ValueError:
                state, expires = "noexp", "Validade registrada em formato inválido"
            else:
                if left < 0:
                    state, expires = "expired", f"Venceu em {raw}"
                    if str((meta.get("custom_metadata") or {}).get("tested") or "").startswith("ok "):
                        expires += ", mas a plataforma aceitou no último teste. Corrija a data ou revogue"
                else:
                    state, expires = ("soon" if left <= EXPIRY_WARN_DAYS else "ok"), f"Vence em {left} dias ({raw})"
        else:
            state, expires = "noexp", "Validade não registrada"
    return {
        "id": f"{client}-{provider['name']}", "client": client, "provider": provider["kind"], "name": provider["name"],
        "label": f"Provedor {provider['name']} no cofre", "state": state, "expires": expires,
        "tested": tested_text(meta, updated),
        "fields": [], "fieldsRead": False, "serves": serves, "source": "live",
    }


def clean_route(path):
    """Sem query e sem identificadores: rota é para agrupar, não para expor dado."""
    route = str(path or "").split("?", 1)[0].split("#", 1)[0]
    if not route:
        return ""
    parts = [p if ROUTE_WORD.fullmatch(p) else (":id" if re.fullmatch(r"[A-Za-z0-9._~-]*", p) else ":seg") for p in route.split("/")]
    return "/".join(parts)[:120]


def log_row(hit, client, env, app_of, index):
    micros = hit.get("_timestamp")
    moment = datetime.fromtimestamp(micros / 1e6, timezone.utc).astimezone() if isinstance(micros, (int, float)) else None
    today = moment and moment.date() == datetime.now().astimezone().date()
    service = str(hit.get("service_name") or "")
    body = hit.get("body")
    status = hit.get("http_status")
    ms = hit.get("duration_ms")
    return {
        "id": f"live-{client}-{env}-{micros}-{index}", "client": client, "env": env,
        "time": moment.strftime("%H:%M:%S" if today else "%d/%m %H:%M") if moment else "Sem hora",
        "app": app_of.get(service.replace("-", "_")) or (service if SAFE_NAME.fullmatch(service) else "Serviço não identificado"),
        "level": LEVELS.get(str(hit.get("severity") or "").lower(), "info"),
        "event": body if isinstance(body, str) and EVENT.fullmatch(body) else ("http.request" if hit.get("http_path") else "registro"),
        "route": clean_route(hit.get("http_path")),
        "status": status if isinstance(status, int) else "",
        "ms": ms if isinstance(ms, (int, float)) else "",
        "rid": "",
        "flag": "Sondagem marcada pelo app" if hit.get("scan") in (True, "true", "1", 1) else "",
        "source": "live",
    }


# ---------- Sessão ----------
class Session:
    """Token de leitura do cofre, só em memória."""

    def __init__(self, addr, cacert, target):
        self.addr, self.cacert, self.target = addr.rstrip("/"), cacert, target
        self._token, self.expires, self.error = None, 0.0, ""

    @property
    def state(self):
        if self.error:
            return "failed"
        return "connected" if time.time() < self.expires else "expired"

    def open(self, root):
        try:
            done = subprocess.run([sys.executable, str(root / "scripts" / "cp-secrets"), "panel-session"], capture_output=True, text=True, timeout=30, cwd=root)
        except (OSError, subprocess.SubprocessError):
            self.error = "Não foi possível rodar o cp-secrets."
            return
        if done.returncode != 0:
            detail = done.stderr or ""
            self.error = "O cofre está selado. Faça o unseal." if "selado" in detail else "O cofre recusou a sessão. Confira a credencial de operador desta máquina."
            return
        try:
            out = json.loads(done.stdout)
            self._token, self.expires = out["token"], time.time() + int(out["ttl"])
        except (ValueError, KeyError, TypeError):
            self.error = "A sessão voltou em formato inesperado."

    def vault(self, path):
        if self.state != "connected":
            raise ReadError(403)
        return request_json("GET", f"{self.addr}/v1/{path}", {"X-Vault-Token": self._token}, cacert=self.cacert)

    def meta(self, path):
        try:
            return self.vault(f"kv/metadata/{path}")["data"]
        except ReadError as err:
            if err.status == 404:
                return None
            raise

    def close(self):
        token, self._token, self.expires = self._token, None, 0.0
        if token:
            try:
                request_json("POST", f"{self.addr}/v1/auth/token/revoke-self", {"X-Vault-Token": token}, cacert=self.cacert, timeout=3)
            except ReadError:
                pass

    def describe(self, read_at=None, problems=()):
        names = {"lab": "Laboratório", "local": "Stack local"}
        name = names.get(self.target, "Cofre")
        command = "scripts/cp-lab cp-panel" if self.target == "lab" else "scripts/cp-panel --cofre"
        return {
            "state": self.state, "target": self.target, "name": name, "command": command, "error": self.error,
            "expires_at": datetime.fromtimestamp(self.expires, timezone.utc).isoformat(timespec="seconds") if self.expires else None,
            "read_at": read_at, "problems": list(problems),
        }


def open_session(root, addr, cacert):
    target = "lab" if addr.rstrip("/").endswith(":8210") else "local" if addr.rstrip("/").endswith(":8200") else "outro"
    session = Session(addr, cacert, target)
    session.open(root)
    signal.signal(signal.SIGTERM, lambda *_: (session.close(), os._exit(0)))
    return session


# ---------- Leitura ----------
def desired_targets(config):
    """(cliente, projeto, target) declarados, para casar recursos do Coolify com sync e serviço."""
    return [(c["slug"], p["slug"], t) for c in config.get("client", []) for p in c.get("project", []) for t in p.get("target", [])]


def coolify_apps(session, client, provider, config, kinds):
    """Recursos de um time. Falha vira "Não lido" nos alvos declarados, nunca exemplo."""
    targets = [(ps, t) for cs, ps, t in desired_targets(config) if cs == client and kinds.get(t["provider"]) == "coolify"]
    by_resource = {t.get("resource_name"): (ps, t) for ps, t in targets}
    cred = session.vault(f"kv/data/{client}/_providers/{provider}")["data"]["data"]
    base = cred["url"].rstrip("/") + "/api/v1"
    headers = {"Authorization": f"Bearer {cred['token']}"}
    services = request_json("GET", f"{base}/services", headers) or []
    databases = request_json("GET", f"{base}/databases", headers) or []
    servers = [{"name": s.get("name"), "usable": bool((s.get("settings") or {}).get("is_usable") or s.get("is_usable"))}
               for s in request_json("GET", f"{base}/servers", headers) or [] if not s.get("is_coolify_host")]
    apps, unmatched = {}, []

    def add(name, env_data, raw_type):
        base_name, env = split_env(name)
        if not env:
            unmatched.append(str(name))
            return
        app = apps.setdefault(base_name, {"id": base_name, "client": client, "name": base_name, "type": raw_type, "envs": {}, "source": "live", "project": ""})
        target = by_resource.get(name)
        if target:
            app["project"] = target[0]
            level, text = sync_text(session.meta(f"{client}/{target[0]}/{env}"), target[1]["name"])
            env_data["secrets"], env_data["secretsState"] = text, level
            env_data["target"] = target[1]["name"]
        else:
            env_data["secretsState"] = "na"
        app["envs"][env] = env_data

    for svc in services:
        name = str(svc.get("name"))
        record = session.meta(f"{client}/_releases/{name}") if SAFE_NAME.fullmatch(name) else None
        add(name, service_env(svc, release=(record or {}).get("custom_metadata")), "api-coolify")
    for db in databases:
        add(db.get("name"), database_env(db), "db-coolify")
    return list(apps.values()), unmatched, servers


def unread_apps(client, config, kinds, reason):
    apps = {}
    for cs, ps, target in desired_targets(config):
        if cs != client or kinds.get(target["provider"]) != "coolify":
            continue
        name, env = split_env(target.get("resource_name"))
        if env:
            app = apps.setdefault(name, {"id": name, "client": client, "name": name, "type": "api-coolify", "envs": {}, "source": "live", "project": ps})
            app["envs"][env] = {"state": "unread", "health": reason, "version": "Não lido", "moving": False, "commit": "", "when": "Sem leitura", "where": "Sem leitura", "hostOk": None, "secretsState": "todo", "next": reason}
    return list(apps.values())


def read_logs(session, client, provider):
    cred = session.vault(f"kv/data/{client}/_providers/{provider}")["data"]["data"]
    base = cred["url"].rstrip("/")
    now = int(time.time() * 1e6)
    start = now - LOG_WINDOW_DAYS * 86400 * 10**6
    found, streams = [], {}
    for org, info in (cred.get("orgs") or {}).items():
        headers = {"Authorization": f"Basic {info['auth']}"}
        listed = request_json("GET", f"{base}/api/{urllib.parse.quote(info['id'])}/streams", headers) or {}
        names = [s["name"] for s in listed.get("list", []) if s.get("stream_type") == "logs" and SAFE_NAME.fullmatch(str(s.get("name")))]
        streams[org] = names
        for name in names:
            query = {"query": {"sql": f'SELECT * FROM "{name}" ORDER BY _timestamp DESC', "start_time": start, "end_time": now, "from": 0, "size": LOG_LIMIT}}
            res = request_json("POST", f"{base}/api/{urllib.parse.quote(info['id'])}/_search?type=logs", headers, query) or {}
            found.append((org, res.get("hits") or []))
    return found, streams


def read_live(session, config):
    """Monta as linhas reais. Cada fonte falha sozinha."""
    problems, apps, accounts, logs = [], [], [], []
    servers_of = {}
    kinds = {p["name"]: p["kind"] for c in config.get("client", []) for p in c.get("provider", [])}
    clients = [c["slug"] for c in config.get("client", [])]

    jobs = {}
    with futures.ThreadPoolExecutor(max_workers=8) as pool:
        for c in config.get("client", []):
            slug = c["slug"]
            coolify = next((p["name"] for p in c.get("provider", []) if p["kind"] == "coolify" and p["name"].endswith("-read")), None)
            if coolify:
                jobs[pool.submit(coolify_apps, session, slug, coolify, config, kinds)] = ("coolify", slug, coolify)
            elif any(kinds.get(t["provider"]) == "coolify" for cs, _, t in desired_targets(config) if cs == slug):
                problems.append({"area": "Aplicações", "text": f"{slug} não tem credencial de leitura do Coolify.", "next": "Veja em Configurar, na seção Conexão com o cofre."})
            oo = next((p["name"] for p in c.get("provider", []) if p["kind"] == "openobserve" and p["name"].endswith("-read")), None)
            if oo:
                jobs[pool.submit(read_logs, session, slug, oo)] = ("logs", slug, oo)
        results = {key: (job.result() if not job.exception() else job.exception()) for job, key in jobs.items()}

    log_streams = {}
    for (kind, slug, provider), result in results.items():
        if kind == "coolify":
            if isinstance(result, Exception):
                reason = cause("O Coolify", result)
                if not isinstance(result, ReadError):
                    reason = "Credencial de leitura do Coolify ausente ou incompleta."
                elif result.status == 404:
                    reason = "A credencial de leitura do Coolify ainda não foi gravada."
                problems.append({"area": "Aplicações", "text": reason, "next": "Confira o token em Contas e se o Coolify está no ar."})
                apps += unread_apps(slug, config, kinds, reason)
            else:
                apps += result[0]
                servers_of[slug] = result[2]
                if result[1]:
                    problems.append({"area": "Aplicações", "text": f"{len(result[1])} recurso(s) do Coolify sem ambiente no nome.", "next": "Use o final -dev, -staging ou -prod no nome do recurso."})
        elif isinstance(result, Exception):
            reason = cause("O OpenObserve", result) if isinstance(result, ReadError) else "Credencial de leitura de logs ausente ou incompleta."
            problems.append({"area": "Logs", "text": reason, "next": "Rode cp-obs panel-read e abra o painel de novo."})
        else:
            hits, log_streams = result
            app_of = {}
            for cs, ps, target in desired_targets(config):
                name, _ = split_env(target.get("resource_name"))
                if name and cs in clients:
                    app_of.setdefault(ps.replace("-", "_"), name)
            for org, rows in hits:
                client, _, env = org.partition("_")
                if client in clients and env in ENVS:
                    logs += [log_row(hit, client, env, app_of, i) for i, hit in enumerate(rows)]

    apps += declared_apps(session, config, kinds, apps)
    finish_apps(apps, log_streams)

    try:
        for c in config.get("client", []):
            for p in c.get("provider", []):
                if p["kind"] not in ACCOUNT_KINDS or p["name"].endswith(("-read", "-local")):
                    continue
                serves = sorted({ps for cs, ps, t in desired_targets(config) if cs == c["slug"] and t["provider"] == p["name"]})
                accounts.append(account_row(c["slug"], p, session.meta(f"{c['slug']}/_providers/{p['name']}"), serves))
    except ReadError as err:
        reason = cause("O cofre", err)
        problems.append({"area": "Contas", "text": reason, "next": "Abra o painel de novo para criar uma sessão."})
        accounts = [{"id": f"{c['slug']}-{p['name']}", "client": c["slug"], "provider": p["kind"], "name": p["name"], "label": f"Provedor {p['name']} no cofre", "state": "unread", "expires": reason, "tested": "Sem leitura", "fields": [], "fieldsRead": False, "serves": [], "source": "live"}
                    for c in config.get("client", []) for p in c.get("provider", []) if p["kind"] in ACCOUNT_KINDS and not p["name"].endswith(("-read", "-local"))]

    logs.sort(key=lambda row: row["id"].rsplit("-", 2)[1], reverse=True)
    rollout = {}
    try:
        for c in config.get("client", []):
            rollout[c["slug"]] = rollout_rows(session, c, apps, servers_of.get(c["slug"]), log_streams, kinds)
    except ReadError:
        rollout = {}
    rows = [{"id": c["slug"], "name": c.get("name") or c["slug"], "hosting": hosting_text(c)} for c in config.get("client", [])]
    return {"apps": apps, "accounts": accounts, "logs": logs, "problems": problems, "log_read": not any(p["area"] == "Logs" for p in problems),
            "clients": clients, "client_rows": rows, "rollout": rollout}


PLATFORM_NAMES = {"coolify": "Coolify", "vercel": "Vercel", "railway": "Railway", "github": "GitHub Actions"}
TYPE_BY_KIND = {"vercel": "front-vercel", "railway": "api-railway", "github": "front-vercel"}


def hosting_text(client):
    kinds = {p["kind"] for p in client.get("provider", [])}
    return ", ".join(name for kind, name in PLATFORM_NAMES.items() if kind in kinds) or "Sem conta declarada"


def declared_apps(session, config, kinds, known):
    """Vercel e Railway ainda não têm leitura (fase 1b). O que está declarado aparece, sem inventar versão."""
    have = {a["id"] for a in known}
    apps = {}
    for cs, ps, target in desired_targets(config):
        kind = kinds.get(target["provider"])
        if kind in (None, "coolify", "github") or ps in have:
            continue
        app = apps.setdefault(ps, {"id": ps, "client": cs, "name": ps, "type": TYPE_BY_KIND[kind], "envs": {}, "source": "live", "project": ps})
        level, text = sync_text(session.meta(f"{cs}/{ps}/{target['environment']}"), target["name"]) if session.state == "connected" else ("todo", "Sem leitura")
        app["envs"][target["environment"]] = {"state": "waiting", "health": "Sem leitura da plataforma ainda", "version": "Sem leitura ainda", "moving": False, "commit": "",
                                              "when": "Sem leitura", "where": PLATFORM_NAMES[kind], "hostOk": None, "secrets": text, "secretsState": level, "target": target["name"]}
    return list(apps.values())


def rollout_rows(session, client, apps, servers, log_streams, kinds):
    """O caminho do cliente, lido agora: o que está feito, o que falta e como fazer."""
    slug = client["slug"]
    providers = client.get("provider", [])
    usable = [p for p in providers if p["kind"] in ACCOUNT_KINDS and not p["name"].endswith(("-read", "-local"))]
    rows = []

    def add(id_, title, state, **extra):
        rows.append({"id": id_, "title": title, "state": state, "source": "live", **extra})

    missing = [p for p in usable if not session.meta(f"{slug}/_providers/{p['name']}")]
    add("contas", "Contas conectadas", "todo" if missing else "ok",
        hint=f"Falta: {', '.join(p['name'] for p in missing)}. Cada conta tem o passo a passo." if missing else "",
        to=f"#/contas/{slug}-{missing[0]['name']}" if missing else "", toLabel="Abrir a conta")
    writer = next((p["name"] for p in usable if p["kind"] == "coolify"), None)
    reader = next((p["name"] for p in providers if p["kind"] == "coolify" and p["name"].endswith("-read")), None)
    if writer:
        has_reader = bool(reader and session.meta(f"{slug}/_providers/{reader}"))
        team = "" if slug == cp_paths.home_client() else f"CP_CLIENT={slug} "
        add("leitura", "Leitura do Coolify pelo painel", "ok" if has_reader else "todo",
            hint="" if has_reader else "Grave o token só de leitura. O painel não usa o token de escrita.",
            cmd="" if has_reader else f"ssh root@<cp> {team}bash -s < install/coolify-read-token.sh \\\n  | scripts/cp-secrets provider set {slug} {reader or 'coolify-read'} url=http://<cp>:8000 --stdin token --expires \"$(date -u -d '+90 days' +%F)\"")
    pending = [p["slug"] for p in client.get("project", []) if p.get("railway_pending")]
    add("projetos", "Projetos declarados", "todo" if pending or not client.get("project") else "ok",
        hint=f"Faltam os ids da Railway em {', '.join(pending)}. Use Buscar projetos e complete clients/{slug}.toml." if pending else "")
    targets = [(p["slug"], t) for p in client.get("project", []) for t in p.get("target", [])]
    if writer:
        ready = [s for s in (servers or []) if s["usable"]]
        add("vps", "VPS cadastradas no time", "ok" if ready else "todo",
            hint="" if ready else "Instale a chave na VPS do cliente e cadastre o servidor no time dele.",
            to="" if ready else "#/guias/vps-nova", toLabel="Ver o guia",
            cmd="" if ready or servers is None else f"scripts/cp-coolify --client {slug} key\n# dentro da VPS, como root\nCOOLIFY_PUBKEY=\"<chave>\" SERVER_TAG=cliente-{slug} bash /opt/cp-install/app-server.sh\n# na sua máquina\nscripts/cp-coolify --client {slug} server add <nome> <ip>")
        coolify_targets = [(ps, t) for ps, t in targets if kinds.get(t["provider"]) == "coolify"]
        names = {f"{a['id']}-{env}" for a in apps if a["client"] == slug for env, e in a["envs"].items() if e["state"] != "unread"}
        absent = [t["resource_name"] for _, t in coolify_targets if t.get("resource_name") not in names]
        if coolify_targets and servers is not None:
            add("services", "Aplicações criadas no Coolify", "todo" if absent else "ok",
                hint=f"Falta criar: {', '.join(absent)}." if absent else "",
                cmd=f"scripts/cp-coolify --client {slug} service ensure <projeto> <ambiente> <servidor> <nome> <compose.yml>" if absent else "")
    with_logs = sorted({t["environment"] for _, t in targets if "OBS_OTLP_ENDPOINT" in (t.get("keys") or [])})
    if with_logs:
        absent = [env for env in with_logs if f"{slug}_{env}" not in log_streams]
        add("logs", "Logs ligados", "todo" if absent else "ok", hint=f"Sem leitura de logs em: {', '.join(absent)}. Rode Terminar a preparação." if absent else "")
    empty = [f"{ps}/{t['environment']}" for ps, t in targets if not session.meta(f"{slug}/{ps}/{t['environment']}")]
    add("valores", "Valores no cofre", "todo" if empty else "ok", hint=f"Sem valores em: {', '.join(empty)}. Rode Terminar a preparação." if empty else "Use Conferir diferenças para ver se falta alguma chave.")
    for id_, title, group in (("dev", "Segredos levados para dev e staging", [x for x in targets if x[1]["environment"] != "prod"]),
                              ("prod", "Segredos levados para prod", [x for x in targets if x[1]["environment"] == "prod"])):
        if not group:
            add(id_, title, "na")
            continue
        late = [(ps, t) for ps, t in group if sync_text(session.meta(f"{slug}/{ps}/{t['environment']}"), t["name"])[0] != "ok"]
        extra = {}
        if late:
            extra = {"hint": f"Pendente: {', '.join(t['name'] for _, t in late)}.",
                     "real": {"action": "sync_apply", "label": f"Levar os segredos para {late[0][1]['name']}", "client": slug, "target": late[0][1]["name"],
                              "env": late[0][1]["environment"], "confirm": late[0][1]["name"] if late[0][1]["environment"] == "prod" else "", "button": f"Levar para {late[0][1]['name']}"}}
        add(id_, title, "todo" if late else "ok", **extra)
    return rows


def finish_apps(apps, log_streams):
    """Sinais do quadro, por aplicação, calculados no servidor."""
    worst = {"todo": 2, "ok": 1, "na": 0}
    for app in apps:
        envs = app["envs"].values()
        states = [e.get("secretsState", "na") for e in envs]
        known = [e.get("hostOk") for e in envs if e.get("hostOk") is not None]
        if app["type"] == "db-coolify":
            logs = "na"
        else:
            stream = app["project"].replace("-", "_")
            has = [org for org, names in log_streams.items() if org.startswith(f"{app['client']}_") and stream in names]
            logs = "ok" if has else "todo"
        unread = any(e["state"] == "unread" for e in envs)
        app["ready"] = {
            "conta": "todo" if unread else "ok",
            "segredos": max(states, key=lambda s: worst.get(s, 0)) if states else "na",
            "host": "todo" if unread or not known else ("ok" if all(known) else "err"),
            "logs": logs,
        }
        for env in envs:
            env.pop("hostOk", None)
            if env["state"] == "degraded" and not env.get("next"):
                env["next"] = "Veja os logs filtrados. Se não bastar, abra o log bruto no Coolify."


class LiveCache:
    def __init__(self, session, root):
        self.session, self.root = session, root
        self.lock = threading.Lock()
        self.value, self.at, self.read_at = None, 0.0, None

    def config(self):
        layout = cp_paths.Layout()
        return cp_config.load(layout.main_toml, layout.clients_dir)

    def invalidate(self):
        with self.lock:
            self.value = None

    def get(self):
        with self.lock:
            if self.value is None or time.monotonic() - self.at > LIVE_SECONDS:
                self.value = read_live(self.session, self.config())
                self.at = time.monotonic()
                self.read_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            return self.value, self.read_at


def merge(data, live, session_info):
    """Linha real substitui o exemplo de mesmo cliente e tipo. O resto continua hachurado."""
    clients = set(live["clients"])
    known = {c["id"] for c in data["clients"]}
    data["clients"] += [row for row in live.get("client_rows", []) if row["id"] not in known]
    data["rollout"].update(live.get("rollout", {}))
    if live.get("rollout"):
        data["sources"]["rollout"] = "mixed"
    real_apps = {a["id"] for a in live["apps"]}
    has_coolify_read = any(a["client"] in clients for a in live["apps"])
    data["apps"] = live["apps"] + [
        a for a in data["apps"]
        if a["id"] not in real_apps and not (has_coolify_read and a["client"] in clients and a["type"].endswith("coolify"))
    ]
    data["accounts"] = live["accounts"] + [a for a in data["accounts"] if a["client"] not in clients]
    if live["log_read"]:
        data["logs"] = live["logs"] + [row for row in data["logs"] if row["client"] not in clients]
    data["connection"] = session_info
    data["sources"].update({"apps": "mixed", "accounts": "mixed", "logs": "mixed" if live["log_read"] else "demo"})
    return data



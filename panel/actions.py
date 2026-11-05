"""Ações do painel (fase 2, ADR 067): a mesma lógica dos scripts, em segundo plano, com histórico.

Regras:
  - Desligadas por padrão. Ligam só com --acoes, com sessão aberta e no cofre do laboratório.
  - Lista fechada de ações. O alvo vem do inventário real; nada do pedido vira argumento sem passar por ele.
  - Sem shell e sem stdin: o que pediria um segredo falha em vez de esperar.
  - Em prod, o servidor exige o nome digitado.
  - A saída passa por limpeza antes de ir para a Atividade, para o navegador e para o disco.
"""
import json
import os
import re
import secrets
import subprocess
import threading
import time
from datetime import datetime, timezone

MAX_RUNNING = 2
MAX_LINES = 40
MAX_LINE = 240
JOB_TIMEOUT = 900
KEEP_HISTORY = 200
SAFE_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
ENVS = ("dev", "staging", "prod")
ACCOUNT_KINDS = {"coolify", "vercel", "railway", "github"}

# Formatos de credencial e o corpo de erro das plataformas, que pode ecoar o que foi enviado.
SECRET_SHAPES = re.compile(
    r"ghp_[A-Za-z0-9]{20,}|github_pat_\w+|-----BEGIN[^\n]*|hvs\.[A-Za-z0-9_-]{20,}|s\.[A-Za-z0-9]{24,}|sk_(?:live|test)_\w+|"
    r"APP_USR-[\w-]+|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_.-]*|\d+\|[A-Za-z0-9]{20,}|postgres(?:ql)?://\S+|Bearer\s+\S+|[A-Za-z0-9+/_-]{40,}={0,2}"
)
ERROR_BODY = re.compile(r"(→ \d{3}):.*")
ANSI = re.compile(r"\x1b\[[0-9;]*m")
BACKUP_FILE = re.compile(r"\S*/?(pg-dump-[\w-]+\.dmp)")  # o nome do arquivo ajuda e não é segredo


class Refused(Exception):
    """Pedido recusado, com mensagem segura para mostrar."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def scrub(line):
    line = ANSI.sub("", line).rstrip()
    backup = BACKUP_FILE.fullmatch(line)
    if backup:
        return f"[ok] backup gravado: {backup.group(1)}"[:MAX_LINE]
    line = ERROR_BODY.sub(r"\1", line)
    line = SECRET_SHAPES.sub("[oculto]", line)
    return line[:MAX_LINE]


def safe_id(value, what):
    if not isinstance(value, str) or not SAFE_ID.fullmatch(value):
        raise Refused(f"{what} inválido.")
    return value


def find_client(config, slug):
    safe_id(slug, "Cliente")
    client = next((c for c in config.get("client", []) if c["slug"] == slug), None)
    if not client:
        raise Refused("Cliente não declarado em openbao/secrets.toml.")
    return client


def coolify_provider(client):
    """A escrita usa o provedor do sync; o painel só conhece o nome, e quem abre a credencial é o script."""
    reader = next((p["name"] for p in client.get("provider", []) if p["kind"] == "coolify" and p["name"].endswith("-read")), None)
    writer = reader and reader[: -len("-read")]
    if not writer or not any(p["name"] == writer for p in client.get("provider", [])):
        raise Refused("Este cliente não tem provedor do Coolify declarado.")
    return writer


def find_app(apps, client, name, env):
    safe_id(name, "Aplicação")
    if env not in ENVS:
        raise Refused("Ambiente inválido.")
    app = next((a for a in apps if a.get("client") == client and a.get("id") == name and a.get("source") == "live"), None)
    if not app or env not in app.get("envs", {}):
        raise Refused("Essa aplicação não existe neste ambiente, na última leitura.")
    return app


def coolify_plan(req, config, apps, verb):
    client = find_client(config, req.get("client"))
    app = find_app(apps, client["slug"], req.get("app"), req.get("env"))
    resource = f"{app['id']}-{req['env']}"
    is_db = app["type"] == "db-coolify"
    base = ["cp-coolify", "--client", client["slug"], "--provider", coolify_provider(client)]
    if verb == "restart":
        return {"label": f"Reiniciar {app['name']} em {req['env']}", "argv": [*base, "db" if is_db else "service", "restart", resource],
                "env": req["env"], "confirm": app["name"], "lock": resource}
    if verb == "deploy":
        if is_db:
            raise Refused("Banco não tem deploy.")
        return {"label": f"Fazer deploy de {app['name']} em {req['env']}", "argv": [*base, "service", "restart", resource, "--latest"],
                "env": req["env"], "confirm": app["name"], "lock": resource}
    if not is_db:
        raise Refused("Backup é só para banco.")
    return {"label": f"Fazer backup de {app['name']} em {req['env']}", "argv": [*base, "backup", "now", resource],
            "env": req["env"], "confirm": None, "lock": f"backup-{resource}"}


def sync_plan_plan(req, config, _apps):
    client = find_client(config, req.get("client"))
    return {"label": f"Conferir diferenças de {client['slug']}", "argv": ["cp-secrets", "sync", "plan", client["slug"], "--json"],
            "env": None, "confirm": None, "lock": f"plan-{client['slug']}", "report": client["slug"]}


def sync_apply_plan(req, config, _apps):
    client = find_client(config, req.get("client"))
    wanted = safe_id(req.get("target"), "Destino")
    for project in client.get("project", []):
        for target in project.get("target", []):
            if target["name"] == wanted:
                path = f"{client['slug']}/{project['slug']}/{wanted}"
                return {"label": f"Levar os segredos para {project['slug']}/{wanted}", "argv": ["cp-secrets", "sync", "apply", path],
                        "env": target["environment"], "confirm": wanted, "lock": f"sync-{wanted}"}
    raise Refused("Destino não declarado em openbao/secrets.toml.")


def test_account_plan(req, config, _apps):
    client = find_client(config, req.get("client"))
    name = safe_id(req.get("provider"), "Conta")
    provider = next((p for p in client.get("provider", []) if p["name"] == name and p["kind"] in ACCOUNT_KINDS), None)
    if not provider or name.endswith(("-read", "-local")):
        raise Refused("Conta não declarada em openbao/secrets.toml.")
    return {"label": f"Testar a conta {name} de {client['slug']}", "argv": ["cp-secrets", "provider", "test", client["slug"], name],
            "env": None, "confirm": None, "lock": f"test-{client['slug']}-{name}"}


PLANS = {
    "restart": lambda req, config, apps: coolify_plan(req, config, apps, "restart"),
    "deploy": lambda req, config, apps: coolify_plan(req, config, apps, "deploy"),
    "backup": lambda req, config, apps: coolify_plan(req, config, apps, "backup"),
    "sync_plan": sync_plan_plan,
    "sync_apply": sync_apply_plan,
    "test_account": test_account_plan,
}


def build_plan(req, config, apps):
    if not isinstance(req, dict) or req.get("action") not in PLANS:
        raise Refused("Ação desconhecida.")
    plan = PLANS[req["action"]](req, config, apps)
    if plan["env"] == "prod" and plan["confirm"] and req.get("confirm") != plan["confirm"]:
        raise Refused(f"Em prod, digite {plan['confirm']} para confirmar.")
    return plan


def drift_rows(client, report):
    """Só nomes de chave. Divergência é alguém ter mudado direto no destino; pendência comum aparece em cada ambiente."""
    return [
        {"id": f"live-{client}-{t['target']}", "client": client, "target": f"{t['target']}, {t['environment']}", "targetId": t["target"],
         "env": t["environment"], "keys": [k for k in t.get("drift", []) if isinstance(k, str)], "source": "live"}
        for t in report.get("targets", []) if t.get("drift")
    ]


class Runner:
    def __init__(self, root, state_dir, session, on_finish=None, spawn=None):
        self.root, self.session, self.on_finish = root, session, on_finish
        self.state_file = state_dir / "activity.jsonl"
        self.state_dir = state_dir
        self.key = secrets.token_urlsafe(32)
        self.lock = threading.Lock()
        self.running = {}
        self.history = self._load()
        self.plans = {}
        self.spawn = spawn or self._spawn

    def _load(self):
        try:
            lines = self.state_file.read_text(encoding="utf-8").splitlines()[-KEEP_HISTORY:]
        except OSError:
            return []
        rows = []
        for line in lines:
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
        return rows

    def _save(self, job):
        self.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(self.state_file, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as out:
            out.write(json.dumps(job, ensure_ascii=False) + "\n")

    @property
    def enabled(self):
        return self.session.state == "connected" and self.session.target == "lab"

    def describe(self):
        return {"enabled": self.enabled, "running": len(self.running)}

    def submit(self, req, config, apps):
        if not self.enabled:
            raise Refused("As ações estão desligadas: a sessão venceu. Abra o painel de novo.", 403)
        plan = build_plan(req, config, apps)
        with self.lock:
            if len(self.running) >= MAX_RUNNING:
                raise Refused("Já há ações em andamento. Espere uma terminar.", 409)
            if any(job["lock"] == plan["lock"] for job in self.running.values()):
                raise Refused("Essa ação já está em andamento para este alvo.", 409)
            job = {
                "id": f"live-{int(time.time() * 1000)}-{secrets.token_hex(3)}", "action": plan["label"], "who": "Operador",
                "where": "Laboratório", "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "result": "running",
                "steps": [], "lock": plan["lock"], "source": "live",
            }
            self.running[job["id"]] = job
        threading.Thread(target=self._run, args=(job, plan), daemon=True).start()
        return public(job)

    def _spawn(self, argv):
        tool = self.root / "scripts" / argv[0]
        return subprocess.Popen([str(tool), *argv[1:]], cwd=self.root, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})

    def _run(self, job, plan):
        report = {}
        try:
            proc = self.spawn(plan["argv"])
            timer = threading.Timer(JOB_TIMEOUT, proc.kill)
            timer.start()
            stderr_lines = []
            reader = threading.Thread(target=lambda: self._follow(proc.stderr, job, stderr_lines), daemon=True)
            reader.start()
            out = []
            self._follow(proc.stdout, job, out, keep_raw=bool(plan.get("report")))
            proc.wait()
            reader.join(timeout=5)
            timer.cancel()
            for stream in (proc.stdout, proc.stderr):
                if hasattr(stream, "close"):
                    stream.close()
            if plan.get("report") and out:
                try:
                    report = json.loads(out[-1])
                except ValueError:
                    report = {}
            job["result"] = "ok" if proc.returncode == 0 else "err"
            if proc.returncode != 0:
                job["steps"].append("A ação terminou com erro. Veja o detalhe no terminal ou na ferramenta.")
        except OSError:
            job["result"] = "err"
            job["steps"].append("Não foi possível rodar o script.")
        job["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.lock:
            self.running.pop(job["id"], None)
            self.history.append(job)
            self.history = self.history[-KEEP_HISTORY:]
            if report:
                self.plans[plan["report"]] = drift_rows(plan["report"], report)
        try:
            self._save(public(job))
        except OSError:
            job["steps"].append("A Atividade não foi gravada em disco.")
        if self.on_finish:
            self.on_finish()

    @staticmethod
    def _follow(stream, job, sink, keep_raw=False):
        for raw in stream:
            if keep_raw:
                sink.append(raw)
                continue
            line = scrub(raw)
            if line:
                job["steps"] = (job["steps"] + [line])[-MAX_LINES:]

    def rows(self):
        with self.lock:
            live = list(self.running.values()) + list(reversed(self.history))
        return [public(job) for job in live]

    def apply_to(self, data):
        with self.lock:
            plans = dict(self.plans)
        data["activity"] = self.rows() + data["activity"]
        for client, rows in plans.items():
            data["diverge"] = rows + [d for d in data["diverge"] if d["client"] != client]
        data.setdefault("connection", {})["actions"] = self.describe()
        data["connection"]["plans"] = sorted(plans)
        data["sources"]["activity"] = "mixed"
        if plans:
            data["sources"]["diverge"] = "mixed"
        return data


def public(job):
    return {k: job[k] for k in ("id", "action", "who", "where", "at", "finished_at", "result", "steps", "source") if k in job}

"""Painel do control plane: servidor local, só leitura e sem dependências (stdlib).

Funciona em qualquer device, mesmo sem cofre, Docker ou credenciais:
  - /api/device  lê o que existe nesta máquina (dado real).
  - /api/data    entrega as telas de operação: exemplos de demo.json e, conectado (scripts/cp-lab cp-panel), linhas reais.

Regras de segurança:
  - Escuta só em 127.0.0.1. Na VPS, o acesso virá pela tailnet (tailscale serve), com login próprio.
  - Só GET e HEAD para o navegador. POST existe em /api/actions (com --acoes, no laboratório) e em /api/setup (primeira
    visita, só na instalação). Os dois pedem a chave do terminal e recusam outra origem.
  - Nunca abre .env, .init.json nem .bootstrap.env: desses arquivos só verifica se existem.
  - Em /api/device, lê do cofre apenas sys/seal-status, sem token.
  - A sessão de leitura (live.py) fica só em memória, não alcança segredo de aplicação e nunca vai para o navegador.
  - Lê da configuração só nomes e estrutura. Onde ela fica: scripts/cp_paths.py.
"""
import argparse
import concurrent.futures as futures
import hmac
import json
import mimetypes
import os
import platform
import re
import secrets
import shutil
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import actions  # noqa: E402
import clients  # noqa: E402
import cp_config  # noqa: E402
import cp_paths  # noqa: E402
import live  # noqa: E402
import workspace  # noqa: E402

ROOT = cp_paths.PROGRAM
LAYOUT = cp_paths.Layout()
SETUP_KEY = secrets.token_urlsafe(24)  # vale nesta execução; o terminal mostra o link que a leva para o navegador
WEB = Path(__file__).resolve().parent / "web"
DEMO = Path(__file__).resolve().parent / "demo.json"
DEFAULT_PORT = 4700
MAX_ACTION_BODY = 2048
CACHE_SECONDS = 4
PROBE_TIMEOUT = 1.2

mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("text/javascript", ".js")

CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)

# Fonte de cada área: "demo" (demo.json) até o adaptador real entrar. Ver docs/painel.md.
DATA_SOURCES = {
    "clients": "demo", "accounts": "demo", "apps": "demo", "logs": "demo",
    "activity": "demo", "diverge": "demo", "rollout": "demo",
}


def lab_ca():
    return LAYOUT.vault_dir / "tls" / "sim-ca.crt"


def version():
    try:
        return (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "repositório"


def run(*cmd, timeout=4):
    """Roda um comando sem shell. Devolve (código, stdout); código None se não existir ou estourar o tempo."""
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=ROOT)
        return done.returncode, done.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None, ""


def http_get(url, timeout=PROBE_TIMEOUT):
    """Devolve (status, corpo curto); status None se nada responder. Não envia credencial."""
    context = None
    if url.startswith("https:"):
        # Sem a CA do lab, a conexão falha e o cofre aparece como não encontrado. A verificação nunca é desligada.
        context = ssl.create_default_context(cafile=str(lab_ca()) if lab_ca().exists() else None)
    try:
        with urllib.request.urlopen(url, timeout=timeout, context=context) as resp:
            return resp.status, resp.read(2048)
    except urllib.error.HTTPError as err:
        return err.code, b""
    except (OSError, ValueError):
        return None, b""


def check(id_, state, detail, **extra):
    return {"id": id_, "state": state, "detail": detail, **extra}


def vault(id_, url, target):
    status, body = http_get(f"{url}/v1/sys/seal-status")
    if status is None:
        return check(id_, "missing", "Nenhum cofre respondeu neste endereço.", target=target, url=f"{url}/ui/")
    try:
        seal = json.loads(body)
    except ValueError:
        return check(id_, "warn", "Algo responde na porta, mas não parece um cofre.", target=target, url=f"{url}/ui/")
    if not seal.get("initialized"):
        return check(id_, "warn", "Cofre no ar, mas ainda não inicializado.", target=target, url=f"{url}/ui/")
    if seal.get("sealed"):
        return check(id_, "warn", "Cofre no ar e selado. Precisa de unseal.", target=target, url=f"{url}/ui/", sealed=True)
    return check(id_, "ok", "Cofre no ar e aberto.", target=target, url=f"{url}/ui/", sealed=False)


def service(id_, url, target, name):
    status, _ = http_get(url)
    if status is None:
        return check(id_, "missing", f"{name} não respondeu neste endereço.", target=target, url=url)
    return check(id_, "ok", f"{name} respondeu.", target=target, url=url)


def app_probe(id_, url, name):
    status, _ = http_get(url)
    meta = {"target": "all", "url": url, "name": name, "track": "apps", "optional": True}
    if status is None:
        return check(id_, "missing", f"{name} não está rodando neste device.", **meta)
    if status >= 400:
        return check(id_, "warn", f"{name} respondeu com erro {status}.", **meta)
    return check(id_, "ok", f"{name} no ar neste device.", **meta)


def check_repo():
    if not (ROOT / ".git").exists():
        return check("repo", "ok", f"Versão {version()} instalada.")
    code, branch = run("git", "rev-parse", "--abbrev-ref", "HEAD")
    if code != 0:
        return check("repo", "warn", "Pasta sem histórico do git.")
    _, commit = run("git", "rev-parse", "--short", "HEAD")
    return check("repo", "ok", f"Branch {branch}, commit {commit}.")


def check_python():
    return check("python", "ok", f"Python {platform.python_version()}.")


def check_docker():
    if not shutil.which("docker"):
        return check("docker", "missing", "Docker não instalado neste device.")
    code, _ = run("docker", "info", "--format", "{{.ServerVersion}}")
    if code != 0:
        return check("docker", "warn", "Docker instalado, mas não respondeu. Ligue o Docker Desktop.")
    return check("docker", "ok", "Docker respondendo.")


def check_binary(id_, name, missing):
    return check(id_, "ok", f"{name} instalado.") if shutil.which(name) else check(id_, "missing", missing)


def check_operator():
    if (LAYOUT.vault_dir / ".bootstrap.env").exists():
        return check("operator", "ok", "Credencial de operador presente. O painel não abre este arquivo.")
    return check("operator", "missing", "Sem credencial de operador neste device.")


def check_init_json():
    places = [LAYOUT.vault_dir / ".init.json", ROOT.parent.parent / ".init.json"]
    if any(p.exists() for p in places):
        return check("init_json", "warn", "Há um .init.json nesta máquina. Ele guarda as chaves de unseal.")
    return check("init_json", "ok", "Nenhum .init.json nas pastas conferidas.")


def check_tailscale():
    if not shutil.which("tailscale"):
        return check("tailscale", "missing", "Tailscale não instalado neste device.")
    code, _ = run("tailscale", "status", "--json")
    if code != 0:
        return check("tailscale", "warn", "Tailscale instalado, mas desconectado.")
    return check("tailscale", "ok", "Tailscale conectado.")


def read_desired(path, clients_dir=None):
    """Estrutura de um secrets*.toml e dos arquivos por cliente: só nomes. Devolve None se não houver arquivo ou leitor."""
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
        data = cp_config.load(path, clients_dir)
    except (OSError, ValueError, KeyError, cp_config.ConfigError):
        return {"error": True, "clients": [], "todos": 0}
    clients = [
        {
            "slug": c.get("slug", "?"),
            "providers": [{"name": p.get("name", "?"), "kind": p.get("kind", "?")} for p in c.get("provider", [])],
            "projects": [{"slug": p.get("slug", "?"), "environments": p.get("environments", [])} for p in c.get("project", [])],
        }
        for c in data.get("client", [])
    ]
    return {"error": False, "clients": clients, "todos": len(re.findall(r"\bTODO\b", raw))}


def check_desired(desired):
    if not desired:
        return check("desired", "missing", "Nenhuma conta nesta máquina. Importe uma ou comece do zero.")
    if desired.get("error"):
        return check("desired", "warn", "Não foi possível ler a configuração desta conta.")
    clients = desired["clients"]
    providers = sum(len(c["providers"]) for c in clients)
    projects = sum(len(c["projects"]) for c in clients)
    return check("desired", "ok", f"{len(clients)} cliente(s), {providers} conta(s) e {projects} projeto(s) declarados.")


def docker_containers():
    if not shutil.which("docker"):
        return []
    code, out = run("docker", "ps", "-a", "--format", "{{json .}}", timeout=5)
    if code != 0:
        return []
    rows = []
    for line in out.splitlines()[:80]:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        rows.append({k.lower(): row.get(k, "") for k in ("Names", "State", "Status", "Image")})
    return rows


def read_device():
    desired = read_desired(LAYOUT.main_toml, LAYOUT.clients_dir)
    draft = read_desired(LAYOUT.draft_toml)
    jobs = [
        check_repo, check_python, check_docker, check_operator, check_init_json, check_tailscale,
        lambda: check_binary("jq", "jq", "jq não instalado. Só os scripts de terminal precisam dele."),
        lambda: vault("vault_local", "http://127.0.0.1:8200", "local"),
        lambda: service("oo_local", "http://127.0.0.1:15080/healthz", "local", "OpenObserve"),
        lambda: service("umami_local", "http://127.0.0.1:13300/api/heartbeat", "local", "Umami"),
        lambda: service("gw_local", "http://127.0.0.1:18280/", "local", "Gateway de logs"),
    ]
    if (ROOT / "sim").is_dir():  # o laboratório só existe no repositório
        jobs += [
            lambda: vault("vault_lab", "https://127.0.0.1:8210", "lab"),
            lambda: service("coolify_lab", "http://127.0.0.1:8000/api/health", "lab", "Coolify"),
            lambda: service("oo_lab", "http://127.0.0.1:5080/healthz", "lab", "OpenObserve"),
            lambda: service("umami_lab", "http://127.0.0.1:3300/api/heartbeat", "lab", "Umami"),
            lambda: service("gw_lab", "http://127.0.0.1:8280/", "lab", "Gateway de logs"),
        ]
    jobs += [(lambda p=p: app_probe(p["id"], p["url"], p["name"])) for p in workspace.probes(LAYOUT)]
    with futures.ThreadPoolExecutor(max_workers=len(jobs) + 1) as pool:
        found = list(pool.map(lambda job: job(), jobs))
        containers = pool.submit(docker_containers).result()
    found.append(check_desired(desired))
    found.append(check("vps", "missing", "Nenhuma VPS cadastrada nesta conta.", target="vps"))
    return {
        "read_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "system": platform.system(),
        "checks": found,
        "containers": containers,
        "desired": desired,
        "draft_todos": draft.get("todos", 0) if draft else None,
    }


class DeviceCache:
    def __init__(self):
        self.lock = threading.Lock()
        self.value = None
        self.at = 0.0

    def invalidate(self):
        with self.lock:  # espera uma leitura em andamento: sem isso, ela regravaria o estado anterior
            self.value = None

    def get(self):
        with self.lock:
            if self.value is None or time.monotonic() - self.at > CACHE_SECONDS:
                self.value = read_device()
                self.at = time.monotonic()
            return self.value


CACHE = DeviceCache()


SESSION = None  # sessão de leitura; só existe em scripts/cp-lab cp-panel
LIVE = None
RUNNER = None  # ações; só existe em scripts/cp-lab cp-panel --acoes


def base_data():
    """Exemplos só em quem pediu. Conta real começa do que está declarado, para exemplo nunca se misturar a ela."""
    if workspace.status(LAYOUT, version())["view"] == "real":
        try:
            config = cp_config.load(LAYOUT.main_toml, LAYOUT.clients_dir) if LAYOUT.main_toml.exists() else {}
        except (OSError, ValueError, KeyError, cp_config.ConfigError):
            config = {}
        return workspace.config_view(config)
    data = json.loads(DEMO.read_text(encoding="utf-8"))
    data["sources"] = dict(DATA_SOURCES)
    for area in ("apps", "accounts", "logs"):
        for row in data[area]:
            row["source"] = "demo"
    return data


def read_data():
    data = base_data()
    data["connection"] = {"state": "off", "problems": []}
    if SESSION is None:
        return data
    if SESSION.state != "connected":
        data["connection"] = SESSION.describe()
        data = live.merge(data, live.read_live(SESSION, LIVE.config()), SESSION.describe()) if SESSION.state == "expired" else data
    else:
        current, read_at = LIVE.get()
        data = live.merge(data, current, SESSION.describe(read_at, current["problems"]))
    return RUNNER.apply_to(data) if RUNNER else data


class Handler(BaseHTTPRequestHandler):
    server_version = "cp-panel"
    sys_version = ""

    def log_message(self, *_):  # sem log de acesso
        pass

    def send_body(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_json(self, status, payload):
        self.send_body(status, json.dumps(payload, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def host_allowed(self):
        # Barra DNS rebinding: um site externo não consegue ler este painel apontando um domínio para 127.0.0.1.
        port = self.server.server_address[1]
        return self.headers.get("Host", "") in {f"127.0.0.1:{port}", f"localhost:{port}"}

    def do_GET(self):
        if not self.host_allowed():
            return self.send_json(403, {"error": "host não permitido"})
        path = self.path.split("?", 1)[0]
        if path == "/api/setup":
            return self.send_json(200, workspace.status(LAYOUT, version()))
        if path == "/api/device":
            return self.send_json(200, {**CACHE.get(), "setup": workspace.status(LAYOUT, version())})
        if path == "/api/data":
            return self.send_json(200, read_data())
        if path == "/api/client-preview":
            return self.send_preview()
        if path == "/api/jobs" and RUNNER:
            return self.send_json(200, {"jobs": RUNNER.rows()})
        if path.startswith("/api/"):
            return self.send_json(404, {"error": "rota inexistente"})
        return self.send_static(path)

    do_HEAD = do_GET

    def send_preview(self):
        """Arquivo que o assistente gravaria. Não grava nada: é a mesma função, para a tela não mostrar outra coisa."""
        raw = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("spec", [""])[0]
        desired = read_desired(LAYOUT.main_toml, LAYOUT.clients_dir) or {"clients": []}
        try:
            spec = clients.validate(json.loads(raw), {c["slug"] for c in desired["clients"]})
            return self.send_json(200, {"toml": clients.render(spec)})
        except (ValueError, clients.SpecError) as err:
            return self.send_json(400, {"error": str(err) if isinstance(err, clients.SpecError) else "Pedido inválido."})

    def send_static(self, path):
        target = (WEB / ("index.html" if path == "/" else path.lstrip("/"))).resolve()
        if not target.is_relative_to(WEB) or not target.is_file():
            return self.send_json(404, {"error": "arquivo inexistente"})
        kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if kind.startswith("text/") or kind.endswith("javascript"):
            kind += "; charset=utf-8"
        self.send_body(200, target.read_bytes(), kind)

    def refuse(self):
        self.send_json(405, {"error": "este painel é só leitura"})

    do_PUT = do_PATCH = do_DELETE = refuse

    def action_allowed(self, key):
        """Só esta página, neste navegador: sem Host, Origin e chave certos, um site externo não dispara nada."""
        port = self.server.server_address[1]
        if not self.host_allowed():
            return 403, "host não permitido"
        origin = self.headers.get("Origin")
        if origin is not None and origin not in {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}:
            return 403, "origem não permitida"
        if self.headers.get("Sec-Fetch-Site") not in (None, "same-origin"):
            return 403, "origem não permitida"
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            return 415, "envie JSON"
        if not hmac.compare_digest(self.headers.get("X-CP-Key", ""), key):
            return 403, "chave ausente ou errada: abra o link que o terminal mostrou"
        return None

    def read_body(self):
        """Devolve o JSON do pedido, ou None depois de já ter respondido o erro."""
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            size = -1
        if not 0 < size <= MAX_ACTION_BODY:
            self.send_json(413, {"error": "pedido inválido"})
            return None
        try:
            return json.loads(self.rfile.read(size))
        except ValueError:
            self.send_json(400, {"error": "pedido inválido"})
            return None

    def do_setup(self):
        if LAYOUT.legacy:
            return self.refuse()
        denied = self.action_allowed(SETUP_KEY)
        if denied:
            return self.send_json(denied[0], {"error": denied[1]})
        req = self.read_body()
        if req is None:
            return None
        try:
            out = workspace.apply(LAYOUT, req)
            CACHE.invalidate()
        except workspace.SetupError as err:
            return self.send_json(400, {"error": str(err)})
        except (OSError, ValueError, KeyError, cp_config.ConfigError):
            return self.send_json(500, {"error": "Não foi possível gravar a configuração. Rode cplane doctor no terminal."})
        return self.send_json(200, {**out, "setup": workspace.status(LAYOUT, version())})

    def do_POST(self):
        if self.path == "/api/setup":
            return self.do_setup()
        if self.path != "/api/actions" or RUNNER is None:
            return self.refuse()
        denied = self.action_allowed(RUNNER.key)
        if denied:
            return self.send_json(denied[0], {"error": denied[1]})
        req = self.read_body()
        if req is None:
            return None
        try:
            current, _ = LIVE.get()
            job = RUNNER.submit(req, LIVE.config(), current["apps"])
        except actions.Refused as err:
            return self.send_json(err.status, {"error": str(err)})
        return self.send_json(202, {"job": job})


def make_server(port=DEFAULT_PORT):
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Painel do control plane nesta máquina (só leitura).")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"porta local (padrão {DEFAULT_PORT})")
    parser.add_argument("--acoes", action="store_true", help="liga as ações no laboratório: scripts/cp-lab cp-panel --acoes")
    parser.add_argument("--abrir", action="store_true", help="abre o navegador com o link")
    parser.add_argument("--cofre", action="store_true", help="conecta ao cofre desta máquina: sessão de leitura de 1 h")
    args = parser.parse_args(argv)
    if args.cofre:
        os.environ.setdefault("CP_BAO_ADDR", "http://127.0.0.1:8200")
    try:
        server = make_server(args.port)
    except OSError:
        sys.exit(f"A porta {args.port} já está em uso. Use outra: scripts/cp-panel --port {args.port + 1}")
    connect(args.acoes)
    print(f"Painel em http://127.0.0.1:{args.port} (Ctrl+C encerra). {'Só leitura.' if RUNNER is None else 'Com ações no laboratório.'}", flush=True)
    # A chave vai depois do #: não chega ao servidor em nenhum pedido, nem fica em log.
    key = RUNNER.key if RUNNER else None if LAYOUT.legacy else SETUP_KEY
    link = f"http://127.0.0.1:{args.port}/" + (f"#k={key}" if key else "")
    if key:
        print(f"Abra este link, válido só nesta execução: {link}", flush=True)
    if args.abrir:
        open_browser(link)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nPainel encerrado.")
    finally:
        if SESSION:
            SESSION.close()
        server.server_close()


def open_browser(link):
    """Melhor esforço: sem navegador (VPS, SSH), o link já foi mostrado no terminal."""
    if cp_paths.os_kind() == "wsl":
        try:
            subprocess.run(["powershell.exe", "-NoProfile", "-Command", "Start-Process", f"'{link}'"], capture_output=True, timeout=10)
            return
        except (OSError, subprocess.SubprocessError):
            pass
    import webbrowser
    try:
        webbrowser.open(link)
    except webbrowser.Error:
        pass


def connect(with_actions=False):
    """Sem CP_BAO_ADDR, o painel fica nos exemplos. Com ele (scripts/cp-lab), abre a sessão de leitura de 1 h."""
    global SESSION, LIVE, RUNNER
    addr = os.environ.get("CP_BAO_ADDR")
    if not addr:
        if with_actions:
            sys.exit("As ações existem só no laboratório: scripts/cp-lab cp-panel --acoes")
        return
    if with_actions and not addr.rstrip("/").endswith(":8210"):
        sys.exit("As ações existem só no laboratório até o login com MFA (ADR 067): scripts/cp-lab cp-panel --acoes")
    SESSION = live.open_session(ROOT, addr, os.environ.get("CP_BAO_CACERT"))
    LIVE = live.LiveCache(SESSION, ROOT)
    if SESSION.error:
        print(f"Sem dados reais: {SESSION.error} O painel segue nos exemplos.", flush=True)
        if with_actions:
            print("As ações ficam desligadas sem sessão.", flush=True)
    else:
        print(f"Sessão de leitura aberta em {addr}, por 1 h.", flush=True)
        if with_actions:
            RUNNER = actions.Runner(ROOT, LAYOUT.state_dir, SESSION, on_finish=LIVE.invalidate)


if __name__ == "__main__":
    main()

"""Painel do control plane: servidor local, só leitura e sem dependências (stdlib).

Funciona em qualquer device, mesmo sem cofre, Docker ou credenciais:
  - /api/device  lê o que existe nesta máquina (dado real).
  - /api/data    entrega as telas de operação; hoje com os exemplos de demo.json (dado fictício).

Regras de segurança:
  - Escuta só em 127.0.0.1. Na VPS, o acesso virá pela tailnet (tailscale serve), com login próprio.
  - Só GET e HEAD: esta etapa não executa nenhuma ação.
  - Nunca abre .env, .init.json nem .bootstrap.env: desses arquivos só verifica se existem.
  - Lê do cofre apenas sys/seal-status, rota sem autenticação. Nenhum token é enviado.
  - Lê de openbao/*.toml só nomes e estrutura, que já são versionados.
"""
import argparse
import concurrent.futures as futures
import json
import mimetypes
import platform
import re
import shutil
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    import tomllib
except ImportError:  # Python < 3.11: o painel funciona, só sem ler o estado desejado
    tomllib = None

ROOT = Path(__file__).resolve().parent.parent
WEB = Path(__file__).resolve().parent / "web"
DEMO = Path(__file__).resolve().parent / "demo.json"
LAB_CA = ROOT / "openbao" / "tls" / "sim-ca.crt"
DEFAULT_PORT = 4700
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
        context = ssl.create_default_context(cafile=str(LAB_CA) if LAB_CA.exists() else None)
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
    if status is None:
        return check(id_, "missing", f"{name} não está rodando neste device.", target="all", url=url)
    if status >= 400:
        return check(id_, "warn", f"{name} respondeu com erro {status}.", target="all", url=url)
    return check(id_, "ok", f"{name} no ar neste device.", target="all", url=url)


def check_repo():
    code, branch = run("git", "rev-parse", "--abbrev-ref", "HEAD")
    if code != 0:
        return check("repo", "warn", "Pasta sem histórico do git.")
    _, commit = run("git", "rev-parse", "--short", "HEAD")
    return check("repo", "ok", f"Branch {branch}, commit {commit}.")


def check_python():
    version = platform.python_version()
    if tomllib is None:
        return check("python", "warn", f"Python {version}. Com 3.11 ou mais novo, o painel também lê o estado desejado.")
    return check("python", "ok", f"Python {version}.")


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
    if (ROOT / "openbao" / ".bootstrap.env").exists():
        return check("operator", "ok", "Credencial de operador presente. O painel não abre este arquivo.")
    return check("operator", "missing", "Sem credencial de operador neste device.")


def check_init_json():
    places = [ROOT / "openbao" / ".init.json", ROOT.parent.parent / ".init.json"]
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


def read_desired(path):
    """Estrutura de um secrets*.toml: só nomes. Devolve None se não houver arquivo ou leitor."""
    if tomllib is None or not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
        data = tomllib.loads(raw)
    except (OSError, ValueError):
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
    if tomllib is None:
        return check("desired", "warn", "Precisa de Python 3.11 ou mais novo para ler o estado desejado.")
    if not desired or desired.get("error"):
        return check("desired", "warn", "Não foi possível ler openbao/secrets.toml.")
    clients = desired["clients"]
    providers = sum(len(c["providers"]) for c in clients)
    projects = sum(len(c["projects"]) for c in clients)
    return check("desired", "ok", f"{len(clients)} cliente(s), {providers} conta(s) e {projects} projeto(s) declarados em secrets.toml.")


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
    desired = read_desired(ROOT / "openbao" / "secrets.toml")
    draft = read_desired(ROOT / "openbao" / "secrets.draft.toml")
    jobs = [
        check_repo, check_python, check_docker, check_operator, check_init_json, check_tailscale,
        lambda: check_binary("jq", "jq", "jq não instalado. Só os scripts de terminal precisam dele."),
        lambda: vault("vault_local", "http://127.0.0.1:8200", "local"),
        lambda: vault("vault_lab", "https://127.0.0.1:8210", "lab"),
        lambda: service("coolify_lab", "http://127.0.0.1:8000/api/health", "lab", "Coolify"),
        lambda: service("oo_local", "http://127.0.0.1:15080/healthz", "local", "OpenObserve"),
        lambda: service("umami_local", "http://127.0.0.1:13300/api/heartbeat", "local", "Umami"),
        lambda: service("gw_local", "http://127.0.0.1:18280/", "local", "Gateway de logs"),
        lambda: service("oo_lab", "http://127.0.0.1:5080/healthz", "lab", "OpenObserve"),
        lambda: service("umami_lab", "http://127.0.0.1:3300/api/heartbeat", "lab", "Umami"),
        lambda: service("gw_lab", "http://127.0.0.1:8280/", "lab", "Gateway de logs"),
        lambda: app_probe("hs_api", "http://127.0.0.1:3001/health", "API do Health Stay"),
        lambda: app_probe("hs_web", "http://127.0.0.1:3000/", "Web do Health Stay"),
    ]
    with futures.ThreadPoolExecutor(max_workers=len(jobs) + 1) as pool:
        found = list(pool.map(lambda job: job(), jobs))
        containers = pool.submit(docker_containers).result()
    found.append(check_desired(desired))
    found.append(check("vps", "missing", "VPS do control plane ainda não contratada.", target="vps"))
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

    def get(self):
        with self.lock:
            if self.value is None or time.monotonic() - self.at > CACHE_SECONDS:
                self.value = read_device()
                self.at = time.monotonic()
            return self.value


CACHE = DeviceCache()


def read_data():
    data = json.loads(DEMO.read_text(encoding="utf-8"))
    data["sources"] = DATA_SOURCES
    return data


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
        if path == "/api/device":
            return self.send_json(200, CACHE.get())
        if path == "/api/data":
            return self.send_json(200, read_data())
        if path.startswith("/api/"):
            return self.send_json(404, {"error": "rota inexistente"})
        return self.send_static(path)

    do_HEAD = do_GET

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

    do_POST = do_PUT = do_PATCH = do_DELETE = refuse


def make_server(port=DEFAULT_PORT):
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Painel do control plane nesta máquina (só leitura).")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"porta local (padrão {DEFAULT_PORT})")
    args = parser.parse_args(argv)
    try:
        server = make_server(args.port)
    except OSError:
        sys.exit(f"A porta {args.port} já está em uso. Use outra: scripts/cp-panel --port {args.port + 1}")
    print(f"Painel em http://127.0.0.1:{args.port} (Ctrl+C encerra). Nesta etapa, só leitura.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nPainel encerrado.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

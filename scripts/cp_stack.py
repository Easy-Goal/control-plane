"""Sobe a stack desta máquina de uma vez: cofre, logs, analytics e gateway, parando só para pedir o que é da pessoa.

Só Python com stdlib, para valer em todo sistema. As chaves de unseal nunca passam por aqui: quem as pede, sem eco, é o
cp-secrets, direto no terminal. Nada é apagado: repetir é seguro.
"""
import hashlib
import json
import os
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import cp_install
import cp_paths

HERE = Path(__file__).resolve().parent
OO_URL = "http://127.0.0.1:15080"
UMAMI_URL = "http://127.0.0.1:13300"
GATEWAY_URL = "http://127.0.0.1:18280"
ADMIN_EMAIL = "operador@cp-local.local"
OO_PROVIDER = "openobserve-local"
UMAMI_PROVIDER = "umami-local"
LOCAL_PROVIDERS = {"CP_OBS_PROVIDER": OO_PROVIDER, "CP_UMAMI_PROVIDER": UMAMI_PROVIDER}
LAB_ADDR = "https://127.0.0.1:8210"
UNSEAL_ATTEMPTS = 3


def die(text):
    sys.exit(text)


def step(text):
    print(f"\n== {text}", flush=True)


def ok(text):
    print(f"  [ok] {text}", flush=True)


def warn(text):
    print(f"  [atenção] {text}", flush=True)


def tool(script, args, env=None):
    """Roda um script no terminal da pessoa: os prompts sem eco chegam direto a ela."""
    full = {**os.environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1", **(env or {})}
    return subprocess.call([sys.executable, str(HERE / script), *args], env=full)


def tool_output(script, args, env=None, stdin=None):
    full = {**os.environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1", **(env or {})}
    return subprocess.run([sys.executable, str(HERE / script), *args], env=full, input=stdin, capture_output=True, text=True, encoding="utf-8")


def _docker_responds():
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def ensure_docker(wait=120):
    if not shutil.which("docker"):
        fix = next(row[3] for row in cp_install.checks() if row[0] == "Docker")
        die(f"A stack roda em contêineres e falta o Docker.\n  Como resolver: {fix}")
    deadline = time.monotonic() + wait
    told = False
    while not _docker_responds():
        if time.monotonic() >= deadline:
            die("O Docker não respondeu. Confira se ele está ligado e rode cplane up de novo.")
        if not told:
            print(f"  O Docker não responde. Ligue o Docker Desktop: vou esperar até {wait // 60} minutos.", flush=True)
            told = True
        time.sleep(3)
    ok("Docker respondendo")


def vault_compose(layout):
    # O projeto do compose é fixo no arquivo: em outro projeto, o volume mudaria de nome e o cofre pareceria vazio.
    project = ["-p", os.environ["CP_VAULT_PROJECT"]] if os.environ.get("CP_VAULT_PROJECT") else []
    return subprocess.call(["docker", "compose", "--project-directory", str(layout.compose_dir), *project, "up", "-d", "--wait"])


def seal_status(addr, cafile=None, wait=60):
    """Espera o cofre responder. Devolve None se ele não responder a tempo."""
    context = ssl.create_default_context(cafile=cafile) if cafile else None
    deadline = time.monotonic() + wait
    while True:
        try:
            with urllib.request.urlopen(f"{addr}/v1/sys/seal-status", timeout=3, context=context) as res:
                return json.loads(res.read())
        except (OSError, ValueError):
            if time.monotonic() >= deadline:
                return None
            time.sleep(2)


def unlock_vault(label, addr, init_file, env=None, cafile=None):
    """Abre o cofre se precisar. Nunca inicializa sozinho: um cofre vazio aqui pode ser sinal de volume trocado."""
    status = seal_status(addr, cafile)
    if status is None:
        die(f"{label} não respondeu em {addr}. Veja com: docker ps")
    if not status.get("initialized"):
        die(f"{label} está vazio, sem inicializar.\n"
            "  Se é a primeira vez nesta máquina: cplane secrets init, cplane secrets apply e cplane up de novo.\n"
            "  Se ele já tinha dados, não inicialize: confira o volume com docker volume ls.")
    if not status.get("sealed"):
        ok(f"{label} aberto")
        return
    if not Path(init_file).exists() and not sys.stdin.isatty():
        die(f"{label} está selado e as chaves só podem ser digitadas em um terminal. Rode cplane up em um terminal.")
    print(f"  {label} selado: cole {status.get('t')} das {status.get('n')} chaves do seu gerenciador de senhas. Nada aparece na tela.", flush=True)
    for attempt in range(UNSEAL_ATTEMPTS):
        code = tool("cp-secrets", ["unseal"], env)
        if code < 0 or code == 130:
            raise KeyboardInterrupt
        status = seal_status(addr, cafile, wait=10)
        if status and not status.get("sealed"):
            ok(f"{label} aberto")
            return
        if attempt + 1 < UNSEAL_ATTEMPTS:
            print("  Não abriu. Confira as chaves e tente de novo.", flush=True)
    die(f"{label} continua selado. Nada foi alterado: rode cplane up quando tiver as chaves certas.")


def read_env(path):
    values = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def _digest(path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return ""


def write_obs_env(path):
    """Só gera se não existir: trocar estas senhas com os volumes já criados tira tudo de sincronia."""
    path = Path(path)
    if path.exists():
        return False
    lines = [f"ZO_ROOT_USER_EMAIL={ADMIN_EMAIL}", f"ZO_ROOT_USER_PASSWORD=Zo9-{secrets.token_hex(24)}", f"UMAMI_DB_PASSWORD={secrets.token_hex(24)}",
             f"UMAMI_APP_SECRET={secrets.token_hex(32)}", f"UMAMI_ADMIN_PASSWORD={secrets.token_hex(24)}"]
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write("\n".join(lines) + "\n")
    return True


def start_observability(layout):
    """Os mesmos compose.yml, Caddyfile e images.env da VPS e do laboratório. Devolve True se gerou senhas novas."""
    source = layout.program / "install" / "observability"
    folder = layout.obs_dir
    folder.mkdir(parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    gateway_rules = folder / "Caddyfile"
    before = _digest(gateway_rules)
    for name in ("compose.yml", "Caddyfile"):
        shutil.copyfile(source / name, folder / name)
    fresh = write_obs_env(folder / ".env")
    env = {**os.environ, **read_env(source / "images.env"), "OBS_BIND": "127.0.0.1", "GW_BIND": "127.0.0.1"}
    compose = ["docker", "compose", "--project-directory", str(folder), "--env-file", str(folder / ".env"), "-f", str(folder / "compose.yml"),
               "-f", str(layout.program / "local" / "observability.ports.yml")]
    print("  Na primeira vez, baixa cerca de 2,85 GB de imagens.", flush=True)
    result = subprocess.run([*compose, "up", "-d", "--quiet-pull", "--remove-orphans"], env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        die(f"Logs e analytics não subiram. Mensagem do Docker:\n{result.stderr.strip()}")
    # O Caddyfile é montado como arquivo: regra nova só vale depois de reiniciar o gateway.
    if before and before != _digest(gateway_rules):
        subprocess.run(["docker", "restart", "cp-observability-ingest-1"], capture_output=True)
        ok("gateway reiniciado com as regras novas")
    return fresh


def url_answers(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as res:
            return 200 <= res.status < 300
    except OSError:
        return False


def wait_url(url, wait=180):
    deadline = time.monotonic() + wait
    while not url_answers(url):
        if time.monotonic() >= deadline:
            return False
        time.sleep(2)
    return True


def _post_json(url, body, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=15) as res:
            return res.status, json.loads(res.read() or b"{}")
    except urllib.error.HTTPError as err:
        return err.code, {}
    except (OSError, ValueError):
        return 0, {}


def secure_umami(password, url=UMAMI_URL):
    """O Umami nasce com admin/umami. Falha fechada: só segue se a senha do .env entrar."""
    login = f"{url}/api/auth/login"
    status, body = _post_json(login, {"username": "admin", "password": "umami"})
    if status == 200:
        changed, _ = _post_json(f"{url}/api/me/password", {"currentPassword": "umami", "newPassword": password}, body.get("token"))
        if changed != 200:
            die("Não consegui trocar a senha padrão do Umami. Corrija antes de usar o gateway.")
        ok("Umami: senha padrão do admin trocada")
    elif status != 401:
        die(f"Umami: o login de verificação respondeu {status}, e o esperado era 200 ou 401.")
    status, _ = _post_json(login, {"username": "admin", "password": password})
    if status != 200:
        die(f"Umami: a senha do .env não entra (resposta {status}). Corrija antes de usar o gateway.")


def _provider_fields(listing):
    fields = {}
    for line in listing.splitlines():
        parts = line.split()
        found = next((p for p in parts if p.startswith("campos=")), None)
        if parts and found:
            fields[parts[0]] = found[len("campos="):].split(",")
    return fields


def register_providers(layout, values, force):
    """Grava as senhas de admin no cofre quando faltam. Repetir não cria versão nova à toa. Devolve True se estão lá."""
    client = cp_paths.home_client(layout)
    if not client:
        warn("A conta ainda não tem cliente: as senhas de admin ficam só no .env local.")
        return False
    listed = tool_output("cp-secrets", ["provider", "list", client])
    if listed.returncode != 0:
        warn("Não consegui consultar as credenciais no cofre. Confira com: cplane secrets status")
        return False
    fields = _provider_fields(listed.stdout)
    wanted = {
        OO_PROVIDER: ([f"url={OO_URL}", f"email={ADMIN_EMAIL}", f"ingest_url={GATEWAY_URL}"], values["ZO_ROOT_USER_PASSWORD"]),
        UMAMI_PROVIDER: ([f"url={UMAMI_URL}", "username=admin", f"ingest_url={GATEWAY_URL}"], values["UMAMI_ADMIN_PASSWORD"]),
    }
    complete = True
    for name, (plain, password) in wanted.items():
        if name not in fields:
            warn(f"{name} não está declarado na conta: declare para consultar logs e analytics por aqui.")
            complete = False
        elif force or "password" not in fields[name]:
            written = tool_output("cp-secrets", ["provider", "set", client, name, *plain, "--stdin", "password"], stdin=password)
            if written.returncode != 0:
                warn(f"Não consegui gravar {name} no cofre.")
                complete = False
            else:
                ok(f"{name}: senha de admin no cofre")
    return complete


def verify(addr, cafile=None):
    """O que precisa estar de pé. Devolve a lista de (nome, deu certo, como resolver)."""
    status = seal_status(addr, cafile, wait=5)
    vault_open = bool(status and status.get("initialized") and not status.get("sealed"))
    return [
        ("Cofre aberto", vault_open, "cplane secrets unseal"),
        ("OpenObserve", url_answers(f"{OO_URL}/healthz"), "docker logs cp-observability-openobserve-1"),
        ("Umami", url_answers(f"{UMAMI_URL}/api/heartbeat"), "docker logs cp-observability-umami-1"),
        ("Gateway de ingestão", url_answers(f"{GATEWAY_URL}/healthz"), "docker logs cp-observability-ingest-1"),
    ]


def port_in_use(port):
    with socket.socket() as probe:
        probe.settimeout(1)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def lab_env(layout):
    return {"CP_BAO_ADDR": LAB_ADDR, "CP_BAO_CACERT": str(layout.vault_dir / "tls" / "sim-ca.crt")}


def start_lab(layout):
    """Só religa o que já existe. Criar o laboratório é com sim/lab.sh."""
    folder = layout.program / "sim"
    if not folder.is_dir():
        die("O laboratório existe só no repositório, não no pacote instalado.")
    env = lab_env(layout)
    if not Path(env["CP_BAO_CACERT"]).exists():
        die("O laboratório ainda não foi criado nesta máquina. Crie com: sim/lab.sh up")
    # start, e não up: nunca recria contêiner, e o estado do laboratório fica como estava.
    code = subprocess.call(["docker", "compose", "-f", str(folder / "docker-compose.yml"), "start"], cwd=str(layout.program))
    if code != 0:
        die("O laboratório não subiu. Veja a mensagem do Docker acima. Para recriar: sim/lab.sh up")
    unlock_vault("Cofre do laboratório", LAB_ADDR, layout.vault_dir / ".init.json", env, env["CP_BAO_CACERT"])
    if tool("cp-secrets", ["status"], env) != 0:
        warn("O cofre do laboratório abriu, mas o status falhou. Confira com: cplane lab secrets status")


def up(layout, with_lab=False):
    """Devolve 0 só com tudo conferido. Com falha, diz o que falta e como resolver."""
    addr = os.environ.get("CP_BAO_ADDR", "http://127.0.0.1:8200")
    cafile = os.environ.get("CP_BAO_CACERT")

    step("Docker")
    ensure_docker()

    step("Cofre")
    if vault_compose(layout) != 0:
        die("O cofre não subiu. Veja a mensagem do Docker acima.")
    unlock_vault("Cofre", addr, layout.vault_dir / ".init.json", cafile=cafile)

    step("Logs e analytics")
    fresh = start_observability(layout)
    pending = [name for name, url in (("OpenObserve", f"{OO_URL}/healthz"), ("Umami", f"{UMAMI_URL}/api/heartbeat"), ("Gateway de ingestão", f"{GATEWAY_URL}/healthz")) if not wait_url(url)]
    if pending:
        die(f"Não responderam a tempo: {', '.join(pending)}. Veja com: docker ps")
    values = read_env(layout.obs_dir / ".env")
    secure_umami(values["UMAMI_ADMIN_PASSWORD"])
    ok("OpenObserve, Umami e gateway no ar")
    registered = register_providers(layout, values, force=fresh)

    if with_lab:
        step("Laboratório")
        start_lab(layout)

    step("Status")
    vault_report = tool("cp-secrets", ["status"])
    obs_report = tool("cp-obs", ["status"], LOCAL_PROVIDERS) if registered else 0
    rows = verify(addr, cafile)
    rows.append(("Status do cofre", vault_report == 0, "cplane secrets status"))
    if registered:
        rows.append(("Status de logs e analytics", obs_report == 0, "cplane obs status"))

    step("Conferência")
    for name, passed, _ in rows:
        print(f"  [{'ok' if passed else 'falhou'}] {name}", flush=True)
    failed = [(name, fix) for name, passed, fix in rows if not passed]
    if failed:
        print("\nAinda falta resolver:", flush=True)
        for name, fix in failed:
            print(f"  {name}. Veja: {fix}", flush=True)
        print("Depois, rode cplane up de novo. Repetir é seguro.", flush=True)
        return 1
    print(f"\nTudo no ar.\n  OpenObserve  {OO_URL}\n  Umami        {UMAMI_URL}\n  Gateway      {GATEWAY_URL}  só recebe logs; abrir no navegador dá 404", flush=True)
    return 0

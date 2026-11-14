"""Acesso remoto ao painel: quem é a máquina e quem é a pessoa (etapa 2, ADR 068).

Regra: dispositivo aprovado + pessoa com MFA + tailnet quando houver. Nome, IP e navegador só dão um rótulo legível.

Só stdlib. O que fica em disco (state/auth.json, 600):
  - senha: hash scrypt; códigos de recuperação e tokens: só o hash;
  - segredo TOTP em texto: precisa ser lido para conferir. Quem lê este arquivo já é dono da máquina.
Sessões ficam só em memória: reiniciar o painel pede login de novo.
A criação da conta e a primeira aprovação são só pelo terminal: nada pela rede cria acesso do zero.
"""
import base64
import contextlib
import copy
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import shutil
import struct
import subprocess
import threading
import time
from datetime import datetime, timezone
from urllib.parse import quote

CLASSES = {"operacao": "Operação", "consulta": "Consulta", "lab": "Lab/teste"}
LAB_ENVS = ("dev", "staging")
LAB_HINT = "O detalhe fica com um dispositivo de Operação."
# Pela tailnet (HTTPS do tailscale serve), os cookies levam o prefixo __Host-: o navegador só aceita com Secure, Path=/
# e sem Domain, e nenhuma outra máquina de *.ts.net consegue plantar um cookie com esse nome para o painel.
# Só o acesso local em http://127.0.0.1 ou localhost usa o nome sem prefixo, que é o que funciona fora do HTTPS.
COOKIES = {
    "tailnet": {"device": "__Host-cp_device", "session": "__Host-cp_session"},
    "local": {"device": "cp_device", "session": "cp_session"},
}
LOCAL_HOSTS = ("127.0.0.1", "localhost")
DEVICE_MAX_AGE = 400 * 86400
SESSION_MAX = 12 * 3600
SESSION_IDLE = 3600
FRESH_MFA = 300
PENDING_TTL = 1800
MAX_PENDING = 20
MAX_FAILS = 5
FAIL_WINDOW = 900
MIN_PASSWORD = 12
SEEN_EVERY = 60
WHOIS_TTL = 60
EVENTS_KEEP = 1_000_000
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ23456789"  # sem letras e números que se confundem
SCRYPT = {"n": 2 ** 15, "r": 8, "p": 1}
SCRYPT_MEM = 128 * 1024 * 1024
PBKDF2_ROUNDS = 600_000
STEP = 30
ALERTS = {"unknown_device", "revoked_used", "node_mismatch", "origin_refused", "login_fail", "lockout", "device_approved", "prod_action", "recovery_used"}
TAILNET_V4 = ipaddress.ip_network("100.64.0.0/10")
TAILNET_V6 = ipaddress.ip_network("fd7a:115c:a1e0::/48")


class AuthError(Exception):
    """Recusa com mensagem segura para mostrar."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class OriginRefused(AuthError):
    """Modo remoto, pedido sem origem identificada: nem local, nem de uma máquina que a tailnet reconhece."""

    def __init__(self):
        super().__init__("Acesso só pela tailnet. A origem deste pedido não foi identificada.", 403)


def utc(moment=None):
    return datetime.fromtimestamp(time.time() if moment is None else moment, timezone.utc).isoformat(timespec="seconds")


def _sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


# ---------- Senha e TOTP ----------
def _derive(password, salt, kind):
    if kind == "scrypt":
        return hashlib.scrypt(password.encode(), salt=salt, maxmem=SCRYPT_MEM, dklen=32, **SCRYPT).hex()
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS).hex()


def hash_password(password, salt=None, kind=None):
    """scrypt quando o Python tem. O Python de alguns macOS vem sem ele: nesses, PBKDF2 com muitas rodadas."""
    kind = kind or ("scrypt" if hasattr(hashlib, "scrypt") else "pbkdf2")
    salt = salt or secrets.token_bytes(16)
    return {"kind": kind, "salt": salt.hex(), "hash": _derive(password, salt, kind)}


def check_password(password, stored):
    candidate = _derive(password, bytes.fromhex(stored["salt"]), stored.get("kind", "scrypt"))
    return hmac.compare_digest(candidate, stored["hash"])


DUMMY_PASSWORD = None


def _burn_time(password):
    """Usuário errado leva o mesmo tempo que senha errada."""
    global DUMMY_PASSWORD
    if DUMMY_PASSWORD is None:
        DUMMY_PASSWORD = hash_password("x")
    check_password(password, DUMMY_PASSWORD)


def hotp(secret, counter, digits=6):
    key = base64.b32decode(secret, casefold=True)
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = mac[-1] & 15
    value = struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10 ** digits).zfill(digits)


def totp(secret, moment=None, digits=6):
    return hotp(secret, int((time.time() if moment is None else moment) // STEP), digits)


def otpauth_uri(secret, username, account):
    label = quote(f"{account}:{username}", safe="")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(account, safe='')}&digits=6&period={STEP}"


def new_code(size=8):
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(size))


def clean_code(value):
    return re.sub(r"[\s-]", "", value).upper() if isinstance(value, str) else ""


def clean_label(value, limit=40):
    """Texto vindo da rede que vai para o registro. isprintable também barra surrogate, que o JSON aceita e o UTF-8 não grava."""
    return " ".join(value.split())[:limit] if isinstance(value, str) and value.isprintable() else ""


def encodable(value):
    try:
        value.encode()
    except UnicodeEncodeError:
        return False
    return True


class Store:
    """Um arquivo, gravado por inteiro e com trava: o terminal e o painel mudam o mesmo estado."""

    def __init__(self, folder):
        self.folder = folder
        self.path = folder / "auth.json"
        self.lock_path = folder / ".auth.lock"
        self.events_path = folder / "security.jsonl"

    @contextlib.contextmanager
    def locked(self):
        self.folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        deadline = time.monotonic() + 8
        while True:
            try:
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                break
            except FileExistsError:
                try:
                    if time.time() - self.lock_path.stat().st_mtime > 30:  # processo morto no meio
                        self.lock_path.unlink()
                        continue
                except OSError:
                    continue
                if time.monotonic() > deadline:
                    raise AuthError("O registro de acesso está ocupado. Tente de novo.", 503) from None
                time.sleep(0.03)
        try:
            yield
        finally:
            os.close(fd)
            with contextlib.suppress(OSError):
                self.lock_path.unlink()

    def load(self):
        for attempt in range(40):
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                break
            except FileNotFoundError:
                return {"account": None, "devices": {}}
            except OSError:
                # No Windows, ler durante a troca do arquivo falha por um instante. Tratar como "sem conta" apagaria tudo na gravação seguinte.
                if attempt == 39:
                    raise AuthError("Não foi possível ler o registro de acesso. Tente de novo.", 503) from None
                time.sleep(0.025)
            except ValueError:
                raise AuthError("O registro de acesso está corrompido. Veja no terminal da principal.", 500) from None
        data.setdefault("account", None)
        data.setdefault("devices", {})
        return data

    def save(self, data):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")  # antes de abrir: um erro aqui não deixa cópia parcial do segredo em disco
        self.folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        temp = self.path.with_name(f".auth.{secrets.token_hex(4)}")
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as out:
                out.write(payload)
            for attempt in range(40):
                try:
                    os.replace(temp, self.path)
                    return
                except PermissionError:  # alguém lendo no Windows
                    if attempt == 39:
                        raise AuthError("Não foi possível gravar o registro de acesso. Tente de novo.", 503) from None
                    time.sleep(0.025)
        except BaseException:
            with contextlib.suppress(OSError):
                temp.unlink()
            raise

    def event(self, kind, **detail):
        self.folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            if self.events_path.stat().st_size > EVENTS_KEEP:  # registro não cresce sem limite
                os.replace(self.events_path, self.events_path.with_suffix(".jsonl.1"))
        fd = os.open(self.events_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as out:
            out.write(json.dumps({"at": utc(), "kind": kind, **detail}, ensure_ascii=False) + "\n")

    def events(self, limit=100):
        try:
            lines = self.events_path.read_text(encoding="utf-8").splitlines()[-limit:]
        except OSError:
            return []
        rows = []
        for line in reversed(lines):
            with contextlib.suppress(ValueError):
                rows.append(json.loads(line))
        return rows


# ---------- Conta, só pelo terminal ----------
def validate_credentials(username, password):
    if not re.fullmatch(r"[A-Za-z0-9._@+-]{2,60}", username or ""):
        raise AuthError("Usuário inválido: use de 2 a 60 letras, números, ponto, hífen ou @.")
    if len(password or "") < MIN_PASSWORD:
        raise AuthError(f"A senha precisa de ao menos {MIN_PASSWORD} caracteres.")


def new_totp_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode()


def create_account(store, username, password, replace=False, secret=None):
    validate_credentials(username, password)
    secret = secret or new_totp_secret()
    recovery = [f"{new_code(5)}-{new_code(5)}" for _ in range(8)]
    with store.locked():
        data = store.load()
        if data["account"] and not replace:
            raise AuthError("Já existe uma conta de acesso. Para trocar: cplane account reset")
        epoch = (data["account"] or {}).get("epoch", 0) + 1
        for device in data["devices"].values():  # redefinir a conta libera quem estava bloqueado
            device.pop("fails", None)
        data["account"] = {"username": username, "password": hash_password(password), "totp": secret, "last_step": 0,
                           "recovery": [_sha(clean_code(c)) for c in recovery], "epoch": epoch, "created": utc()}
        store.save(data)
    store.event("account_created", who=username)
    return secret, recovery


def password_matches(account, username, password):
    if not hmac.compare_digest((username or "").encode(), account["username"].encode()):
        _burn_time(password or "")
        return False
    return check_password(password or "", account["password"])


def _recent_fails(data, device_id, moment):
    """Erros contam por dispositivo: um aprovado com pouca confiança não pode trancar a pessoa nos outros."""
    device = data["devices"].get(device_id)
    if device is None:
        raise AuthError("Este dispositivo não está aprovado.", 403)
    device["fails"] = [t for t in device.get("fails", []) if moment - t < FAIL_WINDOW]
    if len(device["fails"]) >= MAX_FAILS:
        raise AuthError("Muitas tentativas neste dispositivo. Espere 15 minutos ou redefina no terminal da principal.", 429)
    return device["fails"]


def _consume_totp(account, code, moment):
    """Código de 6 dígitos, com 1 passo de folga para o relógio. Cada um vale uma vez só."""
    if not re.fullmatch(r"[0-9]{6}", code):  # \d aceitaria dígitos de outras escritas, e compare_digest não aceita texto fora do ASCII
        return False
    current = int(moment // STEP)
    for step in (current - 1, current, current + 1):
        if step > account.get("last_step", 0) and hmac.compare_digest(hotp(account["totp"], step), code):
            account["last_step"] = step
            return True
    return False


def _consume_recovery(account, code):
    if not code.isascii():
        return False
    digest = _sha(clean_code(code))
    if digest in account.get("recovery", []):
        account["recovery"].remove(digest)
        return True
    return False


def describe_agent(agent):
    """Rótulo para reconhecer o pedido, nunca prova de nada."""
    agent = agent or ""
    browser = next((name for mark, name in (("Edg/", "Edge"), ("Firefox/", "Firefox"), ("Chrome/", "Chrome"), ("Safari/", "Safari")) if mark in agent), "Navegador")
    system = next((name for mark, name in (("Android", "Android"), ("iPhone", "iPhone"), ("iPad", "iPad"), ("Windows", "Windows"), ("Mac OS", "macOS"), ("Linux", "Linux")) if mark in agent), "sistema não informado")
    return f"{browser} em {system}"


def public_device(device):
    return {k: device.get(k) for k in ("id", "name", "kind", "state", "class", "owner", "approved_by", "approved_at", "created", "last_seen", "node", "instance", "revoked_at")}


def purge_pending(data, moment=None):
    moment = time.time() if moment is None else moment
    for key in [k for k, d in data["devices"].items() if d["state"] == "pending" and moment - d.get("created_ts", 0) > PENDING_TTL]:
        del data["devices"][key]


def approve_device(store, code, klass, by):
    if klass not in CLASSES:
        raise AuthError("Classe inválida. Use operacao, consulta ou lab.")
    wanted = clean_code(code)
    with store.locked():
        data = store.load()
        purge_pending(data)
        device = next((d for d in data["devices"].values() if d["state"] == "pending" and hmac.compare_digest(d.get("code", ""), wanted)), None) if wanted.isascii() else None
        if device is None:
            raise AuthError("Nenhum pedido com esse código. Confira na tela do dispositivo: o pedido vale 30 minutos.", 404)
        device.update({"state": "approved", "class": klass, "approved_by": by, "approved_at": utc(), "owner": (device.get("node") or {}).get("user") or (data["account"] or {}).get("username", "")})
        device.pop("code", None)
        store.save(data)
    store.event("device_approved", device=device["name"], device_id=device["id"], by=by, device_class=klass)
    return public_device(device)


def find_device(data, wanted):
    device = data["devices"].get(wanted)
    if device is None:
        raise AuthError("Dispositivo não encontrado.", 404)
    return device


def revoke_device(store, device_id, by):
    with store.locked():
        data = store.load()
        device = find_device(data, device_id)
        if device["state"] == "pending":
            del data["devices"][device_id]
        else:
            device.update({"state": "revoked", "revoked_at": utc()})
        store.save(data)
    store.event("device_revoked", device=device["name"], device_id=device_id, by=by)


def set_class(store, device_id, klass, by):
    if klass not in CLASSES:
        raise AuthError("Classe inválida. Use operacao, consulta ou lab.")
    with store.locked():
        data = store.load()
        device = find_device(data, device_id)
        if device["state"] != "approved":
            raise AuthError("Só um dispositivo aprovado tem classe.")
        device["class"] = klass
        store.save(data)
    store.event("device_class", device=device["name"], device_id=device_id, by=by, device_class=klass)


def _forwarded(headers):
    """Último item do X-Forwarded-For: o que o tailscale serve acrescentou ou sobrescreveu (teste manual em docs/maquinas.md)."""
    return (headers.get("X-Forwarded-For") or "").split(",")[-1].strip()


def _in_tailnet(raw):
    try:
        address = ipaddress.ip_address(raw)
    except ValueError:
        return False
    return address in (TAILNET_V4 if address.version == 4 else TAILNET_V6)


class Remote:
    """Decide cada pedido quando o painel abre para fora de 127.0.0.1."""

    def __init__(self, store, hosts=(), whois=None, clock=time.time):
        self.store = store
        self.hosts = {h.lower() for h in hosts}
        self.whois = whois if whois is not None else tailscale_whois
        self.clock = clock
        self.lock = threading.Lock()
        self.sessions = {}
        self.whois_cache = {}
        self.warned = {}

    # ---------- Origem do pedido ----------
    def host_allowed(self, host, port):
        host = (host or "").lower()
        return host in self.hosts or host in {f"127.0.0.1:{port}", f"localhost:{port}"}

    def origin_allowed(self, origin, port):
        return origin in {f"https://{h}" for h in self.hosts} | {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}

    def node_of(self, headers):
        """Quem a tailnet diz que é. O painel só escuta em 127.0.0.1, atrás do tailscale serve, que coloca este cabeçalho.
        Só sucesso entra no cache: uma falha do whois (CLI ausente, tailscaled lento) é tentada de novo no próximo pedido."""
        raw = _forwarded(headers)
        if not _in_tailnet(raw):
            return None
        moment = self.clock()
        with self.lock:
            cached = self.whois_cache.get(raw)
            if cached and moment - cached[0] < WHOIS_TTL:
                return cached[1]
        node = self.whois(raw)
        if not (isinstance(node, dict) and node.get("id")):
            with self.lock:
                self.whois_cache.pop(raw, None)
            return None
        with self.lock:
            self.whois_cache[raw] = (moment, node)
        return node

    @staticmethod
    def is_local(headers):
        """Acesso nesta mesma máquina, sem passar pelo tailscale serve: sem X-Forwarded-For e com Host 127.0.0.1 ou localhost.
        É a exceção explícita do modo remoto. O dispositivo criado assim fica preso ao acesso local (ver context)."""
        if headers.get("X-Forwarded-For") is not None:
            return False
        host = (headers.get("Host") or "").lower().rsplit(":", 1)[0]
        return host in LOCAL_HOSTS

    def origin(self, headers):
        """Falha fechada: pedido que não é local nem de uma máquina que a tailnet identifica é recusado, inclusive em /api/auth/.
        Devolve (canal, nó). O registro guarda só o motivo e o IP, quando o cabeçalho traz um IP válido."""
        if self.is_local(headers):
            return "local", None
        node = self.node_of(headers)
        if node:
            return "tailnet", node
        raw = _forwarded(headers)
        reason = "sem_origem" if not raw else "whois_falhou" if _in_tailnet(raw) else "fora_da_tailnet"
        try:
            address = str(ipaddress.ip_address(raw))
        except ValueError:
            address = ""  # texto qualquer do cabeçalho não vai para o registro
        self.warn_once("origin_refused", reason, reason=reason, address=address)  # um por motivo a cada 10 min: IP forjado não enche o registro
        raise OriginRefused()

    @staticmethod
    def cookies(headers, channel="local"):
        """Só os dois cookies do painel, com o nome do canal. Pela tailnet, cookie sem __Host- é ignorado: pode ter sido
        plantado por outra máquina de *.ts.net. Outra aplicação no mesmo host pode mandar cookie fora do padrão: um parser estrito perderia os nossos."""
        names = COOKIES[channel]
        wanted = {names["device"]: "device", names["session"]: "session"}
        found = {}
        for part in (headers.get("Cookie") or "").split(";"):
            name, sep, value = part.partition("=")
            name = name.strip()
            if sep and name in wanted:
                found.setdefault(wanted[name], value.strip())
        return found

    def warn_once(self, kind, key, **detail):
        moment = self.clock()
        with self.lock:
            if moment - self.warned.get((kind, key), 0) < 600:
                return
            self.warned[(kind, key)] = moment
        self.store.event(kind, **detail)

    # ---------- Estado de quem pediu ----------
    def context(self, headers, active=False):
        """active: o pedido veio de alguém usando o painel. A leitura periódica da tela não conta, ou a sessão nunca venceria por inatividade."""
        channel, node = self.origin(headers)
        cookies = self.cookies(headers, channel)
        data = self.store.load()
        ctx = {"state": "unknown", "device": None, "session": None, "node": node, "channel": channel, "data": data, "address": _forwarded(headers)[:45]}
        if not data["account"]:
            ctx["state"] = "no_account"
            return ctx
        token = cookies.get("device")
        digest = _sha(token) if token else None
        device = next((d for d in data["devices"].values() if digest and hmac.compare_digest(d.get("token_hash", ""), digest)), None)
        if device is None:
            return ctx
        ctx["device"] = device
        if device["state"] == "pending":
            ctx["state"] = "pending" if self.clock() - device.get("created_ts", 0) <= PENDING_TTL else "unknown"
            if ctx["state"] == "unknown":
                ctx["device"] = None
            return ctx
        if device["state"] == "revoked":
            ctx["state"] = "revoked"
            self.warn_once("revoked_used", device["id"], device=device["name"], device_id=device["id"], address=ctx["address"])
            return ctx
        # Preso à origem do pedido: aprovado por uma máquina da tailnet, só vale nela; criado no acesso local, só vale local.
        bound = (device.get("node") or {}).get("id")
        if bound != (node or {}).get("id"):
            ctx["state"] = "node_mismatch"
            self.warn_once("node_mismatch", device["id"], device=device["name"], device_id=device["id"], seen=(node or {}).get("name") or channel, expected=(device.get("node") or {}).get("name") or "local")
            return ctx
        ctx["state"] = "need_login"
        self._touch(device)
        if device.get("kind") == "install":
            ctx["state"] = "registered"
            return ctx
        ctx["session"] = self._session(cookies.get("session"), device, data["account"], active)
        if ctx["session"]:
            ctx["state"] = "ok"
        return ctx

    def _touch(self, device):
        moment = self.clock()
        if moment - device.get("seen_ts", 0) < SEEN_EVERY:
            return
        with self.store.locked():
            data = self.store.load()
            live = data["devices"].get(device["id"])
            if live:
                live.update({"seen_ts": moment, "last_seen": utc(moment)})
                self.store.save(data)
        device.update({"seen_ts": moment, "last_seen": utc(moment)})

    def _session(self, token, device, account, active=False):
        if not token:
            return None
        digest = _sha(token)
        moment = self.clock()
        with self.lock:
            session = self.sessions.get(digest)
            if not session:
                return None
            if session["device"] != device["id"] or session["epoch"] != account.get("epoch") or moment - session["created"] > SESSION_MAX or moment - session["last"] > SESSION_IDLE:
                del self.sessions[digest]
                return None
            if active:
                session["last"] = moment
            return session

    # ---------- Pedidos ----------
    def request_device(self, headers, req):
        """Só cria um pedido pendente. Não dá acesso a nada até alguém aprovar pelo código."""
        ctx = self.context(headers)
        if ctx["state"] == "no_account":
            raise AuthError("A conta de acesso ainda não existe. Crie no terminal da principal: cplane account create", 409)
        if ctx["device"] is not None:
            raise AuthError("Este dispositivo já fez o pedido.", 409)
        name = clean_label(req.get("name"))
        kind = "install" if req.get("kind") == "install" else "browser"
        node = ctx["node"]
        token = secrets.token_urlsafe(32)
        code = new_code()
        moment = self.clock()
        device = {"id": secrets.token_hex(8), "kind": kind, "state": "pending", "code": code, "token_hash": _sha(token), "created": utc(moment), "created_ts": moment,
                  "name": name or (node or {}).get("name") or describe_agent(headers.get("User-Agent")), "agent": describe_agent(headers.get("User-Agent")), "node": node, "address": ctx["address"]}
        if kind == "install" and isinstance(req.get("instance"), dict):
            device["instance"] = {k: clean_label(req["instance"].get(k)) for k in ("id", "role", "os")}
        with self.store.locked():
            data = self.store.load()
            purge_pending(data, moment)
            if sum(d["state"] == "pending" for d in data["devices"].values()) >= MAX_PENDING:
                raise AuthError("Há pedidos demais aguardando. Aprove ou espere 30 minutos.", 429)
            data["devices"][device["id"]] = device
            self.store.save(data)
        self.store.event("unknown_device", device=device["name"], device_id=device["id"], node=(node or {}).get("name"), address=ctx["address"])
        return token, code

    def login(self, headers, req):
        ctx = self.context(headers, active=True)
        if ctx["state"] not in ("need_login", "ok"):
            raise AuthError("Este dispositivo não está aprovado.", 403)
        username, password, code = req.get("username"), req.get("password"), req.get("code")
        if not all(isinstance(v, str) and len(v) <= 200 and encodable(v) for v in (username, password, code)):
            raise AuthError("Pedido inválido.")
        device = ctx["device"]
        moment = self.clock()
        with self.store.locked():
            data = self.store.load()
            account = data["account"]
            fails = _recent_fails(data, device["id"], moment)
            used_recovery = False
            good = password_matches(account, username, password)
            if good:
                good = _consume_totp(account, code.strip(), moment)
                if not good:
                    used_recovery = good = _consume_recovery(account, code)
            if good:
                fails.clear()
            else:
                fails.append(moment)
            locked = len(fails) >= MAX_FAILS
            self.store.save(data)
            epoch = account.get("epoch")
            person = account["username"]
        if not good:
            self.store.event("lockout" if locked else "login_fail", device=device["name"], device_id=device["id"], address=ctx["address"])
            raise AuthError("Usuário, senha ou código incorretos.", 401)
        if used_recovery:
            self.store.event("recovery_used", device=device["name"], device_id=device["id"])
        token = secrets.token_urlsafe(32)
        with self.lock:
            self.sessions = {k: s for k, s in self.sessions.items() if s["device"] != device["id"]}  # uma sessão por dispositivo
            self.sessions[_sha(token)] = {"device": device["id"], "person": person, "created": moment, "last": moment, "mfa_at": moment, "epoch": epoch}
        self.store.event("login", device=device["name"], device_id=device["id"], who=person)
        return token

    def logout(self, headers):
        channel, _ = self.origin(headers)
        token = self.cookies(headers, channel).get("session")
        if token:
            with self.lock:
                self.sessions.pop(_sha(token), None)

    def step_up(self, ctx, code):
        if not isinstance(code, str):
            raise AuthError("Informe o código.")
        moment = self.clock()
        with self.store.locked():
            data = self.store.load()
            account = data["account"]
            fails = _recent_fails(data, ctx["device"]["id"], moment)
            good = _consume_totp(account, code.strip(), moment)
            if not good:
                fails.append(moment)
            locked = len(fails) >= MAX_FAILS
            self.store.save(data)
        if not good:
            self.store.event("lockout" if locked else "login_fail", device=ctx["device"]["name"], device_id=ctx["device"]["id"], step="confirmacao")
            raise AuthError("Código incorreto.", 401)
        with self.lock:
            ctx["session"]["mfa_at"] = moment

    def fresh(self, ctx):
        return bool(ctx["session"]) and self.clock() - ctx["session"].get("mfa_at", 0) <= FRESH_MFA

    # ---------- O que cada classe pode ----------
    def require(self, ctx, *classes, fresh=False):
        if ctx["state"] != "ok":
            raise AuthError("Entre para continuar.", 401)
        if ctx["device"].get("class") not in classes:
            raise AuthError(f"A classe {CLASSES.get(ctx['device'].get('class'), '')} não permite esta ação.", 403)
        if fresh and not self.fresh(ctx):
            raise AuthError("Confirme com o código do autenticador.", 428)

    def guard_action(self, ctx):
        """Devolve a função que aprova um plano já montado: quem vê o ambiente real é o servidor, não a tela."""
        def check(plan):
            self.require(ctx, "operacao", "lab")
            env = plan.get("env")
            if ctx["device"].get("class") == "lab" and env not in LAB_ENVS:
                raise AuthError("Um dispositivo Lab/teste só age em dev e staging.", 403)
            if env not in LAB_ENVS and not plan.get("read_only"):  # sem ambiente também conta: criar cliente mexe no cofre real
                self.require(ctx, "operacao", fresh=True)
                self.store.event("prod_action", device=ctx["device"]["name"], device_id=ctx["device"]["id"], who=ctx["session"]["person"], action=str(plan.get("label"))[:120])
        return check

    def public_state(self, ctx):
        device = ctx["device"]
        out = {"remote": True, "state": ctx["state"]}
        if device:
            out["device"] = {"name": device["name"], "class": device.get("class"), "class_name": CLASSES.get(device.get("class"), "")}
            if ctx["state"] == "pending":
                out["code"] = device.get("code")
        if ctx["session"]:
            out["person"] = ctx["session"]["person"]
            out["fresh"] = self.fresh(ctx)
        return out

    def cookie_headers(self, kind, headers, value, max_age):
        """kind: device ou session. O nome segue o canal do pedido; os atributos são os mesmos e nunca levam Domain."""
        channel = "local" if self.is_local(headers) else "tailnet"
        return f"{COOKIES[channel][kind]}={value}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age={max_age}"


def jobs_for_class(rows, klass):
    """Lab/teste acompanha o que pode executar. Linha sem ambiente conhecido fica de fora."""
    return [row for row in rows if row.get("env") in LAB_ENVS] if klass == "lab" else rows


def _lab_rollout_row(row):
    """Dica e comando citam caminhos e recursos de todos os ambientes. Só a linha de dev e staging é separada por ambiente."""
    kept = {k: row[k] for k in ("id", "title", "state", "source") if k in row}
    if row.get("id") == "dev":
        kept.update({k: row[k] for k in ("hint",) if k in row})
        if (row.get("real") or {}).get("env") in LAB_ENVS:
            kept["real"] = row["real"]
    elif row.get("state") in ("todo", "err"):
        kept["hint"] = LAB_HINT
    return kept


def filter_for_class(data, klass):
    """Lab/teste nunca alcança produção. Quem corta é o servidor, e por lista do que pode passar: campo novo não vaza sozinho."""
    if klass != "lab":
        return data
    data = copy.deepcopy(data)  # as linhas reais vêm de um cache compartilhado com os outros dispositivos
    for app in data.get("apps", []):
        app["envs"] = {env: row for env, row in app["envs"].items() if env in LAB_ENVS}
    data["apps"] = [a for a in data.get("apps", []) if a["envs"]]
    data["logs"] = [row for row in data.get("logs", []) if row.get("env") in LAB_ENVS]
    data["rollout"] = {k: [_lab_rollout_row(p) for p in rows if p.get("id") != "prod"] for k, rows in data.get("rollout", {}).items()}
    data["diverge"] = []
    data["activity"] = jobs_for_class(data.get("activity", []), klass)
    data["accounts"] = []
    data["discoveries"] = {}
    connection = data.get("connection")
    if connection:  # o texto cita clientes, credenciais e endereços
        connection["problems"] = [{"area": p.get("area", ""), "text": "A leitura desta área falhou.", "next": LAB_HINT} for p in connection.get("problems", [])]
        connection["error"] = LAB_HINT if connection.get("error") else connection.get("error")
    return data


def machines_view(store, klass=None):
    """Lista para a tela Máquinas, sem token, sem código e sem hash."""
    data = store.load()
    purge_pending(data)
    rows = [public_device(d) for d in data["devices"].values()]
    rows.sort(key=lambda d: (d["state"] != "pending", d.get("created") or ""), reverse=False)
    account = data["account"] or {}
    moment = time.time()
    locked = [d["name"] for d in data["devices"].values() if sum(moment - t < FAIL_WINDOW for t in d.get("fails", [])) >= MAX_FAILS]
    return {"devices": rows, "events": store.events(), "account": {"exists": bool(data["account"]), "username": account.get("username", ""), "recovery_left": len(account.get("recovery", [])), "locked": locked}, "alert_kinds": sorted(ALERTS), "classes": CLASSES}


def tailscale_whois(address):
    """Máquina e dono que a tailnet associa a este IP. Sem Tailscale, None: o painel segue, sem esse reforço."""
    if not shutil.which("tailscale"):
        return None
    try:
        done = subprocess.run(["tailscale", "whois", "--json", address], capture_output=True, text=True, timeout=3)
        if done.returncode != 0:
            return None
        info = json.loads(done.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    node = info.get("Node") or {}
    return {"id": str(node.get("StableID") or node.get("ID") or ""), "name": (node.get("ComputedName") or node.get("Name") or "")[:60],
            "os": ((node.get("Hostinfo") or {}).get("OS") or "")[:20], "user": ((info.get("UserProfile") or {}).get("LoginName") or "")[:80]} if node else None

"""Conta e papel desta máquina: o que a primeira visita grava e o que o painel mostra sem cofre.

Só nomes e estrutura, nunca valores. Com openbao/secrets.toml na pasta (layout antigo), a primeira visita não aparece.
"""
import json
import os
import re
import secrets
import socket
from datetime import datetime, timezone

import clients
import cp_config
import cp_paths
import live
from cp_toml import tomllib

ROLES = {"lab": "Laboratório", "teste": "Teste", "principal": "Principal"}
PANEL_ROLES = ("lab", "teste")  # principal só pelo terminal da própria máquina: cplane machine promote
MODES = ("empty", "examples")
PROBE_HOST = re.compile(r"https?://(127\.0\.0\.1|localhost)(:\d+)?(/\S*)?")
NO_VAULT = "Sem conexão com o cofre."


class SetupError(Exception):
    pass


def _quote(value):
    return json.dumps(value, ensure_ascii=False)


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{secrets.token_hex(3)}")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write(text)
    os.replace(temp, path)


def read_machine(layout):
    try:
        return tomllib.loads(layout.machine_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_machine(layout, **changes):
    """Só este arquivo registra a máquina. O id nasce uma vez e não muda."""
    machine = read_machine(layout)
    machine.setdefault("id", secrets.token_hex(8))
    machine.setdefault("name", socket.gethostname()[:60])
    machine.setdefault("created", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    machine.update(changes)
    machine = {k: v for k, v in machine.items() if v is not None}
    _write(layout.machine_file, "".join(f"{k} = {_quote(v)}\n" for k, v in machine.items()))
    return machine


def status(layout, version):
    machine = read_machine(layout)
    workspace = cp_paths.read_workspace(layout)
    mode = machine.get("mode")
    return {
        "layout": "checkout" if layout.legacy else "installed",
        "needs_setup": not layout.legacy and not mode,
        "needs_role": not layout.legacy and mode == "real" and not machine.get("role"),
        "view": "examples" if layout.legacy or mode == "examples" or not mode else "real",
        "version": version,
        "os": cp_paths.os_kind(),
        "machine": {k: machine.get(k, "") for k in ("id", "name", "role")},
        "role_name": ROLES.get(machine.get("role"), ""),
        "account": workspace.get("name", ""),
        "home_client": cp_paths.home_client(layout),
        "config_dir": str(layout.config_dir),
        "config_git": (layout.config_dir / ".git").exists(),
    }


def _valid_name(value):
    if not isinstance(value, str) or not 2 <= len(value.strip()) <= 60 or not value.isprintable():
        raise SetupError("Informe um nome com 2 a 60 caracteres.")
    return value.strip()


def _valid_role(value):
    if value not in PANEL_ROLES:
        raise SetupError("Escolha Laboratório ou Teste. A principal é definida no terminal da própria máquina.")
    return value


def _start(layout, req):
    mode = req.get("mode")
    if mode not in MODES:
        raise SetupError("Escolha como começar.")
    if read_machine(layout).get("mode") == "real":
        raise SetupError("Esta máquina já tem uma conta.")
    if mode == "examples":
        return write_machine(layout, mode="examples", role=read_machine(layout).get("role") or "teste")
    name = _valid_name(req.get("name"))
    role = _valid_role(req.get("role"))
    if not layout.workspace_file.exists():
        _write(layout.workspace_file, f'name = {_quote(name)}\nhome_client = ""\n')
    if not layout.main_toml.exists():
        _write(layout.main_toml, "# Clientes declarados aqui ou em clients/<cliente>.toml. Só nomes, nenhum valor.\n")
    layout.clients_dir.mkdir(parents=True, exist_ok=True)
    return write_machine(layout, mode="real", role=role)


def _set_home(layout, slug):
    workspace = cp_paths.read_workspace(layout)
    if workspace.get("home_client"):
        return
    raw = layout.workspace_file.read_text(encoding="utf-8")
    line = f"home_client = {_quote(slug)}"
    _write(layout.workspace_file, re.sub(r"(?m)^home_client\s*=.*$", line, raw) if "home_client" in raw else f"{line}\n{raw}")


def _client(layout, req):
    if read_machine(layout).get("mode") != "real":
        raise SetupError("Os exemplos não gravam clientes.")
    config = cp_config.load(layout.main_toml, layout.clients_dir)
    try:
        spec = clients.validate(req.get("spec"), {c["slug"] for c in config.get("client", [])})
        clients.write(layout.clients_dir, spec)
    except clients.SpecError as err:
        raise SetupError(str(err)) from None
    _set_home(layout, spec["slug"])
    return {"slug": spec["slug"]}


def apply(layout, req):
    """Lista fechada de mudanças vindas da tela. Importar conta só pelo terminal: pode pedir a chave SSH de quem opera."""
    if layout.legacy:
        raise SetupError("Esta pasta usa o layout antigo: a configuração é feita nos arquivos.")
    if not isinstance(req, dict):
        raise SetupError("Pedido inválido.")
    action = req.get("action")
    if action == "start":
        _start(layout, req)
        return {}
    if action == "role":
        write_machine(layout, role=_valid_role(req.get("role")))
        return {}
    if action == "leave_examples":
        if read_machine(layout).get("mode") != "examples":
            raise SetupError("Esta máquina não está nos exemplos.")
        write_machine(layout, mode=None, role=None)
        return {}
    if action == "client":
        return _client(layout, req)
    raise SetupError("Pedido inválido.")


def probes(layout):
    """Aplicações que a conta quer ver no ar nesta máquina. Só endereço local: o painel não sonda fora dela."""
    rows = cp_paths.read_workspace(layout).get("probe", [])
    out = []
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and isinstance(row.get("url"), str) and PROBE_HOST.fullmatch(row["url"]) and isinstance(row.get("name"), str):
            out.append({"id": f"probe_{len(out)}", "name": row["name"][:60], "url": row["url"]})
    return out


def empty_data():
    return {"clients": [], "accounts": [], "apps": [], "diverge": [], "rollout": {}, "logs": [], "activity": []}


def _env_row(where):
    return {"state": "unread", "health": NO_VAULT, "version": "Não lido", "moving": False, "commit": "", "when": "Sem leitura", "where": where,
            "secretsState": "todo", "next": "Conecte esta máquina ao cofre para ver o estado."}


def _app_type(project, kind):
    return project.get("type") or live.TYPE_BY_KIND.get(kind) or "api-coolify"


def config_view(config):
    """O que a configuração declara, sem inventar estado: tudo aparece como não lido até haver cofre."""
    data = empty_data()
    data["sources"] = {area: "config" for area in ("clients", "accounts", "apps", "logs", "activity", "diverge", "rollout")}
    kinds = {p["name"]: p["kind"] for c in config.get("client", []) for p in c.get("provider", [])}
    for client in config.get("client", []):
        slug = client["slug"]
        data["clients"].append({"id": slug, "name": client.get("name") or slug, "hosting": live.hosting_text(client)})
        apps = {}
        for project in client.get("project", []):
            targets = [t for t in project.get("target", []) if kinds.get(t.get("provider")) != "github"]
            for target in targets:
                kind = kinds.get(target.get("provider"))
                name, env = live.split_env(target.get("resource_name"))
                name, env = (name, env) if env else (project["slug"], target.get("environment"))
                if not env:
                    continue
                app = apps.setdefault(name, {"id": name, "client": slug, "name": name, "type": _app_type(project, kind), "envs": {}, "source": "config", "project": project["slug"]})
                app["envs"][env] = _env_row(live.PLATFORM_NAMES.get(kind, "Sem leitura"))
            if not targets:
                app = apps.setdefault(project["slug"], {"id": project["slug"], "client": slug, "name": project["slug"], "type": _app_type(project, None), "envs": {}, "source": "config", "project": project["slug"]})
                for env in project.get("environments", []):
                    app["envs"][env] = _env_row("Sem leitura")
        for app in apps.values():
            app["ready"] = {"conta": "todo", "segredos": "todo", "host": "todo", "logs": "na" if app["type"] == "db-coolify" else "todo"}
        data["apps"] += apps.values()
        usable = [p for p in client.get("provider", []) if p["kind"] in live.ACCOUNT_KINDS and not p["name"].endswith(("-read", "-local", "-sim"))]
        for provider in usable:
            serves = sorted({p["slug"] for p in client.get("project", []) for t in p.get("target", []) if t.get("provider") == provider["name"]})
            data["accounts"].append({"id": f"{slug}-{provider['name']}", "client": slug, "provider": provider["kind"], "name": provider["name"],
                                     "label": f"Conta {provider['name']}", "state": "unread", "expires": NO_VAULT, "tested": "Sem leitura",
                                     "fields": [], "fieldsRead": False, "serves": serves, "source": "config"})
        data["rollout"][slug] = [
            {"id": "declarado", "title": "Cliente e projetos declarados", "state": "ok" if client.get("project") else "todo", "source": "config",
             "hint": "" if client.get("project") else "Este cliente ainda não tem projetos."},
            {"id": "cofre", "title": "Cofre conectado", "state": "todo", "source": "config", "hint": "Com o cofre, esta tela passa a mostrar o estado real.", "to": "#/configurar/maquina#cofre", "toLabel": "Ver como conectar"},
        ]
    return data

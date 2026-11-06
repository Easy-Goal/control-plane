"""Cliente novo (fase 3, ADR 067): valida o pedido do assistente e gera openbao/clients/<cliente>.toml.

É o único gerador desse arquivo: a prévia da tela e a gravação usam a mesma função. O arquivo tem só nomes, nenhum valor.
"""
import json
import os
import re

try:
    import tomllib
except ImportError:
    tomllib = None

SLUG = re.compile(r"[a-z][a-z0-9]{1,30}")  # sem hífen: o nome da org de logs é <cliente>_<ambiente>
PROJECT = re.compile(r"[a-z][a-z0-9-]{0,50}[a-z0-9]")
KEY = re.compile(r"[A-Z][A-Z0-9_]{1,62}")
TYPES = {"front-vercel": "vercel", "api-railway": "railway", "api-coolify": "coolify", "db-coolify": "coolify"}
PLATFORMS = ("vercel", "railway", "github", "coolify", "droplet")
ENVS = ("dev", "staging", "prod")
RESERVED = {"easygoal", "default", "meta", "root", "admin"}
OBS_KEYS = ["OBS_OTLP_ENDPOINT", "OBS_OTLP_AUTHORIZATION", "OBS_SERVICE", "OBS_ENV", "OBS_IP_SALT"]
NODE_ENV = {"dev": "development", "staging": "production", "prod": "production"}
MARK = "# Gerado pelo painel do control plane (ADR 067). Só nomes, nenhum valor."


class SpecError(Exception):
    pass


def validate(spec, existing=()):
    """Devolve o pedido normalizado. Nada fora daqui chega ao arquivo."""
    if not isinstance(spec, dict):
        raise SpecError("Pedido inválido.")
    name = spec.get("name")
    if not isinstance(name, str) or not 2 <= len(name.strip()) <= 60 or not name.isprintable():
        raise SpecError("Informe o nome do cliente, com 2 a 60 caracteres.")
    slug = spec.get("slug")
    if not isinstance(slug, str) or not SLUG.fullmatch(slug):
        raise SpecError("O identificador precisa ter só letras minúsculas e números, começando por letra.")
    if slug in RESERVED or slug in existing:
        raise SpecError("Já existe um cliente com esse identificador.")
    platforms = spec.get("platforms")
    if not isinstance(platforms, list) or not set(platforms) <= set(PLATFORMS) or len(set(platforms)) != len(platforms):
        raise SpecError("Plataforma desconhecida.")
    if not set(platforms) & {"vercel", "railway", "coolify"}:
        raise SpecError("Escolha ao menos uma plataforma de hospedagem.")
    if "droplet" in platforms and "coolify" not in platforms:
        raise SpecError("O Droplet é operado pelo Coolify: marque o Coolify também.")
    variables = spec.get("variables", [])
    if not isinstance(variables, list) or len(variables) > 80:
        raise SpecError("Lista de variáveis inválida.")
    seen, clean_vars = {"NODE_ENV"}, []
    for var in variables:
        key = var.get("name") if isinstance(var, dict) else None
        if not isinstance(key, str) or not KEY.fullmatch(key):
            raise SpecError("Variável com nome inválido: use letras maiúsculas, números e sublinhado.")
        if key in seen or key.startswith("NEXT_PUBLIC_") and var.get("origin") == "generated":
            raise SpecError(f"Variável {key} repetida ou não pode ser gerada.")
        seen.add(key)
        clean_vars.append({"name": key, "origin": "generated" if var.get("origin") == "generated" else "manual"})
    projects = spec.get("projects")
    if not isinstance(projects, list) or not 1 <= len(projects) <= 30:
        raise SpecError("Escolha ao menos um projeto.")
    clean_projects, names = [], set()
    for project in projects:
        if not isinstance(project, dict) or not isinstance(project.get("slug"), str) or not PROJECT.fullmatch(project["slug"]):
            raise SpecError("Projeto com nome inválido: use letras minúsculas, números e hífen.")
        if project["slug"] in names:
            raise SpecError(f"Projeto {project['slug']} repetido.")
        names.add(project["slug"])
        kind = project.get("type")
        if kind not in TYPES or TYPES[kind] not in platforms:
            raise SpecError(f"O projeto {project['slug']} usa uma plataforma que não foi escolhida.")
        envs = project.get("environments", ["dev", "prod"])
        if not isinstance(envs, list) or not envs or not set(envs) <= set(ENVS):
            raise SpecError(f"Ambientes inválidos em {project['slug']}.")
        clean_projects.append({"slug": project["slug"], "type": kind, "environments": [e for e in ENVS if e in envs]})
    return {"name": name.strip(), "slug": slug, "platforms": [p for p in PLATFORMS if p in platforms], "variables": clean_vars,
            "projects": clean_projects, "logs": spec.get("logs") is True, "analytics": spec.get("analytics") is True}


def q(value):
    return json.dumps(value, ensure_ascii=False)


def render(spec):
    lines = [MARK, "", "[[client]]", f"slug = {q(spec['slug'])}", f"name = {q(spec['name'])}"]
    for platform in spec["platforms"]:
        if platform == "droplet":  # sem token: entra como servidor do time no Coolify
            continue
        lines += ["", "[[client.provider]]", f"name = {q(platform)}", f"kind = {q(platform)}"]
        if platform == "coolify":
            lines += ["", "[[client.provider]]", 'name = "coolify-read"  # só leitura, para o painel', 'kind = "coolify"']
    generated = [v["name"] for v in spec["variables"] if v["origin"] == "generated"]
    keys = ["NODE_ENV", *[v["name"] for v in spec["variables"]]]
    for project in spec["projects"]:
        kind = project["type"]
        has_app = kind != "db-coolify"
        lines += ["", "[[client.project]]", f"slug = {q(project['slug'])}", f"environments = {q(project['environments'])}", f"type = {q(kind)}"]
        if has_app:
            lines += [f"generate = {q(generated)}", f"logs = {q(spec['logs'])}"]
        if kind == "api-railway":
            lines += ["# Faltam os ids: rode cp-secrets discover e acrescente o [[client.project.target]] de cada ambiente.", "railway_pending = true"]
            continue
        if not has_app:
            continue
        target_keys = keys + (OBS_KEYS if spec["logs"] else [])
        for env in project["environments"]:
            name = f"{project['slug']}-{env}"
            lines += ["", "[[client.project.target]]", f"name = {q(name)}", f"provider = {q(TYPES[kind])}", f"environment = {q(env)}"]
            if kind == "api-coolify":
                lines += ['resource = "service"', f"resource_name = {q(name)}"]
            else:
                lines += [f"project = {q(project['slug'])}", f"vercel_targets = {q(['production'] if env == 'prod' else ['preview'])}"]
            lines.append(f"keys = {q(target_keys)}")
    text = "\n".join(lines) + "\n"
    if tomllib:
        parsed = tomllib.loads(text)["client"][0]
        if parsed["slug"] != spec["slug"] or parsed["name"] != spec["name"]:  # o arquivo precisa dizer o que foi pedido
            raise SpecError("Não foi possível gerar o arquivo.")
    return text


def write(clients_dir, spec):
    """Só cria: nunca sobrescreve um arquivo de cliente."""
    text = render(spec)
    clients_dir.mkdir(parents=True, exist_ok=True)
    path = clients_dir / f"{spec['slug']}.toml"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        raise SpecError("Já existe um arquivo para esse cliente.") from None
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write(text)
    return path


def prepare_steps(client, obs_provider=None):
    """O que dá para fazer sem você: snapshot, identidades, segredos internos e logs. Tudo idempotente."""
    slug = client["slug"]
    steps = [
        {"label": "Snapshot do cofre", "argv": ["cp-secrets", "backup"]},
        {"label": "Criar policies e identidades", "argv": ["cp-secrets", "apply", "--client", slug]},
    ]
    logs = False
    for project in client.get("project", []):
        if not project.get("generate") and project.get("type") == "db-coolify":
            continue
        for env in project["environments"]:
            path = f"{slug}/{project['slug']}/{env}"
            steps.append({"label": f"Segredos internos de {path}", "argv": ["cp-secrets", "secret", "set", path, "NODE_ENV", "--stdin", "--if-missing"], "input": NODE_ENV[env]})
            steps += [{"argv": ["cp-secrets", "secret", "gen", path, key, "--if-missing"]} for key in project.get("generate", [])]
            if project.get("logs") and obs_provider:
                logs = True
                steps.append({"label": f"Logs de {path}", "argv": ["cp-obs", "ingest", path], "env": {"CP_OBS_PROVIDER": obs_provider}})
    if logs:
        steps.append({"label": "Liberar a leitura dos logs no painel", "argv": ["cp-obs", "panel-read"], "env": {"CP_OBS_PROVIDER": obs_provider}})
    return steps

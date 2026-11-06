#!/usr/bin/env python3
"""cplane: o único comando do control plane, igual em todo sistema.

  cplane                      abre o painel no navegador
  cplane --port 4701          abre em outra porta
  cplane --sem-navegador      só mostra o link (SSH, VPS)
  cplane doctor               confere esta máquina e diz como resolver o que faltar
  cplane import <origem>      traz a conta: repositório git privado ou arquivo gerado pelo export
  cplane import               atualiza a conta já importada de um repositório
  cplane export [arquivo]     gera um arquivo com a configuração, só nomes e nenhum valor
  cplane machine              mostra id, nome e papel desta máquina
  cplane machine role <papel> lab ou teste
  cplane machine promote      torna esta máquina a principal da conta (--substituir, se já houver outra)
  cplane account create       cria usuário, senha e autenticador do acesso remoto (só no terminal)
  cplane account status       mostra se a conta existe e quantos códigos de recuperação restam
  cplane account reset        troca senha e autenticador, derrubando as sessões
  cplane devices              lista dispositivos e pedidos aguardando
  cplane devices approve <código> --classe <operacao|consulta|lab>
  cplane devices class <id> <classe>
  cplane devices revoke <id>  corta o acesso na hora
  cplane connect <endereço>   registra esta instalação na principal
  cplane connect --status     mostra se a principal já aprovou
  cplane --remoto             aceita outras máquinas, com aprovação e login, atrás do tailscale serve
  cplane --cofre              abre o painel conectado ao cofre desta máquina
  cplane vault up             sobe o cofre desta máquina (precisa de Docker)
  cplane secrets ...          segredos no cofre
  cplane obs ...              logs e analytics
  cplane coolify ...          deploy pelo Coolify
  cplane lab <comando> ...    o mesmo, contra o laboratório (só no repositório)
  cplane version              versão instalada
  cplane update <pacote>      instala outra versão, sem mexer nos dados
  cplane rollback             volta para a versão anterior
  cplane uninstall            remove o programa e mantém os dados (--dados também apaga os dados)
"""
import io
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "panel"))

import cp_config  # noqa: E402
import cp_install  # noqa: E402
import cp_paths  # noqa: E402
import cp_toml  # noqa: E402

TOOLS = {"secrets": "cp-secrets", "obs": "cp-obs", "coolify": "cp-coolify"}
# Conta importada é só nomes. Um arquivo destes em um repositório de configuração é um erro a ser corrigido na origem.
FORBIDDEN_FILES = (".env", ".env.*", ".init.json", ".bootstrap.env", "*.pem", "*.key", "*.snap", "*.snapshot", "*.p12")
ALLOWED_ENV = (".env.example",)
SECRET_SHAPES = re.compile(
    r"ghp_[A-Za-z0-9]{20,}|github_pat_\w{20,}|-----BEGIN [A-Z ]*PRIVATE KEY|hvs\.[A-Za-z0-9_-]{20,}|sk_(?:live|test)_\w{10,}|APP_USR-[\w-]{10,}|"
    r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}|postgres(?:ql)?://[^\s\"'<:]+:[^\s\"'<@]+@"
)
GIT_ORIGIN = re.compile(r"(?:ssh://|https://|git@)\S+")


def die(text):
    sys.exit(text)


def layout():
    return cp_paths.Layout()


def version():
    try:
        return (HERE.parent / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "repositório"


def run_tool(script, args, extra_env=None):
    path = HERE / script
    if not path.exists():
        die(f"Este pacote não traz {script}.")
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1", **(extra_env or {})}
    return subprocess.call([sys.executable, str(path), *args], env=env)


def cmd_panel(args):
    import server
    out = list(args)
    if "--sem-navegador" in out:
        out.remove("--sem-navegador")
    else:
        out.append("--abrir")
    server.main(out)
    return 0


def cmd_doctor(_args):
    rows = cp_install.checks()
    current = layout()
    print(f"Control plane {version()} em {cp_paths.os_kind()}\n")
    cp_install.print_checks(rows)
    on_path = cp_install.launcher_path().parent
    if (HERE.parent / "VERSION").exists() and not (HERE.parent / ".git").exists() and not cp_install._on_path(on_path):
        print(f"  [atenção] Comando cplane: fora do PATH ({on_path})")
        fix = "Abra um terminal novo." if cp_install.is_windows() else f'Acrescente ao início do shell: export PATH="{on_path}:$PATH"'
        print(f"      Como resolver: {fix}")
    print(f"\n  Dados: {current.home}")
    has_config = current.main_toml.exists()
    print(f"  Conta: {'importada ou criada' if has_config else 'nenhuma ainda. Abra o painel para começar.'}")
    return 1 if any(r[1] == "fail" for r in rows) else 0


def _is_forbidden(name):
    import fnmatch
    return name not in ALLOWED_ENV and any(fnmatch.fnmatchcase(name, pattern) for pattern in FORBIDDEN_FILES)


def validate_config(folder):
    """Recusa o que não deveria estar em uma configuração. A mensagem cita o arquivo, nunca o conteúdo."""
    problems = []
    for path in folder.rglob("*"):
        if ".git" in path.relative_to(folder).parts or not path.is_file():
            continue
        relative = path.relative_to(folder).as_posix()
        if _is_forbidden(path.name):
            problems.append(f"{relative}: este tipo de arquivo não pode ficar na configuração")
            continue
        try:
            if path.stat().st_size < 2_000_000 and SECRET_SHAPES.search(path.read_text(encoding="utf-8", errors="ignore")):
                problems.append(f"{relative}: parece conter um valor de segredo")
        except OSError:
            problems.append(f"{relative}: não foi possível ler")
    if problems:
        die("Importação recusada. Corrija na origem e tente de novo:\n  " + "\n  ".join(problems))
    main = folder / "secrets.toml"
    if not main.exists() and not (folder / "workspace.toml").exists():
        die("Essa origem não tem uma configuração do control plane: faltam workspace.toml e secrets.toml. Se o repositório estiver vazio, rode cplane export em uma máquina que já tenha a conta.")
    if not main.exists():
        main.write_text("# Clientes declarados aqui ou em clients/<cliente>.toml. Só nomes, nenhum valor.\n", encoding="utf-8")
    try:
        return cp_config.load(main, folder / "clients")
    except (ValueError, KeyError, cp_config.ConfigError) as err:
        die(f"A configuração não pôde ser lida: {err}")


def _is_git_path(parts):
    """Inclui as grafias que o Windows trata como a mesma pasta: .GIT, ".git ." e o nome curto git~1."""
    return any(part.casefold().rstrip(" .") in (".git", "git~1") for part in parts)


def _extract_config(source, target, only_config=True):
    """Só arquivos comuns. Uma pasta .git vinda de arquivo faria o próximo git executar o que ela configurar."""
    with tarfile.open(fileobj=source, mode="r:*") as tar:
        for member in tar.getmembers():
            parts = member.name.split("/")
            if _is_git_path(parts):
                die(f"Arquivo recusado: {member.name} não pode vir em uma conta.")
            if member.isdir():
                continue
            allowed = not only_config or parts[-1] == ".gitkeep" or parts[-1].endswith((".toml", ".md"))
            if not member.isfile() or member.name.startswith("/") or "\\" in member.name or ".." in parts or ":" in member.name or not allowed:
                die(f"Arquivo recusado: {member.name} não é permitido.")
            dest = target / member.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(member) as source, open(dest, "wb") as out:
                shutil.copyfileobj(source, out)


# Mesmo com .git escrita só por clone nosso, nada de gancho ou programa configurado no repositório roda nesta conta.
GIT_SAFE = ("-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false")


def _update_from_git(current):
    """Baixa, valida uma cópia do que chegou e só então avança a conta. Recusada, ela fica como estava."""
    if _git(*GIT_SAFE, "fetch", "origin", cwd=current.config_dir) != 0:
        die("Não foi possível atualizar a conta. Veja a mensagem do git acima.")
    upstream = "@{upstream}"
    packed = subprocess.run(["git", *GIT_SAFE, "archive", "--format=tar", upstream], cwd=current.config_dir, capture_output=True)
    if packed.returncode != 0:
        die("Não foi possível ler o que veio do repositório.")
    with tempfile.TemporaryDirectory(dir=current.home, prefix=".conferindo-") as temp:
        _extract_config(io.BytesIO(packed.stdout), Path(temp), only_config=False)
        config = validate_config(Path(temp))
    if _git(*GIT_SAFE, "merge", "--ff-only", upstream, cwd=current.config_dir) != 0:
        die("A conta nesta máquina tem mudanças que o repositório não tem. Resolva na pasta da configuração e rode de novo.")
    return config


def _git(*args, cwd=None):
    if not shutil.which("git"):
        die(f"Importar de um repositório precisa do git.\n  Como resolver: {cp_install._package_manager_hint('Git.Git' if cp_install.is_windows() else 'git')}")
    # Sem transporte que execute comando vindo da URL.
    return subprocess.run(["git", "-c", "protocol.ext.allow=never", "-c", "protocol.fd.allow=never", *args], cwd=cwd).returncode


def _finish_import(current, config):
    import workspace
    machine = workspace.write_machine(current, mode="real")
    clients = config.get("client", [])
    projects = sum(len(c.get("project", [])) for c in clients)
    print(f"Conta importada: {len(clients)} cliente(s) e {projects} projeto(s). Só nomes: nenhum valor veio junto.")
    print(f"Esta máquina: {machine['name']} ({machine['id']})")
    print("Próximo passo: abra o painel com cplane e diga o que é esta máquina." if not machine.get("role") else "Abra o painel com cplane.")


def cmd_import(args):
    current = layout()
    if current.legacy:
        die("Esta pasta usa o layout antigo, com a configuração em openbao/. Use uma instalação para importar.")
    replace = "--substituir" in args
    args = [a for a in args if a != "--substituir"]
    if not args:
        if not (current.config_dir / ".git").exists():
            die("Informe a origem: cplane import <repositório ou arquivo>")
        _finish_import(current, _update_from_git(current))
        return 0
    origin = args[0]
    if current.config_dir.exists() and any(current.config_dir.iterdir()) and not replace:
        die(f"Esta máquina já tem uma conta em {current.config_dir}. Para trocar, rode de novo com --substituir: a atual é guardada ao lado.")
    current.home.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=current.home, prefix=".importando-") as temp:
        fresh = Path(temp) / "config"
        as_file = Path(origin).expanduser()
        if as_file.is_file():
            if not tarfile.is_tarfile(as_file):
                die("Esse arquivo não foi gerado pelo cplane export.")
            fresh.mkdir()
            with open(as_file, "rb") as source:
                _extract_config(source, fresh)
        elif GIT_ORIGIN.fullmatch(origin) or as_file.is_dir():
            # Destino relativo: git estilo Cygwin (MobaXterm, por exemplo) não entende C:\\... como caminho.
            if _git("clone", "--", origin if not as_file.is_dir() else str(as_file.resolve()), "config", cwd=temp) != 0:
                die("Não foi possível baixar esse repositório. Confira o endereço e seu acesso a ele. Para testar a chave: ssh -T git@github.com")
        else:
            die("Origem não reconhecida. Use um endereço git (git@..., https://...) ou o arquivo gerado pelo cplane export.")
        config = validate_config(fresh)
        if current.config_dir.exists() and any(current.config_dir.iterdir()):
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            os.replace(current.config_dir, current.home / f"config.antes-{stamp}")
        elif current.config_dir.exists():
            current.config_dir.rmdir()
        os.replace(fresh, current.config_dir)
    _finish_import(current, config)
    return 0


def cmd_export(args):
    current = layout()
    if not current.main_toml.exists():
        die("Esta máquina ainda não tem conta para exportar.")
    target = Path(args[0]).expanduser() if args else Path.cwd() / f"control-plane-conta-{datetime.now(timezone.utc).strftime('%Y%m%d')}.tar.gz"
    if target.exists():
        die(f"{target} já existe. Informe outro nome.")
    sources = {"secrets.toml": current.main_toml, "workspace.toml": current.workspace_file, "secrets.draft.toml": current.draft_toml}
    if current.clients_dir.is_dir():
        sources.update({f"clients/{p.name}": p for p in sorted(current.clients_dir.glob("*.toml"))})
    with tarfile.open(target, "w:gz") as tar:
        for name, path in sources.items():
            if path.exists():
                tar.add(path, arcname=name, recursive=False)
    print(f"{target}\nSó nomes e estrutura. Valores e chaves de unseal não entram neste arquivo.")
    return 0


def cmd_machine(args):
    import workspace
    current = layout()
    if not args:
        machine = workspace.read_machine(current)
        if not machine:
            print("Esta máquina ainda não foi configurada. Abra o painel com cplane.")
            return 0
        print(f"Id: {machine.get('id')}\nNome: {machine.get('name')}\nPapel: {workspace.ROLES.get(machine.get('role'), 'não definido')}")
        return 0
    if args[0] == "role" and len(args) == 2:
        if args[1] not in workspace.PANEL_ROLES:
            die("Papéis: lab ou teste. Para a principal: cplane machine promote")
        if workspace.read_machine(current).get("role") == "principal":
            workspace.clear_principal(current)
            print("Esta máquina deixou de ser a principal da conta. Publique a mudança no repositório da configuração, se houver.")
        workspace.write_machine(current, role=args[1])
        print(f"Papel: {workspace.ROLES[args[1]]}")
        return 0
    if args and args[0] == "promote":
        return _promote(current, args[1:])
    die("Uso: cplane machine | cplane machine role <lab|teste> | cplane machine promote")


def _principal_upstream(current):
    """Outra máquina pode ter sido promovida e publicado: o que vale é a última versão do repositório, não só a cópia daqui."""
    if not (current.config_dir / ".git").exists() or not shutil.which("git"):
        return {}
    if _git(*GIT_SAFE, "fetch", "origin", cwd=current.config_dir) != 0:
        die("Não foi possível conferir o repositório da conta. Sem isso, duas máquinas poderiam virar principal.")
    shown = subprocess.run(["git", *GIT_SAFE, "show", "@{upstream}:workspace.toml"], cwd=current.config_dir, capture_output=True, text=True, encoding="utf-8")
    if shown.returncode != 0:
        return {}
    try:
        return cp_toml.tomllib.loads(shown.stdout).get("principal", {})
    except ValueError:
        return {}


def _promote(current, args):
    import workspace
    if current.legacy:
        die("Esta pasta usa o layout antigo. Promova uma instalação.")
    if not current.main_toml.exists():
        die("Esta máquina ainda não tem conta. Importe a conta antes de promover.")
    machine = workspace.write_machine(current)
    known = [workspace.principal(current), _principal_upstream(current)]
    other = next((p for p in known if p.get("id") and p["id"] != machine["id"]), None)
    if other and "--substituir" not in args:
        die(f"A conta já tem uma principal: {other.get('name')} ({other.get('id')}). Só pode existir uma.\nPara trocar de máquina, rode de novo com --substituir e desligue a anterior.")
    print("A principal guarda o cofre e controla a conta inteira. Deve existir uma só, normalmente a VPS.")
    if not sys.stdin.isatty() or input("Digite principal para confirmar: ").strip() != "principal":
        die("Nada mudou.")
    workspace.write_machine(current, role="principal")
    workspace.set_principal(current, machine)
    print(f"Esta máquina agora é a principal: {machine['name']} ({machine['id']}).")
    if (current.config_dir / ".git").exists():
        print(f'Publique, para as outras máquinas saberem:\n  git -C "{current.config_dir}" add workspace.toml\n  git -C "{current.config_dir}" commit -m "Principal: {machine["name"]}"\n  git -C "{current.config_dir}" push')
    print("Para abrir o acesso remoto: cplane account create, depois cplane --remoto")
    return 0


def _store():
    import auth
    return auth, auth.Store(layout().state_dir)


def cmd_account(args):
    auth, store = _store()
    action = args[0] if args else "status"
    if action == "status":
        view = auth.machines_view(store)["account"]
        if not view["exists"]:
            print("Conta de acesso: nenhuma. Crie com cplane account create")
            return 0
        print(f"Usuário: {view['username']}\nCódigos de recuperação restantes: {view['recovery_left']}\nBloqueada por tentativas: {'sim' if view['locked'] else 'não'}")
        return 0
    if action not in ("create", "reset"):
        die("Uso: cplane account <create|status|reset>")
    if not sys.stdin.isatty():
        die("Crie a conta em um terminal interativo: a senha nunca passa por argumento ou arquivo.")
    if action == "reset" and input("Isto troca senha e autenticador e derruba todas as sessões. Digite redefinir para confirmar: ").strip() != "redefinir":
        die("Nada mudou.")
    import getpass
    username = input("Usuário: ").strip()
    password = getpass.getpass(f"Senha (ao menos {auth.MIN_PASSWORD} caracteres): ")
    if password != getpass.getpass("Repita a senha: "):
        die("As senhas são diferentes. Nada mudou.")
    return _finish_account(auth, store, username, password, action == "reset")


def _finish_account(auth, store, username, password, replace):
    """Só grava depois de o autenticador responder: interromper aqui não deixa conta que ninguém consegue usar."""
    try:
        auth.validate_credentials(username, password)
        if store.load()["account"] and not replace:
            die("Já existe uma conta de acesso. Para trocar: cplane account reset")
    except auth.AuthError as err:
        die(str(err))
    secret = auth.new_totp_secret()
    account_name = cp_paths.read_workspace(layout()).get("name") or "Control Plane"
    print(f"\nCadastre no seu autenticador:\n  Segredo: {secret}\n  Endereço: {auth.otpauth_uri(secret, username, account_name)}\n")
    for _ in range(3):
        typed = input("Digite o código de 6 dígitos que ele mostra agora: ").strip()
        moment = time.time()
        if typed in {auth.totp(secret, moment + delta) for delta in (-auth.STEP, 0, auth.STEP)}:
            break
        print("O código não bateu. Confira o relógio da máquina e o cadastro.")
    else:
        die("Nada foi gravado. Rode de novo quando o autenticador estiver certo.")
    try:
        _, recovery = auth.create_account(store, username, password, replace=replace, secret=secret)
    except auth.AuthError as err:
        die(str(err))
    print("\nCódigos de recuperação, cada um vale uma vez. Guarde no seu gerenciador de senhas, fora desta máquina:")
    for code in recovery:
        print(f"  {code}")
    print("\nConta de acesso criada. Eles não serão mostrados de novo.")
    return 0


def cmd_devices(args):
    auth, store = _store()
    if not args:
        view = auth.machines_view(store)
        if not view["devices"]:
            print("Nenhum dispositivo ainda.")
        for d in view["devices"]:
            state = {"pending": "AGUARDANDO", "approved": auth.CLASSES.get(d.get("class"), ""), "revoked": "REVOGADO"}[d["state"]]
            node = (d.get("node") or {}).get("name") or "sem identificação da tailnet"
            print(f"{d['id']}  {state:<12} {d['name']}  ({node})  último acesso: {d.get('last_seen') or 'nunca'}")
        return 0
    who = "terminal da principal"
    try:
        if args[0] == "approve" and len(args) == 4 and args[2] == "--classe":
            device = auth.approve_device(store, args[1], args[3], who)
            print(f"Aprovado: {device['name']} como {auth.CLASSES[device['class']]}.")
            return 0
        if args[0] == "revoke" and len(args) == 2:
            auth.revoke_device(store, args[1], who)
            print("Acesso cortado.")
            return 0
        if args[0] == "class" and len(args) == 3:
            auth.set_class(store, args[1], args[2], who)
            print(f"Classe: {auth.CLASSES[args[2]]}.")
            return 0
    except auth.AuthError as err:
        die(str(err))
    die("Uso: cplane devices | cplane devices approve <código> --classe <operacao|consulta|lab> | cplane devices class <id> <classe> | cplane devices revoke <id>")


def cmd_connect(args):
    """Registra esta instalação. Guarda o token ao lado dos dados, com permissão só do dono."""
    import json
    import urllib.error
    import urllib.request
    import workspace
    current = layout()
    remote_file = current.home / "remote.json"
    def call(url, path, token=None, body=None):
        req = urllib.request.Request(url.rstrip("/") + path, data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json", "User-Agent": f"cplane/{version()}"})
        if token:
            req.add_header("Cookie", f"cp_device={token}")
        try:
            with urllib.request.urlopen(req, timeout=15) as res:
                return res.status, json.loads(res.read()), res.headers.get("Set-Cookie", "")
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read() or b"{}"), ""
        except (OSError, ValueError) as err:
            die(f"A principal não respondeu: {err}. Confira o endereço e a tailnet.")
    if args == ["--status"]:
        if not remote_file.exists():
            die("Esta instalação ainda não foi registrada: cplane connect <endereço>")
        saved = json.loads(remote_file.read_text(encoding="utf-8"))
        _, out, _ = call(saved["url"], "/api/auth/state", saved["token"])
        print({"pending": f"Aguardando aprovação. Código: {out.get('code')}", "registered": "Aprovada na principal.", "revoked": "Acesso revogado na principal."}.get(out.get("state"), f"Estado: {out.get('state')}"))
        return 0
    if len(args) != 1:
        die("Uso: cplane connect <endereço> | cplane connect --status")
    url = args[0]
    if not re.fullmatch(r"https://[A-Za-z0-9.-]+(:\d+)?/?|http://(127\.0\.0\.1|localhost):\d+/?", url):
        die("Use o endereço https da principal na tailnet, como https://cp.sua-rede.ts.net")
    if remote_file.exists():
        die(f"Esta instalação já está registrada. Para refazer, apague {remote_file}.")
    machine = workspace.write_machine(current)
    status, out, cookie = call(url, "/api/auth/request", body={"kind": "install", "name": machine["name"], "instance": {"id": machine["id"], "role": machine.get("role", ""), "os": cp_paths.os_kind()}})
    if status != 200:
        die(out.get("error") or f"A principal recusou o pedido ({status}).")
    token = re.search(r"cp_device=([^;]+)", cookie)
    if not token:
        die("A principal não entregou o registro.")
    fd = os.open(remote_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as saved:
        json.dump({"url": url, "token": token.group(1)}, saved)
    print(f"Pedido enviado. Na principal, aprove com:\n  cplane devices approve {out['code']} --classe lab\nDepois, confira: cplane connect --status")
    return 0


def cmd_vault(args):
    if args != ["up"]:
        die("Uso: cplane vault up")
    if not shutil.which("docker"):
        fix = next(row[3] for row in cp_install.checks() if row[0] == "Docker")
        die(f"O cofre roda em um contêiner e falta o Docker.\n  Como resolver: {fix}")
    # O projeto do compose é fixo no arquivo: em outro projeto, o volume mudaria de nome e o cofre pareceria vazio.
    project = ["-p", os.environ["CP_VAULT_PROJECT"]] if os.environ.get("CP_VAULT_PROJECT") else []
    code = subprocess.call(["docker", "compose", "--project-directory", str(layout().compose_dir), *project, "up", "-d", "--wait"])
    if code != 0:
        die("O cofre não subiu. Veja a mensagem do Docker acima. Docker Desktop: confira se está ligado.")
    print("Cofre no ar.\n  Primeira vez: cplane secrets init\n  Depois de reiniciar: cplane secrets unseal\n  Para ver no painel: cplane --cofre")
    return 0


def cmd_lab(args):
    if not args:
        die("Uso: cplane lab <panel|secrets|obs|coolify> ...")
    if not (HERE.parent / "sim").is_dir():
        die("O laboratório existe só no repositório, não no pacote instalado.")
    env = {"CP_BAO_ADDR": "https://127.0.0.1:8210", "CP_BAO_CACERT": str(layout().vault_dir / "tls" / "sim-ca.crt")}
    if args[0] == "panel":
        os.environ.update(env)
        return cmd_panel(args[1:])
    if args[0] not in TOOLS:
        die("Uso: cplane lab <panel|secrets|obs|coolify> ...")
    return run_tool(TOOLS[args[0]], args[1:], env)


def cmd_update(args):
    if len(args) != 1:
        die("Uso: cplane update <pacote .tar.gz>. O SHA256SUMS precisa estar ao lado dele.")
    # Roda o instalador do pacote novo só depois de conferir: a verificação é feita pelo código já instalado.
    version_new, launcher = cp_install.install(package=Path(args[0]).expanduser().resolve())
    print(f"Versão {version_new} ativa. Os dados não mudaram. Para voltar: cplane rollback")
    return 0 if launcher else 1


def cmd_rollback(_args):
    root = cp_install.program_root()
    previous = root / "previous"
    if not previous.exists() or not (root / "versions" / previous.read_text(encoding="utf-8").strip()).is_dir():
        die("Não há versão anterior guardada.")
    target = previous.read_text(encoding="utf-8").strip()
    cp_install._set_pointer(root, target)
    print(f"Versão {target} ativa. Os dados não mudaram.")
    return 0


def cmd_uninstall(args):
    current = layout()
    if "--dados" in args:
        print(f"Isto apaga {current.home}: conta, registro da máquina e, se houver, credenciais do cofre nesta máquina.")
        if not sys.stdin.isatty() or input("Digite apagar para confirmar: ").strip() != "apagar":
            die("Nada foi apagado.")
        shutil.rmtree(current.home)
        print("Dados apagados.")
    else:
        print(f"Os dados continuam em {current.home}.")
    cp_install.uninstall_program()
    print("Programa removido.")
    return 0


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ("-h", "--help", "help"):
        print(__doc__.strip())
        return 0
    if not args or args[0].startswith("--"):
        return cmd_panel(args)
    name, rest = args[0], args[1:]
    if name in TOOLS:
        return run_tool(TOOLS[name], rest)
    commands = {"panel": cmd_panel, "doctor": cmd_doctor, "import": cmd_import, "export": cmd_export, "machine": cmd_machine, "lab": cmd_lab, "vault": cmd_vault, "account": cmd_account, "devices": cmd_devices, "connect": cmd_connect,
                "update": cmd_update, "rollback": cmd_rollback, "uninstall": cmd_uninstall}
    if name in ("version", "--version"):
        print(version())
        return 0
    if name not in commands:
        die(f"Comando desconhecido: {name}. Veja cplane help")
    return commands[name](rest)


if __name__ == "__main__":
    sys.exit(main())

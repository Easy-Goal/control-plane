"""Onde ficam o programa e os dados. É a única resposta para essa pergunta em scripts e painel.

Programa: pasta deste arquivo, substituída a cada atualização.
Dados: CP_HOME, ou a pasta padrão do sistema. Atualizar ou desinstalar não mexe neles.

Layout antigo: uma pasta com openbao/secrets.toml, como um clone do repositório, continua funcionando igual.
"""
import os
import platform
from pathlib import Path

import cp_toml

PROGRAM = Path(__file__).resolve().parent.parent


def default_home(env=None):
    env = os.environ if env is None else env
    if os.name == "nt":
        base = env.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "control-plane"
    return Path(env.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "control-plane"


class Layout:
    def __init__(self, program=PROGRAM, env=None):
        env = os.environ if env is None else env
        self.program = Path(program)
        chosen = env.get("CP_HOME")
        if chosen:
            self.home = Path(chosen).expanduser()
        elif (self.program / "openbao" / "secrets.toml").exists():
            self.home = self.program
        else:
            self.home = default_home(env)
        self.legacy = (self.home / "openbao" / "secrets.toml").exists()
        self.compose_dir = self.program / "openbao"
        self.machine_file = self.home / "machine.toml"
        if self.legacy:
            self.config_dir = self.home / "openbao"
            self.main_toml = self.config_dir / "secrets.toml"
            self.draft_toml = self.config_dir / "secrets.draft.toml"
            self.clients_dir = self.config_dir / "clients"
            self.workspace_file = self.home / "workspace.toml"
            self.vault_dir = self.config_dir
            self.state_dir = self.program / "panel" / "state"
        else:
            self.config_dir = self.home / "config"
            self.main_toml = self.config_dir / "secrets.toml"
            self.draft_toml = self.config_dir / "secrets.draft.toml"
            self.clients_dir = self.config_dir / "clients"
            self.workspace_file = self.config_dir / "workspace.toml"
            self.vault_dir = self.home / "vault"
            self.state_dir = self.home / "state"


def read_workspace(layout):
    try:
        return cp_toml.tomllib.loads(layout.workspace_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def home_client(layout=None):
    """Conta dona das ferramentas: nunca passa por offboard. Sem declaração, é o primeiro cliente do arquivo principal."""
    layout = layout or Layout()
    declared = read_workspace(layout).get("home_client")
    if declared:
        return declared
    try:
        clients = cp_toml.tomllib.loads(layout.main_toml.read_text(encoding="utf-8")).get("client", [])
    except (OSError, ValueError):
        return ""
    return clients[0].get("slug", "") if clients else ""


def os_kind():
    system = platform.system()
    if system == "Windows":
        return "windows"
    if system == "Darwin":
        return "macos"
    if system == "Linux":
        return "wsl" if "microsoft" in platform.release().lower() else "linux"
    return "unix"

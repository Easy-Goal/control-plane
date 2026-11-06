"""Testes da instalação, da conta e da primeira visita. Rodar: python3 -m unittest panel/test_install.py"""
import contextlib
import http.client
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "scripts"))

import cp_install  # noqa: E402
import cp_paths  # noqa: E402
import build_release  # noqa: E402
import cplane  # noqa: E402
import server  # noqa: E402
import workspace  # noqa: E402

SPEC = {"name": "Loja Teste", "slug": "lojateste", "platforms": ["vercel"], "variables": [], "logs": False, "analytics": False,
        "projects": [{"slug": "loja-web", "type": "front-vercel", "environments": ["dev", "prod"]}]}


def layout_in(folder):
    return cp_paths.Layout(program=Path(folder) / "programa", env={"CP_HOME": str(Path(folder) / "dados")})


class LayoutTest(unittest.TestCase):
    def test_dados_ficam_fora_do_programa(self):
        with tempfile.TemporaryDirectory() as temp:
            layout = layout_in(temp)
            self.assertFalse(layout.legacy)
            for path in (layout.main_toml, layout.clients_dir, layout.vault_dir, layout.state_dir, layout.machine_file):
                self.assertFalse(str(path).startswith(str(layout.program)))

    def test_layout_antigo_continua_igual(self):
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / "openbao").mkdir()
            (Path(temp) / "openbao" / "secrets.toml").write_text('[[client]]\nslug = "primeira"\n', encoding="utf-8")
            layout = cp_paths.Layout(program=temp, env={})
            self.assertTrue(layout.legacy)
            self.assertEqual(layout.vault_dir, Path(temp) / "openbao")
            self.assertEqual(cp_paths.home_client(layout), "primeira")

    def test_conta_principal_vem_da_configuracao(self):
        with tempfile.TemporaryDirectory() as temp:
            layout = layout_in(temp)
            layout.config_dir.mkdir(parents=True)
            layout.workspace_file.write_text('name = "Conta"\nhome_client = "minha"\n', encoding="utf-8")
            self.assertEqual(cp_paths.home_client(layout), "minha")


class SetupTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.layout = layout_in(self.temp.name)

    def status(self):
        return workspace.status(self.layout, "1.0")

    def test_primeira_visita_aparece_so_na_instalacao(self):
        self.assertTrue(self.status()["needs_setup"])

    def test_comecar_vazio_nao_tem_exemplo(self):
        workspace.apply(self.layout, {"action": "start", "mode": "empty", "name": "Minha Conta", "role": "teste"})
        st = self.status()
        self.assertEqual((st["needs_setup"], st["view"], st["account"], st["role_name"]), (False, "real", "Minha Conta", "Teste"))
        with mock.patch.object(server, "LAYOUT", self.layout):
            data = server.base_data()
        self.assertEqual(data["clients"], [])
        self.assertEqual(data["apps"], [])

    def test_exemplos_nao_gravam_conta_e_podem_sair(self):
        workspace.apply(self.layout, {"action": "start", "mode": "examples"})
        self.assertFalse(self.layout.main_toml.exists())
        self.assertEqual(self.status()["view"], "examples")
        with self.assertRaises(workspace.SetupError):
            workspace.apply(self.layout, {"action": "client", "spec": SPEC})
        workspace.apply(self.layout, {"action": "leave_examples"})
        self.assertTrue(self.status()["needs_setup"])

    def test_id_da_maquina_nao_muda(self):
        workspace.apply(self.layout, {"action": "start", "mode": "empty", "name": "Conta", "role": "teste"})
        first = self.status()["machine"]["id"]
        workspace.apply(self.layout, {"action": "role", "role": "lab"})
        self.assertEqual(self.status()["machine"]["id"], first)
        self.assertEqual(len(first), 16)

    def test_principal_nao_e_escolhida_pela_tela(self):
        workspace.apply(self.layout, {"action": "start", "mode": "empty", "name": "Conta", "role": "teste"})
        with self.assertRaises(workspace.SetupError):
            workspace.apply(self.layout, {"action": "role", "role": "principal"})

    def test_primeiro_cliente_vira_conta_principal_e_aparece_nao_lido(self):
        workspace.apply(self.layout, {"action": "start", "mode": "empty", "name": "Conta", "role": "teste"})
        workspace.apply(self.layout, {"action": "client", "spec": SPEC})
        self.assertEqual(self.status()["home_client"], "lojateste")
        with mock.patch.object(server, "LAYOUT", self.layout):
            data = server.base_data()
        self.assertEqual({a["source"] for a in data["apps"]}, {"config"})
        self.assertEqual({e["state"] for a in data["apps"] for e in a["envs"].values()}, {"unread"})
        self.assertEqual([c["id"] for c in data["clients"]], ["lojateste"])
        self.assertEqual(data["accounts"][0]["state"], "unread")

    def test_nome_invalido_e_recusado(self):
        for bad in ("", "x", "a\n[[client]]", None, 3):
            with self.assertRaises(workspace.SetupError):
                workspace.apply(self.layout, {"action": "start", "mode": "empty", "name": bad, "role": "teste"})

    def test_sonda_so_em_endereco_local(self):
        self.layout.config_dir.mkdir(parents=True)
        self.layout.workspace_file.write_text(
            '[[probe]]\nname = "Boa"\nurl = "http://127.0.0.1:3000/"\n[[probe]]\nname = "Fora"\nurl = "http://exemplo.com/"\n[[probe]]\nname = "Truque"\nurl = "http://127.0.0.1.exemplo.com/"\n',
            encoding="utf-8")
        self.assertEqual([p["name"] for p in workspace.probes(self.layout)], ["Boa"])


class SetupHttpTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.layout = layout_in(self.temp.name)
        patcher = mock.patch.object(server, "LAYOUT", self.layout)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.srv = server.make_server(0)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def post(self, body, key=None, **headers):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        payload = json.dumps(body).encode()
        base = {"Host": f"127.0.0.1:{self.port}", "Content-Type": "application/json", "X-CP-Key": server.SETUP_KEY if key is None else key, **headers}
        conn.request("POST", "/api/setup", payload, base)
        res = conn.getresponse()
        out = json.loads(res.read() or b"{}")
        conn.close()
        return res.status, out

    START = {"action": "start", "mode": "examples"}

    def test_com_a_chave_grava(self):
        self.assertEqual(self.post(self.START)[0], 200)
        self.assertEqual(workspace.read_machine(self.layout)["mode"], "examples")

    def test_sem_chave_ou_de_outra_origem_nao_grava(self):
        self.assertEqual(self.post(self.START, key="errada")[0], 403)
        self.assertEqual(self.post(self.START, key="")[0], 403)
        self.assertEqual(self.post(self.START, Origin="https://evil.example")[0], 403)
        self.assertEqual(self.post(self.START, **{"Sec-Fetch-Site": "cross-site"})[0], 403)
        self.assertEqual(self.post(self.START, Host="evil.example")[0], 403)
        self.assertEqual(self.post(self.START, **{"Content-Type": "text/plain"})[0], 415)
        self.assertFalse(self.layout.machine_file.exists())

    def test_importar_nao_existe_pela_tela(self):
        self.assertEqual(self.post({"action": "import", "origin": "ext::sh -c id"})[0], 400)

    def test_a_chave_nao_aparece_na_leitura(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        for path in ("/api/setup", "/api/device", "/api/data", "/"):
            conn.request("GET", path, headers={"Host": f"127.0.0.1:{self.port}"})
            self.assertNotIn(server.SETUP_KEY.encode(), conn.getresponse().read(), path)
        conn.close()


class ImportTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        patcher = mock.patch.dict(os.environ, {"CP_HOME": str(self.root / "dados")})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.origin = self.root / "origem"
        (self.origin / "clients").mkdir(parents=True)
        (self.origin / "workspace.toml").write_text('name = "Conta Real"\nhome_client = "minha"\n', encoding="utf-8")
        (self.origin / "secrets.toml").write_text('[[client]]\nslug = "minha"\nname = "Minha"\n', encoding="utf-8")
        (self.origin / "clients" / "outra.toml").write_text('[[client]]\nslug = "outra"\n', encoding="utf-8")

    def silent(self, func, *args):
        with contextlib.redirect_stdout(io.StringIO()):
            return func(*args)

    def pack(self, name="conta.tar.gz", extra=None):
        target = self.root / name
        with tarfile.open(target, "w:gz") as tar:
            for path in self.origin.rglob("*"):
                if path.is_file():
                    tar.add(path, arcname=path.relative_to(self.origin).as_posix())
            for member, data in (extra or {}).items():
                info = tarfile.TarInfo(member)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        return target

    def test_importa_arquivo_e_marca_como_real(self):
        self.silent(cplane.cmd_import, [str(self.pack())])
        layout = cp_paths.Layout(program=self.root / "programa")
        st = workspace.status(layout, "1")
        self.assertEqual((st["view"], st["needs_role"], st["account"], st["home_client"]), ("real", True, "Conta Real", "minha"))

    def test_nao_substitui_sem_pedir_e_guarda_a_anterior(self):
        self.silent(cplane.cmd_import, [str(self.pack())])
        with self.assertRaises(SystemExit):
            self.silent(cplane.cmd_import, [str(self.pack("b.tar.gz"))])
        self.silent(cplane.cmd_import, [str(self.pack("c.tar.gz")), "--substituir"])
        self.assertEqual(len(list((self.root / "dados").glob("config.antes-*"))), 1)

    def test_recusa_segredo_e_nao_mostra_o_valor(self):
        marker = "ghp_" + "a" * 30
        cases = {
            ".env": b"X=1",
            "backup.snap": b"x",
            "chave.pem": b"x",
            ".init.json": b"{}",
            "clients/x.toml": f'# {marker}\n[[client]]\nslug = "x"\n'.encode(),
        }
        for index, (name, content) in enumerate(cases.items()):
            with self.assertRaises(SystemExit) as caught:
                self.silent(cplane.cmd_import, [str(self.pack(f"r{index}.tar.gz", {name: content}))])
            self.assertIn(name, str(caught.exception))
            self.assertNotIn(marker, str(caught.exception))
        self.assertFalse((self.root / "dados" / "config").exists())

    def test_recusa_caminho_para_fora_e_link(self):
        for name in ("../fora.toml", "/abs.toml"):
            with self.assertRaises(SystemExit):
                self.silent(cplane.cmd_import, [str(self.pack("x.tar.gz", {name: b"x"}))])
            (self.root / "x.tar.gz").unlink()
        self.assertFalse((self.root / "fora.toml").exists())
        target = self.pack("l.tar.gz")
        with tarfile.open(target, "w:gz") as tar:
            info = tarfile.TarInfo("secrets.toml")
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            tar.addfile(info)
        with self.assertRaises(SystemExit):
            self.silent(cplane.cmd_import, [str(target)])

    def test_recusa_origem_que_executaria_comando(self):
        for origin in ("ext::sh -c id", "--upload-pack=x", "fd::3"):
            with self.assertRaises(SystemExit) as caught:
                self.silent(cplane.cmd_import, [origin])
            self.assertIn("não reconhecida", str(caught.exception))

    def test_export_so_leva_configuracao(self):
        self.silent(cplane.cmd_import, [str(self.pack())])
        layout = cp_paths.Layout(program=self.root / "programa")
        layout.vault_dir.mkdir(parents=True)
        (layout.vault_dir / ".bootstrap.env").write_text("X=1", encoding="utf-8")
        target = self.root / "saida.tar.gz"
        self.silent(cplane.cmd_export, [str(target)])
        with tarfile.open(target) as tar:
            self.assertEqual(sorted(tar.getnames()), ["clients/outra.toml", "secrets.toml", "workspace.toml"])


class ReleaseTest(unittest.TestCase):
    def test_pacote_e_limpo_e_nao_leva_interno(self):
        names = build_release.tracked()
        self.assertEqual(build_release.audit(names), [])
        for internal in ("sim", "install/", "panel/test_", "openbao/secrets", "scripts/build_release", "docs/go-live", "scripts/cp-lab"):
            self.assertFalse([n for n in names if n.startswith(internal)], internal)

    def test_auditoria_acha_nome_e_segredo(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(build_release, "ROOT", Path(temp)):
            (Path(temp) / "a.txt").write_text("cliente Vay" + "Go\nghp_" + "b" * 30 + "\n", encoding="utf-8")
            self.assertEqual(len(build_release.audit(["a.txt"])), 2)

    def test_lista_de_inclusao_barra_o_resto(self):
        self.assertTrue(cp_install.included("panel/web/app.js"))
        for name in ("panel/test_server.py", "openbao/secrets.toml", ".env", "scripts/__pycache__/x.pyc"):
            self.assertFalse(cp_install.included(name), name)


class InstallTest(unittest.TestCase):
    """De ponta a ponta: gera o pacote, instala em pastas temporárias e roda o comando instalado."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.dist = Path(cls.temp.name) / "dist"
        cls.dist.mkdir()
        names = build_release.tracked()
        build_release.build(names, "9.9.9", cls.dist)
        cls.package = cls.dist / "control-plane-9.9.9.tar.gz"
        (cls.dist / "SHA256SUMS").write_text(f"{cp_install.sha256(cls.package)}  {cls.package.name}\n", encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def env(self, folder):
        return {"CP_PROGRAM_ROOT": str(folder / "prog"), "CP_BIN_DIR": str(folder / "bin"), "CP_HOME": str(folder / "dados")}

    def test_pacote_alterado_e_recusado(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            bad = folder / self.package.name
            bad.write_bytes(self.package.read_bytes() + b"x")
            (folder / "SHA256SUMS").write_text((self.dist / "SHA256SUMS").read_text(encoding="utf-8"), encoding="utf-8")
            with self.assertRaises(SystemExit) as caught:
                cp_install.verify_package(bad)
            self.assertIn("não confere", str(caught.exception))

    def test_instala_atualiza_volta_e_preserva_dados(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            env = self.env(folder)
            version, launcher = cp_install.install(package=self.package, env=env)
            self.assertEqual(version, (cp_install.program_root(env) / "current").read_text(encoding="utf-8"))
            run = {**os.environ, **env}
            ran = subprocess.run([str(launcher), "version"], capture_output=True, text=True, env=run)
            self.assertEqual(ran.returncode, 0, ran.stderr)
            data = folder / "dados"
            data.mkdir()
            (data / "machine.toml").write_text('id = "fixo"\n', encoding="utf-8")
            again = cp_install.install(package=self.package, env=env)
            self.assertEqual(again[0], version)
            self.assertEqual((data / "machine.toml").read_text(encoding="utf-8"), 'id = "fixo"\n')
            self.assertFalse(list((folder / "prog").rglob("secrets.toml")))
            ran = subprocess.run([str(launcher), "doctor"], capture_output=True, text=True, env=run)
            self.assertIn("Python", ran.stdout)

    def test_extrair_recusa_arquivo_fora_da_lista(self):
        with tempfile.TemporaryDirectory() as temp:
            bad = Path(temp) / "x.tar.gz"
            with tarfile.open(bad, "w:gz") as tar:
                info = tarfile.TarInfo("top/scripts/maligno.py")
                info.size = 1
                tar.addfile(info, io.BytesIO(b"x"))
            with self.assertRaises(SystemExit):
                cp_install.extract_package(bad, Path(temp) / "alvo")


if __name__ == "__main__":
    unittest.main()

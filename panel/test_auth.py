"""Testes do acesso remoto. Rodar: python3 -m unittest panel/test_auth.py"""
import http.client
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "scripts"))

import actions  # noqa: E402
import auth  # noqa: E402
import cp_paths  # noqa: E402
import server  # noqa: E402
import test_server  # noqa: E402
import workspace  # noqa: E402

PASSWORD = "uma-senha-bem-comprida"
HOST = "cp.rede.ts.net"


class TotpTest(unittest.TestCase):
    def test_vetores_da_rfc_6238(self):
        secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
        self.assertEqual(auth.totp(secret, 59, digits=8), "94287082")
        self.assertEqual(auth.totp(secret, 1111111109, digits=8), "07081804")
        self.assertEqual(auth.totp(secret, 2000000000, digits=8), "69279037")

    def test_senha_guardada_so_como_hash(self):
        stored = auth.hash_password(PASSWORD)
        self.assertTrue(auth.check_password(PASSWORD, stored))
        self.assertFalse(auth.check_password(PASSWORD + "x", stored))
        self.assertNotIn(PASSWORD, json.dumps(stored))


class PortabilityTest(unittest.TestCase):
    def test_sem_scrypt_usa_pbkdf2(self):
        with mock.patch.object(auth, "hasattr", create=True, return_value=False):
            stored = auth.hash_password(PASSWORD)
        self.assertEqual(stored["kind"], "pbkdf2")
        self.assertTrue(auth.check_password(PASSWORD, stored))
        self.assertFalse(auth.check_password(PASSWORD + "x", stored))

    def test_erro_passageiro_de_leitura_nao_vira_conta_vazia(self):
        """No Windows, ler durante a troca do arquivo falha. Virar "sem conta" apagaria tudo na gravação seguinte."""
        with tempfile.TemporaryDirectory() as temp:
            store = auth.Store(Path(temp) / "s")
            auth.create_account(store, "dona", PASSWORD)
            real = Path.read_text
            fails = iter([True, True])

            def flaky(path, *a, **k):
                if path == store.path and next(fails, False):
                    raise PermissionError("em uso")
                return real(path, *a, **k)

            with mock.patch.object(Path, "read_text", flaky):
                self.assertEqual(store.load()["account"]["username"], "dona")

            def always(path, *a, **k):
                raise PermissionError("em uso")

            with mock.patch.object(Path, "read_text", always), mock.patch.object(auth.time, "sleep"):
                with self.assertRaises(auth.AuthError) as caught:
                    store.load()
            self.assertEqual(caught.exception.status, 503)
            self.assertEqual(store.load()["account"]["username"], "dona")


class Base(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.now = 1_800_000_000.0
        self.store = auth.Store(self.folder / "state")
        self.nodes = {}
        self.remote = auth.Remote(self.store, [HOST], whois=lambda ip: self.nodes.get(ip), clock=lambda: self.now)
        self.secret, self.recovery = auth.create_account(self.store, "dona", PASSWORD)

    def code(self, offset=0):
        return auth.totp(self.secret, self.now + offset)

    def advance(self, seconds):
        self.now += seconds


class RulesTest(Base):
    def headers(self, device=None, session=None, xff=None):
        jar = "; ".join(f"{k}={v}" for k, v in ((auth.DEVICE_COOKIE, device), (auth.SESSION_COOKIE, session)) if v)
        out = {"Cookie": jar, "User-Agent": "Mozilla Chrome/120 Windows"}
        if xff:
            out["X-Forwarded-For"] = xff
        return out

    def approved(self, klass="operacao", xff=None):
        token, code = self.remote.request_device(self.headers(xff=xff), {"name": "Notebook"})
        auth.approve_device(self.store, code, klass, "terminal")
        return token

    def login(self, token, xff=None):
        self.advance(31)
        return self.remote.login(self.headers(token, xff=xff), {"username": "dona", "password": PASSWORD, "code": self.code()})

    def test_conta_so_uma_e_senha_curta_recusada(self):
        with self.assertRaises(auth.AuthError):
            auth.create_account(self.store, "outra", PASSWORD)
        other = auth.Store(self.folder / "b")
        with self.assertRaises(auth.AuthError):
            auth.create_account(other, "dona", "curta")

    def test_arquivo_nao_guarda_senha_token_nem_recuperacao(self):
        token = self.approved()
        raw = self.store.path.read_text(encoding="utf-8")
        for value in (PASSWORD, token, *self.recovery):
            self.assertNotIn(value, raw)

    def test_pedido_nao_da_acesso_e_nao_loga(self):
        token, _ = self.remote.request_device(self.headers(), {"name": "x"})
        self.assertEqual(self.remote.context(self.headers(token))["state"], "pending")
        with self.assertRaises(auth.AuthError) as caught:
            self.remote.login(self.headers(token), {"username": "dona", "password": PASSWORD, "code": self.code()})
        self.assertEqual(caught.exception.status, 403)

    def test_sem_conta_nao_ha_pedido(self):
        remote = auth.Remote(auth.Store(self.folder / "v"), [HOST], whois=lambda _ip: None)
        with self.assertRaises(auth.AuthError):
            remote.request_device({}, {})

    def test_aprovar_exige_o_codigo_certo(self):
        token, code = self.remote.request_device(self.headers(), {})
        with self.assertRaises(auth.AuthError):
            auth.approve_device(self.store, "ERRADO22", "operacao", "t")
        with self.assertRaises(auth.AuthError):
            auth.approve_device(self.store, code, "dona", "t")
        self.assertEqual(self.remote.context(self.headers(token))["state"], "pending")
        auth.approve_device(self.store, code.lower(), "consulta", "t")
        self.assertEqual(self.remote.context(self.headers(token))["state"], "need_login")

    def test_pedido_vence_em_30_minutos(self):
        _, code = self.remote.request_device(self.headers(), {})
        with mock.patch.object(auth.time, "time", return_value=self.now + auth.PENDING_TTL + 1):
            with self.assertRaises(auth.AuthError):
                auth.approve_device(self.store, code, "operacao", "t")

    def test_limite_de_pedidos(self):
        for _ in range(auth.MAX_PENDING):
            self.remote.request_device(self.headers(), {})
        with self.assertRaises(auth.AuthError) as caught:
            self.remote.request_device(self.headers(), {})
        self.assertEqual(caught.exception.status, 429)

    def test_login_precisa_de_senha_e_codigo(self):
        token = self.approved()
        self.advance(31)
        for username, password, code in (("dona", "errada-errada-errada", self.code()), ("outra", PASSWORD, self.code()), ("dona", PASSWORD, "000000"), ("dona", PASSWORD, "")):
            with self.assertRaises(auth.AuthError) as caught:
                self.remote.login(self.headers(token), {"username": username, "password": password, "code": code})
            self.assertEqual(caught.exception.status, 401)
            self.assertEqual(str(caught.exception), "Usuário, senha ou código incorretos.")

    def test_codigo_nao_vale_duas_vezes(self):
        token = self.approved()
        self.advance(31)
        good = {"username": "dona", "password": PASSWORD, "code": self.code()}
        self.remote.login(self.headers(token), good)
        with self.assertRaises(auth.AuthError):
            self.remote.login(self.headers(token), good)

    def test_bloqueio_depois_de_5_erros_mesmo_com_senha_certa(self):
        token = self.approved()
        self.advance(31)
        for _ in range(auth.MAX_FAILS):
            with self.assertRaises(auth.AuthError):
                self.remote.login(self.headers(token), {"username": "dona", "password": "errada-errada-errada", "code": "1"})
        with self.assertRaises(auth.AuthError) as caught:
            self.remote.login(self.headers(token), {"username": "dona", "password": PASSWORD, "code": self.code()})
        self.assertEqual(caught.exception.status, 429)
        self.assertIn("lockout", [e["kind"] for e in self.store.events()])
        self.advance(auth.FAIL_WINDOW + 1)
        self.assertTrue(self.remote.login(self.headers(token), {"username": "dona", "password": PASSWORD, "code": self.code()}))

    def test_codigo_de_recuperacao_vale_uma_vez(self):
        token = self.approved()
        req = {"username": "dona", "password": PASSWORD, "code": self.recovery[0]}
        self.assertTrue(self.remote.login(self.headers(token), req))
        with self.assertRaises(auth.AuthError):
            self.remote.login(self.headers(token), req)
        self.assertIn("recovery_used", [e["kind"] for e in self.store.events()])

    def test_revogar_corta_na_hora_e_registra(self):
        token = self.approved()
        session = self.login(token)
        device = self.remote.context(self.headers(token, session))
        self.assertEqual(device["state"], "ok")
        auth.revoke_device(self.store, device["device"]["id"], "t")
        self.assertEqual(self.remote.context(self.headers(token, session))["state"], "revoked")
        self.assertIn("revoked_used", [e["kind"] for e in self.store.events()])
        with self.assertRaises(auth.AuthError):
            self.remote.request_device(self.headers(token), {})

    def test_sessao_vence_por_inatividade_e_por_tempo(self):
        token = self.approved()
        session = self.login(token)
        self.advance(auth.SESSION_IDLE + 1)
        self.assertEqual(self.remote.context(self.headers(token, session))["state"], "need_login")
        session = self.login(token)
        for _ in range(13):
            self.advance(auth.SESSION_IDLE - 1)
            self.remote.context(self.headers(token, session))
        self.assertEqual(self.remote.context(self.headers(token, session))["state"], "need_login")

    def test_sessao_de_um_dispositivo_nao_serve_em_outro(self):
        first, second = self.approved(), self.approved()
        session = self.login(first)
        self.assertEqual(self.remote.context(self.headers(second, session))["state"], "need_login")

    def test_trocar_a_conta_derruba_sessoes(self):
        token = self.approved()
        session = self.login(token)
        auth.create_account(self.store, "dona", PASSWORD + "2", replace=True)
        self.assertEqual(self.remote.context(self.headers(token, session))["state"], "need_login")

    def test_token_em_outra_maquina_da_tailnet_e_recusado(self):
        self.nodes = {"100.64.0.1": {"id": "a", "name": "notebook", "user": "dona@x"}, "100.64.0.2": {"id": "b", "name": "intruso"}}
        token = self.approved(xff="100.64.0.1")
        self.assertEqual(self.remote.context(self.headers(token, xff="100.64.0.1"))["state"], "need_login")
        self.assertEqual(self.remote.context(self.headers(token, xff="100.64.0.2"))["state"], "node_mismatch")
        self.assertIn("node_mismatch", [e["kind"] for e in self.store.events()])

    def test_cabecalho_fora_da_tailnet_e_ignorado(self):
        calls = []
        self.remote.whois = lambda ip: calls.append(ip)
        self.remote.node_of({"X-Forwarded-For": "8.8.8.8"})
        self.remote.node_of({"X-Forwarded-For": "$(id)"})
        self.assertEqual(calls, [])

    def test_guarda_das_acoes(self):
        token = self.approved("consulta")
        session = self.login(token)
        ctx = self.remote.context(self.headers(token, session))
        with self.assertRaises(auth.AuthError) as caught:
            self.remote.guard_action(ctx)({"env": "dev"})
        self.assertEqual(caught.exception.status, 403)

        token = self.approved("lab")
        session = self.login(token)
        check = self.remote.guard_action(self.remote.context(self.headers(token, session)))
        check({"env": "staging"})
        for env in ("prod", None):
            with self.assertRaises(auth.AuthError):
                check({"env": env})

        token = self.approved("operacao")
        session = self.login(token)
        check = self.remote.guard_action(self.remote.context(self.headers(token, session)))
        check({"env": "prod", "label": "x"})  # acabou de entrar
        self.advance(auth.FRESH_MFA + 1)
        ctx = self.remote.context(self.headers(token, session))
        with self.assertRaises(auth.AuthError) as caught:
            self.remote.guard_action(ctx)({"env": "prod"})
        self.assertEqual(caught.exception.status, 428)
        self.remote.step_up(ctx, self.code())
        self.remote.guard_action(ctx)({"env": "prod", "label": "x"})
        self.assertIn("prod_action", [e["kind"] for e in self.store.events()])

    def test_lab_nao_recebe_producao_e_nao_estraga_o_cache(self):
        shared = {"apps": [{"id": "a", "envs": {"prod": {}, "dev": {}}}, {"id": "b", "envs": {"prod": {}}}], "logs": [{"env": "prod"}, {"env": "dev"}], "rollout": {"c": [{"id": "prod"}, {"id": "dev"}]}, "diverge": [{}], "activity": [{}], "accounts": [{}]}
        out = auth.filter_for_class(shared, "lab")
        self.assertEqual([(a["id"], list(a["envs"])) for a in out["apps"]], [("a", ["dev"])])
        self.assertEqual(out["logs"], [{"env": "dev"}])
        self.assertEqual(out["rollout"]["c"], [{"id": "dev"}])
        self.assertEqual((out["diverge"], out["activity"], out["accounts"]), ([], [], []))
        self.assertIn("prod", shared["apps"][0]["envs"])
        self.assertIs(auth.filter_for_class(shared, "consulta"), shared)

    def test_lista_nao_expoe_token_nem_codigo(self):
        token, code = self.remote.request_device(self.headers(), {"name": "x"})
        raw = json.dumps(auth.machines_view(self.store))
        for value in (token, code, "token_hash", self.secret, PASSWORD):
            self.assertNotIn(value, raw)
        self.assertIn(code, json.dumps(self.remote.public_state(self.remote.context(self.headers(token)))))


class HttpTest(Base):
    def setUp(self):
        super().setUp()
        self.layout = cp_paths.Layout(program=self.folder / "programa", env={"CP_HOME": str(self.folder / "dados")})
        self.store = auth.Store(self.layout.state_dir)
        self.remote = auth.Remote(self.store, [HOST], whois=lambda _ip: None)
        self.secret, self.recovery = auth.create_account(self.store, "dona", PASSWORD)
        workspace.apply(self.layout, {"action": "start", "mode": "empty", "name": "Conta", "role": "lab"})
        for patcher in (mock.patch.object(server, "LAYOUT", self.layout), mock.patch.object(server, "REMOTE", self.remote)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.srv = server.make_server(0)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.jar = {}

    def call(self, method, path, body=None, host=None, **headers):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        base = {"Host": host or HOST}
        if self.jar:
            base["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.jar.items())
        if body is not None:
            base["Content-Type"] = "application/json"
        conn.request(method, path, json.dumps(body) if body is not None else None, {**base, **headers})
        res = conn.getresponse()
        raw = res.read()
        for name, value in res.getheaders():
            if name.lower() == "set-cookie":
                self.last_cookie = value
                key, _, rest = value.partition("=")
                self.jar[key] = rest.split(";")[0]
        conn.close()
        return res.status, (json.loads(raw) if raw[:1] in (b"{", b"[") else raw)

    def enter(self, klass="operacao"):
        _, out = self.call("POST", "/api/auth/request", {"name": "Notebook"})
        auth.approve_device(self.store, out["code"], klass, "terminal")
        status, _ = self.call("POST", "/api/auth/login", {"username": "dona", "password": PASSWORD, "code": self.recovery.pop()})
        self.assertEqual(status, 200)

    def test_nada_de_dado_sem_entrar(self):
        for path in ("/api/data", "/api/device", "/api/setup", "/api/machines", "/api/jobs", "/api/client-preview"):
            self.assertEqual(self.call("GET", path)[0], 401, path)
        self.assertEqual(self.call("GET", "/")[0], 200)
        self.assertEqual(self.call("GET", "/api/auth/state")[1]["state"], "unknown")

    def test_pendente_tambem_nao_ve_dado(self):
        self.call("POST", "/api/auth/request", {"name": "x"})
        self.assertEqual(self.call("GET", "/api/data")[0], 401)
        self.assertEqual(self.call("GET", "/api/auth/state")[1]["state"], "pending")

    def test_host_de_fora_e_recusado(self):
        for path in ("/api/auth/state", "/", "/api/data"):
            self.assertEqual(self.call("GET", path, host="evil.example")[0], 403, path)
        self.assertEqual(self.call("POST", "/api/auth/request", {"name": "x"}, host="evil.example")[0], 403)

    def test_cookies_sao_protegidos(self):
        self.call("POST", "/api/auth/request", {"name": "x"})
        for flag in ("HttpOnly", "Secure", "SameSite=Strict"):
            self.assertIn(flag, self.last_cookie)

    def test_origem_de_outro_site_nao_muda_nada(self):
        self.enter()
        attempts = (dict(Origin="https://evil.example"), {"Sec-Fetch-Site": "cross-site"}, {"Content-Type": "text/plain"})
        for headers in attempts:
            self.assertEqual(self.call("POST", "/api/machines", {"action": "revoke", "id": "x"}, **headers)[0], 403, headers)
            self.assertEqual(self.call("POST", "/api/auth/logout", {}, **headers)[0], 403, headers)
        self.assertEqual(self.call("GET", "/api/data")[0], 200)
        self.assertEqual(self.call("POST", "/api/machines", {"action": "x"}, Origin=f"https://{HOST}")[0], 400)

    def test_primeira_visita_nao_existe_pela_rede(self):
        self.enter()
        self.assertEqual(self.call("POST", "/api/setup", {"action": "start", "mode": "examples"}, **{"X-CP-Key": server.SETUP_KEY})[0], 405)

    def test_aprovar_pede_mfa_recente_e_classe_certa(self):
        self.enter("consulta")
        self.assertEqual(self.call("POST", "/api/machines", {"action": "revoke", "id": "x"})[0], 403)
        self.jar = {}
        self.enter("operacao")
        for session in self.remote.sessions.values():
            session["mfa_at"] -= auth.FRESH_MFA + 1
        status, out = self.call("POST", "/api/machines", {"action": "revoke", "id": "x"})
        self.assertEqual(status, 428, out)

    def test_dispositivo_lab_ve_so_o_proprio_registro(self):
        self.enter("lab")
        _, out = self.call("GET", "/api/machines")
        self.assertEqual(len(out["devices"]), 1)
        self.assertEqual(out["events"], [])
        _, device = self.call("GET", "/api/device")
        self.assertEqual(device["checks"], [])

    def test_sair_encerra_a_sessao(self):
        self.enter()
        cookie = dict(self.jar)
        self.call("POST", "/api/auth/logout", {})
        self.jar = cookie
        self.assertEqual(self.call("GET", "/api/data")[0], 401)

    def test_comeco_de_acao_com_consulta_e_recusado(self):
        runner = mock.Mock()
        runner.key = "k"
        runner.submit.side_effect = lambda *_a, guard=None, **_k: guard({"env": "dev"})
        live = mock.Mock()
        live.get.return_value = ({"apps": []}, None)
        with mock.patch.object(server, "RUNNER", runner), mock.patch.object(server, "LIVE", live):
            self.enter("consulta")
            self.assertEqual(self.call("POST", "/api/actions", {"action": "restart"})[0], 403)

    def runner(self, target="outro", **kwargs):
        session = mock.Mock(state="connected", target=target)
        ran = []

        def spawn(step):
            ran.append(step)
            return subprocess.Popen([sys.executable, "-c", "pass"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        return actions.Runner(ROOT, self.layout.state_dir, session, spawn=spawn, **kwargs), ran

    def test_producao_pede_codigo_novo_e_registra_quem(self):
        """O caminho real do servidor, com um Runner de verdade e um processo inofensivo."""
        runner, ran = self.runner(any_target=True)
        live = mock.Mock()
        live.get.return_value = ({"apps": test_server.APPS}, None)
        live.config.return_value = test_server.CONFIG
        with mock.patch.object(server, "RUNNER", runner), mock.patch.object(server, "LIVE", live):
            self.enter("operacao")
            for item in self.remote.sessions.values():
                item["mfa_at"] -= auth.FRESH_MFA + 1
            body = {"action": "restart", "client": "aurora", "app": "reserva-api", "env": "prod", "confirm": "reserva-api"}
            status, out = self.call("POST", "/api/actions", body)
            self.assertEqual(status, 428, out)
            self.assertEqual(ran, [])
            self.assertEqual(self.call("POST", "/api/auth/step-up", {"code": "000000"})[0], 401)
            self.assertEqual(self.call("POST", "/api/auth/step-up", {"code": auth.totp(self.secret)})[0], 200)
            status, out = self.call("POST", "/api/actions", body)
            self.assertEqual(status, 202, out)
            self.assertEqual(out["job"]["who"], "dona, em Notebook")
            self.assertEqual(out["job"]["where"], "Cofre principal")
        self.assertIn("prod_action", [e["kind"] for e in self.store.events()])

    def test_lab_nao_age_em_producao_pelo_servidor(self):
        runner, ran = self.runner(any_target=True)
        live = mock.Mock()
        live.get.return_value = ({"apps": test_server.APPS}, None)
        live.config.return_value = test_server.CONFIG
        with mock.patch.object(server, "RUNNER", runner), mock.patch.object(server, "LIVE", live):
            self.enter("lab")
            body = {"action": "restart", "client": "aurora", "app": "reserva-api", "env": "prod", "confirm": "reserva-api"}
            self.assertEqual(self.call("POST", "/api/actions", body)[0], 403)
        self.assertEqual(ran, [])

    def test_chave_do_terminal_nao_substitui_o_login(self):
        runner, _ = self.runner(target="lab")
        with mock.patch.object(server, "RUNNER", runner):
            status, _ = self.call("POST", "/api/actions", {"action": "sync_plan", "client": "c"}, **{"X-CP-Key": runner.key})
        self.assertEqual(status, 401)


class LocalUnchangedTest(unittest.TestCase):
    def test_sem_remoto_as_rotas_de_acesso_nao_existem(self):
        srv = server.make_server(0)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("POST", "/api/auth/login", "{}", {"Host": f"127.0.0.1:{port}", "Content-Type": "application/json"})
        self.assertEqual(conn.getresponse().read() and 404, 404)
        conn.request("GET", "/api/auth/state", headers={"Host": f"127.0.0.1:{port}"})
        self.assertEqual(json.loads(conn.getresponse().read()), {"remote": False, "state": "ok"})
        conn.close()

    def test_acoes_fora_do_lab_so_com_remoto(self):
        session = mock.Mock(state="connected", target="outro")
        with tempfile.TemporaryDirectory() as temp:
            self.assertFalse(actions.Runner(ROOT, Path(temp), session).enabled)
            self.assertTrue(actions.Runner(ROOT, Path(temp), session, any_target=True).enabled)


if __name__ == "__main__":
    unittest.main()

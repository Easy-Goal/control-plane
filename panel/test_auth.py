"""Testes do acesso remoto. Rodar: python3 -m unittest panel/test_auth.py"""
import contextlib
import copy
import http.client
import io
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
import cplane  # noqa: E402
import cp_paths  # noqa: E402
import server  # noqa: E402
import test_server  # noqa: E402
import workspace  # noqa: E402

PASSWORD = "uma-senha-bem-comprida"
HOST = "cp.rede.ts.net"
LOCAL = {"Host": "127.0.0.1:4700"}  # acesso local, sem tailscale serve: sem X-Forwarded-For
TAILNET_IP = "100.64.0.9"
NODE = {"id": "nNotebook", "name": "notebook", "os": "linux", "user": "dona@x"}


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
        names = auth.COOKIES["tailnet" if xff else "local"]
        jar = "; ".join(f"{k}={v}" for k, v in ((names["device"], device), (names["session"], session)) if v)
        out = {"Cookie": jar, "User-Agent": "Mozilla Chrome/120 Windows"}
        if xff:
            out.update({"Host": HOST, "X-Forwarded-For": xff})
        else:
            out.update(LOCAL)
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

    def fail_login(self, token, times=auth.MAX_FAILS):
        for _ in range(times):
            with self.assertRaises(auth.AuthError):
                self.remote.login(self.headers(token), {"username": "dona", "password": "errada-errada-errada", "code": "1"})

    def test_dispositivo_ruim_nao_tranca_os_outros(self):
        bad, good = self.approved("lab"), self.approved("operacao")
        self.fail_login(bad)
        with self.assertRaises(auth.AuthError) as caught:
            self.remote.login(self.headers(bad), {"username": "dona", "password": PASSWORD, "code": "1"})
        self.assertEqual(caught.exception.status, 429)
        self.assertTrue(self.login(good))

    def test_confirmacao_errada_bloqueia_so_o_dispositivo(self):
        bad, good = self.approved("lab"), self.approved("operacao")
        ctx = self.remote.context(self.headers(bad, self.login(bad)))
        for _ in range(auth.MAX_FAILS):
            with self.assertRaises(auth.AuthError):
                self.remote.step_up(ctx, "000000")
        with self.assertRaises(auth.AuthError) as caught:
            self.remote.step_up(ctx, self.code())
        self.assertEqual(caught.exception.status, 429)
        self.assertIn("lockout", [e["kind"] for e in self.store.events()])
        self.assertTrue(self.login(good))

    def test_lista_diz_quem_esta_bloqueado(self):
        bad = self.approved("lab")
        self.fail_login(bad)
        with mock.patch.object(auth.time, "time", return_value=self.now):
            self.assertEqual(auth.machines_view(self.store)["account"]["locked"], ["Notebook"])

    def test_redefinir_a_conta_libera_o_dispositivo(self):
        token = self.approved()
        self.fail_login(token)
        self.secret, _ = auth.create_account(self.store, "dona", PASSWORD, replace=True)
        self.assertTrue(self.login(token))

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
            self.remote.context(self.headers(token, session), active=True)
        self.assertEqual(self.remote.context(self.headers(token, session))["state"], "need_login")

    def test_leitura_periodica_nao_segura_a_sessao_aberta(self):
        token = self.approved()
        session = self.login(token)
        for _ in range(3):
            self.advance(auth.SESSION_IDLE / 3)
            self.assertEqual(self.remote.context(self.headers(token, session))["state"], "ok")
        self.advance(1)
        self.assertEqual(self.remote.context(self.headers(token, session))["state"], "need_login")

    def test_uso_de_verdade_segura_a_sessao(self):
        token = self.approved()
        session = self.login(token)
        for _ in range(3):
            self.advance(auth.SESSION_IDLE - 1)
            self.assertEqual(self.remote.context(self.headers(token, session), active=True)["state"], "ok")

    def test_instancia_invalida_nao_deixa_rastro_em_disco(self):
        before = self.store.path.read_bytes()
        token, _ = self.remote.request_device(self.headers(), {"kind": "install", "name": "\ud800", "instance": {"id": "\ud800", "role": {"a": "\ud800"}, "os": "linux"}})
        data = self.store.load()
        device = next(d for d in data["devices"].values() if d["token_hash"] == auth._sha(token))
        self.assertEqual(device["instance"], {"id": "", "role": "", "os": "linux"})
        self.assertNotEqual(before, self.store.path.read_bytes())
        self.assertEqual(self.leftovers(), [])

    def test_gravacao_que_falha_nao_deixa_copia_do_segredo(self):
        before = self.store.path.read_bytes()
        data = self.store.load()
        data["devices"]["x"] = {"name": "\ud800"}
        with self.assertRaises(UnicodeEncodeError):
            self.store.save(data)
        self.assertEqual(self.leftovers(), [])
        self.assertEqual(before, self.store.path.read_bytes())

    def test_troca_de_arquivo_que_falha_nao_deixa_copia_do_segredo(self):
        with mock.patch.object(auth.os, "replace", side_effect=OSError("disco")), self.assertRaises(OSError):
            self.store.save(self.store.load())
        self.assertEqual(self.leftovers(), [])

    def leftovers(self):
        return sorted(p.name for p in self.store.folder.iterdir() if p.name.startswith(".auth."))

    def test_codigo_fora_do_ascii_e_recusado_e_conta_como_erro(self):
        token = self.approved()
        arabic = "".join(chr(0x0660 + int(d)) for d in self.code())
        for code in (arabic, "ééééé-ééééé"):
            with self.assertRaises(auth.AuthError) as caught:
                self.remote.login(self.headers(token), {"username": "dona", "password": PASSWORD, "code": code})
            self.assertEqual(caught.exception.status, 401)
        self.assertEqual(len(next(iter(self.store.load()["devices"].values()))["fails"]), 2)

    def test_surrogate_no_login_e_recusado_sem_olhar_a_senha(self):
        token = self.approved()
        for field in ("username", "password", "code"):
            body = {"username": "dona", "password": PASSWORD, "code": self.code(), field: "\ud800"}
            with self.assertRaises(auth.AuthError) as caught:
                self.remote.login(self.headers(token), body)
            self.assertEqual(caught.exception.status, 400)

    def test_confirmacao_com_codigo_fora_do_ascii_e_recusada(self):
        token = self.approved()
        session = self.login(token)
        ctx = self.remote.context(self.headers(token, session))
        with self.assertRaises(auth.AuthError) as caught:
            self.remote.step_up(ctx, "".join(chr(0x0660 + int(d)) for d in self.code()))
        self.assertEqual(caught.exception.status, 401)

    def test_aprovar_com_codigo_fora_do_ascii_diz_que_nao_achou(self):
        self.remote.request_device(self.headers(), {"name": "Notebook"})
        with self.assertRaises(auth.AuthError) as caught:
            auth.approve_device(self.store, "ÉÉÉÉÉÉÉÉ", "lab", "terminal")
        self.assertEqual(caught.exception.status, 404)

    def test_cookie_de_outra_aplicacao_nao_atrapalha(self):
        token = self.approved()
        session = self.login(token)
        ours = f"cp_device={token}; cp_session={session}"
        for foreign in ("flag", 'prefs={"a":1}', "tema=azul claro", 'x="', "=vazio", "a=b=c"):
            for header in (f"{foreign}; {ours}", f"{ours}; {foreign}"):
                self.assertEqual(self.remote.context({**LOCAL, "Cookie": header})["state"], "ok", header)

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

    def test_lab_nao_recebe_nome_de_producao_em_nenhum_campo(self):
        secret = "segredo-prod"
        rows = [
            {"id": "contas", "title": "Contas", "state": "todo", "source": "live", "hint": f"Falta: {secret}", "to": f"#/contas/{secret}"},
            {"id": "leitura", "title": "Leitura", "state": "todo", "source": "live", "cmd": f"provider set {secret}"},
            {"id": "services", "title": "Aplicações", "state": "todo", "source": "live", "hint": f"Falta criar: {secret}", "cmd": secret},
            {"id": "valores", "title": "Valores", "state": "ok", "source": "live", "hint": f"Sem valores em: {secret}"},
            {"id": "logs", "title": "Logs", "state": "err", "source": "live", "hint": secret, "novo": secret},
            {"id": "dev", "title": "Dev", "state": "todo", "source": "live", "hint": "Pendente: api-dev.", "real": {"action": "sync_apply", "env": "dev", "target": "api-dev"}},
            {"id": "prod", "title": "Prod", "state": "todo", "source": "live", "hint": secret, "real": {"env": "prod", "target": secret}},
        ]
        shared = {"apps": [{"id": "a", "envs": {"dev": {}, "outro": {"where": secret}}}], "logs": [{"env": "outro", "text": secret}], "rollout": {"c": rows},
                  "discoveries": {"c": [{"name": secret}]}, "connection": {"state": "off", "error": secret, "problems": [{"area": "Contas", "text": secret, "next": secret}]}}
        out = auth.filter_for_class(shared, "lab")
        self.assertNotIn(secret, json.dumps(out))
        by_id = {p["id"]: p for p in out["rollout"]["c"]}
        self.assertEqual(sorted(by_id), ["contas", "dev", "leitura", "logs", "services", "valores"])
        self.assertEqual(by_id["dev"]["real"]["target"], "api-dev")
        self.assertEqual(by_id["dev"]["hint"], "Pendente: api-dev.")
        self.assertEqual((by_id["contas"]["state"], by_id["contas"]["hint"]), ("todo", auth.LAB_HINT))
        self.assertNotIn("hint", by_id["valores"])
        self.assertEqual(out["connection"]["problems"][0]["area"], "Contas")
        self.assertIn(secret, json.dumps(shared))

    def test_lab_nao_recebe_acao_de_outro_ambiente_na_linha_de_dev(self):
        row = {"id": "dev", "state": "todo", "real": {"env": "outro"}}
        self.assertNotIn("real", auth.filter_for_class({"rollout": {"c": [row]}}, "lab")["rollout"]["c"][0])

    def test_lab_ve_so_a_atividade_que_pode_executar(self):
        rows = [{"id": env, "env": env} for env in ("dev", "staging", "prod", None)] + [{"id": "antiga"}]
        out = auth.filter_for_class({"activity": rows}, "lab")
        self.assertEqual([r["id"] for r in out["activity"]], ["dev", "staging"])
        self.assertEqual(len(rows), 5)
        self.assertEqual(auth.jobs_for_class(rows, "operacao"), rows)

    def test_lista_nao_expoe_token_nem_codigo(self):
        token, code = self.remote.request_device(self.headers(), {"name": "x"})
        raw = json.dumps(auth.machines_view(self.store))
        for value in (token, code, "token_hash", self.secret, PASSWORD):
            self.assertNotIn(value, raw)
        self.assertIn(code, json.dumps(self.remote.public_state(self.remote.context(self.headers(token)))))


class OriginTest(Base):
    """M1: no modo remoto, pedido sem origem identificada é recusado. Só o acesso local explícito escapa."""
    headers, approved, login = RulesTest.headers, RulesTest.approved, RulesTest.login

    def setUp(self):
        super().setUp()
        self.nodes = {TAILNET_IP: dict(NODE), "100.64.0.2": {"id": "b", "name": "intruso"}}

    def refused(self, headers):
        for call in (lambda: self.remote.context(headers), lambda: self.remote.request_device(headers, {"name": "x"}),
                     lambda: self.remote.login(headers, {"username": "dona", "password": PASSWORD, "code": self.code()}), lambda: self.remote.logout(headers)):
            with self.assertRaises(auth.OriginRefused) as caught:
                call()
            self.assertEqual(caught.exception.status, 403)

    def reasons(self):
        return [(e["reason"], e["address"]) for e in self.store.events() if e["kind"] == "origin_refused"]

    def test_sem_cabecalho_da_tailnet_e_recusado(self):
        self.refused({"Host": HOST})
        self.assertEqual(self.reasons(), [("sem_origem", "")])
        self.assertIn("origin_refused", auth.ALERTS)

    def test_endereco_fora_da_tailnet_e_recusado_sem_gravar_o_texto(self):
        self.refused({"Host": HOST, "X-Forwarded-For": "8.8.8.8"})
        self.refused({"Host": HOST, "X-Forwarded-For": "$(id)"})
        self.refused(self.headers(xff="127.0.0.1"))  # cabeçalho presente não vira acesso local
        self.assertEqual(self.reasons(), [("fora_da_tailnet", "8.8.8.8")])  # um registro por motivo a cada 10 minutos
        self.assertNotIn("$(id)", self.store.events_path.read_text(encoding="utf-8"))

    def test_whois_que_falha_recusa_e_nao_fica_em_cache(self):
        calls, down = [], [True]
        self.remote.whois = lambda ip: calls.append(ip) or (None if down[0] else dict(NODE))
        self.refused(self.headers(xff=TAILNET_IP))
        self.assertEqual(self.reasons(), [("whois_falhou", TAILNET_IP)])
        self.assertEqual(self.remote.whois_cache, {})
        self.assertEqual(len(calls), 4)  # cada pedido recusado perguntou de novo
        down[0] = False
        self.assertEqual(self.remote.context(self.headers(xff=TAILNET_IP))["node"]["id"], NODE["id"])  # volta na hora, sem esperar cache
        self.remote.context(self.headers(xff=TAILNET_IP))
        self.assertEqual(len(calls), 5)  # sucesso fica em cache

    def test_whois_sem_id_conta_como_falha(self):
        self.remote.whois = lambda ip: {"id": "", "name": "?"}
        self.refused(self.headers(xff=TAILNET_IP))

    def test_acesso_local_explicito_continua(self):
        for host in ("127.0.0.1:4700", "localhost:4700", "LOCALHOST:4700"):
            self.assertEqual(self.remote.context({"Host": host})["channel"], "local")
        token = self.approved()
        self.assertEqual(self.remote.context(self.headers(token, self.login(token)))["state"], "ok")

    def test_dispositivo_da_tailnet_nao_vale_no_acesso_local(self):
        token = self.approved(xff=TAILNET_IP)
        self.assertEqual(self.remote.context(self.headers(token, xff=TAILNET_IP))["state"], "need_login")
        self.assertEqual(self.remote.context(self.headers(token))["state"], "node_mismatch")
        self.assertEqual(self.remote.context(self.headers(token, xff="100.64.0.2"))["state"], "node_mismatch")

    def test_dispositivo_local_nao_vale_pela_tailnet(self):
        token = self.approved()
        self.assertEqual(self.remote.context(self.headers(token, xff=TAILNET_IP))["state"], "node_mismatch")
        self.assertIn("node_mismatch", [e["kind"] for e in self.store.events()])


class CookieNameTest(Base):
    """M2: pela tailnet, só o nome com __Host- vale. Cookie plantado sem o prefixo por outra máquina de *.ts.net é ignorado."""
    headers, approved, login = RulesTest.headers, RulesTest.approved, RulesTest.login

    def setUp(self):
        super().setUp()
        self.nodes = {TAILNET_IP: dict(NODE)}

    def test_nome_e_atributos_pela_tailnet(self):
        cookie = self.remote.cookie_headers("device", {"Host": HOST, "X-Forwarded-For": TAILNET_IP}, "tok", 60)
        name, _, rest = cookie.partition("=")
        self.assertEqual(name, "__Host-cp_device")
        attrs = [a.strip() for a in rest.split(";")[1:]]
        for flag in ("Path=/", "Secure", "HttpOnly", "SameSite=Strict"):
            self.assertIn(flag, attrs)
        self.assertFalse(any(a.lower().startswith("domain") for a in attrs))
        self.assertTrue(self.remote.cookie_headers("session", {"Host": HOST, "X-Forwarded-For": TAILNET_IP}, "", 0).startswith("__Host-cp_session=;"))

    def test_nome_sem_prefixo_so_no_acesso_local(self):
        self.assertTrue(self.remote.cookie_headers("device", LOCAL, "tok", 60).startswith("cp_device=tok;"))
        self.assertTrue(self.remote.cookie_headers("session", {"Host": "localhost:4700"}, "tok", 60).startswith("cp_session=tok;"))

    def test_cookie_sem_prefixo_pela_tailnet_e_ignorado(self):
        token = self.approved(xff=TAILNET_IP)
        session = self.login(token, xff=TAILNET_IP)
        tossed = {"Host": HOST, "X-Forwarded-For": TAILNET_IP, "Cookie": f"cp_device={token}; cp_session={session}"}
        self.assertEqual(self.remote.context(tossed)["state"], "unknown")
        self.assertEqual(self.remote.context(self.headers(token, session, xff=TAILNET_IP))["state"], "ok")

    def test_cookie_com_prefixo_nao_vale_no_acesso_local(self):
        token = self.approved()
        self.assertEqual(self.remote.context({**LOCAL, "Cookie": f"__Host-cp_device={token}"})["state"], "unknown")

    def test_cookie_plantado_antes_nao_ganha_do_nosso(self):
        token = self.approved(xff=TAILNET_IP)
        session = self.login(token, xff=TAILNET_IP)
        jar = f"cp_device=plantado; cp_session=plantada; __Host-cp_device={token}; __Host-cp_session={session}"
        self.assertEqual(self.remote.context({"Host": HOST, "X-Forwarded-For": TAILNET_IP, "Cookie": jar})["state"], "ok")


class LabDeviceTest(unittest.TestCase):
    """M3: /api/device para Lab/teste por lista do que pode passar."""

    DEVICE = {
        "read_at": "2026-11-14T00:00:00+00:00", "system": "Linux", "checks": [{"id": "vault_local"}], "containers": [{"names": "openbao"}], "draft_todos": 4,
        "desired": {"error": False, "todos": 2, "clients": [
            {"slug": "aurora", "providers": [{"name": "vercel-prod", "kind": "vercel"}], "projects": [
                {"slug": "site", "environments": ["dev", "staging", "prod"]}, {"slug": "faturamento", "environments": ["prod"]}]},
            {"slug": "so-prod", "providers": [{"name": "x", "kind": "coolify"}], "projects": [{"slug": "api", "environments": ["prod"]}]}]},
        "setup": {"layout": "installed", "view": "real", "machine": {"id": "m", "name": "VPS", "role": "principal"}, "role_name": "Principal", "account": "Conta",
                  "home_client": "aurora", "config_dir": "/root/.config/control-plane/conta", "config_git": True, "os": "linux", "version": "1"},
        "campo_novo": {"segredo": "nao-pode-vazar"},
    }

    def test_lab_recebe_so_a_lista_do_que_pode_passar(self):
        out = auth.device_for_class(copy.deepcopy(self.DEVICE), "lab")
        self.assertEqual(set(out), {"read_at", "checks", "containers", "desired", "setup"})  # chave nova em read_device quebra este teste
        self.assertEqual((out["checks"], out["containers"]), ([], []))
        self.assertLessEqual(set(out["setup"]), set(auth.LAB_SETUP_KEYS))
        raw = json.dumps(out)
        for leaked in ("prod", "so-prod", "faturamento", "vercel-prod", "config_dir", "/root", "nao-pode-vazar", "Linux", "openbao"):
            self.assertNotIn(leaked, raw, leaked)
        self.assertEqual(out["desired"]["clients"], [{"slug": "aurora", "providers": [], "projects": [{"slug": "site", "environments": ["dev", "staging"]}]}])

    def test_outras_classes_recebem_tudo_e_o_original_nao_muda(self):
        original = copy.deepcopy(self.DEVICE)
        auth.device_for_class(original, "lab")
        self.assertEqual(original, self.DEVICE)
        for klass in ("operacao", "consulta", None):
            self.assertEqual(auth.device_for_class(copy.deepcopy(self.DEVICE), klass), self.DEVICE)

    def test_conta_ilegivel_ou_ausente(self):
        self.assertIsNone(auth.device_for_class({"desired": None}, "lab")["desired"])
        self.assertEqual(auth.device_for_class({"desired": {"error": True, "clients": []}}, "lab")["desired"], {"error": True, "clients": []})


class HttpTest(Base):
    def setUp(self):
        super().setUp()
        self.layout = cp_paths.Layout(program=self.folder / "programa", env={"CP_HOME": str(self.folder / "dados")})
        self.store = auth.Store(self.layout.state_dir)
        self.remote = auth.Remote(self.store, [HOST], whois=lambda ip: dict(NODE) if ip == TAILNET_IP else None)
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
        base = {"Host": host or HOST, "X-Forwarded-For": TAILNET_IP}
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

    def test_criar_cliente_pede_codigo_novo_e_registra(self):
        runner, ran = self.runner(any_target=True)
        live = mock.Mock()
        live.get.return_value = ({"apps": test_server.APPS}, None)
        config = copy.deepcopy(test_server.CONFIG)
        config["client"][0]["project"][0]["environments"] = ["prod"]
        live.config.return_value = config
        with mock.patch.object(server, "RUNNER", runner), mock.patch.object(server, "LIVE", live):
            self.enter("operacao")
            for item in self.remote.sessions.values():
                item["mfa_at"] -= auth.FRESH_MFA + 1
            body = {"action": "client_prepare", "client": "aurora"}
            self.assertEqual(self.call("POST", "/api/actions", body)[0], 428)
            self.assertEqual(ran, [])
            self.assertEqual(self.call("POST", "/api/auth/step-up", {"code": auth.totp(self.secret)})[0], 200)
            status, out = self.call("POST", "/api/actions", body)
            self.assertEqual(status, 202, out)
        self.assertIn("prod_action", [e["kind"] for e in self.store.events()])

    def test_testar_conta_grava_no_cofre_e_pede_codigo_novo(self):
        guard = self.remote.guard_action
        plan = actions.build_plan({"action": "test_account", "client": "aurora", "provider": "vercel"}, test_server.CONFIG, test_server.APPS)
        self.enter("operacao")
        for item in self.remote.sessions.values():
            item["mfa_at"] -= auth.FRESH_MFA + 1
        ctx = self.remote.context({"Host": HOST, "X-Forwarded-For": TAILNET_IP, "Cookie": "; ".join(f"{k}={v}" for k, v in self.jar.items())})
        with self.assertRaises(auth.AuthError) as caught:
            guard(ctx)(plan)
        self.assertEqual(caught.exception.status, 428)

    def test_conferir_nao_pede_codigo_novo(self):
        runner, _ = self.runner(any_target=True)
        live = mock.Mock()
        live.get.return_value = ({"apps": test_server.APPS}, None)
        live.config.return_value = test_server.CONFIG
        with mock.patch.object(server, "RUNNER", runner), mock.patch.object(server, "LIVE", live):
            self.enter("operacao")
            for item in self.remote.sessions.values():
                item["mfa_at"] -= auth.FRESH_MFA + 1
            status, out = self.call("POST", "/api/actions", {"action": "sync_plan", "client": "aurora"})
            self.assertEqual(status, 202, out)
        self.assertNotIn("prod_action", [e["kind"] for e in self.store.events()])

    def test_lab_acompanha_a_propria_acao_e_nao_a_de_producao(self):
        """Reproduz o caminho da tela: lança a ação e lê /api/data e /api/jobs em seguida."""
        runner, _ = self.runner(any_target=True)
        runner.history = [{"id": "de-prod", "action": "Reiniciar em prod", "env": "prod", "result": "ok", "steps": [], "source": "live"}]
        live = mock.Mock()
        live.get.return_value = ({"apps": test_server.APPS}, None)
        live.config.return_value = test_server.CONFIG
        with mock.patch.object(server, "RUNNER", runner), mock.patch.object(server, "LIVE", live), mock.patch.object(server, "read_data", lambda: {"activity": runner.rows()}):
            self.enter("lab")
            body = {"action": "restart", "client": "aurora", "app": "reserva-api", "env": "staging"}
            status, out = self.call("POST", "/api/actions", body)
            self.assertEqual(status, 202, out)
            job = out["job"]["id"]
            _, data = self.call("GET", "/api/data")
            self.assertEqual([r["id"] for r in data["activity"]], [job])
            status, jobs = self.call("GET", "/api/jobs")
            self.assertEqual((status, [r["id"] for r in jobs["jobs"]]), (200, [job]))

    def test_so_pedido_que_muda_algo_renova_a_sessao(self):
        self.enter()
        moved = lambda: next(iter(self.remote.sessions.values()))["last"]  # noqa: E731
        for item in self.remote.sessions.values():
            item["last"] -= 100
        before = moved()
        for path in ("/api/data", "/api/device", "/api/machines", "/api/auth/state"):
            self.call("GET", path)
        self.assertEqual(moved(), before)
        self.assertEqual(self.call("POST", "/api/auth/activity", {})[0], 200)
        self.assertGreater(moved(), before)

    def test_aviso_de_uso_pede_sessao(self):
        self.assertEqual(self.call("POST", "/api/auth/activity", {})[0], 401)

    def test_instancia_com_surrogate_pela_rede(self):
        raw = b'{"kind":"install","instance":{"id":"\\ud800"}}'
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("POST", "/api/auth/request", raw, {"Host": HOST, "X-Forwarded-For": TAILNET_IP, "Content-Type": "application/json"})
        res = conn.getresponse()
        res.read()
        conn.close()
        self.assertEqual(res.status, 200)
        self.assertEqual([p.name for p in self.store.folder.iterdir() if p.name.startswith(".auth.")], [])
        self.assertEqual(next(iter(self.store.load()["devices"].values()))["instance"]["id"], "")

    def test_chave_do_terminal_nao_substitui_o_login(self):
        runner, _ = self.runner(target="lab")
        with mock.patch.object(server, "RUNNER", runner):
            status, _ = self.call("POST", "/api/actions", {"action": "sync_plan", "client": "c"}, **{"X-CP-Key": runner.key})
        self.assertEqual(status, 401)


    def test_sem_origem_da_tailnet_nada_responde(self):
        for path in ("/api/auth/state", "/api/data", "/api/device"):
            status, out = self.call("GET", path, **{"X-Forwarded-For": "8.8.8.8"})
            self.assertEqual(status, 403, path)
        self.assertEqual(self.call("GET", "/api/auth/state", **{"X-Forwarded-For": "8.8.8.8"})[1]["state"], "origin_refused")
        self.assertEqual(self.call("POST", "/api/auth/request", {"name": "x"}, **{"X-Forwarded-For": "100.64.0.77"})[0], 403)  # whois não conhece
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("GET", "/api/auth/state", headers={"Host": HOST})  # sem X-Forwarded-For, com o nome da tailnet
        self.assertEqual(conn.getresponse().status, 403)
        conn.close()
        self.assertEqual(self.store.load()["devices"], {})

    def test_acesso_local_usa_o_nome_sem_prefixo(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("POST", "/api/auth/request", json.dumps({"name": "x"}), {"Host": f"127.0.0.1:{self.port}", "Content-Type": "application/json"})
        res = conn.getresponse()
        res.read()
        conn.close()
        self.assertEqual(res.status, 200)
        self.assertTrue(res.getheader("Set-Cookie").startswith("cp_device="))

    def test_cookies_pela_tailnet_tem_prefixo_host(self):
        self.enter()
        self.assertEqual(set(self.jar), {"__Host-cp_device", "__Host-cp_session"})
        self.call("POST", "/api/auth/logout", {})
        self.assertTrue(self.last_cookie.startswith("__Host-cp_session=;"))
        self.assertNotIn("Domain", self.last_cookie)

    def test_lab_nao_recebe_producao_nem_caminho_em_device_e_setup(self):
        self.enter("lab")
        with mock.patch.object(server.CACHE, "get", return_value=copy.deepcopy({k: v for k, v in LabDeviceTest.DEVICE.items() if k != "setup"})):
            _, device = self.call("GET", "/api/device")
        _, setup = self.call("GET", "/api/setup")
        self.assertEqual(set(device), {"read_at", "checks", "containers", "desired", "setup"})
        for leaked in ("so-prod", "vercel-prod", "nao-pode-vazar", str(self.layout.config_dir)):
            self.assertNotIn(leaked, json.dumps(device), leaked)
        self.assertNotIn("config_dir", setup)
        self.jar = {}
        self.enter("operacao")
        _, setup = self.call("GET", "/api/setup")
        self.assertIn("config_dir", setup)

class PrincipalTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.layout = cp_paths.Layout(program=self.folder / "programa", env={"CP_HOME": str(self.folder / "dados")})
        workspace.apply(self.layout, {"action": "start", "mode": "empty", "name": "Conta", "role": "lab"})
        self.me = workspace.write_machine(self.layout, role="principal")

    def demote(self):
        with mock.patch.object(cplane, "layout", lambda: self.layout), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(cplane.cmd_machine(["role", "lab"]), 0)
        self.assertEqual(workspace.read_machine(self.layout)["role"], "lab")
        return out.getvalue()

    def test_rebaixar_tira_o_proprio_registro(self):
        workspace.set_principal(self.layout, self.me)
        self.assertIn("Publique", self.demote())
        self.assertEqual(workspace.principal(self.layout), {})

    def test_rebaixar_nao_apaga_a_principal_nova(self):
        workspace.set_principal(self.layout, {"id": "outra", "name": "VPS"})
        self.assertNotIn("Publique", self.demote())
        self.assertEqual(workspace.principal(self.layout)["id"], "outra")

    def test_rebaixar_sem_arquivo_da_conta_nao_quebra(self):
        self.layout.workspace_file.unlink()
        self.assertNotIn("Publique", self.demote())
        self.assertFalse(self.layout.workspace_file.exists())


class ConnectCookieTest(unittest.TestCase):
    """M2 no cplane connect: pela tailnet (https), o registro lê e manda o cookie com __Host-."""

    def test_connect_usa_o_nome_com_prefixo_pela_tailnet(self):
        with tempfile.TemporaryDirectory() as temp:
            layout = cp_paths.Layout(program=Path(temp) / "programa", env={"CP_HOME": str(Path(temp) / "dados")})
            workspace.apply(layout, {"action": "start", "mode": "empty", "name": "Conta", "role": "lab"})
            sent = []

            class Reply:
                status = 200

                def __init__(self, body, cookie):
                    self.body, self.headers = body, {"Set-Cookie": cookie}

                def read(self):
                    return self.body

                def __enter__(self):
                    return self

                def __exit__(self, *_):
                    return False

            def urlopen(req, timeout=None):
                sent.append(req.get_header("Cookie"))
                if req.full_url.endswith("/api/auth/request"):
                    return Reply(b'{"state": "pending", "code": "ABCD2345"}', "__Host-cp_device=TOKEN1; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=60")
                return Reply(b'{"state": "pending", "code": "ABCD2345"}', "")

            with mock.patch.object(cplane, "layout", lambda: layout), mock.patch("urllib.request.urlopen", urlopen), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cplane.cmd_connect(["https://cp.rede.ts.net"]), 0)
                self.assertEqual(json.loads((layout.home / "remote.json").read_text(encoding="utf-8"))["token"], "TOKEN1")
                cplane.cmd_connect(["--status"])
            self.assertEqual(sent, [None, "__Host-cp_device=TOKEN1"])

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

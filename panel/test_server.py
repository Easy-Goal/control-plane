"""Testes do servidor do painel. Rodar: python3 -m unittest panel/test_server.py"""
import http.client
import importlib.machinery
import importlib.util
import json
import re
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import live  # noqa: E402
import server  # noqa: E402

# Formatos de credencial que nunca podem aparecer nos exemplos nem no código do front.
SECRET_SHAPES = re.compile(
    r"ghp_[A-Za-z0-9]{20,}|github_pat_|-----BEGIN|hvs\.[A-Za-z0-9]{20,}|s\.[A-Za-z0-9]{24,}|"
    r"sk_(live|test)_|APP_USR-|eyJ[A-Za-z0-9_-]{20,}\.|postgres(ql)?://[^\s\"'<]+:[^\s\"'<@]+@"
)


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = server.make_server(0)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def req(self, method, path, host=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        conn.putrequest(method, path, skip_host=True)
        conn.putheader("Host", host or f"127.0.0.1:{self.port}")
        conn.endheaders()
        res = conn.getresponse()
        body = res.read()
        conn.close()
        return res, body

    def test_escuta_so_em_loopback(self):
        self.assertEqual(self.srv.server_address[0], "127.0.0.1")

    def test_recusa_host_externo(self):
        res, _ = self.req("GET", "/api/device", host="evil.example")
        self.assertEqual(res.status, 403)

    def test_e_so_leitura(self):
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            res, _ = self.req(method, "/api/device")
            self.assertEqual(res.status, 405, method)

    def test_nao_sai_da_pasta_web(self):
        for path in ("/../server.py", "/..%2fserver.py", "/../../openbao/secrets.toml", "/%2e%2e/demo.json"):
            res, _ = self.req("GET", path)
            self.assertEqual(res.status, 404, path)

    def test_cabecalhos_de_seguranca(self):
        res, _ = self.req("GET", "/")
        self.assertEqual(res.status, 200)
        csp = res.getheader("Content-Security-Policy")
        self.assertIn("default-src 'none'", csp)
        self.assertNotIn("unsafe", csp)
        self.assertEqual(res.getheader("X-Content-Type-Options"), "nosniff")

    def test_dados_marcados_como_exemplo(self):
        res, body = self.req("GET", "/api/data")
        data = json.loads(body)
        self.assertEqual(res.status, 200)
        for area, source in data["sources"].items():
            self.assertIn(area, data)
            self.assertEqual(source, "demo")

    def test_contas_de_exemplo_sem_valor(self):
        data = json.loads(self.req("GET", "/api/data")[1])
        for account in data["accounts"]:
            for field in account["fields"]:
                self.assertEqual(set(field), {"name", "set"})

    def test_exemplos_e_front_sem_formato_de_credencial(self):
        files = [HERE / "demo.json", *(HERE / "web").glob("*.js"), HERE / "web" / "index.html"]
        for path in files:
            self.assertIsNone(SECRET_SHAPES.search(path.read_text(encoding="utf-8")), path.name)

    def test_comandos_do_coolify_sempre_indicam_o_cliente(self):
        """Sem --client, o cp-coolify usa a Easy Goal: a VPS do cliente iria para o time errado."""
        content = (HERE / "web" / "content.js").read_text(encoding="utf-8")
        self.assertIn("scripts/cp-coolify --client", content)
        self.assertIsNone(re.search(r"scripts/cp-coolify (?!--client)", content))
        self.assertIn("CP_CLIENT=${c}", content)

    def test_funciona_sem_nada_instalado(self):
        """Device vazio: sem Docker, sem Tailscale, sem portas abertas e sem arquivos de operador."""
        def absent(*_a, **_k):
            return None, b""

        with mock.patch.object(server.shutil, "which", return_value=None), \
                mock.patch.object(server, "http_get", absent), \
                mock.patch.object(server, "run", return_value=(None, "")), \
                mock.patch.object(server, "ROOT", Path("/nao/existe")):
            device = server.read_device()
        states = {c["id"]: c["state"] for c in device["checks"]}
        self.assertEqual(states["docker"], "missing")
        self.assertEqual(states["vault_local"], "missing")
        self.assertEqual(states["vault_lab"], "missing")
        self.assertEqual(states["operator"], "missing")
        self.assertEqual(states["init_json"], "ok")
        self.assertEqual(device["containers"], [])

    def test_identifica_cofre_selado_sem_token(self):
        body = json.dumps({"initialized": True, "sealed": True}).encode()
        with mock.patch.object(server, "http_get", return_value=(200, body)) as get:
            found = server.vault("vault_local", "http://127.0.0.1:8200", "local")
        self.assertEqual(found["state"], "warn")
        self.assertTrue(found["sealed"])
        get.assert_called_once_with("http://127.0.0.1:8200/v1/sys/seal-status")

    def test_nao_le_arquivos_de_credencial(self):
        opened = []
        real_read = Path.read_text

        def spy(path, *a, **k):
            opened.append(path.name)
            return real_read(path, *a, **k)

        with mock.patch.object(Path, "read_text", spy):
            server.read_device()
        self.assertFalse({".env", ".init.json", ".bootstrap.env"} & set(opened), opened)


CANARY = "valor-que-nunca-sai-9f3a"
CONFIG = {"client": [{
    "slug": "easygoal",
    "provider": [{"name": "coolify-x", "kind": "coolify"}, {"name": "coolify-x-read", "kind": "coolify"},
                 {"name": "vercel", "kind": "vercel"}, {"name": "obs-read", "kind": "openobserve"}],
    "project": [{"slug": "health-stay", "target": [
        {"name": "api-prod", "provider": "coolify-x", "environment": "prod", "resource_name": "health-stay-api-prod"},
    ]}],
}]}
SERVICE = {
    "name": "health-stay-api-prod", "status": "degraded:unhealthy", "updated_at": "2026-01-01T00:00:00Z", "server_status": True,
    "docker_compose_raw": CANARY, "docker_compose": CANARY, "config_hash": CANARY, "server": {"name": "vps-prd", "ip": CANARY},
    "applications": [
        {"name": "migrate", "status": "exited", "image": "10.0.0.1:5000/migrate:dev", "fqdn": CANARY},
        {"name": "api", "status": "restarting:unknown", "image": "10.0.0.1:5000/health-stay-api:dev", "fqdn": CANARY},
    ],
}
DATABASE = {
    "name": "health-stay-db-prod", "status": "running:healthy", "updated_at": "2026-01-01T00:00:00Z", "server_status": True,
    "image": "postgres:16-alpine", "postgres_password": CANARY, "internal_db_url": CANARY, "external_db_url": CANARY, "postgres_user": CANARY,
    "destination": {"server": {"name": "vps-prd", "settings": {"sentinel_token": CANARY}}},
    "backup_configs": [{"latest_log": {"status": "failed", "message": CANARY, "updated_at": "2026-01-01T00:00:00Z"}}],
}
LOG_HIT = {
    "_timestamp": 1_767_225_600_000_000, "severity": "ERROR", "service_name": "health-stay", "http_path": f"/users/123/{CANARY}?token={CANARY}",
    "http_status": 500, "duration_ms": 12, "body": f"falhou com {CANARY}", "password": CANARY, "err_stack": CANARY, "err_message": CANARY,
    "user_id": CANARY, "ip_hash": CANARY, "ip_prefix": CANARY, "ua": CANARY, "scan": "true",
}


def fake_session(state="connected"):
    session = live.Session("https://cofre.example:8210", None, "lab")
    session._token = CANARY
    session.expires = time.time() + 3600 if state == "connected" else time.time() - 1
    return session


def fake_vault(session):
    def vault(path):
        if session.state != "connected":
            raise live.ReadError(403)
        if path.startswith("kv/data/easygoal/_providers/coolify-x-read"):
            return {"data": {"data": {"url": "http://coolify.example", "token": CANARY}}}
        if path.startswith("kv/data/easygoal/_providers/obs-read"):
            return {"data": {"data": {"url": "http://oo.example", "orgs": {"easygoal_prod": {"id": "abc", "auth": CANARY}}}}}
        if path == "kv/metadata/easygoal/health-stay/prod":
            return {"data": {"current_version": 7, "custom_metadata": {"sync.api-prod": f"v=6 at=2026 dest={CANARY} res={CANARY}"}}}
        if path == "kv/metadata/easygoal/_providers/vercel":
            return {"data": {"updated_time": "2026-01-01T00:00:00Z", "custom_metadata": {"expires": "2020-01-01"}}}
        raise live.ReadError(404)
    session.vault = vault
    return session


def fake_remote(method, url, headers, body=None, **_k):
    if url.endswith("/services"):
        return [SERVICE]
    if url.endswith("/databases"):
        return [DATABASE]
    if url.endswith("/streams"):
        return {"list": [{"name": "health_stay", "stream_type": "logs"}]}
    if "_search" in url:
        return {"hits": [LOG_HIT]}
    raise live.ReadError(404)


class LiveTest(unittest.TestCase):
    def read(self, remote=fake_remote, session=None):
        session = session or fake_vault(fake_session())
        with mock.patch.object(live, "request_json", remote):
            return live.read_live(session, CONFIG)

    def test_nada_fora_da_allowlist_chega_ao_navegador(self):
        result = self.read()
        self.assertEqual(len(result["logs"]), 1)
        self.assertNotIn(CANARY, json.dumps(result, ensure_ascii=False))

    def test_sessao_nao_aparece_na_descricao(self):
        session = fake_session()
        self.assertNotIn(CANARY, json.dumps(session.describe("2026", [])))

    def test_estado_vem_do_coolify_e_tag_movel_e_marcada(self):
        apps = {a["id"]: a for a in self.read()["apps"]}
        prod = apps["health-stay-api"]["envs"]["prod"]
        self.assertEqual((prod["state"], prod["version"], prod["moving"]), ("degraded", "health-stay-api:dev", True))
        self.assertEqual(prod["secrets"], "Cofre na versão 7, destino na 6")
        self.assertEqual(apps["health-stay-api"]["ready"]["segredos"], "todo")
        self.assertEqual(apps["health-stay-api"]["ready"]["logs"], "ok")
        db = apps["health-stay-db"]["envs"]["prod"]
        self.assertTrue(db["backupFailed"])
        self.assertFalse(db["moving"])

    def test_rota_de_log_sem_identificador_e_sem_query(self):
        self.assertEqual(live.clean_route("/users/123/abc?token=x"), "/users/:id/abc")
        self.assertEqual(live.clean_route("/o/0f8fad5b-d9cb-469f-a165-70867728950e"), "/o/:id")
        self.assertEqual(live.clean_route("/a b"), "/:seg")
        self.assertEqual(live.clean_route("/v1/stays"), "/v1/stays")
        self.assertEqual(live.clean_route("/reset/a1b2c3d4"), "/reset/:id")
        self.assertEqual(live.clean_route("/wp-login.php"), "/wp-login.php")

    def test_evento_so_com_nome_de_evento(self):
        hit = dict(LOG_HIT, body="reset-token-a1b2")
        self.assertEqual(live.log_row(hit, "c", "prod", {}, 0)["event"], "http.request")
        self.assertEqual(live.log_row(dict(LOG_HIT, body="http.request"), "c", "prod", {}, 0)["event"], "http.request")

    def test_validade_da_conta(self):
        provider = {"name": "vercel", "kind": "vercel"}
        today = live.date(2026, 11, 5)
        state = lambda exp: live.account_row("c", provider, {"updated_time": "x", "custom_metadata": exp}, [], today)["state"]  # noqa: E731
        self.assertEqual(state({"expires": "2026-11-01"}), "expired")
        self.assertEqual(state({"expires": "2026-11-10"}), "soon")
        self.assertEqual(state({"expires": "2027-11-10"}), "ok")
        self.assertEqual(state({}), "noexp")
        self.assertEqual(live.account_row("c", provider, None, [], today)["state"], "missing")

    def test_coolify_fora_do_ar_vira_nao_lido_e_nao_exemplo(self):
        def down(method, url, headers, body=None, **_k):
            raise live.ReadError("rede")

        result = self.read(remote=down)
        app = next(a for a in result["apps"] if a["id"] == "health-stay-api")
        self.assertEqual(app["envs"]["prod"]["state"], "unread")
        self.assertEqual(app["source"], "live")
        self.assertTrue(any(p["area"] == "Aplicações" and "não respondeu" in p["text"] for p in result["problems"]))
        merged = live.merge(json.loads(server.DEMO.read_text(encoding="utf-8")) | {"sources": {}}, result, {})
        versions = [e["version"] for a in merged["apps"] if a["id"] == "health-stay-api" for e in a["envs"].values()]
        self.assertEqual(set(versions), {"Não lido"})

    def test_sessao_vencida_nao_le_nada_e_nao_mostra_exemplo_como_real(self):
        session = fake_vault(fake_session("expired"))
        self.assertEqual(session.state, "expired")
        with mock.patch.object(live, "request_json", side_effect=AssertionError("não deveria chamar a rede")):
            result = live.read_live(session, CONFIG)
        self.assertEqual({e["state"] for a in result["apps"] for e in a["envs"].values()}, {"unread"})
        self.assertEqual({a["state"] for a in result["accounts"]}, {"unread"})

    def test_cofre_selado_deixa_so_os_exemplos(self):
        done = mock.Mock(returncode=1, stdout="", stderr="erro: OpenBao selado")
        with mock.patch.object(live.subprocess, "run", return_value=done):
            session = live.Session("https://x:8210", None, "lab")
            session.open(server.ROOT)
        self.assertEqual(session.state, "failed")
        self.assertIn("selado", session.error)
        with mock.patch.object(server, "SESSION", session):
            data = server.read_data()
        self.assertEqual({a["source"] for a in data["apps"]}, {"demo"})
        self.assertEqual(data["connection"]["state"], "failed")

    def test_cliente_sem_leitura_continua_hachurado(self):
        merged = live.merge(server.read_data(), self.read(), {"state": "connected"})
        rows = {a["id"]: a["source"] for a in merged["apps"]}
        self.assertEqual(rows["health-stay-api"], "live")
        self.assertEqual(rows["backend-api"], "demo")
        self.assertEqual(rows["app-front"], "demo")
        self.assertEqual({a["source"] for a in merged["accounts"] if a["client"] == "msm"}, {"demo"})

    def test_sem_variavel_nao_conecta(self):
        with mock.patch.dict(server.os.environ, {}, clear=True), mock.patch.object(live, "open_session", side_effect=AssertionError):
            server.connect()
        self.assertIsNone(server.SESSION)

    def test_politica_da_sessao_nao_alcanca_segredo(self):
        loader = importlib.machinery.SourceFileLoader("cps_test", str(server.ROOT / "scripts" / "cp-secrets"))
        cps = importlib.util.module_from_spec(importlib.util.spec_from_loader("cps_test", loader))
        loader.exec_module(cps)
        hcl = cps.panel_hcl(CONFIG)
        self.assertIn('path "kv/data/easygoal/_providers/coolify-x-read"', hcl)
        self.assertNotIn('kv/data/easygoal/_providers/coolify-x"', hcl)
        self.assertNotIn("kv/data/easygoal/health-stay", hcl)
        self.assertNotIn("kv/data/*", hcl)

    def test_redirecionamento_nao_leva_credencial(self):
        self.assertIsNone(live.NoRedirect().redirect_request(None, None, 302, "", {}, "http://outro.example"))


if __name__ == "__main__":
    unittest.main()

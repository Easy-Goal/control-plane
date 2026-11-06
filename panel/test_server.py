"""Testes do servidor do painel. Rodar: python3 -m unittest panel/test_server.py"""
import http.client
import importlib.machinery
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import actions  # noqa: E402
import clients  # noqa: E402
import live  # noqa: E402
import server  # noqa: E402
import cp_config  # noqa: E402
import cp_paths  # noqa: E402
import tomllib  # noqa: E402

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

    def test_front_nao_depende_de_nada_de_fora(self):
        """Sem build: toda fonte existe na pasta, todo ícone usado existe e nenhum estilo inline quebra a CSP."""
        web = HERE / "web"
        css = (web / "styles.css").read_text(encoding="utf-8")
        app = (web / "app.js").read_text(encoding="utf-8")
        icons = (web / "icons.js").read_text(encoding="utf-8")
        urls = re.findall(r"url\('([^']+)'\)", css)
        self.assertTrue(urls)
        for url in urls:
            self.assertTrue((web / url).is_file(), url)
        known = set(re.findall(r"^  '([a-z0-9-]+)':", icons, flags=re.M))
        used = set(re.findall(r"icon\('([a-z0-9-]+)'\)", app)) | set(re.findall(r"\bic: '([a-z0-9-]+)'", app))
        used |= set(re.findall(r"'([a-z0-9-]+)'\]", app.split("const NAV = [")[1].split("];")[0]))
        self.assertTrue(used)
        self.assertEqual(used - known, set())
        self.assertNotIn(' style="', app)
        self.assertNotRegex(css + app, r"https?://(?!127\.0\.0\.1|vercel\.com|railway\.com)[a-z]+\.(googleapis|gstatic|jsdelivr|unpkg|cloudflare)")

    def test_comandos_do_coolify_sempre_indicam_o_cliente(self):
        """Sem --client, o cp-coolify usa a Aurora Software: a VPS do cliente iria para o time errado."""
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
                mock.patch.object(server, "ROOT", Path("/nao/existe")), \
                mock.patch.object(server, "LAYOUT", cp_paths.Layout(program="/nao/existe", env={"CP_HOME": "/nao/existe"})):
            device = server.read_device()
        states = {c["id"]: c["state"] for c in device["checks"]}
        self.assertEqual(states["docker"], "missing")
        self.assertEqual(states["vault_local"], "missing")
        self.assertNotIn("vault_lab", states)  # sem a pasta sim/, não há laboratório para procurar
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
    "slug": "aurora",
    "provider": [{"name": "coolify-x", "kind": "coolify"}, {"name": "coolify-x-read", "kind": "coolify"},
                 {"name": "vercel", "kind": "vercel"}, {"name": "obs-read", "kind": "openobserve"}],
    "project": [{"slug": "reserva", "target": [
        {"name": "api-prod", "provider": "coolify-x", "environment": "prod", "resource_name": "reserva-api-prod"},
    ]}],
}]}
SERVICE = {
    "name": "reserva-api-prod", "status": "degraded:unhealthy", "updated_at": "2026-01-01T00:00:00Z", "server_status": True,
    "docker_compose_raw": CANARY, "docker_compose": CANARY, "config_hash": CANARY, "server": {"name": "vps-prd", "ip": CANARY},
    "applications": [
        {"name": "migrate", "status": "exited", "image": "10.0.0.1:5000/migrate:dev", "fqdn": CANARY},
        {"name": "api", "status": "restarting:unknown", "image": "10.0.0.1:5000/reserva-api:dev", "fqdn": CANARY},
    ],
}
DATABASE = {
    "name": "reserva-db-prod", "status": "running:healthy", "updated_at": "2026-01-01T00:00:00Z", "server_status": True,
    "image": "postgres:16-alpine", "postgres_password": CANARY, "internal_db_url": CANARY, "external_db_url": CANARY, "postgres_user": CANARY,
    "destination": {"server": {"name": "vps-prd", "settings": {"sentinel_token": CANARY}}},
    "backup_configs": [{"latest_log": {"status": "failed", "message": CANARY, "updated_at": "2026-01-01T00:00:00Z"}}],
}
LOG_HIT = {
    "_timestamp": 1_767_225_600_000_000, "severity": "ERROR", "service_name": "reserva", "http_path": f"/users/123/{CANARY}?token={CANARY}",
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
        if path.startswith("kv/data/aurora/_providers/coolify-x-read"):
            return {"data": {"data": {"url": "http://coolify.example", "token": CANARY}}}
        if path.startswith("kv/data/aurora/_providers/obs-read"):
            return {"data": {"data": {"url": "http://oo.example", "orgs": {"aurora_prod": {"id": "abc", "auth": CANARY}}}}}
        if path == "kv/metadata/aurora/reserva/prod":
            return {"data": {"current_version": 7, "custom_metadata": {"sync.api-prod": f"v=6 at=2026 dest={CANARY} res={CANARY}"}}}
        if path == "kv/metadata/aurora/_providers/vercel":
            return {"data": {"updated_time": "2026-01-01T00:00:00Z", "custom_metadata": {"expires": "2020-01-01"}}}
        raise live.ReadError(404)
    session.vault = vault
    return session


def fake_remote(method, url, headers, body=None, **_k):
    if url.endswith("/services"):
        return [SERVICE]
    if url.endswith("/databases"):
        return [DATABASE]
    if url.endswith("/servers"):
        return [{"name": "vps-prd", "settings": {"is_usable": True}, "ip": CANARY}]
    if url.endswith("/streams"):
        return {"list": [{"name": "reserva", "stream_type": "logs"}]}
    if "_search" in url:
        return {"hits": [LOG_HIT]}
    raise live.ReadError(404)


class ReleaseTest(unittest.TestCase):
    def env(self, image, release=None):
        return live.service_env({"status": "running:healthy", "server_status": True, "applications": [{"status": "running:healthy", "image": image}]}, release=release)

    def test_compose_sem_resolver_nao_vira_tag(self):
        env = self.env("r:5000/api:${IMAGE_TAG:-dev}")
        self.assertEqual((env["version"], env["moving"], env["tag"]), ("api:dev", True, ""))

    def test_tag_vem_do_registro_do_release(self):
        env = self.env("r:5000/api:${IMAGE_TAG:-dev}", {"tag": "1.3.0-4f1de39", "at": "2026-01-01T00:00:00Z"})
        self.assertEqual((env["version"], env["moving"], env["tag"], env["commit"], env["whenLabel"]), ("api:1.3.0-4f1de39", False, "1.3.0-4f1de39", "4f1de39", "Último release"))

    def test_sem_imagem_nao_e_tag_movel(self):
        self.assertFalse(self.env(None)["moving"])


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
        prod = apps["reserva-api"]["envs"]["prod"]
        self.assertEqual((prod["state"], prod["version"], prod["moving"]), ("degraded", "reserva-api:dev", True))
        self.assertEqual(prod["secrets"], "Cofre na versão 7, destino na 6")
        self.assertEqual(apps["reserva-api"]["ready"]["segredos"], "todo")
        self.assertEqual(apps["reserva-api"]["ready"]["logs"], "ok")
        db = apps["reserva-db"]["envs"]["prod"]
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
        app = next(a for a in result["apps"] if a["id"] == "reserva-api")
        self.assertEqual(app["envs"]["prod"]["state"], "unread")
        self.assertEqual(app["source"], "live")
        self.assertTrue(any(p["area"] == "Aplicações" and "não respondeu" in p["text"] for p in result["problems"]))
        merged = live.merge(json.loads(server.DEMO.read_text(encoding="utf-8")) | {"sources": {}}, result, {})
        versions = [e["version"] for a in merged["apps"] if a["id"] == "reserva-api" for e in a["envs"].values()]
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
        self.assertEqual(rows["reserva-api"], "live")
        self.assertEqual(rows["backend-api"], "demo")
        self.assertEqual(rows["app-front"], "demo")
        self.assertEqual({a["source"] for a in merged["accounts"] if a["client"] == "horizonte"}, {"demo"})

    def test_sem_variavel_nao_conecta(self):
        with mock.patch.dict(server.os.environ, {}, clear=True), mock.patch.object(live, "open_session", side_effect=AssertionError):
            server.connect()
        self.assertIsNone(server.SESSION)

    def test_politica_da_sessao_nao_alcanca_segredo(self):
        loader = importlib.machinery.SourceFileLoader("cps_test", str(server.ROOT / "scripts" / "cp-secrets"))
        cps = importlib.util.module_from_spec(importlib.util.spec_from_loader("cps_test", loader))
        loader.exec_module(cps)
        hcl = cps.panel_hcl(CONFIG)
        self.assertIn('path "kv/data/aurora/_providers/coolify-x-read"', hcl)
        self.assertNotIn('kv/data/aurora/_providers/coolify-x"', hcl)
        self.assertNotIn("kv/data/aurora/reserva", hcl)
        self.assertNotIn("kv/data/*", hcl)

    def test_redirecionamento_nao_leva_credencial(self):
        self.assertIsNone(live.NoRedirect().redirect_request(None, None, 302, "", {}, "http://outro.example"))


APPS = [
    {"id": "reserva-api", "client": "aurora", "name": "reserva-api", "type": "api-coolify", "source": "live", "envs": {"prod": {}, "staging": {}}},
    {"id": "reserva-db", "client": "aurora", "name": "reserva-db", "type": "db-coolify", "source": "live", "envs": {"prod": {}}},
    {"id": "app-front", "client": "aurora", "name": "app-front", "type": "front-vercel", "source": "demo", "envs": {"prod": {}}},
]


class PlanTest(unittest.TestCase):
    def plan(self, **req):
        return actions.build_plan(req, CONFIG, APPS)

    def refused(self, **req):
        with self.assertRaises(actions.Refused):
            self.plan(**req)

    def test_argumentos_vem_do_inventario(self):
        plan = self.plan(action="restart", client="aurora", app="reserva-api", env="staging")
        self.assertEqual(plan["argv"], ["cp-coolify", "--client", "aurora", "--provider", "coolify-x", "service", "restart", "reserva-api-staging"])
        self.assertEqual(self.plan(action="deploy", client="aurora", app="reserva-api", env="staging")["argv"][-1], "--latest")
        self.assertEqual(self.plan(action="sync_plan", client="aurora")["argv"], ["cp-secrets", "sync", "plan", "aurora", "--json"])

    def test_recusa_acao_e_alvo_fora_da_lista(self):
        self.refused(action="rm -rf", client="aurora")
        self.refused(action="restart", client="outro", app="reserva-api", env="staging")
        self.refused(action="restart", client="aurora", app="inexistente", env="staging")
        self.refused(action="restart", client="aurora", app="reserva-api", env="dev")
        self.refused(action="restart", client="aurora", app="app-front", env="prod")  # linha de exemplo
        self.refused(action="sync_apply", client="aurora", target="inexistente")
        self.refused(action="test_account", client="aurora", provider="coolify-x-read")
        self.refused(action="test_account", client="aurora", provider="obs-read")
        self.refused(action="deploy", client="aurora", app="reserva-db", env="prod", confirm="reserva-db")
        self.refused(action="backup", client="aurora", app="reserva-api", env="staging")

    def test_recusa_injecao_no_alvo(self):
        for bad in ("reserva-api; rm -rf /", "--latest", "../x", "a b", "$(id)", "A", "", None, 3, ["x"]):
            self.refused(action="restart", client="aurora", app=bad, env="staging")
            self.refused(action="sync_plan", client=bad)
            self.refused(action="sync_apply", client="aurora", target=bad)

    def test_prod_exige_o_nome_digitado(self):
        self.refused(action="restart", client="aurora", app="reserva-api", env="prod")
        self.refused(action="restart", client="aurora", app="reserva-api", env="prod", confirm="errado")
        self.refused(action="sync_apply", client="aurora", target="api-prod")
        self.assertTrue(self.plan(action="restart", client="aurora", app="reserva-api", env="prod", confirm="reserva-api"))
        self.assertTrue(self.plan(action="sync_apply", client="aurora", target="api-prod", confirm="api-prod"))

    def test_nome_de_alvo_longo_continua_legivel(self):
        line = "[erro] testeacme/testeacme-api/testeacme-api-dev-muito-comprido-mesmo: faltam no cofre: APP_NOTE"
        self.assertEqual(actions.scrub(line), line)
        self.assertIn("[oculto]", actions.scrub("valor " + "a1b2c3d4" * 8))
        self.assertIn("[oculto]", actions.scrub("valor abc-" + "a1b2c3d4" * 6))

    def test_saida_limpa(self):
        for raw in ("Bearer abc.def", "token 12|" + "a" * 30, "postgresql://u:senha@h/db", "ghp_" + "a" * 30, "x" * 50, "eyJabcdefghijkl.abc"):
            self.assertIn("[oculto]", actions.scrub(raw), raw)
        self.assertEqual(actions.scrub("erro: POST /v1/x → 422: valor=segredo"), "erro: POST /v1/x → 422")
        self.assertEqual(actions.scrub("\x1b[31m[ok] iguais: 8\x1b[0m"), "[ok] iguais: 8")
        self.assertEqual(actions.scrub("/data/x/pg-dump-reserva-1793921530-pxycpp1tazbgv9xsj8prsncx.dmp"), "[ok] backup gravado: pg-dump-reserva-1793921530-pxycpp1tazbgv9xsj8prsncx.dmp")


class ActionsHttpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        cls.srv = server.make_server(0)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.dir.cleanup()

    def setUp(self):
        self.session = fake_session()
        self.release = threading.Event()
        code = "import sys; print('[ok] feito'); print('Bearer " + CANARY + "'); sys.exit(0)"
        self.runner = actions.Runner(server.ROOT, Path(self.dir.name) / str(time.time()), self.session,
                                     spawn=lambda argv: subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
        cache = mock.Mock()
        cache.get.return_value = ({"apps": APPS}, "2026")
        cache.config.return_value = CONFIG
        for patcher in (mock.patch.object(server, "RUNNER", self.runner), mock.patch.object(server, "LIVE", cache)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def post(self, body=None, key="ok", host=None, origin="same", ctype="application/json", site="same-origin", path="/api/actions"):
        host = host or f"127.0.0.1:{self.port}"
        payload = json.dumps(body if body is not None else {"action": "sync_plan", "client": "aurora"}).encode()
        headers = {"Host": host, "Content-Type": ctype}
        if key:
            headers["X-CP-Key"] = self.runner.key if key == "ok" else key
        if origin:
            headers["Origin"] = f"http://{host}" if origin == "same" else origin
        if site:
            headers["Sec-Fetch-Site"] = site
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        conn.request("POST", path, payload, headers)
        res = conn.getresponse()
        out = json.loads(res.read() or b"{}")
        conn.close()
        return res.status, out

    def test_pedido_forjado_e_recusado(self):
        self.assertEqual(self.post(key=None)[0], 403)
        self.assertEqual(self.post(key="errada")[0], 403)
        self.assertEqual(self.post(origin="https://evil.example")[0], 403)
        self.assertEqual(self.post(site="cross-site")[0], 403)
        self.assertEqual(self.post(host="evil.example")[0], 403)
        self.assertEqual(self.post(ctype="text/plain")[0], 415)
        self.assertEqual(self.post(path="/api/data")[0], 405)
        self.assertFalse(self.runner.rows())

    def test_sem_acoes_ligadas_post_e_405(self):
        with mock.patch.object(server, "RUNNER", None):
            self.assertEqual(self.post()[0], 405)

    def test_sessao_vencida_e_outro_cofre_desligam(self):
        self.session.expires = time.time() - 1
        self.assertEqual(self.post()[0], 403)
        self.session.expires = time.time() + 3600
        self.session.target = "local"
        self.assertEqual(self.post()[0], 403)

    def wait_done(self):
        for _ in range(100):
            rows = self.runner.rows()
            if rows and rows[0]["result"] != "running":
                return rows[0]
            time.sleep(0.05)
        self.fail("a ação não terminou")

    def test_acao_roda_limpa_e_grava(self):
        status, out = self.post({"action": "test_account", "client": "aurora", "provider": "vercel"})
        self.assertEqual(status, 202)
        self.assertEqual(out["job"]["result"], "running")
        job = self.wait_done()
        self.assertEqual(job["result"], "ok")
        self.assertIn("[ok] feito", job["steps"])
        self.assertNotIn(CANARY, json.dumps(job))
        saved = self.runner.state_file
        self.assertEqual(saved.stat().st_mode & 0o077, 0)
        self.assertNotIn(CANARY, saved.read_text(encoding="utf-8"))

    def test_falha_do_script_aparece_como_falha(self):
        self.runner.spawn = lambda argv: subprocess.Popen([sys.executable, "-c", "import sys; print('erro: POST /x → 422: valor=segredo'); sys.exit(1)"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(self.post({"action": "test_account", "client": "aurora", "provider": "vercel"})[0], 202)
        job = self.wait_done()
        self.assertEqual(job["result"], "err")
        self.assertNotIn("segredo", json.dumps(job))

    def test_chave_nao_vai_para_os_dados(self):
        data = self.runner.apply_to({"activity": [], "diverge": [], "sources": {}, "connection": {}})
        self.assertNotIn(self.runner.key, json.dumps(data))
        self.assertNotIn("key", data["connection"]["actions"])

    def test_mesmo_alvo_nao_roda_duas_vezes(self):
        gate = threading.Event()
        proc = mock.Mock(stdout=iter([]), stderr=iter([]), returncode=0)
        proc.wait.side_effect = lambda: gate.wait(5)
        self.runner.spawn = lambda argv: proc
        self.addCleanup(gate.set)
        self.assertEqual(self.post()[0], 202)
        self.assertEqual(self.post()[0], 409)

    def test_divergencia_vem_so_com_nomes(self):
        rows = actions.drift_rows("aurora", {"targets": [
            {"target": "api-prod", "environment": "prod", "drift": ["JWT_SECRET"]}, {"target": "api-dev", "environment": "dev", "drift": []}]})
        self.assertEqual([r["keys"] for r in rows], [["JWT_SECRET"]])


SPEC = {"name": "Loja Teste", "slug": "lojateste", "platforms": ["vercel", "coolify"], "logs": True,
        "projects": [{"slug": "loja-web", "type": "front-vercel"}, {"slug": "loja-api", "type": "api-coolify"}],
        "variables": [{"name": "JWT_SECRET", "origin": "generated"}, {"name": "DATABASE_URL", "origin": "manual"}]}


class ClientFileTest(unittest.TestCase):
    def bad(self, **changes):
        with self.assertRaises(clients.SpecError):
            clients.validate({**SPEC, **changes})

    def test_arquivo_gerado_e_coerente(self):
        data = tomllib.loads(clients.render(clients.validate(SPEC)))["client"][0]
        self.assertEqual({p["name"] for p in data["provider"]}, {"vercel", "coolify", "coolify-read"})
        api = next(p for p in data["project"] if p["slug"] == "loja-api")
        self.assertEqual([t["resource_name"] for t in api["target"]], ["loja-api-dev", "loja-api-prod"])
        self.assertIn("OBS_OTLP_ENDPOINT", api["target"][0]["keys"])
        self.assertEqual(api["generate"], ["JWT_SECRET"])
        web = next(p for p in data["project"] if p["slug"] == "loja-web")
        self.assertEqual([t["vercel_targets"] for t in web["target"]], [["preview"], ["production"]])

    def test_recusa_pedido_invalido(self):
        self.bad(slug="Loja")
        self.bad(slug="loja-teste")  # o hífen quebraria o nome da org de logs
        self.bad(slug="admin")
        self.bad(name="x")
        self.bad(name="a\n[[client]]\nslug = \"x\"")
        self.bad(platforms=["github"])
        self.bad(platforms=["droplet", "vercel"])
        self.bad(platforms=["vercel", "rm -rf"])
        self.bad(projects=[])
        self.bad(projects=[{"slug": "x; rm", "type": "front-vercel"}])
        self.bad(projects=[{"slug": "api", "type": "api-railway"}])  # plataforma não escolhida
        self.bad(variables=[{"name": "minha chave"}])
        with self.assertRaises(clients.SpecError):
            clients.validate(SPEC, existing={"lojateste"})

    def test_nome_com_aspas_nao_escapa_do_campo(self):
        spec = clients.validate({**SPEC, "name": 'Loja "x" = [1] # Ação'})
        data = tomllib.loads(clients.render(spec))["client"][0]
        self.assertEqual(data["name"], 'Loja "x" = [1] # Ação')
        self.assertEqual(data["slug"], "lojateste")

    def test_nunca_sobrescreve(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = clients.validate(SPEC)
            path = clients.write(Path(tmp), spec)
            before = path.read_text(encoding="utf-8")
            with self.assertRaises(clients.SpecError):
                clients.write(Path(tmp), clients.validate({**SPEC, "name": "Outro nome"}))
            self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_configuracao_junta_os_arquivos_e_recusa_conflito(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            main = root / "secrets.toml"
            main.write_text('[[client]]\nslug = "aurora"\n', encoding="utf-8")
            folder = root / "clients"
            clients.write(folder, clients.validate(SPEC))
            self.assertEqual([c["slug"] for c in cp_config.load(main, folder)["client"]], ["aurora", "lojateste"])
            (folder / "outro.toml").write_text('[[client]]\nslug = "lojateste"\n', encoding="utf-8")
            with self.assertRaises(cp_config.ConfigError):
                cp_config.load(main, folder)
            (folder / "outro.toml").write_text('[[client]]\nslug = "aurora"\n', encoding="utf-8")
            with self.assertRaises(cp_config.ConfigError):
                cp_config.load(main, folder)

    def test_preparacao_nao_leva_valor_e_so_nomes(self):
        client = tomllib.loads(clients.render(clients.validate(SPEC)))["client"][0]
        steps = clients.prepare_steps(client, "openobserve-sim")
        self.assertEqual(steps[0]["argv"], ["cp-secrets", "backup"])
        self.assertEqual(steps[1]["argv"], ["cp-secrets", "apply", "--client", "lojateste"])  # nunca o apply de todos
        self.assertEqual(steps[-1]["argv"], ["cp-obs", "panel-read"])
        self.assertTrue(all(s.get("input") in (None, "development", "production") for s in steps))

    def test_promover_usa_a_tag_lida(self):
        apps = [{"id": "api", "client": "aurora", "name": "api", "type": "api-coolify", "source": "live",
                 "envs": {"staging": {"tag": "1.3.0-abc1234"}, "prod": {"tag": "1.2.0-abc0000"}}}]
        plan = actions.build_plan({"action": "promote", "client": "aurora", "app": "api", "confirm": "api", "tag": "pedido-maldoso"}, CONFIG, apps)
        self.assertEqual(plan["argv"][-3:], ["release", "api-prod", "1.3.0-abc1234"])
        apps[0]["envs"]["staging"]["tag"] = ""
        with self.assertRaises(actions.Refused):
            actions.build_plan({"action": "promote", "client": "aurora", "app": "api", "confirm": "api"}, CONFIG, apps)


class LabOnlyTest(unittest.TestCase):
    def test_acoes_so_no_laboratorio(self):
        with mock.patch.dict(server.os.environ, {"CP_BAO_ADDR": "http://127.0.0.1:8200"}), self.assertRaises(SystemExit):
            server.connect(True)
        with mock.patch.dict(server.os.environ, {"CP_BAO_ADDR": "https://cp.tailnet.ts.net:8200"}), self.assertRaises(SystemExit):
            server.connect(True)
        with mock.patch.dict(server.os.environ, {}, clear=True), self.assertRaises(SystemExit):
            server.connect(True)


if __name__ == "__main__":
    unittest.main()

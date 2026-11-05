"""Testes do servidor do painel. Rodar: python3 -m unittest panel/test_server.py"""
import http.client
import json
import re
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

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


if __name__ == "__main__":
    unittest.main()

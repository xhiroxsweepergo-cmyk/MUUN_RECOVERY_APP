import importlib.util, json, os, socket, ssl, sys, threading, unittest, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("app", os.path.join(ROOT, "MUUN_RECOVERY_APP.py"))
app = importlib.util.module_from_spec(spec); spec.loader.exec_module(app)


class T(unittest.TestCase):
    def test_tls_acepta_autofirmado(self):
        c = app._tls_context()
        self.assertEqual(c.verify_mode, ssl.CERT_NONE); self.assertFalse(c.check_hostname)

    def test_ranking(self):
        lines = ["a.x:50002:s", "b.x:50002:s", "c.x:50002:s", "d.x:50002:s", "A.X:50002:s", "e.x:50002:s"]
        st = {0: {"ok": True, "latency": 300, "height": "900000"},
              1: {"ok": True, "latency": 100, "height": "900001"},
              2: {"ok": False, "latency": None, "height": ""},
              3: {"ok": True, "latency": 50, "height": "899990"}}   # atrasado
        r = app.rank_servers(lines, st)
        hosts = [p[0] for p in r]
        self.assertEqual(hosts, ["b.x", "a.x", "e.x", "d.x", "c.x"])   # buenos, sin comprobar, atrasado, caido; sin duplicado

    def test_carga_sin_duplicados(self):
        p = os.path.join(tempfile.mkdtemp(), "s.json")
        json.dump(["a.x:50002:s", "A.X:50002:s", "b.x:50002:s"], open(p, "w"))
        old = app.SERVERS_FILE; app.SERVERS_FILE = __import__("pathlib").Path(p)
        try: self.assertEqual(app.load_server_lines(), ["a.x:50002:s", "b.x:50002:s"])
        finally: app.SERVERS_FILE = old

    def test_consulta_a_servidor_tls_autofirmado(self):
        import subprocess, shutil
        if not shutil.which("openssl"): self.skipTest("sin openssl")
        d = tempfile.mkdtemp(); k, c = os.path.join(d, "k.pem"), os.path.join(d, "c.pem")
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", k, "-out", c,
                        "-days", "1", "-subj", "/CN=nada.invalid"], check=True, capture_output=True)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.load_cert_chain(c, k)
        srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(2)
        def run():
            conn, _ = srv.accept(); conn = ctx.wrap_socket(conn, server_side=True); f = conn.makefile("rwb")
            for ln in f:
                m = json.loads(ln)
                res = {"server.version": ["Fake", "1.4"], "blockchain.scripthash.get_history": [],
                       "blockchain.scripthash.listunspent": [{"tx_hash": "a" * 64, "tx_pos": 0, "value": 1234, "height": 5}],
                       "blockchain.scripthash.get_balance": {"confirmed": 1234, "unconfirmed": 0}}[m["method"]]
                f.write((json.dumps({"id": m["id"], "result": res}) + "\n").encode()); f.flush()
        threading.Thread(target=run, daemon=True).start()
        v, h, u, b = app.electrum_address_data("127.0.0.1", srv.getsockname()[1], True, "00" * 32, timeout=5)
        self.assertEqual(u[0]["value"], 1234); srv.close()

if __name__ == "__main__": unittest.main()

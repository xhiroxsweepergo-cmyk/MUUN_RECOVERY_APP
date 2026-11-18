"""Pruebas Python de MUUN RECOVERY PRO (sin red, sin GUI).

Ejecutar:  python3 -m unittest discover -s tests -v
"""
import hashlib
import importlib.util
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("muun_app", ROOT / "ui" / "app.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

SERVERS_GO = (ROOT / "go" / "servers.go").read_text(encoding="utf-8", errors="replace")


class Branding(unittest.TestCase):
    def test_nombre(self):
        self.assertEqual(m.APP_NAME, "MUUN RECOVERY PRO")

    def test_cabecera_centrada_en_codigo(self):
        src = (ROOT / "ui" / "app.py").read_text(encoding="utf-8")
        for txt in ("MUUN RECOVERY PRO", "VERSION 1.0", "RECOVERY • ELECTRUM • BITCOIN"):
            self.assertRegex(src, r'(?s)text="%s".{0,200}?\.pack\(fill="x"' % re.escape(txt))

    def test_tarjetas_y_banner(self):
        self.assertEqual([t for t, _ in m.FEATURES], ["Electrum", "Recovery Scan", "TXID / UTXO", "Transferencias"])
        self.assertEqual(m.FEATURES[3][1], "Firma y autorización independiente.")
        self.assertEqual(m.BANNER_TITLE, "RECUPERACIÓN Y TRANSFERENCIA SEPARADAS")
        self.assertIn("Confirmación manual antes de firmar", m.BANNER_TEXT)


class ServersGo(unittest.TestCase):
    def test_importa_todos_por_defecto(self):
        lines = m.parse_servers_go(SERVERS_GO)
        self.assertEqual(len(lines), 64)
        self.assertEqual(lines[0], "electrum.coinext.com.br:50002:s")

    def test_lista_por_defecto_incluye_todos_los_de_servers_go(self):
        defaults = {tuple(m.parse_server(x)[:2]) for x in m.DEFAULT_SERVERS}
        for line in m.parse_servers_go(SERVERS_GO, limit=10000):
            h, p, _ = m.parse_server(line)
            self.assertIn((h, p), defaults)
        self.assertGreaterEqual(len(m.DEFAULT_SERVERS), 64)

    def test_formato_y_parseable(self):
        for line in m.parse_servers_go(SERVERS_GO, limit=1000):
            host, port, ssl_ = m.parse_server(line)
            self.assertTrue(host)
            self.assertTrue(ssl_)
            self.assertTrue(1 <= port <= 65535)

    def test_sin_duplicados_ignorando_mayusculas(self):
        lines = m.parse_servers_go(SERVERS_GO, limit=1000)
        self.assertEqual(len(lines), len(set(lines)))

    def test_ignora_texto_fuera_de_publicservers(self):
        self.assertEqual(m.parse_servers_go('x := "a.b:50002",\n'), [])

    def test_crlf(self):
        self.assertEqual(len(m.parse_servers_go(SERVERS_GO.replace("\n", "\r\n"))), 64)

    def test_limite(self):
        self.assertEqual(len(m.parse_servers_go(SERVERS_GO, limit=5)), 5)


class Direcciones(unittest.TestCase):
    def test_scripthash_p2wpkh(self):
        prog = bytes.fromhex("e8df018c7e326cc253faac7e46cdc51e68542c42")
        script = b"\x00\x14" + prog
        esperado = hashlib.sha256(script).digest()[::-1].hex()
        self.assertEqual(m.address_to_scripthash("bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq"), esperado)

    def test_rechaza_invalidas(self):
        for bad in ("", "1BoatSLRHtKNngkdXEeobR76b53LETtpyT", "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdx",
                    "tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx"):
            with self.assertRaises(Exception, msg=bad):
                m.address_to_scripthash(bad)


class RecoveryCode(unittest.TestCase):
    def test_normaliza(self):
        raw = "ABCD2345EFGH6723IJKL4567MNOP2345"
        self.assertEqual(m.normalize_code(raw), "ABCD-2345-EFGH-6723-IJKL-4567-MNOP-2345")
        self.assertEqual(m.normalize_code(" ".join(raw[i:i + 4] for i in range(0, 32, 4))),
                         "ABCD-2345-EFGH-6723-IJKL-4567-MNOP-2345")

    def test_invalido(self):
        self.assertEqual(m.normalize_code("corto"), "")
        self.assertEqual(m.normalize_code("abcd!234efgh5678ijkl9012mnop3456"), "")

    def test_mask_no_filtra(self):
        code = "ABCD-2345-EFGH-6723-IJKL-4567-MNOP-2345"
        self.assertNotIn("2345", m.mask(code))


class SalidaEscaner(unittest.TestCase):
    def test_sin_fondos(self):
        self.assertEqual(m.parse_scan_output(["Scan complete", "No funds were discovered"]), (0, 0))

    def test_utxo_txid(self):
        txid = "a" * 64
        utxos, sats = m.parse_scan_output([f"{txid}:0", "Sats found: 12345", "1 UTXO"])
        self.assertEqual((utxos, sats), (1, 12345))

    def test_formato_btc(self):
        self.assertEqual(m.parse_scan_output(["total 0.5 BTC"])[1], 50_000_000)

    def test_ilegible(self):
        self.assertEqual(m.parse_scan_output(["???"]), (0, None))

    def test_fmt_btc(self):
        self.assertEqual(m.fmt_btc(123456789), "1.23456789 BTC")


class Autorizacion(unittest.TestCase):
    def test_exige_frase_y_casilla(self):
        self.assertTrue(m.authorization_ok("AUTORIZO ENVIAR", True))
        self.assertTrue(m.authorization_ok("  AUTORIZO ENVIAR  ", True))
        self.assertFalse(m.authorization_ok("AUTORIZO ENVIAR", False))
        self.assertFalse(m.authorization_ok("autorizo enviar", True))
        self.assertFalse(m.authorization_ok("", True))
        self.assertFalse(m.authorization_ok(None, True))

    def test_envio_no_usa_askyesno(self):
        src = (ROOT / "ui" / "app.py").read_text(encoding="utf-8")
        self.assertNotIn("askyesno", src)
        calls = src.count("_authorize_send(confirmation)") + src.count("_authorize_send(resumen)")
        self.assertGreaterEqual(calls, 2)


class Independencia(unittest.TestCase):
    def test_escaneo_no_llama_envio(self):
        src = (ROOT / "ui" / "app.py").read_text(encoding="utf-8")
        scan = src[src.index("def _scan_worker"):src.index("def scan_addresses_dialog")]
        self.assertNotIn("execute_real_transfer", scan)
        self.assertIn("extra_args", scan)
        src = (ROOT / "core" / "scanner_muun.py").read_text(encoding="utf-8")
        self.assertIn('flags = ["-only-scan"]', src)

    def test_recovery_code_solo_por_stdin(self):
        src = (ROOT / "ui" / "app.py").read_text(encoding="utf-8")
        scan = src[src.index("def _scan_worker"):src.index("def scan_addresses_dialog")]
        self.assertNotRegex(scan, r"cmd\s*=\s*\[[^\]]*acct\[")


class Barrido(unittest.TestCase):
    def setUp(self):
        src = (ROOT / "ui" / "app.py").read_text(encoding="utf-8")
        self.fn = src[src.index("def start_official_transfer"):src.index("def stop_scan")]

    def test_exige_autorizacion_antes_de_lanzar(self):
        self.assertLess(self.fn.index("_authorize_send(resumen)"), self.fn.index("subprocess.Popen"))

    def test_consola_interactiva_sin_stdin_ni_codigo(self):
        self.assertIn("CREATE_NEW_CONSOLE", self.fn)
        self.assertNotIn("stdin=", self.fn)
        self.assertNotIn(".stdin", self.fn)
        self.assertNotIn('acct["code"]', self.fn)
        self.assertNotIn("-only-scan", self.fn)

    def test_limpia_temporal(self):
        self.assertIn("shutil.rmtree(tmp", self.fn)


class SinSimulacion(unittest.TestCase):
    def test_sin_datos_simulados(self):
        src = (ROOT / "ui" / "app.py").read_text(encoding="utf-8").lower()
        for banned in ("import random", "simul", "demo", "fake", "dummy"):
            self.assertNotIn(banned, src, banned)


class InformePorBloques(unittest.TestCase):
    H = [{"tx_hash": "b" * 64, "height": 800}, {"tx_hash": "a" * 64, "height": 700},
         {"tx_hash": "c" * 64, "height": 0}]
    U = [{"tx_hash": "b" * 64, "tx_pos": 1, "value": 5000, "height": 800}]

    def test_orden_ascendente_y_mempool_al_final(self):
        rep = m.build_block_report(self.H, self.U)
        self.assertEqual([k for k, _ in rep], [700, 800, 0])

    def test_marca_utxo_y_gastada(self):
        rep = dict(m.build_block_report(self.H, self.U))
        self.assertEqual(rep[800][0]["utxos"], [(1, 5000)])
        self.assertEqual(rep[700][0]["utxos"], [])

    def test_desde_bloque(self):
        rep = m.build_block_report(self.H, self.U, from_height=750)
        self.assertEqual([k for k, _ in rep], [800, 0])


class FlagsEscaner(unittest.TestCase):
    def test_solo_lectura_siempre(self):
        for c in (False, True):
            self.assertEqual(m.build_scan_flags("", c)[0], "-only-scan")

    def test_profundo_y_servidor(self):
        self.assertEqual(m.build_scan_flags("electrum.blockstream.info:50002", True),
                         ["-only-scan", "-generate-contacts", "-electrum-server=electrum.blockstream.info:50002"])

    def test_servidor_invalido(self):
        for bad in ("sinpuerto", "a b:50002", "x:99999", "x:50002;calc", "-x:1"):
            with self.assertRaises(ValueError, msg=bad):
                m.build_scan_flags(bad)

    def test_worker_usa_los_flags(self):
        src = (ROOT / "ui" / "app.py").read_text(encoding="utf-8")
        self.assertIn("cmd = [engine, *extra_args, str(pdf)]", src)


if __name__ == "__main__":
    unittest.main()

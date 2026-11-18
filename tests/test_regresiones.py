"""Pruebas de regresión de la GUI y de las correcciones de la versión 5.9.3 PRO.

Cubren los fallos detectados en la revisión:
  * facturas Lightning pegadas con espacios o saltos de línea,
  * textos de diálogo con «\\n» literal en lugar de un salto de línea real,
  * entradas de «Máx. entradas» no numéricas,
  * lista de servidores empaquetada (electrum_servers.json),
  * detección del binario en bin/recovery-tool.exe.

Ejecutar:  python -m unittest discover -s tests -v
"""
import importlib.util
import io
import json
import queue
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "ui" / "app.py"
spec = importlib.util.spec_from_file_location("muun_elite", SRC)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class DialogosFalsos:
    """Sustituye los messagebox de Tk para que las pruebas no abran ventanas."""

    def __init__(self):
        self.errores = []
        self.avisos = []
        self.info = []

    def showerror(self, *a, **k):
        self.errores.append(a)

    def showwarning(self, *a, **k):
        self.avisos.append(a)

    def showinfo(self, *a, **k):
        self.info.append(a)

    def askstring(self, *a, **k):  # pragma: no cover - solo si se llama
        return ""


@unittest.skipIf(m.tk is None, "Tkinter no disponible")
class GuiRegresiones(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # En CI/headless no hay servidor gráfico: omitir solo las pruebas que
        # necesitan una ventana real; en Windows con Tk se ejecutan normalmente.
        try:
            cls.root = m.tk.Tk()
            cls.root.withdraw()
        except Exception as exc:
            raise unittest.SkipTest(f"No hay entorno gráfico Tk disponible: {exc}")
        cls.dialogos = DialogosFalsos()
        cls._mb_original = m.messagebox
        m.messagebox = cls.dialogos
        cls.app = m.App(cls.root)

    @classmethod
    def tearDownClass(cls):
        m.messagebox = cls._mb_original
        cls.app._closing = True
        cls.root.destroy()

    def setUp(self):
        self.dialogos.errores.clear()
        self.dialogos.avisos.clear()
        self.app.transfer_destination_var.set("")

    def test_destino_btc_invalido_avisa(self):
        self.app.transfer_destination_var.set("bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdx")
        self.app.preview_transfer()
        self.assertEqual(len(self.dialogos.errores), 1)

    def test_destino_btc_valido_no_avisa(self):
        self.app.transfer_destination_var.set("bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq")
        self.app.preview_transfer()
        self.assertEqual(self.dialogos.errores, [])
        texto = self.app.transfer_preview.get("1.0", "end")
        self.assertIn("NO SE HA ENVIADO NINGÚN FONDO", texto)
        self.assertIn("bc1qar0srrr", texto)  # el resumen enmascara el centro

    def test_max_entradas_no_numerico_no_revienta(self):
        self.app.limit_var.set("no-es-un-numero")
        with tempfile.TemporaryDirectory() as tmp:
            z = Path(tmp) / "muun.zip"
            with zipfile.ZipFile(z, "w") as zf:
                zf.writestr("a/EmergencyKit.pdf", b"%PDF-1.4\n")
            self.app.load_source("zip", str(z))   # debe usar el límite por defecto, sin excepción
        self.assertEqual(len(self.app.accounts), 1)


class ServidoresEmpaquetados(unittest.TestCase):
    def test_json_existe_y_es_parseable(self):
        ruta = ROOT / "electrum_servers.json"
        self.assertTrue(ruta.is_file(), "falta electrum_servers.json en el paquete")
        lineas = json.loads(ruta.read_text(encoding="utf-8"))
        self.assertIsInstance(lineas, list)
        self.assertGreaterEqual(len(lineas), 64)
        for linea in lineas:
            host, puerto, ssl_ = m.parse_server(linea)
            self.assertTrue(host)
            self.assertTrue(1 <= puerto <= 65535)
            self.assertTrue(ssl_)

    def test_carga_prefiere_el_json(self):
        self.assertGreaterEqual(len(m.load_server_lines()), 64)


class DeteccionMotor(unittest.TestCase):
    def test_encuentra_bin_recovery_tool(self):
        esperado = ROOT / "bin" / "recovery-tool.exe"
        if not esperado.is_file():
            self.skipTest("binario no empaquetado")
        app = object.__new__(m.App)  # sin construir la GUI: _guess_engine no la necesita
        ruta = m.App._guess_engine(app)
        self.assertEqual(Path(ruta).name, "recovery-tool.exe")
        self.assertEqual(Path(ruta).parent.name, "bin")


class _ProcesoColgado:
    """Proceso falso que nunca termina ni escribe, para probar la vigilancia de tiempo."""

    lineas = ()

    def __init__(self, cmd=None, **kwargs):
        self.cmd = cmd
        self.stdin = io.StringIO()
        self._fin = threading.Event()
        self._matado = False
        self.stdout = self._stream()

    def _stream(self):
        for linea in self.lineas:
            yield linea
        self._fin.wait()          # bloquea como un motor esperando entrada
        return
        yield ""                  # inalcanzable: convierte la función en generador

    def poll(self):
        return -9 if self._matado else None

    def kill(self):
        self._matado = True
        self._fin.set()

    def wait(self, timeout=None):
        self._fin.wait(timeout)
        return -9 if self._matado else 0


class _AppFalsa:
    """Sustituto mínimo de App para llamar a _scan_worker sin abrir Tk."""

    def __init__(self):
        self.events = queue.Queue()
        self.proc = None


class EscaneoVigilado(unittest.TestCase):
    def _cuenta(self, tmp: str):
        z = Path(tmp) / "muun.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("c/EmergencyKit.pdf", b"%PDF-1.4\n")
        return {"folder": "c", "pdf": "c/EmergencyKit.pdf", "pdf_name": "EmergencyKit.pdf",
                "code": "ABCD-2345-EFGH-6723-IJKL-4567-MNOP-2345", "source": ("zip", str(z))}

    def _run(self, lineas, timeout_scan=1.0):
        original_popen, original_timeout = m.subprocess.Popen, m.SCAN_TIMEOUT
        m.SCAN_TIMEOUT = timeout_scan
        fabrica = type("P", (_ProcesoColgado,), {"lineas": tuple(lineas)})
        m.subprocess.Popen = fabrica
        try:
            with tempfile.TemporaryDirectory() as tmp:
                app = _AppFalsa()
                hilo = threading.Thread(target=m.App._scan_worker, args=(
                    app, 0, self._cuenta(tmp), "recovery-tool.exe", ["-only-scan"]), daemon=True)
                hilo.start()
                hilo.join(15)
                self.assertFalse(hilo.is_alive(), "el worker no terminó")
                eventos = []
                while not app.events.empty():
                    eventos.append(app.events.get_nowait())
                return [e for e in eventos if e[0] == "scan_done"]
        finally:
            m.subprocess.Popen, m.SCAN_TIMEOUT = original_popen, original_timeout

    def test_respeta_el_tiempo_maximo_sin_salida(self):
        eventos = self._run([], timeout_scan=1.0)
        self.assertEqual(len(eventos), 1, eventos)
        self.assertEqual(eventos[0][4], "Tiempo agotado")

    def test_detecta_pdf_ilegible_y_no_espera(self):
        inicio = time.monotonic()
        eventos = self._run(["No se pudo leer\n", "Couldn't read the PDF automatically: x\n"])
        self.assertEqual(len(eventos), 1, eventos)
        self.assertEqual(eventos[0][4], "PDF ilegible")
        self.assertLess(time.monotonic() - inicio, 10)


class SinEscapesDobles(unittest.TestCase):
    def test_no_quedan_barras_dobles_en_cadenas(self):
        src = SRC.read_text(encoding="utf-8")
        self.assertNotIn(r'\\n', src)
        self.assertNotIn(r'r"\\s+', src)


if __name__ == "__main__":
    unittest.main()

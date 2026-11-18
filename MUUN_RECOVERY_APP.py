"""MUUN RECOVERY APP — aplicación estructurada (núcleo desacoplado + interfaz Tkinter)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import *
from core import (_tls_context, _GO_SERVER_RE, _bech32_polymod, _bech32_hrp_expand,
                  _convertbits, _read_file_text, _safe_parts, _build_accounts,
                  _read_response)
from ui.app import *
from ui.app import main, App

# Re-exportar tkinter para compatibilidad con pruebas/extensiones.
try:
    import tkinter as tk
except ImportError:
    tk = None

__all__ = [n for n in globals() if not n.startswith("__")]

if __name__ == "__main__":
    raise SystemExit(main())

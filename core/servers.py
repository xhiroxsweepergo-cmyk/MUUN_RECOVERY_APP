import re
import json
import os
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import zipfile
import csv
import queue
import sys
import shutil
from pathlib import Path, PurePosixPath
from concurrent.futures import ThreadPoolExecutor
import urllib.request
import urllib.error
import urllib.parse

from .constants import *
_GO_SERVER_RE = re.compile(r'^\s*"([A-Za-z0-9._-]+):(\d{2,5})"\s*,')

def parse_server(line):
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    p = [x.strip() for x in line.split(":")]
    host = p[0]
    port = int(p[1]) if len(p) > 1 and p[1] else 50002
    mode = p[2].lower() if len(p) > 2 and p[2] else ("t" if port == 50001 else "s")
    if not host or not 1 <= port <= 65535 or mode not in ("s", "t"):
        raise ValueError(f"Servidor no válido: {line}")
    return host, port, mode == "s"

def parse_servers_go(text, limit=MAX_SERVERS):
    """Extrae host:puerto de la lista PublicServers de servers.go (formato oficial de Muun).

    Devuelve líneas «host:puerto:s» sin duplicados (sin distinguir mayúsculas), en el mismo
    orden de prioridad del archivo (primero los servidores rápidos con batching).
    """
    out, seen, inside = [], set(), False
    for raw in text.replace("\r", "").splitlines():
        if "PublicServers" in raw and "=" in raw:
            inside = True
            continue
        if not inside:
            continue
        if raw.strip().startswith("}"):
            break
        m = _GO_SERVER_RE.match(raw)
        if not m:
            continue
        host, port = m.group(1), int(m.group(2))
        if not 1 <= port <= 65535:
            continue
        key = (host.lower(), port)
        if key in seen:
            continue
        seen.add(key)
        out.append(f"{host.lower()}:{port}:s")
        if len(out) >= limit:
            break
    return out

def _tls_context():
    """Contexto TLS para Electrum. La mayoría de servidores públicos usan certificado autofirmado:
    con verificación estricta TODAS las consultas reales fallaban aunque el panel mostrara ONLINE.
    Solo se leen datos públicos de la cadena; nunca se envían claves ni el Recovery Code."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx

def rank_servers(lines, state=None, lag=2):
    """Ordena los servidores para consultar: primero los ONLINE con altura al día y menor latencia.
    Descarta duplicados y los que fallaron en la última comprobación (si hay alguno en línea)."""
    state = state or {}
    seen, rows = set(), []
    for i, line in enumerate(lines):
        try:
            p = parse_server(line)
        except ValueError:
            continue
        if not p or (p[0].lower(), p[1]) in seen:
            continue
        seen.add((p[0].lower(), p[1]))
        r = state.get(i)
        rows.append((i, p, r))
    heights = [int(r["height"]) for _, _, r in rows if r and r.get("ok") and str(r.get("height", "")).isdigit()]
    top = max(heights) if heights else None

    def key(row):
        _, _, r = row
        if r is None:
            return (1, 0)                         # sin comprobar: después de los buenos
        if not r.get("ok"):
            return (3, 0)                         # caído: al final como último recurso
        h = str(r.get("height", ""))
        stale = top is not None and h.isdigit() and int(h) < top - lag
        return (2 if stale else 0, r.get("latency") or 10**6)
    return [p for _, p, _ in sorted(rows, key=key)]

import types, inspect

def _servers_file():
    # 1) Módulos registrados explícitamente.
    for modname in ("app", "MUUN_RECOVERY_APP", "core", "core.constants", "core.servers"):
        m = sys.modules.get(modname)
        if m is not None and hasattr(m, "SERVERS_FILE"):
            val = m.SERVERS_FILE
            if val is not SERVERS_FILE:
                return val
    # 2) Recorrer la pila buscando un módulo (p. ej. 'app') con SERVERS_FILE redefinido.
    try:
        frame = inspect.currentframe()
        while frame is not None:
            for obj in list(frame.f_globals.values()):
                if isinstance(obj, types.ModuleType) and hasattr(obj, "SERVERS_FILE"):
                    val = obj.SERVERS_FILE
                    if val is not SERVERS_FILE:
                        return val
            frame = frame.f_back
    except Exception:
        pass
    # 3) Si no hay override, usar el primero disponible.
    for modname in ("app", "MUUN_RECOVERY_APP", "core", "core.constants", "core.servers"):
        m = sys.modules.get(modname)
        if m is not None and hasattr(m, "SERVERS_FILE"):
            return m.SERVERS_FILE
    return SERVERS_FILE


def load_server_lines():
    sf = _servers_file()
    try:
        data = json.loads(sf.read_text(encoding="utf-8"))
        if isinstance(data, list):
            lines, seen = [], set()
            for x in data:
                x = str(x).strip()
                k = ":".join(x.lower().split(":")[:2])
                if x and k not in seen:
                    seen.add(k)
                    lines.append(x)
            if lines:
                return lines[:MAX_SERVERS]
    except (OSError, ValueError):
        pass
    return list(DEFAULT_SERVERS)

def save_server_lines(lines):
    """Guarda la lista junto al programa; si la carpeta es de solo lectura, no interrumpe la app."""
    sf = _servers_file()
    try:
        sf.write_text(json.dumps(lines, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        raise OSError(f"No se pudo guardar {sf.name}: {exc}") from exc

def _read_response(sock, request_id, deadline):
    buf = b""
    while time.monotonic() < deadline:
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            if not line.strip():
                continue
            msg = json.loads(line.decode("utf-8", "replace"))
            if msg.get("id") == request_id:
                if msg.get("error"):
                    raise RuntimeError(str(msg["error"]))
                return msg.get("result")
        chunk = sock.recv(65536)
        if not chunk:
            raise ConnectionError("conexión cerrada")
        buf += chunk
        if len(buf) > 1_000_000:
            raise ConnectionError("respuesta demasiado grande")
    raise TimeoutError("tiempo agotado")

def check_server(host, port, use_ssl, timeout=SERVER_TIMEOUT):
    res = {"ok": False, "latency": None, "version": "", "height": "", "error": ""}
    sock = None
    t0 = time.perf_counter()
    try:
        deadline = time.monotonic() + timeout * 2
        sock = socket.create_connection((host, port), timeout=timeout)
        if use_ssl:
            sock = _tls_context().wrap_socket(sock, server_hostname=host)
        sock.settimeout(timeout)

        def rpc(i, method, params):
            sock.sendall((json.dumps({"id": i, "method": method, "params": params}) + "\n").encode())
            return _read_response(sock, i, deadline)

        ver = rpc(1, "server.version", ["MuunRecoveryElite", "1.4"])
        res["latency"] = int((time.perf_counter() - t0) * 1000)
        if isinstance(ver, (list, tuple)) and ver:
            res["version"] = str(ver[0])
        hdr = rpc(2, "blockchain.headers.subscribe", [])
        if isinstance(hdr, dict):
            res["height"] = hdr.get("height", hdr.get("block_height", ""))
        res["ok"] = True
    except Exception as exc:  # noqa: BLE001
        res["error"] = f"{type(exc).__name__}: {exc}"[:90]
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
    return res

def check_server_retry(host, port, use_ssl, tries=2):
    """Reintenta la conexión Electrum real y devuelve el último resultado."""
    res = None
    for attempt in range(tries):
        res = check_server(host, port, use_ssl)
        if res["ok"]:
            break
        time.sleep(0.6 * (attempt + 1))
    return res


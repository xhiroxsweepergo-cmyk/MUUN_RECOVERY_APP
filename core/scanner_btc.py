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
_BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"

def _bech32_polymod(values):
    generators = (0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3)
    chk = 1
    for v in values:
        top = chk >> 25
        chk = ((chk & 0x1ffffff) << 5) ^ v
        for i, g in enumerate(generators):
            if (top >> i) & 1:
                chk ^= g
    return chk

def _bech32_hrp_expand(hrp):
    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]

def _convertbits(data, frombits, tobits, pad=False):
    acc = bits = 0
    ret = []
    maxv = (1 << tobits) - 1
    for value in data:
        if value < 0 or value >> frombits:
            raise ValueError("Dirección SegWit inválida")
        acc = (acc << frombits) | value
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            ret.append((acc >> bits) & maxv)
    if pad:
        if bits:
            ret.append((acc << (tobits - bits)) & maxv)
    elif bits >= frombits or ((acc << (tobits - bits)) & maxv):
        raise ValueError("Padding Bech32 inválido")
    return ret

def address_to_scripthash(address):
    a = address.strip()
    if a.lower() != a and a.upper() != a:
        raise ValueError("La dirección mezcla mayúsculas y minúsculas")
    a = a.lower()
    if not a.startswith("bc1") or len(a) > 90:
        raise ValueError("Solo se admiten direcciones Bitcoin mainnet bc1q/bc1p")
    pos = a.rfind("1")
    if pos < 1 or pos + 7 > len(a):
        raise ValueError("Dirección Bech32 incompleta")
    hrp = a[:pos]
    if hrp != "bc":
        raise ValueError("La dirección no pertenece a Bitcoin mainnet")
    try:
        data = [_BECH32_CHARSET.index(c) for c in a[pos + 1:]]
    except ValueError:
        raise ValueError("Caracteres Bech32 no válidos")
    check = _bech32_polymod(_bech32_hrp_expand(hrp) + data)
    if check not in (1, 0x2bc830a3):
        raise ValueError("Checksum Bech32 incorrecto")
    payload = data[:-6]
    if not payload:
        raise ValueError("Falta la versión SegWit")
    version = payload[0]
    if version > 16:
        raise ValueError("Versión SegWit inválida")
    program = bytes(_convertbits(payload[1:], 5, 8, False))
    if not 2 <= len(program) <= 40 or (version == 0 and len(program) not in (20, 32)):
        raise ValueError("Programa SegWit inválido")
    if (version == 0 and check != 1) or (version != 0 and check != 0x2bc830a3):
        raise ValueError("Checksum no corresponde a la versión SegWit")
    script = bytes([version if version == 0 else 0x50 + version, len(program)]) + program
    return __import__("hashlib").sha256(script).digest()[::-1].hex()

def electrum_address_data(host, port, use_ssl, scripthash, timeout=12):
    """Consulta historial y UTXOs con una sola sesión Electrum, en modo de solo lectura."""
    sock = socket.create_connection((host, port), timeout=min(timeout, CONNECT_TIMEOUT))
    try:
        if use_ssl:
            sock = _tls_context().wrap_socket(sock, server_hostname=host)
        sock.settimeout(timeout)
        f = sock.makefile("rwb")
        next_id = 0
        def rpc(method, params):
            nonlocal next_id
            next_id += 1
            rid = next_id
            f.write((json.dumps({"id": rid, "method": method, "params": params}) + "\n").encode())
            f.flush()
            while True:
                line = f.readline()
                if not line:
                    raise ConnectionError("El servidor cerró la conexión")
                msg = json.loads(line.decode("utf-8", "replace"))
                if msg.get("id") == rid:
                    if msg.get("error"):
                        raise RuntimeError(str(msg["error"]))
                    return msg.get("result")
        version = rpc("server.version", ["MuunRecoveryElite", "1.4"])
        history = rpc("blockchain.scripthash.get_history", [scripthash])
        unspent = rpc("blockchain.scripthash.listunspent", [scripthash])
        balance = rpc("blockchain.scripthash.get_balance", [scripthash]) or {}
        return version, history or [], unspent or [], balance
    finally:
        try:
            sock.close()
        except OSError:
            pass

def electrum_tx_verbose(host, port, use_ssl, txid, timeout=12):
    """Lee una transacción completa (solo lectura) para obtener sus salidas."""
    sock = socket.create_connection((host, port), timeout=min(timeout, CONNECT_TIMEOUT))
    try:
        if use_ssl:
            sock = _tls_context().wrap_socket(sock, server_hostname=host)
        sock.settimeout(timeout)
        f = sock.makefile("rwb")
        next_id = 0
        def rpc(method, params):
            nonlocal next_id
            next_id += 1
            rid = next_id
            f.write((json.dumps({"id": rid, "method": method, "params": params}) + "\n").encode())
            f.flush()
            while True:
                line = f.readline()
                if not line:
                    raise ConnectionError("El servidor cerró la conexión")
                msg = json.loads(line.decode("utf-8", "replace"))
                if msg.get("id") == rid:
                    if msg.get("error"):
                        raise RuntimeError(str(msg["error"]))
                    return msg.get("result")
        return rpc("blockchain.transaction.get", [txid, True]) or {}
    finally:
        try:
            sock.close()
        except OSError:
            pass

def build_block_report(history, unspent, from_height=0, tx_values=None):
    """Ordena el historial REAL de Electrum bloque a bloque (ascendente) y marca cada TX."""
    tx_values = tx_values or {}
    by_tx = {}
    for u in unspent:
        by_tx.setdefault(str(u.get("tx_hash", "")).lower(), []).append(
            (int(u.get("tx_pos", 0)), int(u.get("value", 0))))
    blocks = {}
    for h in history:
        txid = str(h.get("tx_hash", "")).lower()
        height = int(h.get("height", 0) or 0)
        if height > 0 and height < from_height:
            continue
        blocks.setdefault(max(height, 0), []).append(
            {"txid": txid, "height": height, "utxos": sorted(by_tx.get(txid, [])),
             "funded": sorted(tx_values.get(txid, []))})
    order = sorted(k for k in blocks if k > 0) + ([0] if 0 in blocks else [])
    return [(k, blocks[k]) for k in order]

def classify_address_history(history, unspent):
    """Clasifica cada TX del historial de una dirección como ENTRADA o SALIDA.

    Una TX es ENTRADA si deja al menos un UTXO sin gastar en la dirección;
    en caso contrario (ya gastada) se considera SALIDA. Devuelve una lista de
    diccionarios {txid, height, direction, value, confirmed}.
    """
    by_tx = {}
    for u in (unspent or []):
        by_tx.setdefault(str(u.get("tx_hash", "")).lower(), []).append(
            int(u.get("value", 0)))
    out = []
    for h in (history or []):
        txid = str(h.get("tx_hash", "")).lower()
        height = int(h.get("height", 0) or 0)
        vals = by_tx.get(txid, [])
        direction = "ENTRADA" if vals else "SALIDA"
        value = sum(vals) if vals else 0
        out.append({"txid": txid, "height": height, "direction": direction,
                    "value": value, "confirmed": height > 0})
    return out


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
ANSI_RE = __import__("re").compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
TXO_RE = __import__("re").compile(r"\b[0-9a-fA-F]{64}:\d+\b")
UTXO_COUNT_RE = __import__("re").compile(r"(\d+)\s+UTXOs?|UTXOs?\s*[:=]\s*(\d+)", __import__("re").I)
SATS_RE = __import__("re").compile(r"([\d][\d,\.]*)\s*(?:sats?|satoshis?)\b", __import__("re").I)
SATS_LABEL_RE = __import__("re").compile(r"sats?\s+found\s*[:=]\s*([\d,]+)", __import__("re").I)
UTXO_LINE_RE = __import__("re").compile(r"(?:•|\*)\s*[\d,]+\s+sats?\s+in\s+\S+", __import__("re").I)
BTC_RE = __import__("re").compile(r"(\d+\.\d+)\s*BTC\b", __import__("re").I)
_GO_SERVER_RE = __import__("re").compile(r'^\s*"([A-Za-z0-9._-]+):(\d{2,5})"\s*,')
_ELECTRUM_ARG_RE = __import__("re").compile(r"^[A-Za-z0-9.-]{1,253}:\d{2,5}$")
_BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def parse_scan_output(lines):
    """Interpreta tanto el progreso como el resumen final del recovery-tool oficial."""
    text = ANSI_RE.sub("", "\n".join(lines)).replace("\r", "\n")
    utxos = len(set(TXO_RE.findall(text)))
    utxos = max(utxos, len(UTXO_LINE_RE.findall(text)))
    for m in UTXO_COUNT_RE.finditer(text):
        n = int(m.group(1) or m.group(2))
        utxos = max(utxos, n)

    candidates = []
    for pattern in (SATS_RE, SATS_LABEL_RE):
        for m in pattern.finditer(text):
            raw = m.group(1).replace(",", "")
            try:
                candidates.append(int(raw.split(".")[0]))
            except ValueError:
                continue
    sats = max(candidates) if candidates else None

    if sats is None:
        btcs = [float(m.group(1)) for m in BTC_RE.finditer(text)]
        if btcs:
            sats = int(round(max(btcs) * 1e8))
    # Distingue un escaneo finalizado con saldo cero de una salida que no se pudo leer.
    if sats is None and re.search(r"No funds were discovered|Scan complete", text, re.I):
        sats = 0
    return utxos, sats


UTXO_DETAIL_RE = re.compile(r"(\d[\d,]*)\s*sats?\s+in\s+([A-Za-z0-9]{20,})", re.I)


def parse_scan_utxos(lines):
    """Devuelve detalle del resumen final del recovery-tool:

        [{"sats": 1600, "address": "bc1qly8…"}, …]

    La salida del motor muestra "• 1600 sats in bc1q…"; esto la convierte en datos
    estructurados para mostrar de cuántos sats es cada UTXO detectado.
    """
    text = ANSI_RE.sub("", "\n".join(lines)).replace("\r", "\n")
    seen = {}
    for m in UTXO_DETAIL_RE.finditer(text):
        try:
            sats = int(m.group(1).replace(",", ""))
        except ValueError:
            continue
        addr = m.group(2)
        seen[addr] = sats
    return [{"sats": s, "address": a} for a, s in seen.items()]


def utxo_summary_text(details):
    """Texto multilínea para la UI: un renglón por UTXO y el total."""
    if not details:
        return "Sin UTXOs detectados todavía. Escanea una cuenta primero."
    total = sum(d["sats"] for d in details)
    rows = [f"• {d['sats']:,} sats en {d['address']}" for d in details]
    rows.append(f"TOTAL: {total:,} sats ({total / 1e8:.8f} BTC)")
    return "\n".join(rows)

def build_scan_flags(electrum="", contacts=False):
    """Flags del recovery-tool para un escaneo de SOLO LECTURA (nunca genera transacción).

    -generate-contacts: añade las direcciones de contactos al flujo de direcciones (más profundo).
    -electrum-server=host:puerto: fuerza un servidor concreto (verificación cruzada).
    """
    flags = ["-only-scan"]
    if contacts:
        flags.append("-generate-contacts")
    electrum = (electrum or "").strip()
    if electrum:
        if not _ELECTRUM_ARG_RE.match(electrum) or not 1 <= int(electrum.rsplit(":", 1)[1]) <= 65535:
            raise ValueError("Servidor Electrum inválido: usa host:puerto (por ejemplo electrum.blockstream.info:50002)")
        flags.append(f"-electrum-server={electrum}")
    return flags


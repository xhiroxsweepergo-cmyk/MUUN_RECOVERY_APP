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

def lnbits_payments(url, api_key, limit=200, timeout=15):
    """Consulta el historial de pagos de un nodo LNbits (solo lectura).

    Devuelve una lista de diccionarios con los pagos (entrantes y salientes).
    Lanza RuntimeError/urllib.error si el nodo no responde o la clave es inválida.
    """
    url = (url or "").strip().rstrip("/")
    if not url or not api_key:
        raise ValueError("Falta URL o clave API de LNbits")
    endpoint = f"{url}/api/v1/payments?limit={int(limit)}"
    req = urllib.request.Request(endpoint, headers={"X-Api-Key": api_key.strip()})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8", "replace"))
    if isinstance(data, dict):
        for key in ("data", "payments", "results"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
    if not isinstance(data, list):
        return []
    return data

def scan_lightning_payments(url, api_key, limit=200):
    """Agrega el historial Lightning en entrantes/salientes (sats).

    Devuelve (incoming_sats, outgoing_sats, count, rows, error). Si hay error,
    incoming/outgoing quedan en 0 y error describe el motivo.
    """
    incoming = outgoing = 0
    rows = []
    try:
        data = lnbits_payments(url, api_key, limit=limit)
    except Exception as exc:  # noqa: BLE001
        return 0, 0, 0, [], f"{type(exc).__name__}: {exc}"
    for p in data:
        if not isinstance(p, dict):
            continue
        # Dirección: explícita o por signo del importe.
        direction = str(p.get("direction") or p.get("type") or "").lower()
        is_out = p.get("is_outgoing")
        if is_out is None:
            is_out = direction in ("out", "outgoing", "send", "sent")
        amount_msat = p.get("amount", p.get("amount_msat", 0))
        try:
            amount_msat = int(amount_msat)
        except (TypeError, ValueError):
            amount_msat = 0
        # LNbits usa importes negativos para salientes en muchos endpoints.
        if amount_msat < 0:
            is_out = True
            amount_msat = abs(amount_msat)
        status = str(p.get("status") or p.get("state") or "").lower()
        if status and status not in ("success", "paid", "complete", "completed", "settled", ""):
            continue
        sats = amount_msat // 1000
        if is_out:
            outgoing += sats
        else:
            incoming += sats
        memo = str(p.get("memo") or p.get("description") or p.get("payment_hash") or "")
        rows.append({"direction": "SALIDA" if is_out else "ENTRADA", "sats": sats,
                     "status": status or "ok", "memo": memo[:80]})
    return incoming, outgoing, len(rows), rows, ""


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
from .validator import *

def _safe_parts(name):
    parts = PurePosixPath(name.replace("\\", "/")).parts
    if not parts or parts[0] == "/" or ".." in parts:
        return None
    return parts

def _build_accounts(groups, source, limit):
    kind, src = source
    accounts = []
    for folder in sorted(groups):
        files = groups[folder]
        pdfs = [f for f in files if f[0].lower().endswith(".pdf")]
        pdfs.sort(key=lambda f: "emergency" not in f[0].lower())
        code = ""
        code_error = ""
        for fname, loc in files:
            stem = Path(fname).stem
            if fname.lower().endswith(".pdf"):
                continue
            # 1) El código puede estar en el nombre del archivo (comportamiento original).
            for cand in (fname, stem):
                if code:
                    break
                if normalize_code(cand):
                    code = normalize_code(cand)
                elif re.fullmatch(r"[A-Za-z0-9]{28,40}", re.sub(r"[\\s_\\-]+", "", cand.strip())):
                    if not code_error:
                        code_error = "formato inválido (debe tener 32 caracteres A-Z/0-9)"
            # 2) O dentro del contenido del archivo (txt, json, csv, md, ...).
            if not code:
                text = _read_file_text(kind, src, loc)
                if text:
                    c = extract_code_from_text(text)
                    if c:
                        code = c
                    elif re.search(r"[A-Za-z0-9]{28,40}", text) and not code_error:
                        code_error = "formato inválido (debe tener 32 caracteres A-Z/0-9)"
        accounts.append({
            "folder": folder or "(raíz)",
            "pdf": pdfs[0][1] if pdfs else None,
            "pdf_name": pdfs[0][0] if pdfs else "",
            "code": code,
            "code_error": code_error,
            "source": source,
        })
        if len(accounts) >= limit:
            break
    return accounts

def discover_zip(zip_path, limit):
    groups = {}
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            parts = _safe_parts(info.filename)
            if not parts:
                continue
            folder = "/".join(parts[:-1])
            groups.setdefault(folder, []).append((parts[-1], info.filename))
    return _build_accounts(groups, ("zip", str(zip_path)), limit)

def discover_folder(root, limit):
    groups = {}
    root = Path(root)
    for dirpath, _dirs, files in os.walk(root):
        rel = Path(dirpath).relative_to(root).as_posix()
        rel = "" if rel == "." else rel
        for f in files:
            groups.setdefault(rel, []).append((f, str(Path(dirpath) / f)))
    return _build_accounts(groups, ("dir", str(root)), limit)

def materialize_pdf(account, dest_dir):
    """Copia solo el PDF de la cuenta a dest_dir/EmergencyKit.pdf (sin extraer nada más)."""
    dest = Path(dest_dir) / "EmergencyKit.pdf"
    kind, src = account["source"]
    if kind == "zip":
        with zipfile.ZipFile(src) as zf, zf.open(account["pdf"]) as fin, open(dest, "wb") as fout:
            shutil.copyfileobj(fin, fout)
    else:
        shutil.copyfile(account["pdf"], dest)
    return dest


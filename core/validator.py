"""Recovery Code validation with Muun's real format (39 chars, A-Z0-9)."""

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# El motor de Muun espera el Recovery Code como 8 grupos de 4 caracteres
# separados por '-': ABCD-1234-POW2-R561-P120-JK26-12RW-45TT  (39 caracteres).
# Alfabeto: A-Z y 0-9 (el ejemplo oficial incluye 0,1,8,9).
CODE_SEPARATORS = re.compile(r"[\s\-_.,;:|/]+")
GROUP_RE = re.compile(r"^[A-Z0-9]{4}(?:-[A-Z0-9]{4}){7}$")
FLAT_RE = re.compile(r"^[A-Z0-9]{32}$")
CANDIDATE_RE = re.compile(r"[A-Z0-9]{4}(?:[\s\-_]?[A-Z0-9]{4}){7}")


def fmt_btc(sats):
    return f"{sats / 1e8:.8f} BTC"


def mask(code):
    return "****-****-****-****-****-****-****-****" if code else "—"


@dataclass
class ValidationResult:
    ok: bool
    reason: str = ""
    normalized: Optional[str] = None


class RecoveryCodeValidator:
    """Valida y extrae Recovery Codes al estilo Muun (39 chars con guiones)."""

    def normalize(self, code: str) -> str:
        """Quita separadores y devuelve el código en formato Muun con guiones."""
        if not code:
            return ""
        flat = CODE_SEPARATORS.sub("", code.strip().upper())
        if len(flat) == 32 and FLAT_RE.match(flat):
            return "-".join(flat[i:i + 4] for i in range(0, 32, 4))
        return ""

    def validate(self, code: str) -> ValidationResult:
        norm = self.normalize(code)
        if not norm:
            # diagnóstico específico
            raw = (code or "").strip().upper()
            flat = CODE_SEPARATORS.sub("", raw)
            if len(flat) < 32:
                return ValidationResult(False, f"Código demasiado corto ({len(flat)} caracteres; deben ser 32)")
            if len(flat) > 32:
                return ValidationResult(False, f"Código demasiado largo ({len(flat)} caracteres; deben ser 32)")
            bad = sorted({c for c in flat if not ('A' <= c <= 'Z' or '0' <= c <= '9')})
            if bad:
                return ValidationResult(
                    False,
                    "Caracteres no válidos: " + ", ".join(bad)
                    + " (solo A-Z y 0-9)",
                )
            return ValidationResult(False, "Formato no reconocido")
        return ValidationResult(True, "", norm)

    def extract_from_text(self, text: str) -> Optional[str]:
        """Busca un código válido dentro de texto libre/JSON/CSV."""
        if not text:
            return ""
        # 1) candidato con o sin separadores
        for m in CANDIDATE_RE.finditer(text.upper()):
            norm = self.normalize(m.group(0))
            if norm:
                return norm
        # 2) bloque compacto de 32
        for m in re.finditer(r"[A-Z0-9]{32}", text.upper()):
            norm = self.normalize(m.group(0))
            if norm:
                return norm
        return ""


_VALIDATOR = RecoveryCodeValidator()


def normalize_code(code: str) -> str:
    """Normaliza un Recovery Code al formato Muun con guiones (39 caracteres)."""
    return _VALIDATOR.normalize(code)


def validate_code(code: str) -> ValidationResult:
    return _VALIDATOR.validate(code)


def extract_code_from_text(text: str) -> str:
    return _VALIDATOR.extract_from_text(text) or ""


def _read_file_text(kind, src, member):
    try:
        if kind == "zip":
            with zipfile.ZipFile(src) as zf:
                info = zf.getinfo(member)
                if info.file_size > 1024 * 1024:
                    return ""
                with zf.open(member) as f:
                    raw = f.read()
        else:
            p = Path(member)
            if not p.is_file() or p.stat().st_size > 1024 * 1024:
                return ""
            raw = p.read_bytes()
    except (KeyError, OSError, zipfile.BadZipFile):
        return ""
    if not raw:
        return ""
    # Detectar BOM UTF-16/UTF-8 primero (archivos creados por PowerShell, Notepad, etc.).
    for enc in ("utf-8-sig", "utf-16", "utf-16-le", "utf-16-be", "utf-8", "latin-1"):
        try:
            text = raw.decode(enc)
            if "\\x00" not in text or enc.startswith("utf-16"):
                return text
        except (UnicodeDecodeError, UnicodeError):
            continue
    return ""

"""Password encryption so a PUBLIC repo never contains readable data.

- Dashboard data: docs/data/deals.json -> docs/data/deals.enc.json (decrypted in the browser).
- Pipeline cache: data/releases/*.json -> data/state.enc (decrypted at the start of each run).

AES-256-GCM, key from PBKDF2-HMAC-SHA256 (600k iterations, random salt). The browser side
uses the same parameters via Web Crypto. Password comes from the DASHBOARD_PASSWORD secret.
"""
from __future__ import annotations

import base64
import io
import json
import os
import tarfile
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ROOT = Path(__file__).resolve().parent.parent
RELEASES = ROOT / "data" / "releases"
STATE = ROOT / "data" / "state.enc"
DOCS_DATA = ROOT / "docs" / "data"
ITERATIONS = 600_000

b64e = lambda b: base64.b64encode(b).decode()
b64d = base64.b64decode


def password() -> str | None:
    return os.getenv("DASHBOARD_PASSWORD") or None


def _key(pw: str, salt: bytes, iterations: int) -> bytes:
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations).derive(pw.encode())


def encrypt(data: bytes, pw: str) -> dict:
    salt, iv = os.urandom(16), os.urandom(12)
    ct = AESGCM(_key(pw, salt, ITERATIONS)).encrypt(iv, data, None)
    return {"v": 1, "kdf": "PBKDF2-SHA256", "iter": ITERATIONS, "salt": b64e(salt), "iv": b64e(iv), "ct": b64e(ct)}


def decrypt(blob: dict, pw: str) -> bytes:
    key = _key(pw, b64d(blob["salt"]), blob["iter"])
    return AESGCM(key).decrypt(b64d(blob["iv"]), b64d(blob["ct"]), None)


# ---------------------------------------------------------------- dashboard data

def encrypt_dashboard(pw: str) -> None:
    """Replace the plaintext dashboard files with one encrypted file."""
    src = DOCS_DATA / "deals.json"
    blob = encrypt(src.read_bytes(), pw)
    (DOCS_DATA / "deals.enc.json").write_text(json.dumps(blob))
    for f in ("deals.json", "deals.csv"):
        (DOCS_DATA / f).unlink(missing_ok=True)  # never publish plaintext


# ---------------------------------------------------------------- pipeline cache

def unpack_state(pw: str) -> int:
    if not STATE.exists():
        return 0
    try:
        raw = decrypt(json.loads(STATE.read_text()), pw)
    except Exception:
        raise SystemExit("data/state.enc cannot be opened with the current DASHBOARD_PASSWORD. "
                         "If you changed the password on purpose, delete data/state.enc in the repo; "
                         "the next run rebuilds everything from scratch.")
    RELEASES.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        members = [m for m in tar.getmembers() if m.isfile() and "/" not in m.name and m.name.endswith(".json")]
        for m in members:
            (RELEASES / m.name).write_bytes(tar.extractfile(m).read())
    return len(members)


def pack_state(pw: str) -> int:
    buf = io.BytesIO()
    files = sorted(RELEASES.glob("*.json"))
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for f in files:
            tar.add(f, arcname=f.name)
    STATE.write_text(json.dumps(encrypt(buf.getvalue(), pw)))
    return len(files)

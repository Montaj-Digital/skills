"""The token store (ROADMAP phase 9.4): platform sign-in tokens and the developer's app secrets, never in plain files.

Backends, picked automatically (or STUDIO_VAULT=keychain|dpapi|fernet|file):
  keychain  macOS: the login Keychain, service "Studio AI" (the `security` tool; nothing to install)
  dpapi     Windows: encrypted for the signed-in Windows user (CryptProtectData through ctypes), in a file
  fernet    the portal (Linux): an encrypted file; needs `pip install cryptography` and STUDIO_SECRET_KEY (a Fernet key:
            python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
  file      testing only (STUDIO_VAULT=file): a plain JSON file readable only by this user. Never for real tokens.
Entries are named "<team>/<name>", e.g. "local/token:youtube", "local/app:youtube". Values are JSON.
Python 3.9 standard library only (fernet needs the cryptography package on the portal).
"""
import base64, json, os, subprocess, sys, threading
from pathlib import Path

SERVICE = "Studio AI"
_lock = threading.Lock()


class VaultError(RuntimeError):
    pass


def backend():
    want = os.environ.get("STUDIO_VAULT")
    if want:
        return want
    if sys.platform == "darwin":
        return "keychain"
    if os.name == "nt":
        return "dpapi"
    return "fernet"


def _file(folder, name):
    d = Path(folder)
    d.mkdir(parents=True, exist_ok=True)
    return d / name


# ---------------------------------------------------------------- keychain (macOS)
# Values are stored base64-encoded. Writes go through `security -i` (commands on stdin), so a secret never appears in
# the process list the way a command-line argument would.
def _kc_set(key, value):
    b64 = base64.b64encode(value.encode()).decode()
    cmd = f'add-generic-password -U -a "{key}" -s "{SERVICE}" -w "{b64}"\n'
    r = subprocess.run(["security", "-i"], input=cmd, capture_output=True, text=True)
    if r.returncode or "error" in (r.stderr or "").lower():
        raise VaultError(f"Couldn't save to the Keychain: {(r.stderr or r.stdout).strip()[:200]}")


def _kc_get(key):
    r = subprocess.run(["security", "find-generic-password", "-a", key, "-s", SERVICE, "-w"], capture_output=True, text=True)
    if r.returncode:
        return None
    try:
        return base64.b64decode(r.stdout.strip()).decode()
    except ValueError:
        return None


def _kc_del(key):
    subprocess.run(["security", "delete-generic-password", "-a", key, "-s", SERVICE], capture_output=True, text=True)


# ---------------------------------------------------------------- file-based backends (dpapi, fernet, file)
def _seal(data):
    b = backend()
    raw = json.dumps(data).encode()
    if b == "file":
        return raw
    if b == "dpapi":
        return _dpapi(raw, protect=True)
    if b == "fernet":
        return _fernet().encrypt(raw)
    raise VaultError(f"Unknown vault backend {b}")


def _open(blob):
    b = backend()
    if b == "file":
        return json.loads(blob)
    if b == "dpapi":
        return json.loads(_dpapi(blob, protect=False))
    if b == "fernet":
        return json.loads(_fernet().decrypt(blob))
    raise VaultError(f"Unknown vault backend {b}")


def _fernet():
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        raise VaultError("The token store on this server needs: pip install cryptography (and STUDIO_SECRET_KEY)")
    key = os.environ.get("STUDIO_SECRET_KEY")
    if not key:
        raise VaultError("Set STUDIO_SECRET_KEY (a Fernet key) on the server for the token store")
    return Fernet(key.encode())


def _dpapi(data, protect):
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]
    src = BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data, len(data)), ctypes.POINTER(ctypes.c_char)))
    out = BLOB()
    fn = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    if not fn(ctypes.byref(src), None, None, None, None, 0, ctypes.byref(out)):
        raise VaultError("Windows couldn't protect the token store")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def _load_file(folder):
    f = _file(folder, "vault.bin")
    if not f.exists():
        return {}
    return _open(f.read_bytes())


def _save_file(folder, data):
    f = _file(folder, "vault.bin")
    tmp = f.with_suffix(".tmp")
    tmp.write_bytes(_seal(data))
    os.chmod(tmp, 0o600)
    os.replace(tmp, f)


# ---------------------------------------------------------------- the interface
def set(folder, key, value):
    """Store a JSON value. folder: the planner folder (file backends keep vault.bin there)."""
    with _lock:
        if backend() == "keychain":
            _kc_set(key, json.dumps(value))
        else:
            data = _load_file(folder); data[key] = value; _save_file(folder, data)


def get(folder, key):
    with _lock:
        if backend() == "keychain":
            v = _kc_get(key)
            return json.loads(v) if v else None
        return _load_file(folder).get(key)


def delete(folder, key):
    with _lock:
        if backend() == "keychain":
            _kc_del(key)
        else:
            data = _load_file(folder); data.pop(key, None); _save_file(folder, data)


def check(folder):
    """Can the store be used here? -> (ok, message)."""
    try:
        set(folder, "_check", {"ok": True}); ok = get(folder, "_check") == {"ok": True}; delete(folder, "_check")
        return ok, f"{ {'keychain': 'The Mac Keychain', 'dpapi': 'Windows protected storage', 'fernet': 'An encrypted file', 'file': 'A plain file (testing only)'}.get(backend(), backend()) }"
    except VaultError as e:
        return False, str(e)
    except OSError as e:
        return False, f"The token store isn't available: {e}"

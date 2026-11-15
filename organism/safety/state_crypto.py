"""Authenticated symmetric encryption (Fernet AES-128-CBC + HMAC-SHA256) for ORGANISM state."""

from __future__ import annotations

import base64
import binascii
import gzip
import hashlib
import hmac
import json
import os
import secrets
import shutil
import sqlite3
import struct
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from organism.safety.validation import IntegrityValidator

try:
    from cryptography.fernet import Fernet as _CryptoFernet
    from cryptography.fernet import InvalidToken as _CryptoInvalidToken

    _HAS_CRYPTOGRAPHY = True
except ImportError:  # pragma: no cover - tested in restricted runtimes without pip
    _CryptoFernet = None  # type: ignore[assignment]
    _CryptoInvalidToken = Exception
    _HAS_CRYPTOGRAPHY = False


class StateCryptoError(RuntimeError):
    """Raised on missing key, invalid key format, corrupted ciphertext, or integrity failure."""


class InvalidCiphertextError(StateCryptoError):
    """Raised when ciphertext fails HMAC verification or decryption."""


def generate_fernet_key() -> str:
    """Generate a standard 32-byte URL-safe base64 Fernet key."""
    if _HAS_CRYPTOGRAPHY and _CryptoFernet is not None:
        return _CryptoFernet.generate_key().decode("ascii")
    return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")


def _validate_fernet_key(key: str | bytes) -> bytes:
    raw_str = key.decode("ascii") if isinstance(key, bytes) else str(key)
    cleaned = raw_str.strip()
    if not cleaned:
        raise StateCryptoError("ORGANISM_STATE_ENCRYPTION_KEY is empty or missing.")
    try:
        decoded = base64.urlsafe_b64decode(cleaned.encode("ascii"))
    except (ValueError, binascii.Error, UnicodeEncodeError) as exc:
        raise StateCryptoError("ORGANISM_STATE_ENCRYPTION_KEY is not valid URL-safe base64.") from exc
    if len(decoded) != 32:
        raise StateCryptoError(
            f"ORGANISM_STATE_ENCRYPTION_KEY must decode to 32 bytes (got {len(decoded)})."
        )
    return cleaned.encode("ascii")


class _OpenSSLFernetCompat:
    """
    Wire-compatible Fernet (version 0x80: AES-128-CBC + PKCS7 + HMAC-SHA256) using OpenSSL CLI + stdlib HMAC.
    Used only when the `cryptography` Python wheel is absent in a restricted sandbox.
    """

    def __init__(self, key_b64: bytes) -> None:
        raw = base64.urlsafe_b64decode(key_b64)
        self._signing_key = raw[:16]
        self._encryption_key = raw[16:]
        self._openssl = shutil.which("openssl")
        if not self._openssl:
            raise StateCryptoError(
                "Neither Python 'cryptography' package nor 'openssl' binary is available."
            )

    def encrypt(self, data: bytes) -> bytes:
        version = b"\x80"
        timestamp = struct.pack(">Q", int(time.time()))
        iv = os.urandom(16)
        assert self._openssl is not None
        proc = subprocess.run(
            [
                self._openssl,
                "enc",
                "-aes-128-cbc",
                "-K",
                self._encryption_key.hex(),
                "-iv",
                iv.hex(),
            ],
            input=data,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            raise StateCryptoError("OpenSSL AES-128-CBC encryption failed.")
        basic_parts = version + timestamp + iv + proc.stdout
        mac = hmac.new(self._signing_key, basic_parts, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(basic_parts + mac)

    def decrypt(self, token: bytes) -> bytes:
        try:
            raw = base64.urlsafe_b64decode(token)
        except (ValueError, binascii.Error) as exc:
            raise InvalidCiphertextError("Ciphertext is not valid base64.") from exc
        if len(raw) < 1 + 8 + 16 + 16 + 32 or raw[0] != 0x80:
            raise InvalidCiphertextError("Invalid Fernet token structure or version.")
        basic_parts = raw[:-32]
        provided_mac = raw[-32:]
        expected_mac = hmac.new(self._signing_key, basic_parts, hashlib.sha256).digest()
        if not hmac.compare_digest(provided_mac, expected_mac):
            raise InvalidCiphertextError("Ciphertext HMAC integrity check failed.")
        iv = raw[9:25]
        ciphertext = raw[25:-32]
        assert self._openssl is not None
        proc = subprocess.run(
            [
                self._openssl,
                "enc",
                "-d",
                "-aes-128-cbc",
                "-K",
                self._encryption_key.hex(),
                "-iv",
                iv.hex(),
            ],
            input=ciphertext,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            raise InvalidCiphertextError("AES-128-CBC decryption failed.")
        return proc.stdout


class StateEncryptor:
    """Encrypts and authenticates SQLite DB, snapshots, and runtime state files for public branch storage."""

    BUNDLE_FILENAME = "organism_state.fernet"
    META_FILENAME = "metadata.json"

    def __init__(self, key: str | bytes | None = None) -> None:
        resolved = key if key is not None else os.environ.get("ORGANISM_STATE_ENCRYPTION_KEY", "")
        self._key_b64 = _validate_fernet_key(resolved)
        if _HAS_CRYPTOGRAPHY and _CryptoFernet is not None:
            self._fernet: Any = _CryptoFernet(self._key_b64)
            self.backend_name = "cryptography.fernet"
        else:
            self._fernet = _OpenSSLFernetCompat(self._key_b64)
            self.backend_name = "openssl_fernet_compat"

    def encrypt_bytes(self, plaintext: bytes) -> bytes:
        return self._fernet.encrypt(plaintext)

    def decrypt_bytes(self, token: bytes) -> bytes:
        try:
            return self._fernet.decrypt(token)
        except Exception as exc:
            if isinstance(exc, InvalidCiphertextError):
                raise
            if _HAS_CRYPTOGRAPHY and isinstance(exc, _CryptoInvalidToken):
                raise InvalidCiphertextError("Ciphertext failed Fernet authentication/decryption.") from exc
            raise InvalidCiphertextError("Ciphertext decryption failed.") from exc

    @staticmethod
    def _safe_sqlite_backup_bytes(db_path: Path) -> bytes:
        """Create a consistent single-file SQLite backup merging WAL transactions safely."""
        with tempfile.TemporaryDirectory() as tmp:
            backup_path = Path(tmp) / "backup.db"
            src = sqlite3.connect(str(db_path), timeout=10.0)
            dst = sqlite3.connect(str(backup_path), timeout=10.0)
            try:
                src.backup(dst)
                dst.commit()
            finally:
                dst.close()
                src.close()
            return backup_path.read_bytes()

    def pack_state_dir(self, state_dir: Path, encrypted_dir: Path) -> dict[str, Any]:
        """
        Safely snapshot SQLite (with WAL backup) + JSON files into an encrypted Fernet bundle.
        Verifies zero plaintext state files exist in `encrypted_dir`.
        """
        state_dir = Path(state_dir)
        encrypted_dir = Path(encrypted_dir)
        if not state_dir.exists():
            raise StateCryptoError(f"State directory does not exist: {state_dir}")

        files_payload: dict[str, dict[str, str]] = {}
        db_files = sorted(state_dir.glob("*.db"))
        for db_file in db_files:
            raw_bytes = self._safe_sqlite_backup_bytes(db_file)
            files_payload[db_file.name] = {
                "sha256": hashlib.sha256(raw_bytes).hexdigest(),
                "b64": base64.b64encode(raw_bytes).decode("ascii"),
            }

        for item in sorted(state_dir.iterdir()):
            if not item.is_file():
                continue
            if item.name.endswith((".db", ".db-wal", ".db-shm", ".tmp")):
                continue
            raw_bytes = item.read_bytes()
            files_payload[item.name] = {
                "sha256": hashlib.sha256(raw_bytes).hexdigest(),
                "b64": base64.b64encode(raw_bytes).decode("ascii"),
            }

        bundle = {
            "schema": "organism-state-bundle-v1",
            "files": files_payload,
        }
        compressed = gzip.compress(
            json.dumps(bundle, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        )
        token = self.encrypt_bytes(compressed)

        encrypted_dir.mkdir(parents=True, exist_ok=True)
        # Purge any unexpected files so only ciphertext + non-sensitive format descriptor exist
        for existing in list(encrypted_dir.iterdir()):
            if existing.is_file() and existing.name not in {self.BUNDLE_FILENAME, self.META_FILENAME}:
                existing.unlink()

        bundle_path = encrypted_dir / self.BUNDLE_FILENAME
        tmp_bundle = bundle_path.with_suffix(".tmp")
        tmp_bundle.write_bytes(token)
        os.replace(tmp_bundle, bundle_path)

        meta = {
            "schema": "organism-state-enc-v1",
            "cipher": "Fernet-AES128-CBC-HMAC-SHA256",
            "backend": self.backend_name,
            "file_count": len(files_payload),
            "ciphertext_sha256": hashlib.sha256(token).hexdigest(),
        }
        meta_path = encrypted_dir / self.META_FILENAME
        tmp_meta = meta_path.with_suffix(".tmp")
        tmp_meta.write_text(json.dumps(meta, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        os.replace(tmp_meta, meta_path)

        assert_no_plaintext_in_publish_dir(encrypted_dir)
        return meta

    def unpack_state_dir(self, encrypted_dir: Path, state_dir: Path) -> dict[str, Any]:
        """
        Decrypt and integrity-verify an encrypted state bundle into `state_dir`.
        Fails closed before mutating `state_dir` if the key is wrong or ciphertext/checksums fail.
        """
        encrypted_dir = Path(encrypted_dir)
        state_dir = Path(state_dir)
        bundle_path = encrypted_dir / self.BUNDLE_FILENAME
        if not bundle_path.exists():
            raise StateCryptoError(f"Encrypted bundle not found: {bundle_path}")

        token = bundle_path.read_bytes()
        compressed = self.decrypt_bytes(token)
        try:
            raw_json = gzip.decompress(compressed).decode("utf-8")
            bundle = json.loads(raw_json)
        except Exception as exc:
            raise InvalidCiphertextError("Decrypted state bundle is corrupted or malformed.") from exc

        if bundle.get("schema") != "organism-state-bundle-v1" or not isinstance(bundle.get("files"), dict):
            raise InvalidCiphertextError("Unexpected state bundle schema.")

        files_dict: dict[str, dict[str, str]] = bundle["files"]
        decoded_files: dict[str, bytes] = {}
        for filename, entry in files_dict.items():
            # Prevent path traversal
            if Path(filename).name != filename or filename in {"", ".", ".."}:
                raise InvalidCiphertextError(f"Unsafe filename inside state bundle: {filename!r}")
            raw_bytes = base64.b64decode(entry["b64"].encode("ascii"))
            actual_sha = hashlib.sha256(raw_bytes).hexdigest()
            if not hmac.compare_digest(actual_sha, str(entry["sha256"])):
                raise InvalidCiphertextError(f"Checksum mismatch for {filename} inside state bundle.")
            decoded_files[filename] = raw_bytes

        # Validate SQLite integrity and snapshot integrity in temp dir BEFORE replacing state_dir
        with tempfile.TemporaryDirectory() as verify_tmp:
            verify_path = Path(verify_tmp)
            for fname, fbytes in decoded_files.items():
                (verify_path / fname).write_bytes(fbytes)

            for db_file in verify_path.glob("*.db"):
                conn = sqlite3.connect(str(db_file), timeout=10.0)
                try:
                    row = conn.execute("PRAGMA integrity_check;").fetchone()
                    if not row or str(row[0]).lower() != "ok":
                        raise InvalidCiphertextError(f"SQLite integrity check failed for {db_file.name}.")
                finally:
                    conn.close()

            snap_file = verify_path / "latest_checkpoint.json"
            if snap_file.exists():
                snap_data = json.loads(snap_file.read_text(encoding="utf-8"))
                if not IntegrityValidator.verify_snapshot(snap_data):
                    raise InvalidCiphertextError("Snapshot SHA-256 verification failed after decryption.")

        # Atomically populate target state_dir
        state_dir.mkdir(parents=True, exist_ok=True)
        for leftover in list(state_dir.iterdir()):
            if leftover.is_file() and (
                leftover.name in decoded_files or leftover.name.endswith((".db-wal", ".db-shm"))
            ):
                leftover.unlink()
        for fname, fbytes in decoded_files.items():
            target = state_dir / fname
            tmp_target = target.with_suffix(target.suffix + ".tmp")
            tmp_target.write_bytes(fbytes)
            os.replace(tmp_target, target)

        return {
            "restored_files": sorted(decoded_files.keys()),
            "file_count": len(decoded_files),
            "backend": self.backend_name,
        }


def assert_no_plaintext_in_publish_dir(publish_dir: Path) -> None:
    """
    Safety guard ensuring a directory intended for public Git storage contains ONLY
    authenticated Fernet ciphertext and non-sensitive cipher metadata.
    """
    publish_dir = Path(publish_dir)
    if not publish_dir.exists():
        return
    allowed = {StateEncryptor.BUNDLE_FILENAME, StateEncryptor.META_FILENAME}
    for path in publish_dir.rglob("*"):
        if path.is_dir():
            continue
        if path.name not in allowed or path.parent != publish_dir:
            raise StateCryptoError(
                f"Prohibited unencrypted or unexpected artifact in publish directory: {path.name}"
            )
    meta_path = publish_dir / StateEncryptor.META_FILENAME
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        allowed_keys = {"schema", "cipher", "backend", "file_count", "ciphertext_sha256"}
        extra = set(meta.keys()) - allowed_keys
        if extra:
            raise StateCryptoError(f"Unexpected metadata keys in publish directory: {sorted(extra)}")

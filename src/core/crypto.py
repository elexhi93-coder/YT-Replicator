from __future__ import annotations

"""
core.crypto — Authenticated AES-256-GCM Encryption Helper.

Protects OAuth client secrets and refresh tokens at rest (INV-1, ADJ-P2-01).
Uses AES-256 in Galois/Counter Mode (GCM) with 96-bit random IVs and 128-bit authentication tags.
Ciphertext format: base64(iv + ciphertext + tag)
"""

import base64
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from core.exceptions import MasterKeyMissingError, SecretDecryptionError

ENV_MASTER_KEY = "PLATFORM_MASTER_KEY"
NONCE_LENGTH = 12  # 96 bits recommended for AES-GCM


def _get_master_key() -> bytes:
    """Retrieve and validate the 32-byte master key from environment."""
    key_str = os.environ.get(ENV_MASTER_KEY)
    if not key_str:
        raise MasterKeyMissingError(
            f"Environment variable '{ENV_MASTER_KEY}' is not set or empty."
        )

    # Accept raw 32-byte strings or 64-char hex strings or base64 strings
    if len(key_str) == 64:
        try:
            key_bytes = bytes.fromhex(key_str)
            if len(key_bytes) == 32:
                return key_bytes
        except ValueError:
            pass

    key_bytes = key_str.encode("utf-8")
    if len(key_bytes) == 32:
        return key_bytes

    # Try base64
    try:
        decoded = base64.b64decode(key_str)
        if len(decoded) == 32:
            return decoded
    except Exception:
        pass

    raise MasterKeyMissingError(
        f"'{ENV_MASTER_KEY}' must be exactly 32 bytes (or 64 hex characters)."
    )


def encrypt(plaintext: str, key: bytes | None = None) -> str:
    """Encrypt a plaintext string using AES-256-GCM.
    
    Returns URL-safe base64 string formatted as: base64(iv + ciphertext + tag).
    """
    if not isinstance(plaintext, str):
        raise TypeError(f"Plaintext must be str, got {type(plaintext).__name__}")

    master_key = key if key is not None else _get_master_key()
    aesgcm = AESGCM(master_key)
    nonce = os.urandom(NONCE_LENGTH)
    
    # AESGCM.encrypt returns ciphertext + 16-byte tag
    data = plaintext.encode("utf-8")
    encrypted_payload = aesgcm.encrypt(nonce, data, None)
    
    # Envelope: nonce (12 bytes) + encrypted_payload (ciphertext + 16-byte tag)
    envelope = nonce + encrypted_payload
    return base64.urlsafe_b64encode(envelope).decode("utf-8")


def decrypt(token_envelope: str, key: bytes | None = None) -> str:
    """Decrypt an AES-256-GCM envelope back to plaintext.
    
    Raises SecretDecryptionError if data is corrupt, tampered with, or key mismatches.
    """
    if not isinstance(token_envelope, str):
        raise TypeError(f"Token envelope must be str, got {type(token_envelope).__name__}")

    master_key = key if key is not None else _get_master_key()
    aesgcm = AESGCM(master_key)

    try:
        raw_bytes = base64.urlsafe_b64decode(token_envelope.encode("utf-8"))
    except Exception as exc:
        raise SecretDecryptionError(f"Corrupted base64 envelope: {exc}") from exc

    if len(raw_bytes) < NONCE_LENGTH + 16:
        raise SecretDecryptionError(
            f"Envelope length ({len(raw_bytes)}) is smaller than minimum required header."
        )

    nonce = raw_bytes[:NONCE_LENGTH]
    encrypted_payload = raw_bytes[NONCE_LENGTH:]

    try:
        decrypted_bytes = aesgcm.decrypt(nonce, encrypted_payload, None)
        return decrypted_bytes.decode("utf-8")
    except Exception as exc:
        raise SecretDecryptionError(
            "Failed to decrypt secret: authentication tag mismatch or corrupted data."
        ) from exc

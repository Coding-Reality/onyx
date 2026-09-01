import os

from cryptography.fernet import Fernet, InvalidToken

_CIPHERTEXT_PREFIX = b"cr-fernet-v1:"
_KEY_ENV = "CR_ONYX_ENCRYPTION_KEY"


def _fernet(explicit_key: str | None = None) -> Fernet:
    key = explicit_key or os.environ.get(_KEY_ENV, "")
    if not key:
        raise RuntimeError(f"{_KEY_ENV} is required for credential encryption")
    try:
        return Fernet(key.encode("ascii"))
    except (TypeError, ValueError) as error:
        raise RuntimeError(f"{_KEY_ENV} is not a valid Fernet key") from error


def _encrypt_string(input_str: str, key: str | None = None) -> bytes:
    """Encrypt a tenant credential using the CR-owned Community key."""
    token = _fernet(key).encrypt(input_str.encode("utf-8"))
    return _CIPHERTEXT_PREFIX + token


def _decrypt_bytes(input_bytes: bytes, key: str | None = None) -> str:
    """Decrypt CR ciphertext and retain read compatibility with legacy CE rows."""
    if not input_bytes.startswith(_CIPHERTEXT_PREFIX):
        return input_bytes.decode("utf-8")
    try:
        plaintext = _fernet(key).decrypt(input_bytes.removeprefix(_CIPHERTEXT_PREFIX))
    except InvalidToken as error:
        raise ValueError("Credential ciphertext could not be decrypted") from error
    return plaintext.decode("utf-8")

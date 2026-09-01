import pytest
from cr_onyx.utils.encryption import _decrypt_bytes, _encrypt_string
from cryptography.fernet import Fernet


def test_credential_encryption_round_trip() -> None:
    key = Fernet.generate_key().decode("ascii")
    ciphertext = _encrypt_string("client-secret", key)

    assert b"client-secret" not in ciphertext
    assert _decrypt_bytes(ciphertext, key) == "client-secret"


def test_legacy_community_plaintext_remains_readable() -> None:
    assert _decrypt_bytes(b"legacy-secret") == "legacy-secret"


def test_ciphertext_rejects_wrong_key() -> None:
    ciphertext = _encrypt_string("client-secret", Fernet.generate_key().decode("ascii"))
    with pytest.raises(ValueError, match="could not be decrypted"):
        _decrypt_bytes(ciphertext, Fernet.generate_key().decode("ascii"))

from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from cr_onyx.db import user_tenant_mapping
from fastapi_users import exceptions

TENANT_ID = "tenant_5541b68e-2c9e-5e7a-b6a9-528022b4471a"


class _Result:
    def __init__(self, value: str | None) -> None:
        self.value = value

    def scalar_one_or_none(self) -> str | None:
        return self.value


def _install_session(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    @contextmanager
    def session(_tenant_id: str):
        def execute(_statement: Any, params: dict[str, Any]) -> _Result:
            calls.append(params)
            return _Result(TENANT_ID)

        yield SimpleNamespace(execute=execute)

    monkeypatch.setattr(user_tenant_mapping, "_tenant_catalog_session", session)
    monkeypatch.setattr(user_tenant_mapping, "get_current_tenant_id", lambda: TENANT_ID)
    return calls


def test_email_only_lookup_remains_valid_after_oauth_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_session(monkeypatch)
    assert user_tenant_mapping.resolve_tenant_id("User@Example.com") == TENANT_ID
    assert calls[0]["email"] == "user@example.com"
    assert calls[0]["oauth_identity_supplied"] is False


def test_oauth_lookup_requires_provider_and_subject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_session(monkeypatch)
    assert (
        user_tenant_mapping.resolve_tenant_id(
            "user@example.com", "keycloak", "subject-123"
        )
        == TENANT_ID
    )
    assert calls[0]["oauth_identity_supplied"] is True
    assert calls[0]["oauth_name"] == "keycloak"
    assert calls[0]["account_id"] == "subject-123"


@pytest.mark.parametrize(
    ("oauth_name", "account_id"), [("keycloak", None), (None, "subject-123")]
)
def test_partial_oauth_identity_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    oauth_name: str | None,
    account_id: str | None,
) -> None:
    _install_session(monkeypatch)
    with pytest.raises(exceptions.UserNotExists):
        user_tenant_mapping.resolve_tenant_id(
            "user@example.com", oauth_name, account_id
        )


def test_control_plane_role_is_resolved_under_current_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @contextmanager
    def session(_tenant_id: str):
        yield SimpleNamespace(execute=lambda _statement, _params: _Result("user"))

    monkeypatch.setattr(user_tenant_mapping, "_tenant_catalog_session", session)
    monkeypatch.setattr(user_tenant_mapping, "get_current_tenant_id", lambda: TENANT_ID)
    assert user_tenant_mapping.get_new_user_role("user@example.com") == "user"

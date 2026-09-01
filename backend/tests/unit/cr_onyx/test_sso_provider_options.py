from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

from onyx.db.enums import SSOProviderType
from onyx.server.manage import get_state

TENANT_A = "tenant_5541b68e-2c9e-5e7a-b6a9-528022b4471a"
TENANT_B = "tenant_0f51a790-717a-5232-94a9-6495d8a8d339"


def test_sso_provider_options_are_queried_and_cached_per_tenant(monkeypatch) -> None:
    current = {"tenant_id": TENANT_A}
    opened: list[str] = []

    @contextmanager
    def tenant_session(*, tenant_id: str):
        opened.append(tenant_id)
        yield SimpleNamespace(tenant_id=tenant_id)

    def providers(db_session: Any, enabled_only: bool):
        assert enabled_only is True
        suffix = "a" if db_session.tenant_id == TENANT_A else "b"
        return [
            SimpleNamespace(
                name=f"keycloak-{suffix}",
                display_name=f"Keycloak {suffix.upper()}",
                provider_type=SSOProviderType.OIDC,
            )
        ]

    monkeypatch.setattr(get_state, "MULTI_TENANT", True)
    monkeypatch.setattr(get_state, "sso_configuration_enabled", lambda: True)
    monkeypatch.setattr(
        get_state, "get_current_tenant_id", lambda: current["tenant_id"]
    )
    monkeypatch.setattr(get_state, "get_session_with_tenant", tenant_session)
    monkeypatch.setattr(get_state, "fetch_sso_providers", providers)
    get_state.invalidate_sso_provider_options_cache()

    first_a = get_state._fetch_sso_provider_options()
    second_a = get_state._fetch_sso_provider_options()
    current["tenant_id"] = TENANT_B
    first_b = get_state._fetch_sso_provider_options()

    assert [option.name for option in first_a] == ["keycloak-a"]
    assert second_a == first_a
    assert [option.name for option in first_b] == ["keycloak-b"]
    assert opened == [TENANT_A, TENANT_B]

from unittest.mock import patch

from onyx.db.enums import SSOProviderType
from onyx.server.manage.sso.policy import (
    sso_configuration_enabled,
    sso_provider_type_allowed,
    sso_web_domain,
)


def test_cr_ce_extension_allows_multi_tenant_sso_configuration() -> None:
    with (
        patch("onyx.server.manage.sso.policy.MULTI_TENANT", True),
        patch(
            "onyx.server.manage.sso.policy.fetch_ce_extension_implementation_with_fallback",
            return_value=lambda: True,
        ),
    ):
        assert sso_configuration_enabled() is True


def test_multi_tenant_sso_fails_closed_without_ce_extension() -> None:
    with (
        patch("onyx.server.manage.sso.policy.MULTI_TENANT", True),
        patch(
            "onyx.server.manage.sso.policy.fetch_ce_extension_implementation_with_fallback",
            return_value=lambda: False,
        ),
    ):
        assert sso_configuration_enabled() is False


def test_cr_extension_allows_only_oidc_in_multi_tenant_mode() -> None:
    def allowed(provider_type: SSOProviderType) -> bool:
        return provider_type is SSOProviderType.OIDC

    with (
        patch("onyx.server.manage.sso.policy.MULTI_TENANT", True),
        patch(
            "onyx.server.manage.sso.policy.fetch_ce_extension_implementation_with_fallback",
            return_value=allowed,
        ),
    ):
        assert sso_provider_type_allowed(SSOProviderType.OIDC) is True
        assert sso_provider_type_allowed(SSOProviderType.SAML) is False
        assert sso_provider_type_allowed(SSOProviderType.GOOGLE_OAUTH) is False


def test_multi_tenant_web_domain_comes_from_ce_extension() -> None:
    request = object()
    with (
        patch("onyx.server.manage.sso.policy.MULTI_TENANT", True),
        patch(
            "onyx.server.manage.sso.policy.fetch_ce_extension_implementation_with_fallback",
            return_value=lambda actual_request: (
                "https://tenant-a.example.com"
                if actual_request is request
                else "https://wrong.example.com"
            ),
        ),
    ):
        assert sso_web_domain(request) == "https://tenant-a.example.com"

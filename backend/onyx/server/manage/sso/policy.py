from urllib.parse import urlparse

from fastapi import Request

from onyx.configs.app_configs import WEB_DOMAIN
from onyx.db.enums import SSOProviderType
from onyx.utils.variable_functionality import (
    fetch_ce_extension_implementation_with_fallback,
)
from shared_configs.configs import MULTI_TENANT


def sso_configuration_enabled() -> bool:
    """Whether this deployment may manage SSO providers for this workspace.

    Upstream Community Edition supports SSO provider rows for a single-tenant
    deployment.  A multi-tenant deployment must provide its own authorization
    and tenant-scoping policy through the optional CE extension package.
    """
    if not MULTI_TENANT:
        return True

    allow_multi_tenant_sso = fetch_ce_extension_implementation_with_fallback(
        "onyx.server.manage.sso.policy",
        "allow_multi_tenant_sso_configuration",
        lambda: False,
    )
    return bool(allow_multi_tenant_sso())


def sso_provider_type_allowed(provider_type: SSOProviderType) -> bool:
    """Fail closed on multi-tenant protocol types the CE extension did not bind."""
    if not MULTI_TENANT:
        return True
    is_allowed = fetch_ce_extension_implementation_with_fallback(
        "onyx.server.manage.sso.policy",
        "multi_tenant_sso_provider_type_allowed",
        lambda _provider_type: False,
    )
    return bool(is_allowed(provider_type))


def sso_web_domain(request: Request) -> str:
    """Return the trusted callback origin for the current tenant request."""
    if not MULTI_TENANT:
        return WEB_DOMAIN.rstrip("/")
    resolve_web_domain = fetch_ce_extension_implementation_with_fallback(
        "onyx.server.manage.sso.policy",
        "get_tenant_web_domain",
        lambda _request: "",
    )
    web_domain = str(resolve_web_domain(request)).rstrip("/")
    parsed = urlparse(web_domain)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError("CE extension returned an invalid tenant web domain")
    return web_domain

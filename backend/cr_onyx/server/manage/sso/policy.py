import os
from typing import Any

from onyx.db.enums import SSOProviderType


def allow_multi_tenant_sso_configuration() -> bool:
    """Enable upstream CE SSO CRUD after CR tenant middleware has scoped it.

    The CR application always installs ``TenantContextMiddleware`` before the
    request reaches these routes.  Provider rows therefore live in the schema
    selected from the operator-owned hostname map, and the admin dependency is
    evaluated against the user table in that same tenant schema.
    """
    return True


def multi_tenant_sso_provider_type_allowed(
    provider_type: SSOProviderType,
) -> bool:
    """Keycloak uses OIDC; other protocols remain disabled until tenant-bound."""
    return provider_type is SSOProviderType.OIDC


def get_tenant_web_domain(request: Any) -> str:
    """Build an origin only from the hostname verified by tenant middleware."""
    tenant_host = getattr(request.state, "tenant_host", None)
    if not isinstance(tenant_host, str) or not tenant_host:
        raise RuntimeError("Verified tenant host is missing from request context")
    scheme = os.environ.get("CR_TENANT_PUBLIC_SCHEME", "https").strip().lower()
    if scheme not in {"http", "https"}:
        raise RuntimeError("CR_TENANT_PUBLIC_SCHEME must be http or https")
    return f"{scheme}://{tenant_host}"

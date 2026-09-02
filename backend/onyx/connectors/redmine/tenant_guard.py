from onyx.utils.variable_functionality import (
    fetch_ce_extension_implementation_with_fallback,
)


def _allow_unmanaged_installation(base_url: str, root_project_id: int) -> None:
    """Default for upstream and single-tenant installations."""


def enforce_tenant_binding(base_url: str, root_project_id: int) -> None:
    guard = fetch_ce_extension_implementation_with_fallback(
        "onyx.connectors.redmine.tenant_guard",
        "enforce_tenant_binding",
        _allow_unmanaged_installation,
    )
    guard(base_url, root_project_id)

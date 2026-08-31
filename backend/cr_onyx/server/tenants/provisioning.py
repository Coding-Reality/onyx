from typing import Any

from cr_onyx.db.user_tenant_mapping import resolve_tenant_id


async def get_or_provision_tenant(
    *,
    email: str,
    oauth_name: str | None = None,
    account_id: str | None = None,
    **_: Any,
) -> str:
    """Resolve a pre-provisioned membership. Public sign-up creates no tenant."""
    return resolve_tenant_id(email, oauth_name, account_id)

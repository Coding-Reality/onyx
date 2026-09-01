from collections.abc import Iterator
from contextlib import contextmanager

from fastapi_users import exceptions as fastapi_users_exceptions
from sqlalchemy import text
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_catalog_session
from shared_configs.contextvars import get_current_tenant_id


def _normalized_email(email: str) -> str:
    return email.strip().lower()


def _tenant_uuid(tenant_id: str) -> str:
    if not tenant_id.startswith("tenant_"):
        raise ValueError("Invalid tenant context")
    return tenant_id.removeprefix("tenant_")


@contextmanager
def _tenant_catalog_session(tenant_id: str) -> Iterator[Session]:
    with get_catalog_session() as session:
        session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": _tenant_uuid(tenant_id)},
        )
        yield session


def _resolve_membership(
    email: str,
    oauth_name: str | None = None,
    account_id: str | None = None,
) -> str:
    if (oauth_name is None) != (account_id is None):
        raise fastapi_users_exceptions.UserNotExists()

    tenant_id = get_current_tenant_id()
    with _tenant_catalog_session(tenant_id) as session:
        row = session.execute(
            text(
                """
                SELECT tenant.schema_name
                FROM public.cr_tenant_membership AS membership
                JOIN public.cr_tenant AS tenant ON tenant.id = membership.tenant_id
                WHERE membership.tenant_id = :tenant_id
                  AND tenant.status = 'active'
                  AND (
                    (:oauth_identity_supplied = false
                     AND membership.email = :email)
                    OR
                    (:oauth_identity_supplied = true AND (
                      (membership.oauth_provider = :oauth_name
                       AND membership.oauth_subject = :account_id)
                      OR
                      (membership.oauth_subject IS NULL
                       AND membership.email = :email)
                    ))
                  )
                """
            ),
            {
                "tenant_id": _tenant_uuid(tenant_id),
                "email": _normalized_email(email),
                "oauth_name": oauth_name,
                "account_id": account_id,
                "oauth_identity_supplied": oauth_name is not None,
            },
        ).scalar_one_or_none()
    if row != tenant_id:
        raise fastapi_users_exceptions.UserNotExists()
    return tenant_id


def get_tenant_id_for_email(email: str) -> str:
    return _resolve_membership(email)


def get_new_user_role(email: str) -> str:
    """Return the role provisioned in the tenant control plane.

    OAuth registration has already resolved the same active membership before
    this is called.  Re-reading under RLS prevents a first-login user marked
    ``user`` from becoming admin merely because their tenant schema is empty.
    """
    tenant_id = get_current_tenant_id()
    with _tenant_catalog_session(tenant_id) as session:
        role = session.execute(
            text(
                """
                SELECT membership.role
                FROM public.cr_tenant_membership AS membership
                JOIN public.cr_tenant AS tenant ON tenant.id = membership.tenant_id
                WHERE membership.tenant_id = :tenant_id
                  AND membership.email = :email
                  AND tenant.status = 'active'
                """
            ),
            {
                "tenant_id": _tenant_uuid(tenant_id),
                "email": _normalized_email(email),
            },
        ).scalar_one_or_none()
    if role not in {"admin", "user"}:
        raise fastapi_users_exceptions.UserNotExists()
    return role


def resolve_tenant_id(
    email: str,
    oauth_name: str | None = None,
    account_id: str | None = None,
) -> str:
    return _resolve_membership(email, oauth_name, account_id)


def record_oauth_identity(
    email: str,
    tenant_id: str,
    oauth_name: str,
    account_id: str,
) -> None:
    if tenant_id != get_current_tenant_id():
        raise ValueError("Tenant context mismatch")
    with _tenant_catalog_session(tenant_id) as session:
        updated = session.execute(
            text(
                """
                UPDATE public.cr_tenant_membership
                SET oauth_provider = :oauth_name, oauth_subject = :account_id
                WHERE tenant_id = :tenant_id AND email = :email
                  AND (
                    oauth_subject IS NULL
                    OR (oauth_provider = :oauth_name AND oauth_subject = :account_id)
                  )
                RETURNING 1
                """
            ),
            {
                "tenant_id": _tenant_uuid(tenant_id),
                "email": _normalized_email(email),
                "oauth_name": oauth_name,
                "account_id": account_id,
            },
        ).scalar_one_or_none()
        if updated is None:
            raise fastapi_users_exceptions.UserNotExists()
        session.commit()


def rekey_user_mapping_email(
    email: str,
    tenant_id: str,
    oauth_identities: list[tuple[str, str]],
    previous_email: str | None = None,
) -> None:
    if tenant_id != get_current_tenant_id() or not previous_email:
        return
    if not oauth_identities:
        raise ValueError("A verified OAuth identity is required to rekey membership")
    oauth_name, account_id = oauth_identities[0]
    with _tenant_catalog_session(tenant_id) as session:
        updated = session.execute(
            text(
                """
                UPDATE public.cr_tenant_membership
                SET email = :email
                WHERE tenant_id = :tenant_id AND email = :previous_email
                  AND oauth_provider = :oauth_name AND oauth_subject = :account_id
                RETURNING 1
                """
            ),
            {
                "tenant_id": _tenant_uuid(tenant_id),
                "email": _normalized_email(email),
                "previous_email": _normalized_email(previous_email),
                "oauth_name": oauth_name,
                "account_id": account_id,
            },
        ).scalar_one_or_none()
        if updated is None:
            raise fastapi_users_exceptions.UserNotExists()
        session.commit()

from collections.abc import Collection
from typing import Any

from sqlalchemy import text

from onyx.access.models import ExternalAccess
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.db.engine.sql_engine import get_catalog_session
from shared_configs.contextvars import get_current_tenant_id


def redmine_binding_for_current_tenant() -> dict[str, Any]:
    tenant_schema = get_current_tenant_id()
    with get_catalog_session() as session:
        configuration = session.execute(
            text(
                """
                SELECT configuration
                FROM public.cr_tenant
                WHERE schema_name = :tenant_schema AND status = 'active'
                """
            ),
            {"tenant_schema": tenant_schema},
        ).scalar_one_or_none()
    if not isinstance(configuration, dict):
        raise ConnectorValidationError("Onyx tenant has no active control-plane row")
    integrations = configuration.get("integrations")
    if not isinstance(integrations, dict):
        raise ConnectorValidationError("Onyx tenant has no integration bindings")
    redmine = integrations.get("redmine")
    if not isinstance(redmine, dict):
        raise ConnectorValidationError("Onyx tenant has no Redmine binding")
    return redmine


def tenant_wiki_access(project_ids: Collection[int]) -> ExternalAccess:
    if not project_ids:
        raise ConnectorValidationError("Redmine permission scope has no projects")
    tenant_schema = get_current_tenant_id()
    with get_catalog_session() as session:
        tenant_id = session.execute(
            text(
                """
                SELECT id FROM public.cr_tenant
                WHERE schema_name = :tenant_schema AND status = 'active'
                """
            ),
            {"tenant_schema": tenant_schema},
        ).scalar_one_or_none()
        if tenant_id is None:
            raise ConnectorValidationError("Onyx tenant is not active")
        session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(tenant_id)},
        )
        snapshot = (
            session.execute(
                text(
                    """
                    SELECT snapshot.redmine_group_id,
                           tenant.configuration #>>
                             '{integrations,redmine,redmine_group_id}' AS bound_group_id
                    FROM public.cr_redmine_identity_snapshot AS snapshot
                    JOIN public.cr_tenant AS tenant ON tenant.id = snapshot.tenant_id
                    WHERE snapshot.tenant_id = :tenant_id
                    """
                ),
                {"tenant_id": str(tenant_id)},
            )
            .mappings()
            .one_or_none()
        )
        if snapshot is None:
            raise ConnectorValidationError(
                "Redmine identity projection has not been synchronized"
            )
        if str(snapshot["redmine_group_id"]) != snapshot["bound_group_id"]:
            raise ConnectorValidationError(
                "Redmine identity projection does not match the tenant binding"
            )
        rows = session.execute(
            text(
                """
                SELECT membership.email
                FROM public.cr_tenant_membership AS membership
                JOIN public.cr_redmine_identity AS redmine_identity
                  ON redmine_identity.tenant_id = membership.tenant_id
                 AND redmine_identity.email = membership.email
                WHERE membership.tenant_id = :tenant_id
                ORDER BY membership.email
                """
            ),
            {"tenant_id": str(tenant_id)},
        )
        emails = {
            str(row.email).strip().lower()
            for row in rows
            if row.email and "@" in str(row.email)
        }
    return ExternalAccess(
        external_user_emails=emails,
        external_user_group_ids=set(),
        is_public=False,
    )

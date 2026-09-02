import json
import uuid
from collections.abc import Sequence
from copy import deepcopy
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.schema import CreateSchema

from cr_onyx.tenancy.integrations import RedmineTenantBinding
from onyx.db.engine.sql_engine import get_catalog_session
from onyx.db.engine.tenant_utils import validate_tenant_id

CONTROL_PLANE_MIGRATION = Path(__file__).parent / "migrations" / "001_control_plane.sql"


def schema_name_for_tenant(tenant_id: uuid.UUID) -> str:
    return f"tenant_{tenant_id}"


def apply_control_plane_migration() -> None:
    migration_sql = CONTROL_PLANE_MIGRATION.read_text()
    with get_catalog_session() as session:
        session.connection().exec_driver_sql(migration_sql)
        session.commit()


def _set_rls_tenant(session, tenant_id: uuid.UUID) -> None:
    session.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": str(tenant_id)},
    )


def create_tenant(
    tenant_id: uuid.UUID,
    slug: str,
    name: str,
    hostnames: Sequence[str],
    configuration: dict[str, object] | None = None,
) -> str:
    schema_name = schema_name_for_tenant(tenant_id)
    if not validate_tenant_id(schema_name):
        raise ValueError("Generated tenant schema is invalid")

    normalized_hosts = sorted(
        {hostname.strip().lower().rstrip(".") for hostname in hostnames}
    )
    if not normalized_hosts or any(not hostname for hostname in normalized_hosts):
        raise ValueError("At least one non-empty tenant host is required")

    with get_catalog_session() as session:
        session.execute(CreateSchema(schema_name, if_not_exists=True))
        session.execute(
            text(
                """
                INSERT INTO public.cr_tenant
                    (id, slug, name, schema_name, status, configuration)
                VALUES
                    (:id, :slug, :name, :schema_name, 'active', CAST(:configuration AS jsonb))
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    configuration = EXCLUDED.configuration
                """
            ),
            {
                "id": str(tenant_id),
                "slug": slug.strip(),
                "name": name.strip(),
                "schema_name": schema_name,
                "configuration": json.dumps(configuration or {}),
            },
        )
        _set_rls_tenant(session, tenant_id)
        for hostname in normalized_hosts:
            session.execute(
                text(
                    """
                    INSERT INTO public.cr_tenant_host (hostname, tenant_id)
                    VALUES (:hostname, :tenant_id)
                    ON CONFLICT (hostname) DO UPDATE SET tenant_id = EXCLUDED.tenant_id
                    """
                ),
                {"hostname": hostname, "tenant_id": str(tenant_id)},
            )
        session.commit()
    return schema_name


def set_tenant_status(slug: str, status: str) -> None:
    if status not in {"active", "disabled"}:
        raise ValueError("Tenant status must be active or disabled")
    with get_catalog_session() as session:
        updated = session.execute(
            text(
                """
                UPDATE public.cr_tenant SET status = :status
                WHERE slug = :slug
                RETURNING id
                """
            ),
            {"status": status, "slug": slug},
        ).scalar_one_or_none()
        if updated is None:
            raise ValueError("Tenant does not exist")
        session.commit()


def set_redmine_tenant_binding(
    slug: str,
    binding: RedmineTenantBinding,
    actor: str,
) -> None:
    """Install an audited RevenueOS projection without storing credentials."""
    normalized_actor = actor.strip()
    if not normalized_actor:
        raise ValueError("Binding actor is required")

    with get_catalog_session() as session:
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": f"cr_redmine_binding:{slug.strip()}"},
        )
        tenant = (
            session.execute(
                text(
                    """
                    SELECT id, configuration
                    FROM public.cr_tenant
                    WHERE slug = :slug
                    FOR UPDATE
                    """
                ),
                {"slug": slug.strip()},
            )
            .mappings()
            .one_or_none()
        )
        if tenant is None:
            raise ValueError("Tenant does not exist")

        configuration = deepcopy(tenant["configuration"] or {})
        if not isinstance(configuration, dict):
            raise ValueError("Tenant configuration is invalid")
        integrations = configuration.setdefault("integrations", {})
        if not isinstance(integrations, dict):
            raise ValueError("Tenant integration configuration is invalid")
        binding_json = binding.model_dump(mode="json")
        integrations["redmine"] = binding_json

        _set_rls_tenant(session, tenant["id"])
        session.execute(
            text(
                """
                UPDATE public.cr_tenant
                SET configuration = CAST(:configuration AS jsonb)
                WHERE id = :tenant_id
                """
            ),
            {
                "tenant_id": str(tenant["id"]),
                "configuration": json.dumps(configuration),
            },
        )
        session.execute(
            text(
                """
                INSERT INTO public.cr_tenant_audit
                    (tenant_id, actor, action, target, detail)
                VALUES
                    (:tenant_id, :actor, 'set_redmine_binding', 'redmine',
                     CAST(:detail AS jsonb))
                """
            ),
            {
                "tenant_id": str(tenant["id"]),
                "actor": normalized_actor,
                "detail": json.dumps(binding_json),
            },
        )
        session.commit()


def replace_redmine_identity_snapshot(
    slug: str,
    redmine_group_id: int,
    identities: Sequence[tuple[int, str]],
    actor: str,
) -> None:
    """Atomically replace the explicit Redmine-to-Onyx identity intersection."""
    normalized_actor = actor.strip()
    if not normalized_actor:
        raise ValueError("Identity snapshot actor is required")
    if redmine_group_id <= 0:
        raise ValueError("Redmine group ID must be positive")

    normalized: list[tuple[int, str]] = []
    seen_user_ids: set[int] = set()
    seen_emails: set[str] = set()
    for redmine_user_id, email in identities:
        normalized_email = email.strip().lower()
        if redmine_user_id <= 0 or "@" not in normalized_email:
            raise ValueError("Each Redmine identity requires a valid ID and email")
        if redmine_user_id in seen_user_ids or normalized_email in seen_emails:
            raise ValueError("Redmine identity snapshot contains duplicates")
        seen_user_ids.add(redmine_user_id)
        seen_emails.add(normalized_email)
        normalized.append((redmine_user_id, normalized_email))

    with get_catalog_session() as session:
        tenant_id = session.execute(
            text("SELECT id FROM public.cr_tenant WHERE slug = :slug FOR UPDATE"),
            {"slug": slug.strip()},
        ).scalar_one_or_none()
        if tenant_id is None:
            raise ValueError("Tenant does not exist")
        _set_rls_tenant(session, tenant_id)
        session.execute(
            text("DELETE FROM public.cr_redmine_identity WHERE tenant_id = :tenant_id"),
            {"tenant_id": str(tenant_id)},
        )
        for redmine_user_id, email in normalized:
            session.execute(
                text(
                    """
                    INSERT INTO public.cr_redmine_identity
                        (tenant_id, redmine_user_id, email)
                    VALUES (:tenant_id, :redmine_user_id, :email)
                    """
                ),
                {
                    "tenant_id": str(tenant_id),
                    "redmine_user_id": redmine_user_id,
                    "email": email,
                },
            )
        session.execute(
            text(
                """
                INSERT INTO public.cr_redmine_identity_snapshot
                    (tenant_id, redmine_group_id, identity_count, actor, synced_at)
                VALUES (:tenant_id, :redmine_group_id, :identity_count, :actor, now())
                ON CONFLICT (tenant_id) DO UPDATE SET
                    redmine_group_id = EXCLUDED.redmine_group_id,
                    identity_count = EXCLUDED.identity_count,
                    actor = EXCLUDED.actor,
                    synced_at = now()
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "redmine_group_id": redmine_group_id,
                "identity_count": len(normalized),
                "actor": normalized_actor,
            },
        )
        session.execute(
            text(
                """
                INSERT INTO public.cr_tenant_audit
                    (tenant_id, actor, action, target, detail)
                VALUES
                    (:tenant_id, :actor, 'replace_redmine_identity_snapshot',
                     'redmine', CAST(:detail AS jsonb))
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "actor": normalized_actor,
                "detail": json.dumps(
                    {
                        "redmine_group_id": redmine_group_id,
                        "identity_count": len(normalized),
                    }
                ),
            },
        )
        session.commit()


def add_tenant_user(slug: str, email: str, role: str) -> None:
    if role not in {"admin", "user"}:
        raise ValueError("Tenant role must be admin or user")
    with get_catalog_session() as session:
        tenant_id = session.execute(
            text("SELECT id FROM public.cr_tenant WHERE slug = :slug"),
            {"slug": slug},
        ).scalar_one_or_none()
        if tenant_id is None:
            raise ValueError("Tenant does not exist")
        _set_rls_tenant(session, tenant_id)
        session.execute(
            text(
                """
                INSERT INTO public.cr_tenant_membership (tenant_id, email, role)
                VALUES (:tenant_id, :email, :role)
                ON CONFLICT (tenant_id, email) DO UPDATE SET role = EXCLUDED.role
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "email": email.strip().lower(),
                "role": role,
            },
        )
        session.commit()


def remove_tenant_user(slug: str, email: str) -> None:
    with get_catalog_session() as session:
        tenant_id = session.execute(
            text("SELECT id FROM public.cr_tenant WHERE slug = :slug"),
            {"slug": slug},
        ).scalar_one_or_none()
        if tenant_id is None:
            raise ValueError("Tenant does not exist")
        _set_rls_tenant(session, tenant_id)
        session.execute(
            text(
                """
                DELETE FROM public.cr_tenant_membership
                WHERE tenant_id = :tenant_id AND email = :email
                """
            ),
            {"tenant_id": str(tenant_id), "email": email.strip().lower()},
        )
        session.commit()


def tenant_host_map() -> dict[str, str]:
    with get_catalog_session() as session:
        rows = session.execute(
            text(
                """
                SELECT host.hostname, tenant.schema_name
                FROM public.cr_tenant_host AS host
                JOIN public.cr_tenant AS tenant ON tenant.id = host.tenant_id
                WHERE tenant.status = 'active'
                ORDER BY host.hostname
                """
            )
        )
        return {row.hostname: row.schema_name for row in rows}

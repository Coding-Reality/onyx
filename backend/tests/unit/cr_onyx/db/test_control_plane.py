import uuid
from unittest.mock import MagicMock, patch

import pytest
from cr_onyx.db.control_plane import (
    replace_redmine_identity_snapshot,
    schema_name_for_tenant,
    set_redmine_tenant_binding,
)
from cr_onyx.tenancy.integrations import RedmineTenantBinding


def test_schema_name_for_tenant_is_upstream_compatible() -> None:
    tenant_id = uuid.UUID("088b9a54-e144-58e7-a210-800f2201a6c1")
    assert schema_name_for_tenant(tenant_id) == (
        "tenant_088b9a54-e144-58e7-a210-800f2201a6c1"
    )


def test_invalid_uuid_is_rejected_before_schema_creation() -> None:
    with pytest.raises(ValueError):
        uuid.UUID("coding-reality")


def test_redmine_binding_update_is_audited() -> None:
    tenant_id = uuid.UUID("088b9a54-e144-58e7-a210-800f2201a6c1")
    tenant_result = MagicMock()
    tenant_result.mappings.return_value.one_or_none.return_value = {
        "id": tenant_id,
        "configuration": {"existing": True},
    }
    session = MagicMock()
    session.execute.side_effect = [tenant_result, MagicMock(), MagicMock(), MagicMock()]
    context = MagicMock()
    context.__enter__.return_value = session
    binding = RedmineTenantBinding(
        revenueos_tenant_id="tenant-coding-reality",
        base_url="https://redmine.example",
        root_project_id=1,
        redmine_group_id=6,
    )

    with patch("cr_onyx.db.control_plane.get_catalog_session", return_value=context):
        set_redmine_tenant_binding("coding-reality", binding, "gitops/post-sync")

    assert session.execute.call_count == 4
    executed_sql = "\n".join(
        str(call.args[0]) for call in session.execute.call_args_list
    )
    assert "UPDATE public.cr_tenant" in executed_sql
    assert "INSERT INTO public.cr_tenant_audit" in executed_sql
    update_parameters = session.execute.call_args_list[2].args[1]
    assert '"existing": true' in update_parameters["configuration"]
    assert '"enabled": false' in update_parameters["configuration"]
    session.commit.assert_called_once()


def test_redmine_binding_update_requires_actor() -> None:
    binding = RedmineTenantBinding(
        revenueos_tenant_id="tenant-coding-reality",
        base_url="https://redmine.example",
        root_project_id=1,
        redmine_group_id=6,
    )

    with pytest.raises(ValueError, match="actor"):
        set_redmine_tenant_binding("coding-reality", binding, " ")


def test_redmine_identity_snapshot_is_atomic_and_audited() -> None:
    tenant_id = uuid.UUID("088b9a54-e144-58e7-a210-800f2201a6c1")
    tenant_result = MagicMock()
    tenant_result.scalar_one_or_none.return_value = tenant_id
    session = MagicMock()
    session.execute.side_effect = [
        tenant_result,
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    ]
    context = MagicMock()
    context.__enter__.return_value = session

    with patch("cr_onyx.db.control_plane.get_catalog_session", return_value=context):
        replace_redmine_identity_snapshot(
            "coding-reality",
            42,
            [(9, " Member@Example.COM ")],
            "revenueos/identity-sync",
        )

    executed_sql = "\n".join(
        str(call.args[0]) for call in session.execute.call_args_list
    )
    assert "DELETE FROM public.cr_redmine_identity" in executed_sql
    assert "INSERT INTO public.cr_redmine_identity" in executed_sql
    assert "INSERT INTO public.cr_redmine_identity_snapshot" in executed_sql
    assert "replace_redmine_identity_snapshot" in executed_sql
    identity_parameters = session.execute.call_args_list[3].args[1]
    assert identity_parameters["email"] == "member@example.com"
    session.commit.assert_called_once()


def test_redmine_identity_snapshot_rejects_ambiguous_mapping() -> None:
    with pytest.raises(ValueError, match="duplicates"):
        replace_redmine_identity_snapshot(
            "coding-reality",
            42,
            [(9, "member@example.com"), (10, "member@example.com")],
            "revenueos/identity-sync",
        )

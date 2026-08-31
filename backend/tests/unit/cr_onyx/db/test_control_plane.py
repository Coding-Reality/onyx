import uuid

import pytest
from cr_onyx.db.control_plane import schema_name_for_tenant


def test_schema_name_for_tenant_is_upstream_compatible() -> None:
    tenant_id = uuid.UUID("088b9a54-e144-58e7-a210-800f2201a6c1")
    assert schema_name_for_tenant(tenant_id) == (
        "tenant_088b9a54-e144-58e7-a210-800f2201a6c1"
    )


def test_invalid_uuid_is_rejected_before_schema_creation() -> None:
    with pytest.raises(ValueError):
        uuid.UUID("coding-reality")

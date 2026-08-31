import json
import os
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict

from onyx.db.engine.tenant_utils import validate_tenant_id
from shared_configs.contextvars import (
    CURRENT_TENANT_ID_CONTEXTVAR,
    get_current_user_id,
)


class TenantContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: str
    user_id: str | None = None


def load_tenant_host_map(raw_value: str | None = None) -> Mapping[str, str]:
    raw_value = (
        raw_value
        if raw_value is not None
        else os.environ.get("CR_ONYX_TENANT_HOST_MAP", "{}")
    )
    parsed = json.loads(raw_value)
    if not isinstance(parsed, dict):
        raise ValueError("CR_ONYX_TENANT_HOST_MAP must be a JSON object")

    tenant_host_map: dict[str, str] = {}
    for raw_host, raw_tenant_id in parsed.items():
        host = str(raw_host).strip().lower().rstrip(".")
        tenant_id = str(raw_tenant_id).strip()
        if not host:
            raise ValueError("Tenant host names must not be empty")
        if not validate_tenant_id(tenant_id):
            raise ValueError(f"Invalid tenant ID for host {host}")
        tenant_host_map[host] = tenant_id
    return tenant_host_map


def get_tenant_context() -> TenantContext:
    tenant_id = CURRENT_TENANT_ID_CONTEXTVAR.get()
    if tenant_id is None:
        raise RuntimeError("Tenant context is not set")
    return TenantContext(tenant_id=tenant_id, user_id=get_current_user_id())

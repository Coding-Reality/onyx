import json
from typing import Any

import pytest
from cr_onyx.tenancy.context import load_tenant_host_map
from cr_onyx.tenancy.middleware import TenantContextMiddleware

from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

TENANT_A = "tenant_5541b68e-2c9e-5e7a-b6a9-528022b4471a"
TENANT_B = "tenant_0f51a790-717a-5232-94a9-6495d8a8d339"


def test_load_tenant_host_map_validates_tenant_ids() -> None:
    with pytest.raises(ValueError, match="Invalid tenant ID"):
        load_tenant_host_map(json.dumps({"tenant.example.com": "coding-reality"}))


async def _request(
    middleware: TenantContextMiddleware,
    host: str,
    authorization: str | None = None,
    forwarded_host: str | None = None,
) -> tuple[int, str | None]:
    observed_tenant: str | None = None
    response_status = 0

    async def app(_scope: dict[str, Any], _receive: Any, send: Any) -> None:
        nonlocal observed_tenant
        observed_tenant = CURRENT_TENANT_ID_CONTEXTVAR.get()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        nonlocal response_status
        if message["type"] == "http.response.start":
            response_status = int(message["status"])

    headers = [(b"host", host.encode())]
    if forwarded_host:
        headers.append((b"x-forwarded-host", forwarded_host.encode()))
    if authorization:
        headers.append((b"authorization", authorization.encode()))
    scope = {"type": "http", "method": "GET", "path": "/api/chat", "headers": headers}
    middleware = TenantContextMiddleware(app, middleware.tenant_host_map)
    await middleware(scope, receive, send)
    return response_status, observed_tenant


@pytest.mark.asyncio
async def test_host_mapping_sets_and_clears_tenant_context() -> None:
    original_tenant = CURRENT_TENANT_ID_CONTEXTVAR.get()
    middleware = TenantContextMiddleware(lambda: None, {"a.example.com": TENANT_A})
    status, observed_tenant = await _request(middleware, "a.example.com")
    assert status == 200
    assert observed_tenant == TENANT_A
    assert CURRENT_TENANT_ID_CONTEXTVAR.get() == original_tenant


@pytest.mark.asyncio
async def test_unmapped_host_fails_closed() -> None:
    middleware = TenantContextMiddleware(lambda: None, {"a.example.com": TENANT_A})
    status, observed_tenant = await _request(middleware, "unknown.example.com")
    assert status == 421
    assert observed_tenant is None


@pytest.mark.asyncio
async def test_forwarded_external_host_resolves_server_side_request() -> None:
    middleware = TenantContextMiddleware(lambda: None, {"a.example.com": TENANT_A})
    status, observed_tenant = await _request(
        middleware,
        "onyx-api-service",
        forwarded_host="a.example.com",
    )
    assert status == 200
    assert observed_tenant == TENANT_A


@pytest.mark.asyncio
async def test_unmapped_forwarded_host_fails_closed() -> None:
    middleware = TenantContextMiddleware(lambda: None, {"a.example.com": TENANT_A})
    status, observed_tenant = await _request(
        middleware,
        "a.example.com",
        forwarded_host="unknown.example.com",
    )
    assert status == 421
    assert observed_tenant is None


@pytest.mark.asyncio
async def test_credential_tenant_must_match_host_tenant() -> None:
    middleware = TenantContextMiddleware(lambda: None, {"a.example.com": TENANT_A})
    authorization = f"Bearer on_{TENANT_B}.not-a-real-secret"
    status, observed_tenant = await _request(middleware, "a.example.com", authorization)
    assert status == 403
    assert observed_tenant is None

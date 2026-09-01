from collections.abc import Mapping
from typing import Any

from cr_onyx.tenancy.context import load_tenant_host_map
from onyx.auth.utils import extract_tenant_from_auth_header
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

_PUBLIC_PATHS = frozenset({"/health", "/health/ready", "/metrics"})


class TenantContextMiddleware:
    """Resolve tenant context from an operator-owned host mapping."""

    def __init__(
        self,
        app: Any,
        tenant_host_map: Mapping[str, str] | None = None,
    ) -> None:
        self.app = app
        self.tenant_host_map = tenant_host_map or load_tenant_host_map()

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Any,
        send: Any,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path", ""))
        if path in _PUBLIC_PATHS:
            token = CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA)
            try:
                await self.app(scope, receive, send)
            finally:
                CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
            return

        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        # The public nginx proxy overwrites X-Forwarded-Host with the external
        # host, and the Next.js server propagates that same value for its
        # server-side API fetches. Resolve only through the operator-owned map;
        # an unknown or forged hostname still fails closed.
        forwarded_host = headers.get("x-forwarded-host", "").split(",", 1)[0]
        host = forwarded_host or headers.get("host", "")
        host = host.split(":", 1)[0].lower().rstrip(".")
        tenant_id = self.tenant_host_map.get(host)
        if tenant_id is None:
            await self._reject(send, 421, "Unmapped tenant host")
            return

        from starlette.requests import Request

        token_tenant_id = extract_tenant_from_auth_header(Request(scope))
        if token_tenant_id is not None and token_tenant_id != tenant_id:
            await self._reject(send, 403, "Credential tenant does not match host")
            return

        context_token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
        scope.setdefault("state", {})["tenant_id"] = tenant_id
        try:
            await self.app(scope, receive, send)
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(context_token)

    @staticmethod
    async def _reject(send: Any, status_code: int, detail: str) -> None:
        body = f'{{"detail":"{detail}"}}'.encode()
        await send(
            {
                "type": "http.response.start",
                "status": status_code,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

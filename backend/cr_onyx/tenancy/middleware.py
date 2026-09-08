from collections.abc import Mapping
from typing import Any

from cr_onyx.tenancy.context import load_allowed_tenant_ids, load_tenant_host_map
from onyx.auth.session_tokens import SessionRejection, classify_session_token_value
from onyx.auth.utils import extract_tenant_from_auth_header
from onyx.configs.app_configs import REDIS_AUTH_KEY_PREFIX
from onyx.configs.constants import FASTAPI_USERS_AUTH_COOKIE_NAME
from onyx.redis.redis_pool import get_async_redis_connection
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

_PUBLIC_PATHS = frozenset({"/health", "/health/ready", "/metrics"})


class TenantContextMiddleware:
    """Resolve tenant context on the single trusted host.

    Unauthenticated requests use the host's bootstrap tenant. Authenticated
    requests use the tenant embedded in the server-side Redis session or in a
    tenant-bound API credential. Both must be operator-allowlisted.
    """

    def __init__(
        self,
        app: Any,
        tenant_host_map: Mapping[str, str] | None = None,
        allowed_tenant_ids: frozenset[str] | None = None,
    ) -> None:
        self.app = app
        self.tenant_host_map = (
            tenant_host_map if tenant_host_map is not None else load_tenant_host_map()
        )
        self.allowed_tenant_ids = (
            allowed_tenant_ids
            if allowed_tenant_ids is not None
            else load_allowed_tenant_ids()
        )

    async def _session_tenant(self, request: Any) -> str | None:
        token = request.cookies.get(FASTAPI_USERS_AUTH_COOKIE_NAME)
        if not token:
            return None
        redis = await get_async_redis_connection()
        result = classify_session_token_value(
            await redis.get(f"{REDIS_AUTH_KEY_PREFIX}{token}")
        )
        if isinstance(result, SessionRejection):
            return None
        return result.tenant_id

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

        request = Request(scope)
        credential_tenant_id = extract_tenant_from_auth_header(request)
        session_tenant_id = await self._session_tenant(request)
        if (
            credential_tenant_id is not None
            and session_tenant_id is not None
            and credential_tenant_id != session_tenant_id
        ):
            await self._reject(send, 403, "Credential and session tenants differ")
            return

        authenticated_tenant_id = credential_tenant_id or session_tenant_id
        if authenticated_tenant_id is not None:
            if authenticated_tenant_id not in self.allowed_tenant_ids:
                await self._reject(send, 403, "Credential tenant is not allowed")
                return
            tenant_id = authenticated_tenant_id

        context_token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
        scope.setdefault("state", {})["tenant_id"] = tenant_id
        # This is safe to reuse for callbacks: ``host`` came from the
        # operator-owned single-host map, never from an unverified tenant value.
        scope["state"]["tenant_host"] = host
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

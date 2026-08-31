from fastapi import FastAPI

from cr_onyx.tenancy.middleware import TenantContextMiddleware


def get_application() -> FastAPI:
    from onyx.main import get_application as get_community_application

    application = get_community_application()
    application.add_middleware(TenantContextMiddleware)
    return application

from urllib.parse import urlparse

from pydantic import ValidationError

from cr_onyx.db.redmine import redmine_binding_for_current_tenant
from cr_onyx.tenancy.integrations import RedmineTenantBinding
from onyx.connectors.exceptions import ConnectorValidationError


def _normalized_base_url(url: str) -> tuple[str, str, int | None, str]:
    parsed = urlparse(url.rstrip("/"))
    scheme = parsed.scheme.lower()
    port = parsed.port
    if port is None:
        port = 443 if scheme == "https" else 80 if scheme == "http" else None
    return scheme, (parsed.hostname or "").lower(), port, parsed.path.rstrip("/")


def enforce_tenant_binding(base_url: str, root_project_id: int) -> None:
    try:
        binding = RedmineTenantBinding.model_validate(
            redmine_binding_for_current_tenant()
        )
    except ValidationError as error:
        raise ConnectorValidationError(
            "Onyx tenant has an invalid Redmine binding"
        ) from error
    if not binding.enabled:
        raise ConnectorValidationError("Redmine is disabled for this Onyx tenant")
    if _normalized_base_url(binding.base_url) != _normalized_base_url(base_url):
        raise ConnectorValidationError("Redmine base URL does not match tenant binding")
    if binding.root_project_id != root_project_id:
        raise ConnectorValidationError("Redmine root does not match tenant binding")

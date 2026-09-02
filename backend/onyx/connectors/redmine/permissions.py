from collections.abc import Collection

from onyx.access.models import ExternalAccess
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.utils.variable_functionality import (
    fetch_ce_extension_implementation_with_fallback,
)


def _permission_sync_unavailable(_project_ids: Collection[int]) -> ExternalAccess:
    raise ConnectorValidationError(
        "Redmine permission synchronization is not configured for this installation"
    )


def tenant_wiki_access(project_ids: Collection[int]) -> ExternalAccess:
    provider = fetch_ce_extension_implementation_with_fallback(
        "onyx.connectors.redmine.permissions",
        "tenant_wiki_access",
        _permission_sync_unavailable,
    )
    return provider(project_ids)

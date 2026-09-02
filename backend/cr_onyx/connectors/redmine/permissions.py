from collections.abc import Collection

from cr_onyx.db.redmine import tenant_wiki_access as db_tenant_wiki_access
from onyx.access.models import ExternalAccess


def tenant_wiki_access(project_ids: Collection[int]) -> ExternalAccess:
    """Return the current tenant-wide Wiki ACL from the Onyx control plane."""
    return db_tenant_wiki_access(project_ids)

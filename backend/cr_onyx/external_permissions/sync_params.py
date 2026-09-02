from onyx.configs.constants import DocumentSource


def source_should_fetch_permissions_during_indexing(source: DocumentSource) -> bool:
    """Enable ACL-bearing indexing only for reviewed CR Community sources."""
    return source == DocumentSource.REDMINE

from onyx.document_index.interfaces_new import TenantState
from onyx.document_index.opensearch.schema import (
    DOCUMENT_ID_FIELD_NAME,
    TENANT_ID_FIELD_NAME,
)
from onyx.document_index.opensearch.search import DocumentQuery

TENANT_A = "tenant_a"
TENANT_B = "tenant_b"


def _tenant_term(tenant_id: str) -> dict[str, object]:
    return {"term": {TENANT_ID_FIELD_NAME: {"value": tenant_id}}}


def test_direct_document_filter_is_always_tenant_scoped() -> None:
    filters = DocumentQuery._get_search_filters(
        tenant_state=TenantState(tenant_id=TENANT_A, multitenant=True),
        include_hidden=True,
        access_control_list=None,
        source_types=[],
        tags=[],
        document_sets=[],
        project_id_filter=None,
        persona_id_filter=None,
        created_at_range=None,
        updated_at_range=None,
        min_chunk_index=None,
        max_chunk_index=None,
        document_id="document-owned-by-tenant-b",
    )

    assert _tenant_term(TENANT_A) in filters
    assert _tenant_term(TENANT_B) not in filters
    assert {"term": {DOCUMENT_ID_FIELD_NAME: {"value": "document-owned-by-tenant-b"}}} in filters


def test_direct_document_delete_is_always_tenant_scoped() -> None:
    query = DocumentQuery.delete_port_written_chunks_query(
        document_ids=["document-owned-by-tenant-b"],
        tenant_state=TenantState(tenant_id=TENANT_A, multitenant=True),
    )

    filters = query["query"]["bool"]["filter"]
    assert _tenant_term(TENANT_A) in filters
    assert _tenant_term(TENANT_B) not in filters

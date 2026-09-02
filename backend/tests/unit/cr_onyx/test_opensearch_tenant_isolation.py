from onyx.document_index.interfaces_new import TenantState
from onyx.document_index.opensearch.schema import TENANT_ID_FIELD_NAME
from onyx.document_index.opensearch.search import DocumentQuery


def test_multitenant_delete_query_cannot_target_another_tenant() -> None:
    tenant = TenantState(tenant_id="tenant_a", multitenant=True)

    query = DocumentQuery.delete_from_document_id_query("shared-document-id", tenant)

    filters = query["query"]["bool"]["filter"]
    assert {"term": {TENANT_ID_FIELD_NAME: {"value": "tenant_a"}}} in filters


def test_multitenant_port_cleanup_keeps_tenant_filter() -> None:
    tenant = TenantState(tenant_id="tenant_b", multitenant=True)

    query = DocumentQuery.delete_port_written_chunks_query(["doc"], tenant)

    filters = query["query"]["bool"]["filter"]
    assert {"term": {TENANT_ID_FIELD_NAME: {"value": "tenant_b"}}} in filters

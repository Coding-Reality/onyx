# ADR: Redmine as organizational knowledge source for Onyx

Status: Accepted for development; production enablement is conditional.

Date: 2026-09-02.

## Context

Redmine is the operational source for projects, Wiki knowledge, issues, and files.
Onyx provides semantic retrieval and assistants. Shared Redmine uses private project
isolation. Onyx uses tenant SQL schemas and a shared tenant-filtered OpenSearch index.

The integration must preserve source authority, tenant isolation, internal ACLs,
updates, deletions, hierarchy, attachments, source links, and recovery behavior.

## Alternatives

### Native Onyx connector

Uses Onyx credentials, checkpoints, workers, pruning, hierarchy, file parsers, ACLs,
and tenant context. It needs changes in the Onyx fork and careful upstream separation.

### External ingestion service

Can deploy independently. It would duplicate scheduler, checkpoint, prune, parser,
and ACL logic. It also adds a tenant-routing API boundary and larger leak risk.

### Hybrid native connector plus webhook hints

Uses native polling and reconciliation for correctness. A signed webhook can request
faster targeted refresh without becoming the source of truth.

## Decision

Implement a native connector. Keep generic Redmine code under
`onyx/connectors/redmine`. Keep Coding Reality tenant binding under `cr_onyx`.
Consider signed webhook hints only after polling operates correctly.

Use one connector and one tenant-scoped Redmine credential per Onyx tenant. Bind it
to one numeric Redmine tenant root through operator-owned configuration. Reject a
missing or mismatched binding.

Index current Wiki pages first. Add optional attachments as child documents. Use
checkpointed updates and slim reconciliation. Defer Documents and issues.

## Security implications

The design has two independent isolation layers: tenant routing and source ACLs.
Onyx metadata never substitutes for the trusted tenant field. Redmine credentials
must not span tenants. Identity mapping failures grant no access.

The CR Community extension implements Redmine-only document ACL synchronization.
RevenueOS projects Redmine user IDs and normalized mail for the exact bound tenant
group into an RLS-scoped snapshot; Onyx intersects it with its own tenant members.
Missing or mismatched snapshots fail closed and a synchronized empty group revokes
everyone. Production remains blocked until this path passes end-to-end staging
addition/removal tests. Internal Onyx connector groups are not treated as source ACLs.

## Operational implications

The connector adds Redmine API load from frequent metadata scans and daily full ID
reconciliation. Attachment bytes pass through Onyx workers and native parsers.
Workers need Redmine egress and metric scraping. Bad attachments fail independently.

Redmine remains unchanged and authoritative. MinIO backup archives are not ingested.

## Migration implications

No content moves out of Redmine as a new source of truth. Existing Wiki URLs remain
canonical. Page renames appear as delete/create until Redmine exposes immutable Wiki
IDs. Connector rollback removes only Onyx index data.

The connector can be proposed upstream because its client and document mapping are
generic. The `cr_onyx` control-plane guard and RevenueOS mapping remain local.

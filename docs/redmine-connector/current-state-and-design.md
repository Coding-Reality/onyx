# Production Redmine connector assessment and design

Status: production Wiki vertical slice deployed and acceptance-tested. Documents and
Issues remain separately gated future phases.

Assessment date: 2026-09-02 UTC.

## Executive decision

Build a first-class native Onyx connector. Add an optional event trigger later.

The native path gives the connector Onyx checkpoints, pruning, hierarchy,
attachment parsing, credentials, worker retries, and tenant context. An external
ingestion service would duplicate these controls and could bypass tenant routing.

Use this boundary for each production connector:

```text
one RevenueOS tenant
  -> one Onyx tenant schema
  -> one operator-owned Redmine root mapping
  -> one tenant-scoped Redmine read-only API identity
  -> one Redmine root and its approved descendants
```

The Coding Reality connector is enabled with its own non-admin, tenant-scoped
Redmine identity. RevenueOS owns the immutable Redmine root/group to Onyx tenant
mapping and projects the authoritative identity intersection every two minutes.
Attachments and permission synchronization are enabled; Issues remain disabled.

### Production closure evidence (2026-09-02)

- Argo CD reports Onyx and Windmill synced and healthy at cloud revision
  `d726675ac82784e548ffd27447dff34a6d50729a`.
- All Onyx backend and worker workloads use the audited CE image built from
  `e489e6a68`, pinned by digest. The web workload uses the matching connector UI
  image built from `3eb108b91`.
- The scoped Redmine credential sees ten approved Coding Reality projects,
  including root project `1`, and zero foreign tenant roots.
- The connector indexed Wiki create/update state incrementally, reconstructed a
  parent/child page hierarchy, indexed a text attachment as a child document, and
  preserved canonical Redmine links and normalized metadata.
- A group removal produced an authoritative zero-identity snapshot and reduced
  both PostgreSQL and OpenSearch ACLs to zero while the document remained private.
  Restoring membership returned both ACLs to one.
- Deleting the acceptance page and forcing authoritative prune removed its page,
  hierarchy node, attachment document, and both unique OpenSearch canaries.
- The recurring identity schedule completed successfully on the isolated
  `revenueos-identity` worker tag with overlap disabled.
- The focused final suite passed 43 Python tests, 13 Windmill projection
  assertions, Ruff, and ty.

## Evidence labels

- **Observed** means local source, live API, database, or Kubernetes state proved it.
- **Inferred** means code behavior strongly supports the conclusion.
- **Required** means the design adds a control which does not exist yet.
- **Unresolved** means rollout must stay blocked for that boundary.

## Current Onyx deployment

### Observed

- Argo CD application: `onyx`, healthy and synced.
- Namespace: `onyx` on `crc-k3s`.
- Helm chart: `0.8.19`; cloud application revision:
  `d726675ac82784e548ffd27447dff34a6d50729a`.
- Product version: `v4.6.5`.
- Backend image source commit: `e489e6a68b1d56ccc8bc1329c6c3991bef9bc544`.
- Backend image: private `ghcr.io/coding-reality/onyx-backend` build.
- Web image: private `ghcr.io/coding-reality/onyx-web-server` build.
- Local source is the `Coding-Reality/onyx` fork on `cr/main` at that backend commit.
- The fork includes Community, Enterprise-derived, and `cr_onyx` extension code.
- Paid Enterprise features and license enforcement are disabled.
- `ONYX_CE_EXTENSION_PACKAGE=cr_onyx` loads local Community extensions.
- `MULTI_TENANT=true`; authentication is basic authentication.
- PostgreSQL is CloudNativePG with one PostgreSQL pod and a 20 Gi Longhorn PVC.
- Redis uses one operator-managed pod and a 1 Gi Longhorn PVC.
- MinIO uses a 30 Gi Longhorn PVC for Onyx file storage.
- OpenSearch `3.6.0` uses one node and a 64 Gi Longhorn PVC.
- No Vespa workload exists. Vespa names in code are migration compatibility paths.
- Celery has beat, primary, doc-fetching, doc-processing, light, heavy,
  monitoring, and user-file-processing workers.
- Worker metric services exist. Helm ServiceMonitors are disabled.

Relevant source paths:

- `backend/cr_onyx/tenancy/middleware.py`
- `backend/cr_onyx/db/control_plane.py`
- `backend/onyx/db/engine/sql_engine.py`
- `backend/onyx/document_index/opensearch/`
- `backend/onyx/background/celery/apps/`
- `backend/onyx/background/celery/tasks/beat_schedule.py`
- `backend/onyx/connectors/interfaces.py`
- `backend/onyx/connectors/models.py`

### Exact Onyx tenant boundary

The operator maps a trusted host to an Onyx tenant schema. Middleware rejects an
unknown host with 421. It rejects a credential tenant which differs from the host
with 403.

Onyx has these live control-plane tenants:

| Slug | SQL schema | Purpose |
|---|---|---|
| `coding-reality` | `tenant_b41264e1-9035-5fbd-8bc6-6c7c315b649b` | Real tenant |
| `tenant-a` | `tenant_aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa` | Isolation fixture |
| `tenant-b` | `tenant_bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb` | Isolation fixture |

Each schema has separate users, groups, connectors, credentials, connector pairs,
documents, document sets, and personas. A connector and credential therefore
belong to one Onyx tenant schema. They are not global.

Celery beat adds `tenant_id` to scheduled tasks. Tenant-aware tasks set the same
context before database and index work. Direct task dispatch remains a sensitive
path because missing context can fall back to the default schema.

OpenSearch has one shared document index. Chunks carry `tenant_id`, and query,
update, and delete paths construct a tenant filter from current context. Thus SQL
schema isolation and OpenSearch tenant filtering are separate controls.

### Onyx boundary rollout state

The inspected live RevenueOS registry had no `service=onyx` integration row and
the live Onyx tenant configuration JSON was empty. Source now includes a staged
RevenueOS mapping, a strict secret-free `RedmineTenantBinding`, an audited
control-plane writer, and a runtime guard. These facts remain rollout evidence,
not live state, until the migrations and binding are applied.

Do not let a tenant admin select an arbitrary Redmine root. Store the approved
Redmine base URL and numeric root ID in the Onyx public control plane. A local
extension guard must compare it on every connector run.

## Current Redmine deployment

### Observed

- Argo CD application: `shared-redmine`, healthy and synced.
- Namespace: `redmine-shared` on `crc-k3s`.
- Redmine: `6.0.10.stable`; Rails `7.2.3.1`.
- Image: `redmine:6.0.10-bookworm`.
- One Rails web pod; no separate Redmine worker.
- PostgreSQL `17.9`, dedicated `redmine` database and role on shared PostgreSQL.
- Plugins: `redmine_oidc 0.2.0` and `redmine_revenueos_admin 0.2.0`.
- REST API enabled; JSONP disabled.
- Login required; self-registration disabled; new projects default private.
- Anonymous and Non-member roles have no permissions.
- Text formatter: `common_mark`.
- OIDC issuer: shared Keycloak global realm.
- OIDC maps verified, lower-case email and reconciles `tenant-*` groups on login.
- API integrations use Redmine API keys.
- Attachments are on `/usr/src/redmine/files` on a 10 Gi Longhorn PVC.
- MinIO stores verified backup archives. It is not live attachment storage.
- Six-hour logical database/files backups and MinIO read-back verification exist.
- All former dedicated Redmine sources are offline and retained.

Relevant source and deployment paths:

- `cr/technology/cloud-as-code/argo-cd/manifests/shared-redmine/`
- `cr/technology/cloud-as-code/docs/shared-redmine-multitenancy.md`
- `cr/technology/cloud-as-code/docs/shared-redmine-migration-report.md`
- Redmine tables: `projects`, `wikis`, `wiki_pages`, `wiki_contents`,
  `wiki_content_versions`, `attachments`, `issues`, `journals`, `members`,
  `member_roles`, `roles`, `users`, and `groups_users`.

### Exact Redmine tenant boundary

RevenueOS `revenueos.tenant.id` is authoritative. Its `tenant_integration` row
stores the Redmine numeric root and group IDs. Redmine stores the same tenant ID
as a required hidden project custom value.

| RevenueOS tenant | Root project | Group | Registry state |
|---|---:|---:|---|
| `tenant-coding-reality` | 1 | 6 | active |
| `tenant-andrew` | 2 | 7 | staging |
| `tenant-deai-summit` | 3 | 8 | staging |
| `tenant-tlm` | 66 | 89 | active |
| `tenant-m2a` | 67 | 90 | active |

All 20 live projects are private. Migrated subprojects inherit tenant membership.
The current model provides tenant-wide access. It does not yet express separate
Management, Sales, and Engineering ACLs.

Redmine tenant isolation is application-level. All tenants share one database,
process, and attachment volume. Project ancestry, private state, tenant custom
value, group membership, and role checks form the security boundary. The hidden
`tenant_id` field is operator-verifiable but is not returned to a least-privilege
non-admin API account, so the connector cannot treat that field as a runtime ACL.

### Current inventory

| Object | Count |
|---|---:|
| Projects | 20 |
| Wiki containers | 53 |
| Current Wiki pages | 86 |
| Wiki versions | 131 |
| Issues | 166 |
| Journals | 4,682 |
| Attachments | 66 |
| Documents records | 0 |

Attachments total about 18.9 MB: 39 PDF, 22 PNG, 3 SVG, one Markdown, and
one octet-stream object. Four belong to Wiki pages, 48 to issues, and 13 to the
Files module.

## Tenant mapping specification

```text
RevenueOS tenant.id                         authoritative identity
  -> tenant_integration(service=redmine)    trusted numeric project/group IDs
  -> private Redmine tenant root            operator validates tenant_id field
  -> private descendant projects            runtime ancestry revalidated
  -> tenant-scoped Redmine API account      sees only this tree
  -> cr_tenant.configuration.integrations.redmine
  -> Onyx tenant UUID and SQL schema         operator-owned host mapping
  -> Redmine connector + credential          rows inside that schema only
  -> Onyx documents                          SQL row in that schema
  -> OpenSearch chunks                       mandatory matching tenant_id field
```

Required mapping record in the Onyx control plane:

```json
{
  "integrations": {
    "redmine": {
      "schema_version": 1,
      "revenueos_tenant_id": "tenant-coding-reality",
      "base_url": "https://redmine.cloud.coding-reality.com",
      "root_project_id": 1,
      "redmine_group_id": 6,
      "enabled": false
    }
  }
}
```

The `enabled` flag must stay false until isolation tests and credential scope pass.
The CR Onyx extension exposes an audited `set_redmine_tenant_binding` control-plane
operation for the Cloud GitOps projection. It validates this schema, replaces only
the Redmine integration subtree under a row lock, and records the non-secret value
in `cr_tenant_audit`.

## Redmine capability matrix

| Resource | API available | Incremental sync | Permissions | Attachments | Recommendation |
|---|---|---|---|---|---|
| Wiki | Yes, core Alpha REST | Full metadata scan; compare version/time | Project `view_wiki_pages`; no per-page read ACL | Included on detail | Phase 1; latest only |
| Wiki attachments | Yes | Reconcile with changed parent and full prune | Inherit Wiki/project ACL | Direct authorized download | Phase 2; child documents |
| Documents | No supported representation | None | Project `view_documents` | Document contains files | Defer; add narrow REST plugin, never scrape |
| Files | Yes, core Alpha REST | Full list; IDs and digests | Project `view_files` | Resource is an attachment | Default off; strict filters |
| Issues | Yes | `updated_on`, pagination, overlap | Project role plus private-issue rules | Included on detail | Later; current state per issue |
| Journals | Through issue detail | Refetch when issue changes | Private notes can be narrower | Attribution is incomplete | Visible notes as issue sections |
| Issue attachments | Yes | Reconcile with issue | Inherit issue ACL | Direct authorized download | Later child documents |
| Projects | Yes | Full paginated visible scan | API returns visible projects | N/A | Validate scope and hierarchy |
| Memberships | Yes | Full per-project snapshot | Read permission needed | N/A | Needed for ACL sync |
| Groups | Partial | Full snapshot | List is admin-only; direct visible group works | N/A | Use explicit group API extension or IdP |

## Connector architecture

```text
RevenueOS registry / Onyx control plane
                | trusted tenant binding
                v
Redmine REST API -> retrying Redmine client
                -> project-scope validator
                -> Wiki metadata scanner
                -> current page converter
                -> optional attachment downloader
                -> permission mapper (disabled initially)
                -> hierarchy emitter
                -> checkpointed connector + slim reconciliation
                -> Onyx doc-fetching worker
                -> Onyx document processing and native file parsing
                -> tenant SQL schema + shared tenant-filtered OpenSearch index
```

Use a native connector, not the ingestion API, because native connector work is
already tenant-routed and recoverable. Use a hybrid only for future webhook hints.
Polling and authoritative reconciliation remain the correctness path.

## Connector configuration

Connector configuration contains non-secret source scope and behavior:

```yaml
base_url: https://redmine.cloud.coding-reality.com
root_project_id: 1
include_subprojects: true
include_attachments: false
batch_size: 100
overlap_seconds: 300
max_attachment_size_mb: 100
allowed_content_types:
  - application/pdf
  - text/*
  - application/vnd.openxmlformats-officedocument.*
```

Credentials contain only `redmine_api_key`. Use a separate read-only Redmine API
account for each tenant. Store it through Onyx encrypted credentials and the
existing Vault/External Secret flow. Never store it in Git.

Tenant configuration contains immutable RevenueOS tenant, numeric Redmine root,
numeric group, Onyx UUID, and Onyx schema mappings. Only the platform operator can
change it.

Deployment configuration contains feature flags, worker sizing, timeouts, metrics
scrape settings, and egress policy. Do not put source credentials there.

## Content and hierarchy model

Use stable, type-prefixed IDs:

```text
redmine:project:12
redmine:wiki:12:Advertising_Operations
redmine:wiki_attachment:456
redmine:issue:892
redmine:issue_attachment:917
```

Wiki titles are not immutable. A rename is a new ID plus prune of the old ID until
a Redmine endpoint exposes `wiki_pages.id`.

```text
Redmine
  -> tenant root project
     -> project / subproject
        -> Wiki page
           -> child page
           -> attachment document
```

Index only the current Wiki version. Keep version, author, created time, and
updated time as metadata. Do not index old versions by default.

Split Wiki bodies at CommonMark headings. Add the project and page title to each
section. Preserve lists, tables, links, and code. Every section receives an
absolute canonical page URL; relative links inside the body remain source markup
until a dedicated link normalizer is added. Keep unknown Redmine macros as text.

Normalized Wiki metadata:

```json
{
  "source": "redmine",
  "resource_type": "wiki_page",
  "project_id": "12",
  "project_identifier": "m2a",
  "project_name": "M2Adverts",
  "wiki_page_title": "Advertising Operations",
  "wiki_version": "8",
  "author": "Person Name",
  "redmine_url": "https://redmine.example/projects/m2a/wiki/Advertising_Operations"
}
```

Do not add `tenant_id` as user metadata. The Onyx indexing layer owns the trusted
tenant field. User metadata must never be a security control.

## Synchronization and deletion

Every 5-15 minutes:

1. Load the operator tenant binding.
2. Resolve the configured root and visible descendants.
3. Reject public, foreign, or out-of-tree projects. The tenant-scoped account must
   expose no project outside the bound tree.
4. Read each project Wiki index.
5. Select pages whose update time overlaps the requested time window.
6. Fetch current bodies and changed attachments.
7. Return a checkpoint after each bounded metadata page.

Use a five-minute overlap and idempotent document IDs. Keep the sync end fixed for
an attempt, so a page changed during the scan appears on the next overlapping run.

Every 24 hours, enumerate all authoritative page and enabled attachment IDs with
the slim connector. Let Onyx pruning remove absent documents. Run a faster targeted
permission reconciliation when ACL sync exists. Permission revocation must not wait
for the content prune.

Webhooks can later request a targeted refresh. Each event needs tenant ID, numeric
project ID, resource type, resource ID, operation, update/version, delivery ID, and
HMAC. Never depend only on webhooks.

## Attachments

Download through Redmine with the tenant-scoped API identity. Do not read the
Redmine PVC or backup MinIO bucket.

Create one child document per supported attachment. Retain filename, MIME, size,
author, creation time, attachment ID, parent page, and the authorized Redmine URL.
Reject redirects to another origin so an API key cannot leak.

Reuse Onyx parsers for PDF, DOCX, PPTX, XLSX/XLSM, CSV/TSV, text, Markdown, HTML,
EML, EPUB, and supported images. Keep SVG, archives, installers, and generic binary
objects off by default. Isolate a corrupt attachment as `ConnectorFailure`.

## Permission design

Tenant isolation and source ACLs are different controls.

Upstream Community behavior does not turn an internal connector-group association
into document search ACLs. The CR extension now supplies the missing path for
Redmine only: `CheckpointedConnectorWithPermSync`, slim permission enumeration,
preservation of stored external ACLs during indexing, and a recurring tenant-aware
reconciliation task. No other Community connector is implicitly enabled.

RevenueOS resolves the exact current members of the immutable Redmine tenant group
using the audited provisioner and atomically writes an RLS-scoped identity snapshot.
Onyx intersects that snapshot with its own tenant memberships by normalized email.
The snapshot records the bound numeric group ID, which must match the operator-owned
tenant binding. Missing or mismatched snapshots fail validation; a valid empty
snapshot produces an empty private ACL and revokes all access. Email remains the
bridge, but ambiguity or hidden mail blocks the projection instead of widening it.

Required fail-closed rules:

- Blank, hidden, duplicate, or malformed identity: grant no access.
- Missing membership snapshot: keep the previous ACL or remove access; never public.
- Private issue or journal without exact mapping: do not index it.
- Removed user/group: apply ACL removal before ordinary content cleanup.

The projection stores Redmine user ID plus normalized email, while Onyx membership
stores the verified OIDC subject when a user signs in. RevenueOS remains the
cross-system mapping owner. Redmine group reconciliation currently happens at
login, so the recurring projection and the existing permission audit are both
required; correctness never depends on a webhook.

## Issues and organizational knowledge

Add issues only after Wiki and ACL controls are stable. Use one document per current
issue. Put useful visible journals into dated sections. Skip field-only journal
noise. Do not make every journal a document: the migrated corpus has about 4,682
journals for 166 issues.

Redmine Wiki is suitable for living knowledge. Use conventions, not connector code:

- `Meeting_YYYY-MM-DD_Topic`
- `Decision_YYYY-MM-DD_Topic`
- `SOP_Topic`
- `Architecture_System`

Use a decision Wiki page for durable rationale and link it to meeting pages and
execution issues. Add a dedicated tracker only when decisions need workflow,
owners, review dates, or compliance reports.

## Observability and recovery

Reuse Onyx connector, indexing, pruning, permission-sync, and Celery task metrics.
The implementation adds low-cardinality Redmine request count/duration, final 429,
attachment outcome, permission-run outcome, and changed/revoked ACL counters.
Use source and outcome labels.
Do not use tenant ID, project ID, page title, URL, or attachment name as labels.

Log the tenant schema, connector pair ID, Redmine numeric project ID, resource type,
and stable resource ID. Do not log API keys, page bodies, private titles, attachment
URLs with tokens, or identity lists.

Use bounded retries with exponential backoff and `Retry-After`. A page or attachment
conversion failure produces `ConnectorFailure`; HTTP scope or tenant validation
failure stops the run. Checkpoints update only after a complete bounded batch.

## Threat model

| Threat | Required mitigation |
|---|---|
| Cross-tenant indexing | Operator mapping, tenant-scoped key, private root, runtime ancestry checks, operator-side custom-field validation, schema context, OpenSearch tenant filter |
| Permission widening | Private connector pair, fail-closed ACLs, no fallback to public |
| Stale permissions | Fast authoritative IdP/registry reconciliation and full periodic snapshot |
| Deleted source remains | Daily slim reconciliation/prune; urgent targeted delete later |
| Credential leakage | Encrypted Onyx credential, Vault delivery, log redaction, same-origin downloads |
| Attachment URL leakage | Store authorized Redmine URL; Redmine rechecks access; never presign backup storage |
| Tenant admin selects foreign root | Compare with operator control-plane binding on every run |
| Worker loses tenant context | Tenant-aware tasks, explicit tests, reject default schema in multi-tenant connector work |

## Test strategy

Unit tests cover API pagination, Wiki conversion, metadata, hierarchy, checkpoints,
same-origin attachment downloads, MIME/size filtering, and failure isolation.

Disposable Redmine tests cover page create/update/delete/rename, parent changes,
attachments, module disablement, subprojects, role changes, hidden email, group
changes, private issues, and corrupt files.

Multi-tenant Onyx tests must prove:

| Assertion | Expected |
|---|---|
| Tenant A user -> Tenant A Wiki | yes |
| Tenant A user -> Tenant B Wiki | no |
| Project member -> private project Wiki | yes |
| Non-member -> private project Wiki | no |
| Permission removed -> result after ACL sync | no |
| Group membership added -> result | yes |
| Group membership removed -> result | no |
| Missing worker tenant context | task rejected |
| Mismatched root mapping | connector rejected |

Run retrieval tests against real PostgreSQL, Redis, MinIO, OpenSearch, model servers,
and workers. Search for unique canary strings and inspect citations and source URLs.

## Phased implementation and rollout

1. Add the disabled native source, Wiki client, hierarchy, metadata, checkpoints,
   slim reconciliation, and unit tests.
2. Add attachment child documents and parser tests. Keep attachments off by default.
3. Provision the trusted Onyx mapping and one tenant-scoped Redmine identity.
4. Run tenant isolation tests with one private, single-user staging connector.
5. Deploy and acceptance-test the implemented identity projection and document ACL
   reconciliation before enabling multi-user access.
6. Add Documents through a reviewed Redmine REST extension if demand exists.
7. Add non-private issues, journals, and attachments with exact issue ACL tests.
8. Add signed webhook hints only if polling freshness is insufficient.

Feature gates:

```text
REDMINE_CONNECTOR_ENABLED
REDMINE_ATTACHMENTS_ENABLED
REDMINE_PERMISSION_SYNC_ENABLED
REDMINE_ISSUES_ENABLED
```

Rollback: pause the connector pair, disable its scheduled identity sync, and delete
its indexed documents through the asynchronous Onyx deletion-attempt flow. Do not
use immediate credential dissociation on a pair with indexing history. Keep Redmine unchanged.
Restore the previous application image and values through GitOps if code rollback is
needed. Never delete source Redmine data during connector rollback.

## Production gates

- [x] Apply the authoritative RevenueOS-to-Onyx tenant integration mapping.
- [x] Put the matching Redmine mapping in the operator-owned Onyx control plane.
- [x] Provision and audit one tenant-scoped, non-admin Redmine account.
- [x] Prove that the account cannot enumerate another tenant root.
- [x] Stage privately before switching the pair to permission synchronization.
- [x] Deploy CE Redmine-only permission reconciliation before multi-user use.
- [x] Pass tenant canary tests in SQL, OpenSearch, hierarchy, and source links.
- [x] Enable permission sync only after explicit identity grant/revocation tests.
- [x] Expose low-cardinality connector, attachment, permission, failure, and prune metrics.
- [x] Prove source deletion and attachment removal through authoritative prune.
- [x] Document a source-preserving GitOps rollback.

These gates close the Wiki vertical slice only. Documents, Files, Issues, Journals,
and event-triggered refresh remain disabled until their own permission and scale
acceptance tests pass.

## References

- Redmine REST overview: <https://www.redmine.org/projects/redmine/wiki/REST_Api>
- Wiki API: <https://www.redmine.org/projects/redmine/wiki/Rest_WikiPages>
- Attachment API: <https://www.redmine.org/projects/redmine/wiki/Rest_Attachments>
- Files API: <https://www.redmine.org/projects/redmine/wiki/Rest_Files>
- Issues API: <https://www.redmine.org/projects/redmine/wiki/Rest_Issues>
- Membership API: <https://www.redmine.org/projects/redmine/wiki/Rest_Memberships>
- Groups API: <https://www.redmine.org/projects/redmine/wiki/Rest_Groups>

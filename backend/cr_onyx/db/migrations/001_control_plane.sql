CREATE TABLE IF NOT EXISTS public.cr_tenant (
    id uuid PRIMARY KEY,
    slug text NOT NULL UNIQUE,
    name text NOT NULL,
    schema_name text NOT NULL UNIQUE,
    status text NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'disabled')),
    configuration jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (schema_name ~ '^tenant_[a-f0-9-]{36}$')
);

CREATE TABLE IF NOT EXISTS public.cr_tenant_host (
    hostname text PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES public.cr_tenant(id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.cr_tenant_membership (
    tenant_id uuid NOT NULL REFERENCES public.cr_tenant(id) ON DELETE CASCADE,
    email text NOT NULL,
    role text NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user')),
    oauth_provider text,
    oauth_subject text,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, email)
);

CREATE UNIQUE INDEX IF NOT EXISTS cr_tenant_membership_oauth_identity
    ON public.cr_tenant_membership (tenant_id, oauth_provider, oauth_subject)
    WHERE oauth_provider IS NOT NULL AND oauth_subject IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.cr_tenant_audit (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES public.cr_tenant(id) ON DELETE RESTRICT,
    actor text NOT NULL,
    action text NOT NULL,
    target text,
    detail jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.cr_tenant_membership ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.cr_tenant_membership FORCE ROW LEVEL SECURITY;
ALTER TABLE public.cr_tenant_audit ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.cr_tenant_audit FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS cr_tenant_membership_isolation ON public.cr_tenant_membership;
CREATE POLICY cr_tenant_membership_isolation ON public.cr_tenant_membership
    USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);

DROP POLICY IF EXISTS cr_tenant_audit_isolation ON public.cr_tenant_audit;
CREATE POLICY cr_tenant_audit_isolation ON public.cr_tenant_audit
    USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);

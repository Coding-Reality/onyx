import argparse
import json
import subprocess
import uuid
from pathlib import Path

from cr_onyx.db.control_plane import (
    add_tenant_user,
    apply_control_plane_migration,
    create_tenant,
    remove_tenant_user,
    set_tenant_status,
    tenant_host_map,
)

from onyx.configs.constants import POSTGRES_UNKNOWN_APP_NAME
from onyx.db.engine.sql_engine import SqlEngine, get_session_with_tenant
from onyx.setup import setup_onyx
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR


def _initialize_database_engine() -> None:
    SqlEngine.set_app_name(POSTGRES_UNKNOWN_APP_NAME)
    SqlEngine.init_engine(pool_size=2, max_overflow=1)


def _migrate_tenant_schema(schema_name: str) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    subprocess.run(
        ["alembic", "-x", f"schemas={schema_name}", "upgrade", "head"],
        cwd=backend_dir,
        check=True,
    )


def _initialize_tenant(schema_name: str) -> None:
    context_token = CURRENT_TENANT_ID_CONTEXTVAR.set(schema_name)
    try:
        with get_session_with_tenant(tenant_id=schema_name) as session:
            setup_onyx(session, schema_name)
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(context_token)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Coding Reality Onyx tenant control")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("migrate-control-plane")

    create_parser = subparsers.add_parser("create-tenant")
    create_parser.add_argument("--id", required=True, type=uuid.UUID)
    create_parser.add_argument("--slug", required=True)
    create_parser.add_argument("--name", required=True)
    create_parser.add_argument("--host", action="append", required=True)
    create_parser.add_argument("--configuration", default="{}")
    create_parser.add_argument("--skip-initialize", action="store_true")

    status_parser = subparsers.add_parser("set-status")
    status_parser.add_argument("--slug", required=True)
    status_parser.add_argument(
        "--status", choices=("active", "disabled"), required=True
    )

    add_user_parser = subparsers.add_parser("add-user")
    add_user_parser.add_argument("--slug", required=True)
    add_user_parser.add_argument("--email", required=True)
    add_user_parser.add_argument("--role", choices=("admin", "user"), default="user")

    remove_user_parser = subparsers.add_parser("remove-user")
    remove_user_parser.add_argument("--slug", required=True)
    remove_user_parser.add_argument("--email", required=True)

    subparsers.add_parser("host-map")
    return parser


def main() -> None:
    args = _parser().parse_args()
    _initialize_database_engine()

    if args.command == "migrate-control-plane":
        apply_control_plane_migration()
        return
    if args.command == "create-tenant":
        schema_name = create_tenant(
            args.id,
            args.slug,
            args.name,
            args.host,
            json.loads(args.configuration),
        )
        if not args.skip_initialize:
            _migrate_tenant_schema(schema_name)
            _initialize_tenant(schema_name)
        return
    if args.command == "set-status":
        set_tenant_status(args.slug, args.status)
        return
    if args.command == "add-user":
        add_tenant_user(args.slug, args.email, args.role)
        return
    if args.command == "remove-user":
        remove_tenant_user(args.slug, args.email)
        return
    if args.command == "host-map":
        print(json.dumps(tenant_host_map(), sort_keys=True))
        return
    raise ValueError("Unknown command")


if __name__ == "__main__":
    main()

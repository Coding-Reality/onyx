from typing import Any

import pytest
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase

from onyx.auth.schemas import UserRole
from onyx.db import auth


@pytest.mark.asyncio
async def test_control_plane_user_role_overrides_first_user_admin_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def base_create(_self: Any, create_dict: dict[str, Any]) -> dict[str, Any]:
        captured.update(create_dict)
        return create_dict

    monkeypatch.setattr(SQLAlchemyUserDatabase, "create", base_create)
    monkeypatch.setattr(
        auth,
        "fetch_ce_extension_implementation_with_fallback",
        lambda *_args: lambda _email: "user",
    )
    database = object.__new__(auth.SQLAlchemyUserAdminDB)

    await database.create({"email": "user@example.com"})

    assert captured["role"] is UserRole.BASIC


@pytest.mark.asyncio
async def test_control_plane_admin_role_is_applied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def base_create(_self: Any, create_dict: dict[str, Any]) -> dict[str, Any]:
        captured.update(create_dict)
        return create_dict

    monkeypatch.setattr(SQLAlchemyUserDatabase, "create", base_create)
    monkeypatch.setattr(
        auth,
        "fetch_ce_extension_implementation_with_fallback",
        lambda *_args: lambda _email: "admin",
    )
    database = object.__new__(auth.SQLAlchemyUserAdminDB)

    await database.create({"email": "admin@example.com"})

    assert captured["role"] is UserRole.ADMIN

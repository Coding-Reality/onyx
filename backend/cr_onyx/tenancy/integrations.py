from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RedmineTenantBinding(BaseModel):
    """Operator-owned projection of a RevenueOS Redmine tenant mapping."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, ge=1)
    revenueos_tenant_id: str = Field(pattern=r"^tenant-[a-z0-9][a-z0-9-]{0,62}$")
    base_url: str
    root_project_id: int = Field(gt=0)
    redmine_group_id: int = Field(gt=0)
    enabled: bool = False

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        parsed = urlparse(normalized)
        if (
            parsed.scheme.lower() != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Redmine tenant binding requires a clean HTTPS base URL")
        return normalized

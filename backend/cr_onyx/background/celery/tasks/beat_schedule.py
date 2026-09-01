"""CE multi-tenant periodic schedule overrides.

Onyx cloud uses one Enterprise dispatcher task to fan work out to tenants.
The Coding Reality CE deployment uses the upstream per-tenant schedule instead.
"""

from typing import Any


def get_cloud_tasks_to_schedule(beat_multiplier: float) -> list[dict[str, Any]]:
    """Return no Enterprise cloud dispatcher tasks for the CE runtime."""
    if beat_multiplier <= 0:
        raise ValueError("beat_multiplier must be positive")

    return []

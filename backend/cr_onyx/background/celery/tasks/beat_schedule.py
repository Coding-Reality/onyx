"""CE multi-tenant periodic schedule overrides.

Onyx cloud uses one Enterprise dispatcher task to fan work out to tenants.
The Coding Reality CE deployment uses the upstream task templates directly as
one Celery Beat entry per physical tenant schema instead.
"""

import copy
from typing import Any

from onyx.background.celery.tasks.beat_schedule import beat_task_templates


def get_cloud_tasks_to_schedule(beat_multiplier: float) -> list[dict[str, Any]]:
    """Return no Enterprise cloud dispatcher tasks for the CE runtime."""
    if beat_multiplier <= 0:
        raise ValueError("beat_multiplier must be positive")

    return []


def get_tasks_to_schedule() -> list[dict[str, Any]]:
    """Return CE-safe task definitions for DynamicTenantScheduler fan-out.

    Upstream deliberately leaves ``tasks_to_schedule`` empty when
    ``MULTI_TENANT`` is true because hosted Onyx uses an Enterprise dispatcher.
    Our MIT extension disables that dispatcher, so it must also restore the
    ordinary task templates. The scheduler itself injects each ``tenant_id``.
    """
    tasks: list[dict[str, Any]] = []
    for template in beat_task_templates:
        task = copy.deepcopy(template)
        # These hints belong to the hosted cloud dispatcher and are not valid
        # Celery apply_async options for a normal scheduled task.
        task["options"].pop("skip_gated", None)
        task["options"].pop("work_gated", None)
        tasks.append(task)
    return tasks

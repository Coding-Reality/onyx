import pytest
from cr_onyx.background.celery.tasks.beat_schedule import (
    get_cloud_tasks_to_schedule,
)


def test_ce_multi_tenant_schedule_has_no_cloud_dispatcher() -> None:
    assert get_cloud_tasks_to_schedule(1.0) == []


def test_ce_multi_tenant_schedule_rejects_invalid_multiplier() -> None:
    with pytest.raises(ValueError, match="beat_multiplier must be positive"):
        get_cloud_tasks_to_schedule(0)

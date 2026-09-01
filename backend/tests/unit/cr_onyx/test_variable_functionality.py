from onyx.utils.variable_functionality import (
    _EXTENSION_MISSING,
    fetch_ce_extension_implementation,
)


def test_missing_extension_parent_falls_back_to_ce(monkeypatch) -> None:
    monkeypatch.setattr(
        "onyx.utils.variable_functionality.CE_EXTENSION_PACKAGE", "cr_onyx"
    )
    fetch_ce_extension_implementation.cache_clear()

    assert (
        fetch_ce_extension_implementation(
            "onyx.background.celery.apps.light", "celery_app"
        )
        is _EXTENSION_MISSING
    )


def test_present_extension_attribute_is_loaded(monkeypatch) -> None:
    monkeypatch.setattr(
        "onyx.utils.variable_functionality.CE_EXTENSION_PACKAGE", "cr_onyx"
    )
    fetch_ce_extension_implementation.cache_clear()

    assert callable(fetch_ce_extension_implementation("onyx.main", "get_application"))


def test_ce_extension_can_disable_enterprise_cloud_beat_tasks(monkeypatch) -> None:
    monkeypatch.setattr(
        "onyx.utils.variable_functionality.CE_EXTENSION_PACKAGE", "cr_onyx"
    )
    fetch_ce_extension_implementation.cache_clear()

    get_cloud_tasks = fetch_ce_extension_implementation(
        "onyx.background.celery.tasks.beat_schedule",
        "get_cloud_tasks_to_schedule",
    )

    assert get_cloud_tasks(1.0) == []

from types import ModuleType

from onyx.utils import variable_functionality


def test_ce_extension_loads_without_enabling_ee(monkeypatch) -> None:
    extension_module = ModuleType("test_extension.main")
    extension_value = object()
    extension_module.get_application = extension_value  # type: ignore[attr-defined]

    monkeypatch.setattr(
        variable_functionality, "CE_EXTENSION_PACKAGE", "test_extension"
    )
    monkeypatch.setattr(
        variable_functionality.importlib,
        "import_module",
        lambda module: extension_module if module == "test_extension.main" else None,
    )
    variable_functionality.fetch_ce_extension_implementation.cache_clear()
    variable_functionality.fetch_versioned_implementation.cache_clear()
    variable_functionality.global_version.unset_ee()

    result = variable_functionality.fetch_versioned_implementation(
        "onyx.main", "get_application"
    )
    assert result is extension_value
    assert not variable_functionality.global_version.is_ee_version()

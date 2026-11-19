"""Plugins appear in the admin console when active and disappear when deactivated."""
from unittest.mock import patch

import pytest

from karpy_platform.core.dashboard import console
from karpy_platform.core.dashboard.console import ConsoleRegistry, MenuSection, OverviewWidget, visible_sections, visible_widgets

ACTIVE = "karpy_platform.packages.plugin_management.service.get_active_plugins"


def everything(_permission: str) -> bool:
    return True


def nothing(_permission: str) -> bool:
    return False


@pytest.fixture(autouse=True)
def fresh_registry(monkeypatch):
    registry = ConsoleRegistry()
    monkeypatch.setattr(console, "console_registry", registry)
    console.register_core_console()
    return registry


def section_ids(can=everything):
    return [section["id"] for section in visible_sections(can)]


def widget_ids(can=everything):
    return [widget["id"] for widget in visible_widgets(can)]


def test_active_plugin_adds_its_section_and_widgets():
    with patch(ACTIVE, return_value=["hello_world"]):
        sections = visible_sections(everything)
        widgets = widget_ids()
    hello = next(section for section in sections if section["id"] == "hello")
    assert hello["plugin"] == "hello_world"
    inbox = next(item for item in hello["items"] if item["id"] == "hello.inbox")
    assert inbox["badge"]["endpoint"] == "/api/plugins/hello_world/admin/pending-count"
    library = next(item for item in hello["items"] if item["id"] == "hello.library")
    assert [child["id"] for child in library["children"]] == ["hello.library.languages", "hello.library.templates"] or \
        {child["id"] for child in library["children"]} == {"hello.library.templates", "hello.library.languages"}
    assert widgets == ["hello.greetings_total", "hello.greetings_by_day"]


def test_deactivated_plugin_disappears():
    with patch(ACTIVE, return_value=[]):
        assert "hello" not in section_ids()
        assert widget_ids() == []
        assert "platform" in section_ids()


def test_items_hidden_without_permission():
    with patch(ACTIVE, return_value=["hello_world"]):
        assert section_ids(nothing) == []
        assert widget_ids(nothing) == []
        only_pages = visible_sections(lambda permission: permission == "pages.index")
    assert [item["id"] for item in only_pages[0]["items"]] == ["platform.pages"]


def test_invalid_metadata_is_rejected():
    with pytest.raises(ValueError):
        MenuSection(id="x", label="x", items=[{"id": "y", "label": "y"}])  # no route, no children
    with pytest.raises(ValueError):
        OverviewWidget(id="w", type="kpi", title="t", endpoint="https://elsewhere.example/data")


def test_registering_the_same_section_id_replaces_it(fresh_registry):
    fresh_registry.register_section({"id": "platform", "label": "x", "items": [
        {"id": "platform.extra", "label": "extra", "route": "/admin/extra"}]}, source="other")
    with patch(ACTIVE, return_value=[]):
        platform = next(section for section in visible_sections(everything) if section["id"] == "platform")
    assert [item["id"] for item in platform["items"]] == ["platform.extra"]

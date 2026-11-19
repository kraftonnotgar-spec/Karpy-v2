from __future__ import annotations

from karpy_platform.core.setting.models import Setting
from karpy_platform.core.table.actions import EditAction
from karpy_platform.core.table.bulk import DeleteBulkAction, TextBulkChange
from karpy_platform.core.table.columns import Column, IdColumn
from karpy_platform.core.table.filters import TableFilter
from karpy_platform.core.table.table import TableAbstract


class SettingsTable(TableAbstract):
    def __init__(self) -> None:
        super().__init__(Setting, "settings")

    def setup(self) -> None:
        self.set_ajax_url("/api/admin/tables/settings/data")
        self.set_page_length(20)
        self.set_default_sorting("key", "asc")
        self.set_bulk_key("key")
        self.add_columns(
            [
                IdColumn.make("key").title("Key"),
                Column.make("value").title("Value").with_empty_state(),
            ]
        )
        self.add_filter(TableFilter.make("key", "Key"))
        self.add_filter(TableFilter.make("value", "Value"))
        self.add_action(EditAction.make().url(lambda item: f"/admin/settings?highlight={item.key}"))
        self.add_bulk_change(TextBulkChange.make().name("value").title("Value"))
        self.add_bulk_action(DeleteBulkAction.make())

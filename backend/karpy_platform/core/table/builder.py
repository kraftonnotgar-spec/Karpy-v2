from __future__ import annotations

from typing import Callable

from karpy_platform.core.table.table import TableAbstract


TableFactory = Callable[[], TableAbstract] | type[TableAbstract]


class TableBuilder:
    def __init__(self) -> None:
        self._tables: dict[str, TableFactory] = {}

    def register(self, table_id: str, table: TableFactory) -> None:
        self._tables[table_id] = table

    def has(self, table_id: str) -> bool:
        return table_id in self._tables

    def create(self, table_id: str) -> TableAbstract:
        table = self._tables.get(table_id)
        if not table:
            raise KeyError(f'Table "{table_id}" is not registered.')
        return table() if isinstance(table, type) else table()

    def all(self) -> list[str]:
        return sorted(self._tables)


table_builder = TableBuilder()

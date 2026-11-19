from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy import String, func, inspect, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from karpy_platform.core.base.hooks import hooks
from karpy_platform.core.table.actions import HeaderAction, TableAction
from karpy_platform.core.table.bulk import TableBulkAction, TableBulkChange
from karpy_platform.core.table.columns import CheckboxColumn, Column, RowActionsColumn
from karpy_platform.core.table.constants import (
    BASE_FILTER_GET_LIST_DATA,
    BASE_FILTER_TABLE_AFTER_RENDER,
    BASE_FILTER_TABLE_BEFORE_RENDER,
    BASE_FILTER_TABLE_BUTTONS,
    BASE_FILTER_TABLE_HEADINGS,
    BASE_FILTER_TABLE_QUERY,
)
from karpy_platform.core.table.filters import TableFilter


@dataclass
class TableQuery:
    draw: int = 1
    page: int = 1
    per_page: int = 10
    start: int | None = None
    length: int | None = None
    search: str = ""
    order_by: str | None = None
    order_dir: str = "desc"
    filters: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None = None):
        payload = payload or {}
        search = payload.get("search", "")
        if isinstance(search, dict):
            search = search.get("value", "")

        length = payload.get("length")
        start = payload.get("start")
        per_page = int(payload.get("perPage") or payload.get("per_page") or length or 10)
        if per_page <= 0:
            per_page = 100000

        page = int(payload.get("page") or 1)
        if start is not None and length:
            page = int(int(start) / max(int(length), 1)) + 1

        order_by = payload.get("orderBy") or payload.get("order_by")
        order_dir = payload.get("orderDir") or payload.get("order_dir") or "desc"

        order = payload.get("order")
        columns = payload.get("columns") or []
        if isinstance(order, list) and order:
            first_order = order[0]
            index = int(first_order.get("column", 0))
            order_dir = first_order.get("dir", order_dir)
            if 0 <= index < len(columns):
                order_by = columns[index].get("data") or columns[index].get("name")

        return cls(
            draw=int(payload.get("draw") or 1),
            page=max(page, 1),
            per_page=max(per_page, 1),
            start=int(start) if start is not None else None,
            length=int(length) if length is not None else None,
            search=str(search or ""),
            order_by=order_by,
            order_dir="asc" if str(order_dir).lower() == "asc" else "desc",
            filters=list(payload.get("filters") or []),
        )


class TableAbstract:
    table_type_advanced = "advanced"
    table_type_simple = "simple"

    def __init__(self, model: type | None = None, table_id: str | None = None) -> None:
        self.model = model
        self.type = self.table_type_advanced
        self.ajax_url = ""
        self.page_length = 10
        self.options: dict[str, Any] = {
            "id": table_id or self.__class__.__name__.replace("Table", "").lower(),
            "class": "table card-table table-vcenter table-striped table-hover",
        }
        self.columns_list: list[Column] = []
        self.row_actions: dict[str, TableAction] = {}
        self.header_actions: dict[str, HeaderAction] = {}
        self.bulk_actions: dict[str, TableBulkAction] = {}
        self.bulk_changes: dict[str, TableBulkChange] = {}
        self.filters: dict[str, TableFilter] = {}
        self.bulk_key = "id"
        self.default_sort_column: str | None = None
        self.default_sort_dir = "desc"
        self.query_callback: Callable[[Any], Any] | None = None
        self.modify_query_callback: Callable[[Any], Any] | None = None
        self.setup()
        self.booted()

    def setup(self) -> None:
        return None

    def booted(self) -> None:
        return None

    def set_option(self, key: str, value: Any):
        self.options[key] = value
        return self

    def get_option(self, key: str, default: Any = None) -> Any:
        return self.options.get(key, default)

    def set_type(self, value: str):
        self.type = value
        return self

    def set_ajax_url(self, value: str):
        self.ajax_url = value
        return self

    def set_page_length(self, value: int):
        self.page_length = value
        return self

    def set_default_sorting(self, column: str, direction: str = "desc"):
        self.default_sort_column = column
        self.default_sort_dir = "asc" if direction == "asc" else "desc"
        return self

    def set_bulk_key(self, value: str):
        self.bulk_key = value
        return self

    def add_column(self, column: Column):
        self.columns_list.append(column)
        return self

    def add_columns(self, columns: list[Column]):
        for column in columns:
            self.add_column(column)
        return self

    def remove_column(self, name: str):
        self.columns_list = [column for column in self.columns_list if column.data != name and column.name != name]
        return self

    def columns(self) -> list[Column]:
        return []

    async def get_columns(self) -> list[Column]:
        columns = [*self.columns(), *self.columns_list]
        if self.has_bulk_actions() and self.type != self.table_type_simple:
            columns = [CheckboxColumn.make(self.bulk_key), *columns]
        if self.row_actions and self.type != self.table_type_simple:
            columns = [*columns, RowActionsColumn.make()]
        filtered = await hooks.apply_filters_async(BASE_FILTER_TABLE_HEADINGS, columns, self.model, self)
        return list(filtered)

    def add_action(self, action: TableAction):
        self.row_actions[action.name] = action
        return self

    def add_header_action(self, action: HeaderAction):
        self.header_actions[action.name] = action
        return self

    def add_bulk_action(self, action: TableBulkAction):
        self.bulk_actions[action.name] = action
        return self

    def add_bulk_change(self, change: TableBulkChange):
        self.bulk_changes[change.get_name()] = change
        return self

    def add_filter(self, table_filter: TableFilter):
        self.filters[table_filter.key] = table_filter
        return self

    def has_bulk_actions(self) -> bool:
        return bool(self.bulk_actions or self.bulk_changes)

    async def schema(self) -> dict[str, Any]:
        columns = await self.get_columns()
        header_actions = sorted(self.header_actions.values(), key=lambda action: action.priority_value)
        buttons = await hooks.apply_filters_async(BASE_FILTER_TABLE_BUTTONS, header_actions, self.model)
        return {
            "id": self.get_option("id"),
            "type": self.type,
            "ajaxUrl": self.ajax_url,
            "pageLength": self.page_length,
            "options": self.options,
            "columns": [column.to_dict() for column in columns],
            "headerActions": [action.to_dict() for action in buttons],
            "rowActions": [action.to_dict() for action in sorted(self.row_actions.values(), key=lambda item: item.priority_value)],
            "bulkActions": [action.to_dict() for action in sorted(self.bulk_actions.values(), key=lambda item: item.priority_value)],
            "bulkChanges": [change.to_dict() for change in self.bulk_changes.values()],
            "filters": [table_filter.to_dict() for table_filter in self.filters.values()],
            "defaultOrder": {
                "column": self.default_sort_column,
                "direction": self.default_sort_dir,
            },
        }

    async def data(self, db: AsyncSession, query: TableQuery | dict[str, Any] | None = None) -> dict[str, Any]:
        if self.model is None:
            raise RuntimeError("Table model is not configured.")

        table_query = query if isinstance(query, TableQuery) else TableQuery.from_payload(query)
        columns = await self.get_columns()

        await hooks.do_action_async(BASE_FILTER_TABLE_BEFORE_RENDER, self)

        statement = select(self.model)
        statement = await hooks.apply_filters_async(BASE_FILTER_TABLE_QUERY, statement, self)
        if self.query_callback:
            statement = self.query_callback(statement) or statement

        total = await self._count(db, select(self.model))
        statement = self._apply_search(statement, table_query.search, columns)
        statement = self._apply_filters(statement, table_query.filters)
        if self.modify_query_callback:
            statement = self.modify_query_callback(statement) or statement

        filtered = await self._count(db, statement)
        statement = self._apply_ordering(statement, table_query, columns)
        if table_query.per_page < 100000:
            statement = statement.limit(table_query.per_page).offset((table_query.page - 1) * table_query.per_page)

        result = await db.execute(statement)
        rows = result.scalars().all()
        rows = await hooks.apply_filters_async(BASE_FILTER_GET_LIST_DATA, rows, self.model, self)

        data = [self._row_payload(row, columns) for row in rows]
        payload = {
            "draw": table_query.draw,
            "recordsTotal": total,
            "recordsFiltered": filtered,
            "page": table_query.page,
            "perPage": table_query.per_page,
            "data": data,
            "schema": await self.schema(),
        }
        await hooks.do_action_async(BASE_FILTER_TABLE_AFTER_RENDER, payload, self)
        return payload

    async def dispatch_bulk_action(
        self,
        db: AsyncSession,
        action_name: str,
        ids: list[Any],
    ) -> dict[str, Any]:
        action = self.bulk_actions.get(action_name)
        if not action:
            return {"error": True, "message": "Invalid bulk action."}
        if not self.model:
            return {"error": True, "message": "Table model is not configured."}
        response = await action.dispatch(db, self.model, ids)
        self._after_mutation()
        return response.to_dict()

    async def save_bulk_change(
        self,
        db: AsyncSession,
        ids: list[Any],
        input_key: str,
        input_value: Any,
    ) -> dict[str, Any]:
        if input_key not in self.bulk_changes:
            return {"error": True, "message": "Invalid bulk change."}
        if not self.model:
            return {"error": True, "message": "Table model is not configured."}
        primary_key = list(self.model.__table__.primary_key.columns)[0]
        result = await db.execute(
            self.model.__table__.update().where(primary_key.in_(ids)).values(**{input_key: input_value})
        )
        await db.commit()
        self._after_mutation()
        return {"error": False, "message": "Updated successfully", "data": {"updated": result.rowcount or 0}}

    def query_using(self, callback: Callable[[Any], Any]):
        self.query_callback = callback
        return self

    def modify_query_using(self, callback: Callable[[Any], Any]):
        self.modify_query_callback = callback
        return self

    async def _count(self, db: AsyncSession, statement) -> int:
        count_statement = select(func.count()).select_from(statement.order_by(None).subquery())
        return int(await db.scalar(count_statement) or 0)

    def _apply_search(self, statement, search: str, columns: list[Column]):
        if not search:
            return statement
        conditions = []
        for column in columns:
            if not column.searchable_value or column.data in {"rowActions", "checkbox"}:
                continue
            model_column = self._model_column(column.data)
            if model_column is not None:
                conditions.append(model_column.cast(String).ilike(f"%{search}%"))
        if conditions:
            statement = statement.where(or_(*conditions))
        return statement

    def _apply_filters(self, statement, filters: list[dict[str, Any]]):
        for item in filters:
            key = item.get("column") or item.get("key")
            operator = str(item.get("operator") or "=").lower()
            value = item.get("value")
            model_column = self._model_column(str(key or ""))
            if model_column is None or value is None or value == "":
                continue
            if operator == "like":
                statement = statement.where(model_column.cast(String).ilike(f"%{value}%"))
            elif operator == "!=":
                statement = statement.where(model_column != value)
            elif operator == ">":
                statement = statement.where(model_column > value)
            elif operator == "<":
                statement = statement.where(model_column < value)
            elif operator == ">=":
                statement = statement.where(model_column >= value)
            elif operator == "<=":
                statement = statement.where(model_column <= value)
            elif operator == "in" and isinstance(value, list):
                statement = statement.where(model_column.in_(value))
            else:
                statement = statement.where(model_column == value)
        return statement

    def _apply_ordering(self, statement, query: TableQuery, columns: list[Column]):
        order_by = query.order_by or self.default_sort_column
        if not order_by:
            orderable = [column for column in columns if column.orderable_value and column.data not in {"checkbox", "rowActions"}]
            order_by = orderable[0].data if orderable else None
        model_column = self._model_column(order_by or "")
        if model_column is None:
            return statement
        direction = query.order_dir or self.default_sort_dir
        return statement.order_by(model_column.asc() if direction == "asc" else model_column.desc())

    def _model_column(self, key: str):
        if not self.model or "." in key:
            return None
        mapper = inspect(self.model)
        if key not in mapper.columns:
            return None
        return getattr(self.model, key)

    def _row_payload(self, row: Any, columns: list[Column]) -> dict[str, Any]:
        payload = {}
        for column in columns:
            if column.type == "checkbox":
                payload[column.data] = getattr(row, column.metadata.get("valueKey", "id"), None)
            elif column.data == "rowActions":
                payload[column.data] = [
                    action.to_dict(row)
                    for action in sorted(self.row_actions.values(), key=lambda item: item.priority_value)
                    if action.current_user_has_any_permissions()
                ]
            else:
                payload[column.data] = column.render(row)
        return payload

    def _after_mutation(self) -> None:
        if self.model is not None and getattr(self.model, "__tablename__", "") == "settings":
            from karpy_platform.core.setting.store import setting_store

            setting_store.clear_cache()


class CollectionDataTable(TableAbstract):
    def __init__(self, rows: list[dict[str, Any]], table_id: str | None = None) -> None:
        self.rows = rows
        super().__init__(model=None, table_id=table_id)

    async def data(self, db: AsyncSession, query: TableQuery | dict[str, Any] | None = None) -> dict[str, Any]:
        table_query = query if isinstance(query, TableQuery) else TableQuery.from_payload(query)
        columns = await self.get_columns()
        rows = self.rows
        if table_query.search:
            needle = table_query.search.lower()
            rows = [
                row
                for row in rows
                if any(needle in str(row.get(column.data, "")).lower() for column in columns if column.searchable_value)
            ]
        total = len(self.rows)
        filtered = len(rows)
        if table_query.order_by:
            rows = sorted(
                rows,
                key=lambda row: str(row.get(table_query.order_by, "")),
                reverse=table_query.order_dir == "desc",
            )
        start = (table_query.page - 1) * table_query.per_page
        rows = rows[start : start + table_query.per_page]
        return {
            "draw": table_query.draw,
            "recordsTotal": total,
            "recordsFiltered": filtered,
            "page": table_query.page,
            "perPage": table_query.per_page,
            "data": [{column.data: column.render(row) for column in columns} for row in rows],
            "schema": await self.schema(),
        }

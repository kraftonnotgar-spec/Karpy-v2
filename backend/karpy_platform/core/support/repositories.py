from __future__ import annotations

from typing import Any, Generic, TypeVar

from sqlalchemy import delete, func, inspect, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from karpy_platform.core.support.cache import SupportCache, support_cache_manager

ModelT = TypeVar("ModelT")


class ModelNotFoundError(LookupError):
    pass


class AsyncRepository(Generic[ModelT]):
    """Reusable SQLAlchemy repository shaped after Botble's repository contract."""

    def __init__(self, model: type[ModelT]) -> None:
        self.model = model

    def get_table(self) -> str:
        return inspect(self.model).local_table.name

    async def find_by_id(self, db: AsyncSession, id_: Any) -> ModelT | None:
        return await db.get(self.model, id_)

    async def find_or_fail(self, db: AsyncSession, id_: Any) -> ModelT:
        item = await self.find_by_id(db, id_)
        if item is None:
            raise ModelNotFoundError(f"{self.model.__name__} not found: {id_}")
        return item

    async def all(self, db: AsyncSession) -> list[ModelT]:
        result = await db.execute(select(self.model))
        return list(result.scalars().all())

    async def get_first_by(self, db: AsyncSession, condition: dict[str, Any] | None = None) -> ModelT | None:
        result = await db.execute(self._apply_conditions(select(self.model), condition or {}).limit(1))
        return result.scalar_one_or_none()

    async def all_by(self, db: AsyncSession, condition: dict[str, Any]) -> list[ModelT]:
        result = await db.execute(self._apply_conditions(select(self.model), condition))
        return list(result.scalars().all())

    async def pluck(self, db: AsyncSession, column: str, key: str | None = None, condition: dict[str, Any] | None = None) -> dict | list:
        columns = [getattr(self.model, column)]
        if key:
            columns.append(getattr(self.model, key))
        result = await db.execute(self._apply_conditions(select(*columns), condition or {}))
        rows = result.all()
        if key:
            return {row[1]: row[0] for row in rows}
        return [row[0] for row in rows]

    async def create(self, db: AsyncSession, data: dict[str, Any]) -> ModelT:
        item = self.model(**data)
        db.add(item)
        await db.commit()
        await db.refresh(item)
        return item

    async def create_or_update(
        self,
        db: AsyncSession,
        data: dict[str, Any],
        condition: dict[str, Any] | None = None,
    ) -> ModelT:
        item = await self.get_first_by(db, condition or {}) if condition else None
        if item is None:
            return await self.create(db, data)
        for key, value in data.items():
            setattr(item, key, value)
        await db.commit()
        await db.refresh(item)
        return item

    async def first_or_create(self, db: AsyncSession, data: dict[str, Any]) -> ModelT:
        item = await self.get_first_by(db, data)
        return item if item else await self.create(db, data)

    async def update(self, db: AsyncSession, condition: dict[str, Any], data: dict[str, Any]) -> int:
        statement = self._apply_conditions(update(self.model), condition).values(**data)
        result = await db.execute(statement)
        await db.commit()
        return result.rowcount or 0

    async def delete(self, db: AsyncSession, model: ModelT) -> bool:
        await db.delete(model)
        await db.commit()
        return True

    async def delete_by(self, db: AsyncSession, condition: dict[str, Any]) -> bool:
        result = await db.execute(self._apply_conditions(delete(self.model), condition))
        await db.commit()
        return bool(result.rowcount)

    async def count(self, db: AsyncSession, condition: dict[str, Any] | None = None) -> int:
        result = await db.execute(self._apply_conditions(select(func.count()).select_from(self.model), condition or {}))
        return int(result.scalar_one() or 0)

    async def advanced_get(self, db: AsyncSession, params: dict[str, Any] | None = None) -> dict[str, Any] | list[ModelT] | ModelT | None:
        params = {
            "condition": {},
            "order_by": {},
            "take": None,
            "paginate": None,
            **(params or {}),
        }
        statement = self._apply_conditions(select(self.model), params["condition"])
        for column, direction in params["order_by"].items():
            column_obj = getattr(self.model, column)
            statement = statement.order_by(column_obj.desc() if str(direction).lower() == "desc" else column_obj.asc())

        take = params["take"]
        paginate = params["paginate"] or {}
        if take == 1:
            result = await db.execute(statement.limit(1))
            return result.scalar_one_or_none()
        if take:
            statement = statement.limit(int(take))
        if paginate:
            per_page = max(int(paginate.get("per_page") or 10), 1)
            page = max(int(paginate.get("current_paged") or 1), 1)
            total = await self.count(db, params["condition"])
            result = await db.execute(statement.limit(per_page).offset((page - 1) * per_page))
            return {"items": list(result.scalars().all()), "total": total, "perPage": per_page, "page": page}

        result = await db.execute(statement)
        return list(result.scalars().all())

    def _apply_conditions(self, statement, condition: dict[str, Any]):
        for field, value in condition.items():
            column = getattr(self.model, field)
            if isinstance(value, tuple | list) and len(value) == 2:
                operator, target = value
                operator = str(operator).upper()
                if operator == "IN":
                    statement = statement.where(column.in_(target))
                elif operator == "NOT_IN":
                    statement = statement.where(~column.in_(target))
                elif operator == "!=":
                    statement = statement.where(column != target)
                elif operator == ">":
                    statement = statement.where(column > target)
                elif operator == "<":
                    statement = statement.where(column < target)
                elif operator == ">=":
                    statement = statement.where(column >= target)
                elif operator == "<=":
                    statement = statement.where(column <= target)
                elif operator == "LIKE":
                    statement = statement.where(column.like(target))
                else:
                    statement = statement.where(column == target)
            else:
                statement = statement.where(column == value)
        return statement


class CacheRepositoryDecorator(Generic[ModelT]):
    def __init__(self, repository: AsyncRepository[ModelT], group: str | None = None) -> None:
        self.repository = repository
        self.cache: SupportCache = support_cache_manager.make(group or repository.get_table())

    async def find_by_id(self, db: AsyncSession, id_: Any) -> ModelT | None:
        return await self.cache.remember(f"find_by_id:{id_}", 600, lambda: self.repository.find_by_id(db, id_))

    async def all(self, db: AsyncSession) -> list[ModelT]:
        return await self.cache.remember("all", 600, lambda: self.repository.all(db))

    async def count(self, db: AsyncSession, condition: dict[str, Any] | None = None) -> int:
        return await self.cache.remember(f"count:{condition or {}}", 600, lambda: self.repository.count(db, condition))

    async def create(self, db: AsyncSession, data: dict[str, Any]) -> ModelT:
        item = await self.repository.create(db, data)
        await self.cache.flush()
        return item

    async def update(self, db: AsyncSession, condition: dict[str, Any], data: dict[str, Any]) -> int:
        count = await self.repository.update(db, condition, data)
        await self.cache.flush()
        return count

    async def delete(self, db: AsyncSession, model: ModelT) -> bool:
        result = await self.repository.delete(db, model)
        await self.cache.flush()
        return result

    def __getattr__(self, name: str):
        return getattr(self.repository, name)

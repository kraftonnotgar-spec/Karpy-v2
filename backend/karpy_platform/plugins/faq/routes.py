"""API routes for the FAQ plugin."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from karpy_platform.core.base.responses import BaseHttpResponse
from karpy_platform.plugins.faq.models.faq import Faq, FaqCategory
from karpy_platform.plugins.faq.services.faq import FAQ_STATUSES, normalize_status, serialize_category, serialize_faq, slugify

router = APIRouter()


class FaqCategoryPayload(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str | None = Field(default=None, max_length=140)
    description: str | None = None
    parentId: str | None = None
    order: int = 0
    status: str = "published"


class FaqPayload(BaseModel):
    categoryId: str = Field(min_length=1)
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    order: int = 0
    status: str = "published"


class BulkDeletePayload(BaseModel):
    ids: list[str] = Field(default_factory=list)


async def require_admin(request: Request, db: AsyncSession = Depends(get_db)):
    # A real admin session is required (this used to return the bootstrap admin for any caller).
    from karpy_platform.core.acl.admin_guard import require_admin_session

    return await require_admin_session(request, db)


def _category_filters(q: str | None = None, status: str | None = None) -> list[Any]:
    filters = [FaqCategory.is_deleted.is_(False)]
    if q:
        like = f"%{q.strip()}%"
        filters.append(or_(FaqCategory.name.ilike(like), FaqCategory.slug.ilike(like), FaqCategory.description.ilike(like)))
    if status and status != "all":
        filters.append(FaqCategory.status == status)
    return filters


def _faq_filters(q: str | None = None, status: str | None = None, category_id: str | None = None) -> list[Any]:
    filters = [Faq.is_deleted.is_(False)]
    if q:
        like = f"%{q.strip()}%"
        filters.append(or_(Faq.question.ilike(like), Faq.answer.ilike(like)))
    if status and status != "all":
        filters.append(Faq.status == status)
    if category_id and category_id != "all":
        filters.append(Faq.category_id == category_id)
    return filters


async def _count(db: AsyncSession, model, filters: list[Any]) -> int:
    result = await db.execute(select(func.count()).select_from(model).where(*filters))
    return int(result.scalar() or 0)


@router.get("/")
async def index(db: AsyncSession = Depends(get_db), _: Any = Depends(require_admin)) -> dict:
    return {
        "plugin": "faq",
        "name": "FAQs",
        "status": "ready",
        "counts": {
            "faqs": await _count(db, Faq, _faq_filters()),
            "categories": await _count(db, FaqCategory, _category_filters()),
            "published": await _count(db, Faq, _faq_filters(status="published")),
        },
    }


@router.get("/categories")
async def categories(
    q: str | None = None,
    status: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(15, ge=1, le=100, alias="perPage"),
    db: AsyncSession = Depends(get_db),
    _: Any = Depends(require_admin),
) -> dict[str, Any]:
    filters = _category_filters(q=q, status=status)
    total = await _count(db, FaqCategory, filters)
    result = await db.execute(
        select(FaqCategory)
        .options(selectinload(FaqCategory.faqs), selectinload(FaqCategory.parent), selectinload(FaqCategory.children))
        .where(*filters)
        .order_by(FaqCategory.parent_id.asc().nullsfirst(), FaqCategory.order.asc(), FaqCategory.name.asc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    return {"data": [serialize_category(category, include_count=True) for category in result.scalars().unique().all()], "meta": {"page": page, "perPage": per_page, "total": total}}


@router.post("/categories")
async def create_category(payload: FaqCategoryPayload, db: AsyncSession = Depends(get_db), _: Any = Depends(require_admin)) -> dict[str, Any]:
    category = FaqCategory()
    await _fill_category(db, category, payload)
    db.add(category)
    await db.commit()
    return BaseHttpResponse.make().set_data({"category": serialize_category(await _get_category(db, category.id))}).with_created_success_message().to_dict()


@router.post("/categories/bulk-delete")
async def bulk_delete_categories(payload: BulkDeletePayload, db: AsyncSession = Depends(get_db), _: Any = Depends(require_admin)) -> dict[str, Any]:
    ids = [item for item in payload.ids if item]
    if not ids:
        raise HTTPException(status_code=422, detail={"errors": {"ids": "Please select at least one category."}})
    tree_ids = await _category_tree_ids(db, ids)
    await db.execute(update(FaqCategory).where(FaqCategory.id.in_(tree_ids)).values(is_deleted=True))
    await db.execute(update(Faq).where(Faq.category_id.in_(tree_ids)).values(is_deleted=True))
    await db.commit()
    return BaseHttpResponse.make().set_data({"deleted": len(tree_ids)}).with_deleted_success_message().to_dict()


@router.get("/categories/{category_id}")
async def category_detail(category_id: str, db: AsyncSession = Depends(get_db), _: Any = Depends(require_admin)) -> dict[str, Any]:
    category = await _get_category(db, category_id)
    categories_result = await db.execute(
        select(FaqCategory)
        .options(selectinload(FaqCategory.parent), selectinload(FaqCategory.children))
        .where(FaqCategory.is_deleted.is_(False))
        .order_by(FaqCategory.parent_id.asc().nullsfirst(), FaqCategory.order.asc(), FaqCategory.name.asc())
    )
    descendant_ids = set(await _category_tree_ids(db, [category.id]))
    return {
        "category": serialize_category(category),
        "categories": [serialize_category(item) for item in categories_result.scalars().unique().all() if item.id not in descendant_ids],
    }


@router.put("/categories/{category_id}")
async def update_category(category_id: str, payload: FaqCategoryPayload, db: AsyncSession = Depends(get_db), _: Any = Depends(require_admin)) -> dict[str, Any]:
    category = await _get_category(db, category_id)
    await _fill_category(db, category, payload, category_id=category_id)
    await db.commit()
    return BaseHttpResponse.make().set_data({"category": serialize_category(await _get_category(db, category.id))}).with_updated_success_message().to_dict()


@router.delete("/categories/{category_id}")
async def delete_category(category_id: str, db: AsyncSession = Depends(get_db), _: Any = Depends(require_admin)) -> dict[str, Any]:
    category = await _get_category(db, category_id)
    tree_ids = await _category_tree_ids(db, [category.id])
    await db.execute(update(FaqCategory).where(FaqCategory.id.in_(tree_ids)).values(is_deleted=True))
    await db.execute(update(Faq).where(Faq.category_id.in_(tree_ids)).values(is_deleted=True))
    await db.commit()
    return BaseHttpResponse.make().with_deleted_success_message().to_dict()


@router.get("/faqs")
async def faqs(
    q: str | None = None,
    status: str | None = None,
    category_id: str | None = Query(None, alias="categoryId"),
    page: int = Query(1, ge=1),
    per_page: int = Query(15, ge=1, le=100, alias="perPage"),
    db: AsyncSession = Depends(get_db),
    _: Any = Depends(require_admin),
) -> dict[str, Any]:
    filters = _faq_filters(q=q, status=status, category_id=category_id)
    total = await _count(db, Faq, filters)
    result = await db.execute(
        select(Faq)
        .options(selectinload(Faq.category))
        .where(*filters)
        .order_by(Faq.order.asc(), Faq.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    categories_result = await db.execute(
        select(FaqCategory)
        .options(selectinload(FaqCategory.parent), selectinload(FaqCategory.children))
        .where(FaqCategory.is_deleted.is_(False))
        .order_by(FaqCategory.parent_id.asc().nullsfirst(), FaqCategory.order.asc(), FaqCategory.name.asc())
    )
    return {
        "data": [serialize_faq(faq) for faq in result.scalars().unique().all()],
        "categories": [serialize_category(category) for category in categories_result.scalars().all()],
        "meta": {"page": page, "perPage": per_page, "total": total},
    }


@router.post("/faqs")
async def create_faq(payload: FaqPayload, db: AsyncSession = Depends(get_db), _: Any = Depends(require_admin)) -> dict[str, Any]:
    await _get_category(db, payload.categoryId)
    faq = Faq()
    _fill_faq(faq, payload)
    db.add(faq)
    await db.commit()
    result = await db.execute(select(Faq).options(selectinload(Faq.category)).where(Faq.id == faq.id))
    return BaseHttpResponse.make().set_data({"faq": serialize_faq(result.scalars().first())}).with_created_success_message().to_dict()


@router.post("/faqs/bulk-delete")
async def bulk_delete_faqs(payload: BulkDeletePayload, db: AsyncSession = Depends(get_db), _: Any = Depends(require_admin)) -> dict[str, Any]:
    ids = [item for item in payload.ids if item]
    if not ids:
        raise HTTPException(status_code=422, detail={"errors": {"ids": "Please select at least one FAQ."}})
    await db.execute(update(Faq).where(Faq.id.in_(ids)).values(is_deleted=True))
    await db.commit()
    return BaseHttpResponse.make().set_data({"deleted": len(ids)}).with_deleted_success_message().to_dict()


@router.get("/faqs/{faq_id}")
async def faq_detail(faq_id: str, db: AsyncSession = Depends(get_db), _: Any = Depends(require_admin)) -> dict[str, Any]:
    faq = await _get_faq(db, faq_id)
    categories_result = await db.execute(
        select(FaqCategory)
        .options(selectinload(FaqCategory.parent), selectinload(FaqCategory.children))
        .where(FaqCategory.is_deleted.is_(False))
        .order_by(FaqCategory.parent_id.asc().nullsfirst(), FaqCategory.order.asc(), FaqCategory.name.asc())
    )
    return {"faq": serialize_faq(faq), "categories": [serialize_category(category) for category in categories_result.scalars().all()]}


@router.put("/faqs/{faq_id}")
async def update_faq(faq_id: str, payload: FaqPayload, db: AsyncSession = Depends(get_db), _: Any = Depends(require_admin)) -> dict[str, Any]:
    await _get_category(db, payload.categoryId)
    faq = await _get_faq(db, faq_id)
    _fill_faq(faq, payload)
    await db.commit()
    result = await db.execute(select(Faq).options(selectinload(Faq.category)).where(Faq.id == faq.id))
    return BaseHttpResponse.make().set_data({"faq": serialize_faq(result.scalars().first())}).with_updated_success_message().to_dict()


@router.delete("/faqs/{faq_id}")
async def delete_faq(faq_id: str, db: AsyncSession = Depends(get_db), _: Any = Depends(require_admin)) -> dict[str, Any]:
    faq = await _get_faq(db, faq_id)
    faq.is_deleted = True
    await db.commit()
    return BaseHttpResponse.make().with_deleted_success_message().to_dict()


@router.get("/public/faqs")
async def public_faqs(
    category: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    filters = [Faq.is_deleted.is_(False), Faq.status == "published", FaqCategory.is_deleted.is_(False), FaqCategory.status == "published"]
    if category:
        filters.append((FaqCategory.slug == category) | (FaqCategory.id == category))
    result = await db.execute(
        select(Faq)
        .join(FaqCategory, Faq.category_id == FaqCategory.id)
        .options(selectinload(Faq.category))
        .where(*filters)
        .order_by(FaqCategory.order.asc(), Faq.order.asc(), Faq.created_at.desc())
        .limit(limit)
    )
    return {"data": [serialize_faq(faq) for faq in result.scalars().unique().all()]}


@router.get("/public/categories")
async def public_categories(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    result = await db.execute(
        select(FaqCategory)
        .options(selectinload(FaqCategory.parent), selectinload(FaqCategory.children))
        .where(FaqCategory.is_deleted.is_(False), FaqCategory.status == "published")
        .order_by(FaqCategory.parent_id.asc().nullsfirst(), FaqCategory.order.asc(), FaqCategory.name.asc())
    )
    return {"data": [serialize_category(category) for category in result.scalars().unique().all()]}


async def _get_category(db: AsyncSession, category_id: str) -> FaqCategory:
    result = await db.execute(
        select(FaqCategory)
        .options(selectinload(FaqCategory.faqs), selectinload(FaqCategory.parent), selectinload(FaqCategory.children))
        .where(FaqCategory.id == category_id, FaqCategory.is_deleted.is_(False))
    )
    category = result.scalars().unique().first()
    if not category or category.is_deleted:
        raise HTTPException(status_code=404, detail="FAQ category was not found.")
    return category


async def _get_faq(db: AsyncSession, faq_id: str) -> Faq:
    result = await db.execute(select(Faq).options(selectinload(Faq.category)).where(Faq.id == faq_id, Faq.is_deleted.is_(False)))
    faq = result.scalars().first()
    if not faq:
        raise HTTPException(status_code=404, detail="FAQ was not found.")
    return faq


async def _fill_category(db: AsyncSession, category: FaqCategory, payload: FaqCategoryPayload, *, category_id: str | None = None) -> None:
    try:
        status = normalize_status(payload.status)
    except ValueError:
        raise HTTPException(status_code=422, detail={"errors": {"status": "Unsupported category status."}}) from None
    parent_id = (payload.parentId or "").strip() or None
    if parent_id:
        if category_id and parent_id == category_id:
            raise HTTPException(status_code=422, detail={"errors": {"parentId": "A category cannot be its own parent."}})
        parent = await _get_category(db, parent_id)
        if category_id:
            descendants = set(await _category_tree_ids(db, [category_id]))
            if parent.id in descendants:
                raise HTTPException(status_code=422, detail={"errors": {"parentId": "A parent category cannot be one of its own children."}})
    category.name = payload.name.strip()
    category.slug = (payload.slug or slugify(payload.name)).strip()
    category.description = (payload.description or "").strip() or None
    category.parent_id = parent_id
    category.order = payload.order
    category.status = status


async def _category_tree_ids(db: AsyncSession, category_ids: list[str]) -> list[str]:
    seeds = [item for item in category_ids if item]
    if not seeds:
        return []
    result = await db.execute(select(FaqCategory.id, FaqCategory.parent_id).where(FaqCategory.is_deleted.is_(False)))
    children_by_parent: dict[str, list[str]] = {}
    for category_id, parent_id in result.all():
        if parent_id:
            children_by_parent.setdefault(parent_id, []).append(category_id)
    visited: set[str] = set()
    stack = list(seeds)
    while stack:
        current = stack.pop()
        if current in visited:
            continue
        visited.add(current)
        stack.extend(children_by_parent.get(current, []))
    return list(visited)


def _fill_faq(faq: Faq, payload: FaqPayload) -> None:
    try:
        status = normalize_status(payload.status)
    except ValueError:
        raise HTTPException(status_code=422, detail={"errors": {"status": "Unsupported FAQ status."}}) from None
    faq.category_id = payload.categoryId
    faq.question = payload.question.strip()
    faq.answer = payload.answer.strip()
    faq.order = payload.order
    faq.status = status

"""抽取适用集路由：采集页面适用模板查询、正式清洗、补采领取回填与审计回查。

与通用资源路由并列注册，路径统一挂在 ``/api/extract`` 下，不改变既有18个
模块资源接口的契约。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.extract_scope import extract_scope_service
from app.services.data_extract import DataExtractService

router = APIRouter(prefix="/api/extract", tags=["抽取适用集"])

_template_service = DataExtractService()


class ApiResult(BaseModel):
    ok: bool
    message: str = ""
    data: dict[str, Any] | list[Any] | None = None


class PageRegisterPayload(BaseModel):
    page_id: str
    page_type: str
    page_version: str
    source: str = ""
    resolved_fields: dict[str, Any] = Field(default_factory=dict)


class TemplateRegisterPayload(BaseModel):
    template_code: str
    script_id: str
    page_type: str
    cover_fields: list[str]
    source: str = ""
    failed_fields: list[str] = Field(default_factory=list)
    failed_pages: dict[str, list[str]] = Field(default_factory=dict)
    template_label: str = "v1"


class TemplateRevisePayload(BaseModel):
    cover_fields: list[str] | None = None
    failed_fields: list[str] | None = None
    failed_pages: dict[str, list[str]] | None = None
    clear_failed_pages: bool = False
    template_label: str | None = None


class CleaningPayload(BaseModel):
    page_id: str
    pipeline_id: str = ""
    template_id: int | None = None


class BackfillPayload(BaseModel):
    value: Any


def _fail(message: str) -> ApiResult:
    return ApiResult(ok=False, message=message)


@router.post("/demo-seed", response_model=ApiResult)
def demo_seed() -> ApiResult:
    """灌入验收场景演示数据（幂等）：商品详情页通用/专用模板 + 列表页来源。"""
    return ApiResult(ok=True, message="演示数据就绪", data=extract_scope_service.seed_demo())


@router.get("/snapshot", response_model=ApiResult)
def snapshot() -> ApiResult:
    return ApiResult(ok=True, data=extract_scope_service.snapshot())


# ------------------------------------------------------------- 采集页面（原页）
@router.post("/pages", response_model=ApiResult)
def register_page(payload: PageRegisterPayload) -> ApiResult:
    page, message = extract_scope_service.register_page(
        page_id=payload.page_id,
        page_type=payload.page_type,
        page_version=payload.page_version,
        source=payload.source,
        resolved_fields=payload.resolved_fields,
    )
    if page is None:
        return _fail(message)
    return ApiResult(ok=True, message=message, data=page)


@router.post("/pages/{page_id}/confirm", response_model=ApiResult)
def confirm_page(page_id: str) -> ApiResult:
    page, message = extract_scope_service.confirm_page(page_id)
    if page is None:
        return _fail(message)
    return ApiResult(ok=True, message=message, data=page)


@router.get("/pages", response_model=ApiResult)
def list_pages() -> ApiResult:
    return ApiResult(ok=True, data=extract_scope_service.list_pages())


# ----------------------------------------------------------------- 抽取模板
@router.post("/templates", response_model=ApiResult)
def register_template(payload: TemplateRegisterPayload) -> ApiResult:
    entry = _template_service.register_scope_template(
        template_code=payload.template_code,
        script_id=payload.script_id,
        page_type=payload.page_type,
        cover_fields=payload.cover_fields,
        source=payload.source,
        failed_fields=payload.failed_fields,
        failed_pages=payload.failed_pages,
        template_label=payload.template_label,
    )
    return ApiResult(ok=True, message="适用模板已登记并生效", data=entry)


@router.post("/templates/{template_id}/revise", response_model=ApiResult)
def revise_template(template_id: int, payload: TemplateRevisePayload) -> ApiResult:
    entry, message = _template_service.revise_template(
        template_id,
        cover_fields=payload.cover_fields,
        failed_fields=payload.failed_fields,
        failed_pages=payload.failed_pages,
        clear_failed_pages=payload.clear_failed_pages,
        template_label=payload.template_label,
    )
    if entry is None:
        return _fail(message)
    return ApiResult(ok=True, message=message, data=entry)


# --------------------------------------------------------------- 抽取适用集
@router.post("/pages/{page_id}/scope-sets", response_model=ApiResult)
def compute_scope_set(page_id: str, recompute: bool = False, pipeline_id: str = "") -> ApiResult:
    scope_set, message = extract_scope_service.compute_scope_set(
        page_id, recompute=recompute, pipeline_id=pipeline_id)
    if scope_set is None:
        return _fail(message)
    return ApiResult(ok=True, message=message, data=scope_set)


@router.get("/scope-sets", response_model=ApiResult)
def list_scope_sets(page_id: str | None = None) -> ApiResult:
    return ApiResult(ok=True, data=extract_scope_service.list_scope_sets(page_id))


# ----------------------------------------------------------------- 正式清洗
@router.post("/cleaning", response_model=ApiResult)
def start_cleaning(payload: CleaningPayload) -> ApiResult:
    row, message = extract_scope_service.start_cleaning(
        payload.page_id,
        pipeline_id=payload.pipeline_id,
        template_id=payload.template_id,
    )
    if row is None:
        return _fail(message)
    return ApiResult(ok=True, message=message, data=row)


@router.get("/clean-rows", response_model=ApiResult)
def list_clean_rows(page_id: str | None = None, template_version: str | None = None) -> ApiResult:
    """按原页查询正式行；可再按模板版本过滤，验证旧结果仍按原模板查到。"""
    return ApiResult(
        ok=True,
        data=extract_scope_service.list_clean_rows(
            page_id=page_id, template_version=template_version),
    )


# -------------------------------------------------------------------- 补采
@router.get("/supplement-tasks", response_model=ApiResult)
def list_supplement_tasks(page_id: str | None = None, status: str | None = None) -> ApiResult:
    return ApiResult(
        ok=True,
        data=extract_scope_service.list_supplement_tasks(page_id=page_id, status=status),
    )


@router.post("/supplement-tasks/{task_id}/claim", response_model=ApiResult)
def claim_supplement(task_id: str) -> ApiResult:
    task, message = extract_scope_service.claim_supplement(task_id)
    if task is None:
        return _fail(message)
    return ApiResult(ok=True, message=message, data=task)


@router.post("/supplement-tasks/{task_id}/backfill", response_model=ApiResult)
def backfill_supplement(task_id: str, payload: BackfillPayload) -> ApiResult:
    task, message = extract_scope_service.backfill_supplement(task_id, payload.value)
    if task is None:
        return _fail(message)
    return ApiResult(ok=True, message=message, data=task)


# ------------------------------------------------------------ 审计回查入口
@router.get("/audit", response_model=ApiResult)
def audit_events() -> ApiResult:
    """选中、未用、不足的候选与字段、模板版本事件全部可回查。"""
    return ApiResult(ok=True, data=extract_scope_service.audit_events())

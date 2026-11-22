"""清洗管道领域服务：数据清洗编排，消费data_extract输出，驱动transform_rule和quality_guard。

启用工序时在既有转换规则检查之外，执行抽取适用集链路：
若工序输入源声明了采集原页（``page:<原页编号>``），则按页面类型查询适用模板、
执行正式清洗，并把可出数字段和补采项持久化到 ``data/extract/``。
"""
from __future__ import annotations

from typing import Any

from app.store import store
from app.services.base import BaseModuleService, register_hook
from app.services.extract_scope import extract_scope_service
from app import persistence as persist


def _resolve_input_page(entry: dict[str, Any]) -> str:
    """从工序输入源解析采集原页编号，支持 page:PAGE-01 与纯原页编号两种写法。"""
    raw = str(entry.get("输入源") or "")
    for token in raw.replace("，", ",").replace("、", ",").split(","):
        token = token.strip()
        if token.startswith("page:"):
            return token.split(":", 1)[1].strip()
    return ""


def _trigger_transform_on_enable(entry: dict[str, Any]) -> None:
    """清洗工序启用时自动检查关联转换规则是否就绪，并执行抽取适用集清洗。"""
    pipeline_id = entry.get("工序编号", "")
    transforms = [t for t in store.rows("transform_rule") if t.get("关联工序") == pipeline_id]
    # 记录关联触发（无关联转换规则时只记录适用集执行，不阻断主流程）
    persist.append_jsonl("reports", "pipeline_transform_check.jsonl", {
        "pipeline_id": entry.get("id"),
        "pipeline_code": pipeline_id,
        "linked_transforms": len(transforms),
        "transform_ready": sum(1 for t in transforms if t.get("status") == "已生效"),
        "timestamp": persist.now_iso(),
    })
    _run_extract_scope(entry)


def _run_extract_scope(entry: dict[str, Any]) -> None:
    """通过原工序「启用工序」动作执行抽取适用集并启动正式清洗。

    只处理输入源显式绑定的已确认原页；缺字段不跨页拼接，补采项按本页未覆盖范围生成。
    """
    page_id = _resolve_input_page(entry)
    if not page_id:
        return
    page = extract_scope_service.get_page(page_id)
    if page is None or page.get("status") != "已确认":
        persist.append_jsonl("reports", "pipeline_extract_scope.jsonl", {
            "event": "skip_unconfirmed_page",
            "pipeline_code": entry.get("工序编号"),
            "page_id": page_id,
            "timestamp": persist.now_iso(),
        })
        return

    scope_set, scope_msg = extract_scope_service.compute_scope_set(
        page_id, pipeline_id=entry.get("工序编号", ""))
    row, clean_msg = extract_scope_service.start_cleaning(
        page_id, pipeline_id=entry.get("工序编号", ""))
    persist.append_jsonl("reports", "pipeline_extract_scope.jsonl", {
        "event": "scope_cleaning",
        "pipeline_id": entry.get("id"),
        "pipeline_code": entry.get("工序编号"),
        "page_id": page_id,
        "scope_id": scope_set.get("scope_id") if scope_set else "",
        "scope_message": scope_msg,
        "row_id": row.get("row_id") if row else "",
        "clean_message": clean_msg,
        "produced_fields": row.get("produced_fields", []) if row else [],
        "missing_fields": row.get("missing_fields", []) if row else [],
        "timestamp": persist.now_iso(),
    })


register_hook("clean_pipeline", "启用工序", _trigger_transform_on_enable)


class CleanPipelineService(BaseModuleService):
    MODULE = "clean_pipeline"
    ENTITY = "清洗工序"
    OPERATION_TERM = "清洗"
    LIST_FIELDS = ["工序编号", "输入源", "清洗规则", "处理顺序", "脏数据策略", "异常阈值", "采样比例", "工序版本"]
    REQUIRED_FIELDS = ["工序编号", "输入源", "清洗规则"]
    STATUS_ORDER = ["草稿", "待校验", "已启用", "已停用"]
    ACTION_RULES = {"提交校验": "待校验", "启用工序": "已启用", "停用工序": "已停用"}
    NEGATIVE_ACTIONS = ["停用工序"]

    def get_linked_transforms(self, pipeline_code: str) -> list[dict[str, Any]]:
        """查询某工序关联的所有转换规则。"""
        return [t for t in store.rows("transform_rule") if t.get("关联工序") == pipeline_code]

    def domain_snapshot(self) -> dict[str, Any]:
        base = super().domain_snapshot()
        pipelines = store.rows(self.MODULE)
        # 读取关联的质量报告
        reports = persist.read_jsonl("reports", "quality_report.jsonl")
        base["quality_checks"] = len(reports)
        # 关联的归一化规则
        norms = store.rows("field_normalize")
        base["linked_normalize_rules"] = len(norms)
        # 抽取适用集执行统计
        scope_reports = persist.read_jsonl("reports", "pipeline_extract_scope.jsonl")
        base["scope_cleaning_runs"] = len(scope_reports)
        base["scope_rows_emitted"] = sum(
            1 for r in scope_reports if r.get("event") == "scope_cleaning" and r.get("row_id"))
        return base

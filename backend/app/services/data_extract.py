"""数据抽取领域服务：消费behavior_script脚本和element_selector锚点，执行字段抽取。

在「按脚本返回全部生效字段」之外，新增面向采集页面的抽取适用集能力：
- 模板登记时声明适用页面类型、覆盖字段，以及在特定原页上解析失败的字段；
- ``find_applicable_templates`` 只返回已生效且页面类型匹配的模板，不再全量返回；
- ``revise_template`` 用于模板切换/修订换版，旧版本指纹由清洗结果快照保留，可继续回查。
"""
from __future__ import annotations

from typing import Any

from app.store import store
from app.services.base import BaseModuleService, compute_entry_version
from app import persistence as persist

# 模板在标准列表字段之外的扩展业务键，登记/修订时需要原样保留。
TEMPLATE_EXTRA_FIELDS = ["适用页面类型", "覆盖字段", "解析失败字段", "来源标识"]


class DataExtractService(BaseModuleService):
    MODULE = "data_extract"
    ENTITY = "抽取模板"
    OPERATION_TERM = "解析"
    LIST_FIELDS = ["模板编号", "关联脚本", "抽取字段", "提取方式", "数据处理", "输出类型", "默认值", "模板版本"]
    REQUIRED_FIELDS = ["模板编号", "关联脚本", "抽取字段"]
    STATUS_ORDER = ["草稿", "待校验", "已生效", "已停用"]
    ACTION_RULES = {"提交校验": "待校验", "标记生效": "已生效", "停用模板": "已停用"}
    NEGATIVE_ACTIONS = ["停用模板"]

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        entry, missing = super().create_entry(values)
        if entry is None:
            return entry, missing
        self._apply_extra_fields(entry, values)
        # 扩展字段改变了条目内容，需要重算版本指纹并留痕。
        entry["version"] = compute_entry_version(entry)
        return entry, []

    def _apply_extra_fields(self, entry: dict[str, Any], values: dict[str, Any]) -> None:
        """写入适用页面类型/覆盖字段/解析失败字段等扩展键，并做基本归一。"""
        entry["适用页面类型"] = str(values.get("适用页面类型") or "").strip()
        entry["来源标识"] = str(values.get("来源标识") or "").strip()
        entry["覆盖字段"] = _split_fields(values.get("覆盖字段")) or _split_fields(entry.get("抽取字段"))
        entry["解析失败字段"] = _split_fields(values.get("解析失败字段"))

    def extract_fields_for_script(self, script_id: str) -> list[dict[str, Any]]:
        """根据脚本编号查询所有关联的抽取模板并返回字段映射（保留兼容口径）。"""
        templates = store.rows(self.MODULE)
        linked = [t for t in templates if t.get("关联脚本") == script_id and t.get("status") == "已生效"]
        return [{"field": t.get("抽取字段"), "method": t.get("提取方式"), "output_type": t.get("输出类型")} for t in linked]

    def find_applicable_templates(self, page_type: str) -> list[dict[str, Any]]:
        """按实际页面类型查找适用模板：只取已生效且页面类型匹配的模板。

        旧的 ``extract_fields_for_script`` 按脚本返回全部生效字段，不区分页面类型；
        这里把筛选口径收敛到「页面类型 + 生效状态」，供抽取适用集消费。
        """
        page_type = (page_type or "").strip()
        return [
            t for t in store.rows(self.MODULE)
            if t.get("status") == "已生效"
            and page_type
            and t.get("适用页面类型") == page_type
        ]

    def register_scope_template(
        self,
        *,
        template_code: str,
        script_id: str,
        page_type: str,
        cover_fields: list[str],
        source: str = "",
        failed_fields: list[str] | None = None,
        failed_pages: dict[str, list[str]] | None = None,
        template_label: str = "v1",
        extract_method: str = "css选择器",
    ) -> dict[str, Any]:
        """登记一份参与适用集计算的生效模板（同时进入 data_extract 统一模板表）。

        ``failed_fields`` 为全局解析失败字段；``failed_pages`` 为按原页维度的
        解析失败映射（同一模板在不同原页上的可出数范围可以不同）。
        """
        rows = store.rows(self.MODULE)
        entry = {
            "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
            "模板编号": template_code,
            "关联脚本": script_id,
            "抽取字段": ",".join(cover_fields),
            "提取方式": extract_method,
            "数据处理": "直出",
            "输出类型": "string",
            "默认值": "",
            "模板版本": template_label,
            "适用页面类型": page_type,
            "覆盖字段": list(cover_fields),
            "解析失败字段": list(failed_fields or []),
            "解析失败映射": dict(failed_pages or {}),
            "来源标识": source,
            "status": "已生效",
            "pending": False,
            "abnormal": False,
            "updated_at": persist.now_iso(),
        }
        entry["version"] = compute_entry_version(entry)
        rows.append(entry)
        persist.append_jsonl("extract", "template_registry.jsonl", {
            "event": "register_template",
            "template_id": entry["id"],
            "template_code": template_code,
            "page_type": page_type,
            "cover_fields": list(cover_fields),
            "failed_fields": list(failed_fields or []),
            "failed_pages": dict(failed_pages or {}),
            "template_version": template_label,
            "version_fingerprint": entry["version"],
            "source": source,
            "timestamp": persist.now_iso(),
        })
        return entry

    def revise_template(
        self,
        template_id: int,
        *,
        cover_fields: list[str] | None = None,
        failed_fields: list[str] | None = None,
        failed_pages: dict[str, list[str]] | None = None,
        clear_failed_pages: bool = False,
        template_label: str | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        """模板修订/切换：更新覆盖与解析失败字段并换版。

        已经产出的正式清洗结果持有旧版本指纹和模板快照，不被本次修订覆盖，
        因此「旧结果仍按原模板查到」由两侧版本快照共同保证。
        """
        entry = store.find(self.MODULE, template_id)
        if entry is None:
            return None, f"抽取模板 {template_id} 不存在或已归档"
        old_fingerprint = entry.get("version", "")
        old_label = entry.get("模板版本", "")
        if cover_fields is not None:
            entry["覆盖字段"] = list(cover_fields)
            entry["抽取字段"] = ",".join(cover_fields)
        if failed_fields is not None:
            entry["解析失败字段"] = list(failed_fields)
        if clear_failed_pages:
            entry["解析失败映射"] = {}
        elif failed_pages is not None:
            entry["解析失败映射"] = dict(failed_pages)
        if template_label:
            entry["模板版本"] = template_label
        entry["updated_at"] = persist.now_iso()
        entry["version"] = compute_entry_version(entry)
        persist.append_jsonl("extract", "template_registry.jsonl", {
            "event": "revise_template",
            "template_id": template_id,
            "template_code": entry.get("模板编号"),
            "old_template_version": old_label,
            "new_template_version": entry.get("模板版本"),
            "old_version_fingerprint": old_fingerprint,
            "new_version_fingerprint": entry["version"],
            "cover_fields": entry.get("覆盖字段", []),
            "failed_fields": entry.get("解析失败字段", []),
            "failed_pages": entry.get("解析失败映射", {}),
            "timestamp": persist.now_iso(),
        })
        return entry, "模板已修订并换版"

    def domain_snapshot(self) -> dict[str, Any]:
        base = super().domain_snapshot()
        templates = store.rows(self.MODULE)
        # 关联的元素锚点统计
        selectors = store.rows("element_selector")
        base["templates_with_selectors"] = sum(
            1 for t in templates if any(
                s.get("关联脚本") == t.get("关联脚本") for s in selectors))
        # 关联的清洗管道
        pipelines = store.rows("clean_pipeline")
        base["templates_in_pipeline"] = sum(
            1 for t in templates if any(
                p.get("输入源") and t.get("关联脚本") in str(p.get("输入源", "")) for p in pipelines))
        # 适用集口径：声明了页面类型的生效模板
        scope_templates = [
            t for t in templates
            if t.get("适用页面类型") and t.get("status") == "已生效"
        ]
        base["scope_templates"] = len(scope_templates)
        base["scope_page_types"] = sorted({t.get("适用页面类型") for t in scope_templates})
        return base


def _split_fields(raw: Any) -> list[str]:
    """把逗号/顿号分隔的字段串归一成去重去空的字段列表。"""
    if raw is None:
        return []
    if isinstance(raw, (list, tuple, set)):
        items = [str(item).strip() for item in raw]
    else:
        items = str(raw).replace("，", ",").replace("、", ",").split(",")
    seen: list[str] = []
    for item in items:
        item = item.strip()
        if item and item not in seen:
            seen.append(item)
    return seen

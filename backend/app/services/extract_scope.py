"""抽取适用集领域服务：把「按脚本返回全部生效字段」升级为面向采集页面的适用集查询与正式清洗。

核心边界（题面约束的代码化）：
1. 先按页面类型筛选生效模板，再按覆盖字段/出数字段排序，形成可回查的抽取适用集；
2. 同一条正式清洗结果只消费「已确认的原页」和「一个确定版本的模板」，
   缺字段不允许从别的页面、别的来源拼入；
3. 清洗管道持久化可出数字段，未覆盖字段生成可领取的补采项；
4. 补采只面向本页未覆盖字段，领取后回填到对应清洗范围（同一条正式行）；
5. 模板修订换版后，历史适用集和正式行保留原模板版本快照，仍可复算、可回查。

所有状态变更都追加写入 ``data/extract/`` 下的 JSONL，内存态仅作为查询缓存。
"""
from __future__ import annotations

from typing import Any

from app import persistence as persist
from app.services.data_extract import DataExtractService

# 补采任务的生命周期
TASK_OPEN = "待领取"
TASK_CLAIMED = "已领取"
TASK_DONE = "已回填"
TASK_CANCELLED = "已取消"

PAGE_DRAFT = "待确认"
PAGE_CONFIRMED = "已确认"

EXTRACT_SUBDIR = "extract"


class ExtractScopeService:
    """采集页面 → 适用模板集 → 正式清洗行 → 补采回填 的全链路服务。"""

    def __init__(self, template_service: DataExtractService | None = None) -> None:
        self._templates = template_service or DataExtractService()
        self._pages: dict[str, dict[str, Any]] = {}
        self._scope_sets: list[dict[str, Any]] = []
        self._clean_rows: list[dict[str, Any]] = []
        self._tasks: list[dict[str, Any]] = []
        self._seq = 0

    # ------------------------------------------------------------------ 原页
    def register_page(
        self,
        *,
        page_id: str,
        page_type: str,
        page_version: str,
        source: str,
        resolved_fields: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str]:
        """登记采集页面（原页）。未确认前不允许进入适用集和正式清洗。"""
        page_id = page_id.strip()
        if not page_id:
            return None, "原页编号不能为空"
        if page_id in self._pages:
            return None, f"原页 {page_id} 已登记，不能重复登记"
        page = {
            "page_id": page_id,
            "页面类型": page_type.strip(),
            "页面版本": page_version.strip(),
            "来源标识": source.strip(),
            "解析字段": dict(resolved_fields),
            "status": PAGE_DRAFT,
            "registered_at": persist.now_iso(),
            "confirmed_at": "",
        }
        self._pages[page_id] = page
        self._append("pages.jsonl", {"event": "register_page", **self._page_event(page)})
        return page, "原页已登记，待确认"

    def confirm_page(self, page_id: str) -> tuple[dict[str, Any] | None, str]:
        """确认原页：只有已确认原页才允许参与适用集查询和正式清洗。"""
        page = self._pages.get(page_id)
        if page is None:
            return None, f"原页 {page_id} 不存在"
        page["status"] = PAGE_CONFIRMED
        page["confirmed_at"] = persist.now_iso()
        self._append("pages.jsonl", {"event": "confirm_page", **self._page_event(page)})
        return page, "原页已确认"

    def list_pages(self) -> list[dict[str, Any]]:
        return [dict(page) for page in self._pages.values()]

    def get_page(self, page_id: str) -> dict[str, Any] | None:
        page = self._pages.get(page_id)
        return dict(page) if page else None

    def _page_event(self, page: dict[str, Any]) -> dict[str, Any]:
        return {
            "page_id": page["page_id"],
            "页面类型": page["页面类型"],
            "页面版本": page["页面版本"],
            "来源标识": page["来源标识"],
            "解析字段": dict(page["解析字段"]),
            "status": page["status"],
            "timestamp": persist.now_iso(),
        }

    # --------------------------------------------------------------- 适用集
    def compute_scope_set(
        self,
        page_id: str,
        *,
        recompute: bool = False,
        pipeline_id: str = "",
    ) -> tuple[dict[str, Any] | None, str]:
        """按页面类型筛选适用模板并按覆盖字段排序，产出一版抽取适用集。

        ``recompute=True`` 不覆盖旧适用集，而是追加一版新快照，保证模板切换后
        已执行的适用集继续可复算、可回查。
        """
        page = self._pages.get(page_id)
        if page is None:
            return None, f"原页 {page_id} 不存在"
        if page["status"] != PAGE_CONFIRMED:
            return None, f"原页 {page_id} 尚未确认，不能查询抽取适用集"

        page_fields = set(page["解析字段"])
        all_templates = [
            t for t in self._templates.list_entries(page=1, size=1_000_000)[0]
            if t.get("status") == "已生效" and t.get("适用页面类型")
        ]
        candidates: list[dict[str, Any]] = []
        for tpl in all_templates:
            cover = list(tpl.get("覆盖字段") or [])
            failed_map = tpl.get("解析失败映射") or {}
            failed = list(failed_map.get(page_id, [])) + list(tpl.get("解析失败字段") or [])
            failed = [f for i, f in enumerate(failed) if f not in failed[:i]]
            type_matched = tpl.get("适用页面类型") == page["页面类型"]
            produced = [
                f for f in cover
                if type_matched and f in page_fields and f not in failed
            ]
            missing = [f for f in cover if f not in produced] if type_matched else list(cover)
            candidates.append({
                "template_id": tpl["id"],
                "模板编号": tpl.get("模板编号"),
                "模板版本": tpl.get("模板版本"),
                "version_fingerprint": tpl.get("version"),
                "适用页面类型": tpl.get("适用页面类型"),
                "来源标识": tpl.get("来源标识", ""),
                "覆盖字段": cover,
                "出数字段": produced,
                "缺失字段": missing,
                "解析失败字段": failed,
                "页面类型匹配": type_matched,
                "decision": "未用",
                "decision_reason": "",
            })

        matched = [c for c in candidates if c["页面类型匹配"]]
        # 排序：覆盖字段数降序 → 可出数字段数降序 → 模板编号升序（稳定口径）
        matched.sort(key=lambda c: (-len(c["覆盖字段"]), -len(c["出数字段"]), str(c["模板编号"])))
        unmatched = [c for c in candidates if not c["页面类型匹配"]]
        for c in unmatched:
            c["decision_reason"] = "页面类型不匹配，字段来源属于其他页面类型"
        ordered = matched + unmatched

        # 选中：排序后第一个覆盖完整（无缺失）的匹配模板；其余完整模板记未用，缺字段记不足
        selected = next((c for c in matched if not c["缺失字段"]), None)
        for c in matched:
            if selected is not None and c["template_id"] == selected["template_id"]:
                c["decision"] = "选中"
                c["decision_reason"] = "页面类型匹配且覆盖字段全部可出数"
            elif c["缺失字段"]:
                c["decision"] = "不足"
                c["decision_reason"] = "页面类型匹配但存在未出数字段"
            else:
                c["decision"] = "未用"
                c["decision_reason"] = "页面类型匹配但覆盖排序靠后，未被本轮选中"

        rounds = [s for s in self._scope_sets if s["page_id"] == page_id]
        scope_set = {
            "scope_id": self._next_id("SCOPE"),
            "page_id": page_id,
            "页面类型": page["页面类型"],
            "页面版本": page["页面版本"],
            "page_version_fingerprint": page["页面版本"],
            "pipeline_id": pipeline_id,
            "round": len(rounds) + 1,
            "recompute": recompute,
            "selected_template_id": selected["template_id"] if selected else None,
            "selected_template_code": selected["模板编号"] if selected else "",
            "candidate_count": len(ordered),
            "candidates": ordered,
            "created_at": persist.now_iso(),
        }
        self._scope_sets.append(scope_set)
        self._append("scope_sets.jsonl", {"event": "compute_scope_set", **scope_set})
        return scope_set, "抽取适用集已生成"

    def list_scope_sets(self, page_id: str | None = None) -> list[dict[str, Any]]:
        sets = self._scope_sets
        if page_id:
            sets = [s for s in sets if s["page_id"] == page_id]
        return [dict(s) for s in sets]

    def latest_scope_set(self, page_id: str) -> dict[str, Any] | None:
        sets = [s for s in self._scope_sets if s["page_id"] == page_id]
        return dict(sets[-1]) if sets else None

    # --------------------------------------------------------------- 正式清洗
    def start_cleaning(
        self,
        page_id: str,
        *,
        pipeline_id: str = "",
        template_id: int | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        """启动正式清洗：按原页最新适用集的选中模板生成正式行并落盘。

        可选 ``template_id`` 用于重新确认时显式指定模板（仍必须是该页面类型的
        生效模板）。字段值只取自本原页，绝不跨页拼接。
        """
        page = self._pages.get(page_id)
        if page is None:
            return None, f"原页 {page_id} 不存在"
        if page["status"] != PAGE_CONFIRMED:
            return None, f"原页 {page_id} 尚未确认，不能启动正式清洗"

        scope_set = self.latest_scope_set(page_id)
        if scope_set is None:
            scope_set, msg = self.compute_scope_set(page_id, pipeline_id=pipeline_id)
            if scope_set is None:
                return None, msg
        candidate = self._pick_candidate(scope_set, template_id)
        if candidate is None:
            return None, "适用集中没有可用于本页的生效模板"

        cover = list(candidate["覆盖字段"])
        produced_fields = list(candidate["出数字段"])
        missing_fields = [f for f in cover if f not in produced_fields]
        field_results = [
            {
                "field": f,
                "value": page["解析字段"].get(f) if f in produced_fields else None,
                "status": "出数" if f in produced_fields else "未出数",
                "source": page["来源标识"] if f in produced_fields else "",
            }
            for f in cover
        ]
        row = {
            "row_id": self._next_id("CR"),
            "page_id": page_id,
            "页面类型": page["页面类型"],
            "页面版本": page["页面版本"],
            "pipeline_id": pipeline_id,
            "scope_id": scope_set["scope_id"],
            "template_id": candidate["template_id"],
            "模板编号": candidate["模板编号"],
            "模板版本": candidate["模板版本"],
            "template_version_fingerprint": candidate["version_fingerprint"],
            "来源标识": candidate["来源标识"],
            "covered_fields": cover,
            "produced_fields": produced_fields,
            "missing_fields": missing_fields,
            "field_results": field_results,
            "status": "已出数" if not missing_fields else "待补采",
            "created_at": persist.now_iso(),
            "updated_at": persist.now_iso(),
        }
        self._clean_rows.append(row)
        self._append("clean_rows.jsonl", {"event": "start_cleaning", **row})

        # 未覆盖字段生成补采项：同页同字段只保留一条未完成补采，不重复出任务
        created_tasks: list[dict[str, Any]] = []
        for field in missing_fields:
            if self._has_open_task(page_id, field):
                continue
            task = {
                "task_id": self._next_id("SUP"),
                "page_id": page_id,
                "row_id": row["row_id"],
                "field": field,
                "status": TASK_OPEN,
                "claimed_at": "",
                "backfilled_at": "",
                "value": None,
                "created_at": persist.now_iso(),
            }
            self._tasks.append(task)
            created_tasks.append(task)
            self._append("supplement_tasks.jsonl", {"event": "create_task", **task})
        return row, f"正式清洗完成，新增补采项 {len(created_tasks)} 条"

    def _pick_candidate(
        self,
        scope_set: dict[str, Any],
        template_id: int | None,
    ) -> dict[str, Any] | None:
        candidates = scope_set["candidates"]
        if template_id is not None:
            target = next((c for c in candidates if c["template_id"] == template_id), None)
            # 显式指定也必须页面类型匹配，杜绝跨来源消费
            if target is not None and target["页面类型匹配"]:
                return target
            return None
        selected_id = scope_set.get("selected_template_id")
        if selected_id is not None:
            return next((c for c in candidates if c["template_id"] == selected_id), None)
        return None

    def list_clean_rows(
        self,
        *,
        page_id: str | None = None,
        template_version: str | None = None,
    ) -> list[dict[str, Any]]:
        rows = self._clean_rows
        if page_id:
            rows = [r for r in rows if r["page_id"] == page_id]
        if template_version:
            rows = [r for r in rows if r["模板版本"] == template_version]
        return [dict(r) for r in rows]

    # ---------------------------------------------------------------- 补采
    def list_supplement_tasks(
        self,
        *,
        page_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        tasks = self._tasks
        if page_id:
            tasks = [t for t in tasks if t["page_id"] == page_id]
        if status:
            tasks = [t for t in tasks if t["status"] == status]
        return [dict(t) for t in tasks]

    def claim_supplement(self, task_id: str) -> tuple[dict[str, Any] | None, str]:
        """领取补采项：只允许领取待领取任务，且补采范围限定本页未覆盖字段。"""
        task = self._find_task(task_id)
        if task is None:
            return None, f"补采项 {task_id} 不存在"
        if task["status"] != TASK_OPEN:
            return None, f"补采项 {task_id} 当前状态为{task['status']}，不能领取"
        task["status"] = TASK_CLAIMED
        task["claimed_at"] = persist.now_iso()
        self._append("supplement_tasks.jsonl", {"event": "claim_task", **task})
        return dict(task), "补采项已领取"

    def backfill_supplement(self, task_id: str, value: Any) -> tuple[dict[str, Any] | None, str]:
        """回填补采值到对应正式行的清洗范围。

        校验：任务须已领取；字段仍属于该原页当前未覆盖范围；回填只更新本页对应
        的正式行，不触碰其他页面、其他来源的数据。
        """
        task = self._find_task(task_id)
        if task is None:
            return None, f"补采项 {task_id} 不存在"
        if task["status"] != TASK_CLAIMED:
            return None, f"补采项 {task_id} 未领取，不能回填"
        page = self._pages.get(task["page_id"])
        if page is None:
            return None, f"原页 {task['page_id']} 不存在"
        row = next((r for r in self._clean_rows if r["row_id"] == task["row_id"]), None)
        if row is None:
            return None, f"补采项关联的正式行 {task['row_id']} 不存在"
        if task["field"] not in row["missing_fields"]:
            return None, f"字段 {task['field']} 已不在正式行 {row['row_id']} 的未覆盖范围内"

        task["status"] = TASK_DONE
        task["value"] = value
        task["backfilled_at"] = persist.now_iso()
        # 回填到对应清洗范围：同一条正式行增补字段，行标识与模板版本保持不变
        row["missing_fields"] = [f for f in row["missing_fields"] if f != task["field"]]
        if task["field"] not in row["produced_fields"]:
            row["produced_fields"].append(task["field"])
        for result in row["field_results"]:
            if result["field"] == task["field"]:
                result["value"] = value
                result["status"] = "出数"
                result["source"] = f"补采:{page['来源标识']}"
                break
        else:
            row["field_results"].append({
                "field": task["field"],
                "value": value,
                "status": "出数",
                "source": f"补采:{page['来源标识']}",
            })
        row["status"] = "已出数" if not row["missing_fields"] else "待补采"
        row["updated_at"] = persist.now_iso()
        self._append("supplement_tasks.jsonl", {"event": "backfill_task", **task})
        self._append("clean_rows.jsonl", {"event": "backfill_row", **row})
        return dict(task), "补采值已回填到对应正式清洗行"

    def _find_task(self, task_id: str) -> dict[str, Any] | None:
        return next((t for t in self._tasks if t["task_id"] == task_id), None)

    def _has_open_task(self, page_id: str, field: str) -> bool:
        return any(
            t["page_id"] == page_id and t["field"] == field and t["status"] in (TASK_OPEN, TASK_CLAIMED)
            for t in self._tasks
        )

    # ---------------------------------------------------------------- 审计
    def audit_events(self) -> dict[str, list[dict[str, Any]]]:
        """回查入口：把适用集/正式行/补采/原页/模板的落盘事件全部读出。"""
        return {
            "pages": persist.read_jsonl(EXTRACT_SUBDIR, "pages.jsonl"),
            "scope_sets": persist.read_jsonl(EXTRACT_SUBDIR, "scope_sets.jsonl"),
            "clean_rows": persist.read_jsonl(EXTRACT_SUBDIR, "clean_rows.jsonl"),
            "supplement_tasks": persist.read_jsonl(EXTRACT_SUBDIR, "supplement_tasks.jsonl"),
            "template_registry": persist.read_jsonl(EXTRACT_SUBDIR, "template_registry.jsonl"),
        }

    def snapshot(self) -> dict[str, Any]:
        return {
            "module": "extract_scope",
            "pages": len(self._pages),
            "confirmed_pages": sum(1 for p in self._pages.values() if p["status"] == PAGE_CONFIRMED),
            "scope_sets": len(self._scope_sets),
            "clean_rows": len(self._clean_rows),
            "supplement_tasks": len(self._tasks),
            "open_tasks": sum(1 for t in self._tasks if t["status"] == TASK_OPEN),
        }

    # ---------------------------------------------------------------- 演示数据
    def seed_demo(self) -> dict[str, Any]:
        """幂等灌入题面验收场景：同一商品详情页挂通用/专用两份模板，另有列表页来源。"""
        if self._pages:
            return {"skipped": True, **self.snapshot()}

        tpl_general = self._templates.register_scope_template(
            template_code="DATA-GENERAL-01",
            script_id="BEHA-GENERAL-01",
            page_type="商品详情页",
            cover_fields=["名称", "价格"],
            source="来源A-通用",
            template_label="general-v1",
        )
        tpl_shop = self._templates.register_scope_template(
            template_code="DATA-SHOP-01",
            script_id="BEHA-SHOP-01",
            page_type="商品详情页",
            cover_fields=["名称", "商家名称", "价格"],
            source="来源A-专用",
            failed_pages={"PAGE-DETAIL-01": ["价格"]},
            template_label="shop-v1",
        )
        tpl_list = self._templates.register_scope_template(
            template_code="DATA-LIST-01",
            script_id="BEHA-LIST-01",
            page_type="商品列表页",
            cover_fields=["商品标题", "价格"],
            source="来源B-列表",
            template_label="list-v1",
        )

        self.register_page(
            page_id="PAGE-DETAIL-01",
            page_type="商品详情页",
            page_version="detail-v1",
            source="来源A",
            resolved_fields={"名称": "示例商品", "价格": "99.00", "商家名称": "示例旗舰店"},
        )
        self.confirm_page("PAGE-DETAIL-01")
        self.register_page(
            page_id="PAGE-LIST-02",
            page_type="商品列表页",
            page_version="list-v1",
            source="来源B",
            resolved_fields={"商品标题": "列表商品", "价格": "88.00"},
        )
        self.confirm_page("PAGE-LIST-02")
        return {
            "skipped": False,
            "templates": [tpl_general["id"], tpl_shop["id"], tpl_list["id"]],
            "pages": ["PAGE-DETAIL-01", "PAGE-LIST-02"],
        }

    # ---------------------------------------------------------------- 内部工具
    def _next_id(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}-{self._seq:04d}"

    def _append(self, filename: str, record: dict[str, Any]) -> None:
        persist.append_jsonl(EXTRACT_SUBDIR, filename, record)


# 单例：路由与清洗管道钩子共享同一份内存态与 JSONL 落盘。
extract_scope_service = ExtractScopeService()

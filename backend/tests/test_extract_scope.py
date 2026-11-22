"""抽取适用集端到端验收测试。

覆盖题面验收链路：
1. 同一商品详情页同时命中通用模板（名称+价格完整）与专用模板（有商家名称但缺价格）；
2. 商品列表页也有价格字段但属于另一份来源，不能拼入详情页的清洗结果；
3. 先按页面类型筛选适用集并按覆盖字段排序，再启动清洗并按原页查正式行；
4. 通用模板出齐时补采任务列表不出现已取得的价格；
5. 首轮专用模板无价格 → 领取该原页的价格补采 → 验证未出数范围 → 回填；
6. 给专用模板补好价格并重新确认，旧结果仍按原模板版本查到；
7. 适用集快照与候选决策（选中/未用/不足）可回查，模板切换后可复算；
8. 通过清洗管道「启用工序」原动作执行适用集并持久化字段与补采项。
"""
from __future__ import annotations

import os
import sys

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app import persistence as persist

# 清理本特性与既有跨模块测试的落盘目录，保证可重复执行
for sub in ["runs", "snapshots", "reports", "exports", "extract"]:
    p = persist.data_path(sub, "")
    if os.path.isdir(p):
        for f in os.listdir(p):
            os.remove(os.path.join(p, f))

from app.store import store
from app.services.data_extract import DataExtractService
from app.services.extract_scope import (
    ExtractScopeService,
    TASK_OPEN,
    TASK_CLAIMED,
    TASK_DONE,
)
from app.services.clean_pipeline import CleanPipelineService


def _reset_store() -> None:
    """清掉各用例登记进共享模板表的适用集模板，保证用例相互隔离。"""
    for row in list(store.rows("data_extract")):
        if row.get("适用页面类型"):
            store.rows("data_extract").remove(row)


def _fresh_service() -> ExtractScopeService:
    """每个用例使用独立服务实例，并清空上一轮登记的适用集模板。"""
    _reset_store()
    return ExtractScopeService(DataExtractService())


def _seed_shop_scenario(svc: ExtractScopeService) -> dict:
    """构造商品详情页 + 通用/专用模板 + 列表页其他来源的完整验收场景。"""
    general = svc._templates.register_scope_template(
        template_code="DATA-GENERAL-01",
        script_id="BEHA-GENERAL-01",
        page_type="商品详情页",
        cover_fields=["名称", "价格"],
        source="来源A-通用",
        template_label="general-v1",
    )
    shop = svc._templates.register_scope_template(
        template_code="DATA-SHOP-01",
        script_id="BEHA-SHOP-01",
        page_type="商品详情页",
        cover_fields=["名称", "商家名称", "价格"],
        source="来源A-专用",
        failed_pages={"PAGE-DETAIL-01": ["价格"]},
        template_label="shop-v1",
    )
    listing = svc._templates.register_scope_template(
        template_code="DATA-LIST-01",
        script_id="BEHA-LIST-01",
        page_type="商品列表页",
        cover_fields=["商品标题", "价格"],
        source="来源B-列表",
        template_label="list-v1",
    )
    svc.register_page(
        page_id="PAGE-DETAIL-01",
        page_type="商品详情页",
        page_version="detail-v1",
        source="来源A",
        resolved_fields={"名称": "示例商品", "价格": "99.00", "商家名称": "示例旗舰店"},
    )
    svc.register_page(
        page_id="PAGE-LIST-02",
        page_type="商品列表页",
        page_version="list-v1",
        source="来源B",
        resolved_fields={"商品标题": "列表商品", "价格": "88.00"},
    )
    return {"general": general, "shop": shop, "listing": listing}


def test_unconfirmed_page_rejected():
    """未确认原页不能查询适用集、不能启动正式清洗。"""
    svc = _fresh_service()
    _seed_shop_scenario(svc)
    scope_set, msg = svc.compute_scope_set("PAGE-DETAIL-01")
    assert scope_set is None and "尚未确认" in msg
    row, clean_msg = svc.start_cleaning("PAGE-DETAIL-01")
    assert row is None and "尚未确认" in clean_msg
    print("PASS: test_unconfirmed_page_rejected")


def test_scope_set_filters_by_page_type_and_sorts():
    """按页面类型筛选适用集并按覆盖字段排序；跨页面类型模板只记未用、不参与出数。"""
    svc = _fresh_service()
    ids = _seed_shop_scenario(svc)
    svc.confirm_page("PAGE-DETAIL-01")
    svc.confirm_page("PAGE-LIST-02")

    scope_set, msg = svc.compute_scope_set("PAGE-DETAIL-01")
    assert scope_set is not None, msg
    candidates = scope_set["candidates"]

    matched = [c for c in candidates if c["页面类型匹配"]]
    unmatched = [c for c in candidates if not c["页面类型匹配"]]
    assert {c["template_id"] for c in matched} == {ids["general"]["id"], ids["shop"]["id"]}
    # 列表页模板虽含价格字段，但属于另一份来源/页面类型，只能是未用候选
    assert len(unmatched) == 1 and unmatched[0]["template_id"] == ids["listing"]["id"]
    assert unmatched[0]["decision"] == "未用"
    assert unmatched[0]["出数字段"] == []

    # 排序：覆盖字段数降序，专用模板(3字段)排在通用模板(2字段)之前
    assert [c["template_id"] for c in matched] == [ids["shop"]["id"], ids["general"]["id"]]

    # 专用模板缺价格 → 不足；通用模板名称/价格齐 → 选中
    shop_candidate = next(c for c in matched if c["template_id"] == ids["shop"]["id"])
    general_candidate = next(c for c in matched if c["template_id"] == ids["general"]["id"])
    assert shop_candidate["decision"] == "不足"
    assert shop_candidate["缺失字段"] == ["价格"]
    assert shop_candidate["出数字段"] == ["名称", "商家名称"]
    assert general_candidate["decision"] == "选中"
    assert general_candidate["出数字段"] == ["名称", "价格"]
    assert scope_set["selected_template_id"] == ids["general"]["id"]
    print("PASS: test_scope_set_filters_by_page_type_and_sorts")
    return svc, ids, scope_set


def test_general_template_cleaning_no_price_task():
    """通用模板出齐名称和价格：正式行可出数，补采列表不出现已取得的价格。"""
    svc = _fresh_service()
    ids = _seed_shop_scenario(svc)
    svc.confirm_page("PAGE-DETAIL-01")
    svc.compute_scope_set("PAGE-DETAIL-01")

    row, msg = svc.start_cleaning("PAGE-DETAIL-01", pipeline_id="CLEA-GENERAL")
    assert row is not None, msg
    assert row["template_id"] == ids["general"]["id"]
    assert row["produced_fields"] == ["名称", "价格"]
    assert row["missing_fields"] == []
    assert row["status"] == "已出数"
    values = {item["field"]: item["value"] for item in row["field_results"]}
    assert values == {"名称": "示例商品", "价格": "99.00"}

    tasks = svc.list_supplement_tasks(page_id="PAGE-DETAIL-01")
    assert tasks == [], f"通用模板已出齐，不应有补采项，实际: {tasks}"
    assert not any(t["field"] == "价格" for t in tasks)

    # 按原页查询正式行
    rows = svc.list_clean_rows(page_id="PAGE-DETAIL-01")
    assert len(rows) == 1 and rows[0]["row_id"] == row["row_id"]
    print("PASS: test_general_template_cleaning_no_price_task")
    return svc, ids


def test_no_cross_page_value_mixing():
    """另一个页面类型的价格属于另一份来源，详情页缺字段时不得拼入。"""
    svc = _fresh_service()
    ids = _seed_shop_scenario(svc)
    svc.confirm_page("PAGE-DETAIL-01")
    svc.confirm_page("PAGE-LIST-02")
    svc.compute_scope_set("PAGE-DETAIL-01")

    # 显式用专用模板清洗：价格未出数，字段值只允许来自本原页
    row, msg = svc.start_cleaning("PAGE-DETAIL-01", template_id=ids["shop"]["id"])
    assert row is not None, msg
    assert row["missing_fields"] == ["价格"]
    price_result = next(item for item in row["field_results"] if item["field"] == "价格")
    assert price_result["status"] == "未出数" and price_result["value"] is None
    # 列表页的 88.00 绝不能出现在详情页正式行里
    all_values = [item["value"] for item in row["field_results"]]
    assert "88.00" not in all_values
    assert row["来源标识"] == "来源A-专用"

    # 跨页面类型模板不能被显式选中
    bad_row, bad_msg = svc.start_cleaning("PAGE-DETAIL-01", template_id=ids["listing"]["id"])
    assert bad_row is None and "没有可用" in bad_msg
    print("PASS: test_no_cross_page_value_mixing")
    return svc, ids, row


def test_claim_and_backfill_supplement():
    """首轮无价格 → 领取本页补采 → 校验未出数范围 → 回填到对应正式行。"""
    svc, ids, row = test_no_cross_page_value_mixing()
    tasks = svc.list_supplement_tasks(page_id="PAGE-DETAIL-01")
    assert len(tasks) == 1
    task = tasks[0]
    assert task["field"] == "价格" and task["status"] == TASK_OPEN
    assert task["row_id"] == row["row_id"]

    # 未领取直接回填应被拒绝
    bad_task, bad_msg = svc.backfill_supplement(task["task_id"], "79.00")
    assert bad_task is None and "未领取" in bad_msg

    claimed, claim_msg = svc.claim_supplement(task["task_id"])
    assert claimed is not None and claimed["status"] == TASK_CLAIMED, claim_msg
    # 重复领取应被拒绝
    again, again_msg = svc.claim_supplement(task["task_id"])
    assert again is None and "不能领取" in again_msg

    # 验证未出数范围：补采前正式行仍缺价格
    before = svc.list_clean_rows(page_id="PAGE-DETAIL-01")[0]
    assert before["missing_fields"] == ["价格"]

    done, backfill_msg = svc.backfill_supplement(task["task_id"], "79.00")
    assert done is not None and done["status"] == TASK_DONE, backfill_msg

    after = svc.list_clean_rows(page_id="PAGE-DETAIL-01")[0]
    # 回填进入同一条正式行，行标识与模板版本不变
    assert after["row_id"] == row["row_id"]
    assert after["template_version_fingerprint"] == row["template_version_fingerprint"]
    assert after["missing_fields"] == []
    assert "价格" in after["produced_fields"]
    assert after["status"] == "已出数"
    price_result = next(item for item in after["field_results"] if item["field"] == "价格")
    assert price_result["value"] == "79.00" and price_result["source"].startswith("补采:")
    print("PASS: test_claim_and_backfill_supplement")
    return svc, ids, row


def test_template_revision_keeps_old_rows_queryable():
    """给专用模板补好价格并重新确认：新行出齐，旧结果仍按原模板版本查到。"""
    svc, ids, old_row = test_claim_and_backfill_supplement()
    old_fingerprint = old_row["template_version_fingerprint"]
    old_label = old_row["模板版本"]

    # 模板修订：修复该原页的价格选择器（解除解析失败映射），换版 shop-v2
    revised, revise_msg = svc._templates.revise_template(
        ids["shop"]["id"],
        clear_failed_pages=True,
        template_label="shop-v2",
    )
    assert revised is not None, revise_msg
    assert revised["解析失败映射"] == {}
    assert revised["模板版本"] == "shop-v2"
    assert revised["version"] != old_fingerprint

    # 重新计算适用集（复算，旧快照保留）
    scope_sets_before = len(svc.list_scope_sets("PAGE-DETAIL-01"))
    new_scope, msg = svc.compute_scope_set("PAGE-DETAIL-01", recompute=True)
    assert new_scope is not None, msg
    assert len(svc.list_scope_sets("PAGE-DETAIL-01")) == scope_sets_before + 1
    # 专用模板覆盖3字段且已能全部出数，按覆盖排序后成为选中模板
    assert new_scope["selected_template_id"] == ids["shop"]["id"]
    shop_candidate = next(c for c in new_scope["candidates"] if c["template_id"] == ids["shop"]["id"])
    assert shop_candidate["decision"] == "选中" and shop_candidate["缺失字段"] == []

    # 重新确认清洗
    new_row, clean_msg = svc.start_cleaning("PAGE-DETAIL-01", template_id=ids["shop"]["id"])
    assert new_row is not None, clean_msg
    assert new_row["模板版本"] == "shop-v2"
    assert new_row["produced_fields"] == ["名称", "商家名称", "价格"]
    assert new_row["missing_fields"] == []

    # 旧结果仍按原模板版本查到，且保留旧版本指纹
    old_rows = svc.list_clean_rows(page_id="PAGE-DETAIL-01", template_version=old_label)
    assert len(old_rows) == 1
    assert old_rows[0]["row_id"] == old_row["row_id"]
    assert old_rows[0]["template_version_fingerprint"] == old_fingerprint

    new_rows = svc.list_clean_rows(page_id="PAGE-DETAIL-01", template_version="shop-v2")
    assert len(new_rows) == 1 and new_rows[0]["row_id"] == new_row["row_id"]

    # 模板切换前已执行的适用集仍可复算/回查
    first_scope = svc.list_scope_sets("PAGE-DETAIL-01")[0]
    first_shop = next(c for c in first_scope["candidates"] if c["template_id"] == ids["shop"]["id"])
    assert first_shop["decision"] == "不足" and first_shop["缺失字段"] == ["价格"]
    print("PASS: test_template_revision_keeps_old_rows_queryable")


def test_decisions_and_events_are_auditable():
    """选中、未用、不足的候选与字段，以及全部状态事件均可回查。"""
    svc = _fresh_service()
    _seed_shop_scenario(svc)
    svc.confirm_page("PAGE-DETAIL-01")
    svc.compute_scope_set("PAGE-DETAIL-01")
    svc.start_cleaning("PAGE-DETAIL-01")

    audit = svc.audit_events()
    assert any(e["event"] == "confirm_page" for e in audit["pages"])
    scope_events = audit["scope_sets"]
    assert scope_events and scope_events[-1]["event"] == "compute_scope_set"
    decisions = {c["decision"] for c in scope_events[-1]["candidates"]}
    assert {"选中", "未用", "不足"} <= decisions
    assert any(e["event"] == "start_cleaning" for e in audit["clean_rows"])
    assert any(e["event"] == "register_template" for e in audit["template_registry"])

    # 落盘文件实际存在
    for filename in ["pages.jsonl", "scope_sets.jsonl", "clean_rows.jsonl", "template_registry.jsonl"]:
        assert persist.read_jsonl("extract", filename), f"{filename} 无落盘记录"
    print("PASS: test_decisions_and_events_are_auditable")


def test_pipeline_enable_runs_scope_cleaning():
    """通过清洗管道原「启用工序」动作执行适用集，并持久化出数字段与补采项。"""
    svc = _fresh_service()
    ids = _seed_shop_scenario(svc)
    svc.confirm_page("PAGE-DETAIL-01")

    # 把本特性的页面/模板通过共享 store 暴露给管道钩子使用的单例服务
    from app.services.extract_scope import extract_scope_service as singleton
    singleton._pages = svc._pages
    singleton._scope_sets = svc._scope_sets
    singleton._clean_rows = svc._clean_rows
    singleton._tasks = svc._tasks
    singleton._seq = svc._seq

    pipeline_svc = CleanPipelineService()
    entry, missing = pipeline_svc.create_entry({
        "工序编号": "CLEA-SCOPE-01",
        "输入源": "page:PAGE-DETAIL-01",
        "清洗规则": "适用集清洗",
    })
    assert entry is not None, missing
    result, msg = pipeline_svc.run_action(entry["id"], "启用工序")
    assert result is not None and result["status"] == "已启用", msg

    rows = singleton.list_clean_rows(page_id="PAGE-DETAIL-01")
    assert len(rows) == 1
    assert rows[0]["pipeline_id"] == "CLEA-SCOPE-01"
    assert rows[0]["produced_fields"] == ["名称", "价格"]

    reports = persist.read_jsonl("reports", "pipeline_extract_scope.jsonl")
    scope_runs = [r for r in reports if r["event"] == "scope_cleaning"]
    assert scope_runs and scope_runs[-1]["page_id"] == "PAGE-DETAIL-01"

    # 未确认/未登记原页不阻断启用动作，只记录跳过事件
    skip_entry, _ = pipeline_svc.create_entry({
        "工序编号": "CLEA-SCOPE-02",
        "输入源": "page:PAGE-NOT-EXIST",
        "清洗规则": "适用集清洗",
    })
    pipeline_svc.run_action(skip_entry["id"], "启用工序")
    skip_reports = [r for r in persist.read_jsonl("reports", "pipeline_extract_scope.jsonl")
                    if r["event"] == "skip_unconfirmed_page"]
    assert skip_reports and skip_reports[-1]["page_id"] == "PAGE-NOT-EXIST"
    print("PASS: test_pipeline_enable_runs_scope_cleaning")


def test_scope_template_lookup_replaces_script_wide_fields():
    """新口径只按页面类型返回生效模板，区别于按脚本返回全部字段的旧口径。"""
    template_svc = DataExtractService()
    svc = _fresh_service()
    ids = _seed_shop_scenario(svc)
    applicable = template_svc.find_applicable_templates("商品详情页")
    applicable_ids = {t["id"] for t in applicable}
    assert ids["general"]["id"] in applicable_ids
    assert ids["shop"]["id"] in applicable_ids
    # 列表页模板不属于详情页适用集
    assert ids["listing"]["id"] not in applicable_ids
    assert template_svc.find_applicable_templates("不存在的页面类型") == []
    print("PASS: test_scope_template_lookup_replaces_script_wide_fields")


def test_supplement_only_covers_current_page_fields():
    """补采只面向本页未覆盖字段：同页同字段不重复建任务，回填不影响其他页面。"""
    svc = _fresh_service()
    ids = _seed_shop_scenario(svc)
    svc.confirm_page("PAGE-DETAIL-01")
    svc.confirm_page("PAGE-LIST-02")
    svc.compute_scope_set("PAGE-DETAIL-01")
    row, _ = svc.start_cleaning("PAGE-DETAIL-01", template_id=ids["shop"]["id"])
    # 再跑一轮，同一缺失字段不应重复产生补采项
    svc.compute_scope_set("PAGE-DETAIL-01", recompute=True)
    svc.start_cleaning("PAGE-DETAIL-01", template_id=ids["shop"]["id"])
    tasks = svc.list_supplement_tasks(page_id="PAGE-DETAIL-01")
    assert len(tasks) == 1 and tasks[0]["field"] == "价格"

    # 列表页正式行不受详情页补采影响
    svc.compute_scope_set("PAGE-LIST-02")
    list_row, _ = svc.start_cleaning("PAGE-LIST-02")
    assert list_row["page_id"] == "PAGE-LIST-02"
    assert list_row["produced_fields"] == ["商品标题", "价格"]
    assert svc.list_supplement_tasks(page_id="PAGE-LIST-02") == []

    # 回填详情页补采，列表页数据保持原样
    task_id = tasks[0]["task_id"]
    svc.claim_supplement(task_id)
    svc.backfill_supplement(task_id, "79.00")
    list_row_after = svc.list_clean_rows(page_id="PAGE-LIST-02")[0]
    list_price = next(i for i in list_row_after["field_results"] if i["field"] == "价格")
    assert list_price["value"] == "88.00"
    print("PASS: test_supplement_only_covers_current_page_fields")


if __name__ == "__main__":
    test_unconfirmed_page_rejected()
    test_scope_set_filters_by_page_type_and_sorts()
    test_general_template_cleaning_no_price_task()
    test_claim_and_backfill_supplement()
    test_template_revision_keeps_old_rows_queryable()
    test_decisions_and_events_are_auditable()
    test_pipeline_enable_runs_scope_cleaning()
    test_scope_template_lookup_replaces_script_wide_fields()
    test_supplement_only_covers_current_page_fields()
    print("\nALL 9 EXTRACT-SCOPE TESTS PASSED")

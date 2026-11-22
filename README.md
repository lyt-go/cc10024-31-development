# 网页行为采集与内容清洗平台

面向网页行为录制、脚本化采集、内容清洗与结构化输出的数据采集与加工平台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/WorkbenchView.vue|tsx  全部模块共享工作台
│   ├── src/data/modules.ts              18个业务模块配置
│   ├── src/api/              统一请求封装
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/resource.py  通用查询/导出/登记/动作接口
│   ├── app/services/<key>.py    每个模块独立领域逻辑
│   ├── app/services/base.py     共享服务骨架
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm ci
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 行为脚本 | `behavior_script` | 行为脚本 | 脚本编号、目标站点、录制步骤 |
| 元素定位 | `element_selector` | 元素锚点 | 锚点编号、关联脚本、选择器类型 |
| 数据抽取 | `data_extract` | 抽取模板 | 模板编号、关联脚本、抽取字段 |
| 清洗管道 | `clean_pipeline` | 清洗工序 | 工序编号、输入源、清洗规则 |
| 转换规则 | `transform_rule` | 转换规则 | 规则编号、关联工序、源字段 |
| 质量防护 | `quality_guard` | 质量规则 | 规则编号、检核对象、检核维度 |
| 脚本调度 | `script_schedule` | 调度计划 | 计划编号、关联脚本、触发条件 |
| 登录凭证 | `login_mgr` | 登录凭证 | 凭证编号、目标站点、认证方式 |
| 页面快照 | `page_snapshot` | 页面快照 | 快照编号、采集来源、页面版本 |
| 错误恢复 | `error_recover` | 恢复任务 | 任务编号、关联计划、失败步骤 |
| 页面去重 | `page_dedup` | 去重规则 | 规则编号、去重维度、特征字段 |
| 字段归一化 | `field_normalize` | 归一规则 | 规则编号、关联字段、归一类型 |
| 批次队列 | `batch_queue` | 采集批次 | 批次编号、关联计划、任务数量 |
| 画布配置 | `canvas_config` | 画布配置 | 配置编号、关联站点、分辨率 |
| 导出通道 | `export_channel` | 导出配置 | 通道编号、输出格式、目标路径 |
| 运行历史 | `run_history` | 运行记录 | 记录编号、关联计划、开始时间 |
| Schema校验 | `schema_check` | Schema规则 | 规则编号、目标数据、字段名 |
| 内容缓存 | `content_cache` | 缓存配置 | 配置编号、缓存类型、过期策略 |

## 约定

- 全部模块共享`frontend/src/views/WorkbenchView.vue|tsx`和一套资源路由。
- 每个模块仍保留独立`backend/app/services/<模块>.py`；纯前端保留
  `frontend/src/domain/<模块>.ts`，用于承载真实业务差异并维持36题位容量。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 抽取适用集（采集页面 → 适用模板 → 正式清洗 → 补采回填）

`data_extract` 旧口径按脚本返回全部生效字段，不区分页面类型。新增的抽取适用集链路
（`backend/app/services/extract_scope.py`、`backend/app/routers/extract.py`）把口径收敛为
「按实际页面类型筛选 + 按覆盖字段排序」，并把清洗结果和补采项持久化到 `data/extract/`。

领域约束：

- 原页必须先「确认」才能查询适用集和启动正式清洗；
- 同一条正式清洗行只消费已确认原页和一个确定版本的模板（含版本指纹快照），
  缺字段不允许从别的页面、别的来源拼入；
- 候选模板按「覆盖字段数 → 可出数字段数」降序排序，并标注 `选中/未用/不足` 决策，全部可回查；
- 清洗只持久化可出数字段，本页未覆盖字段生成补采项；同页同字段不重复建任务；
- 补采领取后回填到同一条正式行的清洗范围，不影响其他页面；
- 模板修订换版后历史适用集与正式行保留旧版本快照，仍可按原模板版本查询、复算；
- 清洗工序「启用工序」动作（输入源写 `page:<原页编号>`）会自动执行该链路。

专用接口（前缀 `/api/extract`）：

| 接口 | 说明 |
| --- | --- |
| `POST /demo-seed` | 幂等灌入演示场景（商品详情页通用/专用模板 + 列表页其他来源） |
| `POST /pages`、`POST /pages/{id}/confirm`、`GET /pages` | 采集原页登记、确认、查询 |
| `POST /templates`、`POST /templates/{id}/revise` | 适用模板登记、修订换版 |
| `POST /pages/{id}/scope-sets`、`GET /scope-sets` | 按页面类型计算/复算适用集 |
| `POST /cleaning`、`GET /clean-rows` | 启动正式清洗、按原页/模板版本查正式行 |
| `GET /supplement-tasks`、`POST .../{id}/claim`、`POST .../{id}/backfill` | 补采领取与回填 |
| `GET /audit` | 原页、适用集、正式行、补采、模板事件全量回查 |

落盘文件（`data/extract/`）：`pages.jsonl`、`scope_sets.jsonl`、`clean_rows.jsonl`、
`supplement_tasks.jsonl`、`template_registry.jsonl`；管道触发记录在
`data/reports/pipeline_extract_scope.jsonl`。

验收测试：`backend/tests/test_extract_scope.py`（9 个用例，与 `test_cross_module.py` 互相独立）。

领域：数据工程
子方向：数据采集、爬虫与RPA

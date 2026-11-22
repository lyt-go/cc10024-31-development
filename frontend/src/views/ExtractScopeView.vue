<template>
  <section class="page" data-module="extract_scope">
    <header class="page-head">
      <div>
        <h2>抽取适用集与正式清洗</h2>
        <p class="page-desc">
          按采集页面类型筛选生效模板并按覆盖字段排序，正式清洗只消费已确认原页与确定模板版本，
          未覆盖字段生成可领取补采项，全程可回查、可复算。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" data-testid="demo-seed" type="button" @click="seedDemo">
          灌入演示场景
        </button>
        <button class="btn primary" data-testid="open-register" type="button" @click="openRegister">
          登记采集页面
        </button>
      </div>
    </header>

    <div class="stat-row">
      <article class="stat-card">
        <span class="stat-label">采集原页</span>
        <strong class="stat-value">{{ pages.length }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">适用集版本</span>
        <strong class="stat-value">{{ scopeSets.length }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">正式清洗行</span>
        <strong class="stat-value">{{ cleanRows.length }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">待领取补采</span>
        <strong class="stat-value">{{ openTaskCount }}</strong>
      </article>
    </div>

    <p v-if="message" class="status-legend" data-testid="message-bar">
      <span class="legend-item">{{ message }}</span>
    </p>

    <h3 class="section-title">① 采集页面（原页，确认后才进入适用集）</h3>
    <table class="data-table">
      <thead>
        <tr>
          <th>原页编号</th>
          <th>页面类型</th>
          <th>页面版本</th>
          <th>来源标识</th>
          <th>可解析字段</th>
          <th>确认状态</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="page in pages" :key="page.page_id" :data-testid="`page-${page.page_id}`">
          <td>{{ page.page_id }}</td>
          <td>{{ page['页面类型'] }}</td>
          <td>{{ page['页面版本'] }}</td>
          <td>{{ page['来源标识'] }}</td>
          <td>{{ Object.keys(page['解析字段']).join('、') }}</td>
          <td>{{ page.status }}</td>
          <td class="row-actions">
            <button
              v-if="page.status !== '已确认'"
              class="link"
              type="button"
              :data-testid="`confirm-${page.page_id}`"
              @click="confirm(page.page_id)"
            >
              确认原页
            </button>
            <button class="link" type="button" @click="selectPage(page.page_id)">
              查看适用集
            </button>
          </td>
        </tr>
        <tr v-if="!pages.length">
          <td colspan="7" class="empty-state">暂无采集页面，可先灌入演示场景或登记原页</td>
        </tr>
      </tbody>
    </table>

    <div class="page-actions section-actions">
      <button
        class="btn primary"
        data-testid="compute-scope"
        type="button"
        :disabled="!selectedPageId"
        @click="computeScope(false)"
      >
        查询适用集
      </button>
      <button
        class="btn"
        data-testid="recompute-scope"
        type="button"
        :disabled="!selectedPageId"
        @click="computeScope(true)"
      >
        复算适用集（保留历史版本）
      </button>
      <button
        class="btn primary"
        data-testid="start-cleaning"
        type="button"
        :disabled="!selectedPageId"
        @click="cleanWithSelected"
      >
        按选中模板启动正式清洗
      </button>
    </div>

    <template v-if="latestScope">
      <h3 class="section-title">
        ② 抽取适用集（{{ latestScope.scope_id }} · 第 {{ latestScope.round }} 轮 ·
        选中 {{ latestScope.selected_template_code || '无' }}）
      </h3>
      <table class="data-table">
        <thead>
          <tr>
            <th>候选模板</th>
            <th>模板版本</th>
            <th>页面类型匹配</th>
            <th>覆盖字段</th>
            <th>可出数字段</th>
            <th>缺失字段</th>
            <th>来源</th>
            <th>候选决策</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="candidate in latestScope.candidates"
            :key="candidate.template_id"
            :data-testid="`candidate-${candidate.template_id}`"
            :data-decision="candidate.decision"
          >
            <td>{{ candidate['模板编号'] }}</td>
            <td>{{ candidate['模板版本'] }}</td>
            <td>{{ candidate['页面类型匹配'] ? '匹配' : '不匹配' }}</td>
            <td>{{ candidate['覆盖字段'].join('、') }}</td>
            <td>{{ candidate['出数字段'].join('、') || '—' }}</td>
            <td>{{ candidate['缺失字段'].join('、') || '—' }}</td>
            <td>{{ candidate['来源标识'] }}</td>
            <td>
              <span class="decision-tag" :data-decision="candidate.decision">
                {{ candidate.decision }}
              </span>
              <small class="decision-reason">{{ candidate.decision_reason }}</small>
            </td>
            <td class="row-actions">
              <button
                v-if="candidate['页面类型匹配']"
                class="link"
                type="button"
                :data-testid="`clean-${candidate.template_id}`"
                @click="cleanWithTemplate(candidate.template_id)"
              >
                用此模板清洗
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </template>

    <h3 class="section-title">③ 正式清洗行（按原页与模板版本查询）</h3>
    <table class="data-table">
      <thead>
        <tr>
          <th>正式行</th>
          <th>原页</th>
          <th>模板 / 版本</th>
          <th>版本指纹</th>
          <th>出数字段</th>
          <th>未出数字段</th>
          <th>状态</th>
          <th>字段明细</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in cleanRows" :key="row.row_id" :data-testid="`clean-row-${row.row_id}`">
          <td>{{ row.row_id }}</td>
          <td>{{ row.page_id }}</td>
          <td>{{ row['模板编号'] }} / {{ row['模板版本'] }}</td>
          <td>{{ row.template_version_fingerprint.slice(0, 8) }}</td>
          <td>{{ row.produced_fields.join('、') }}</td>
          <td>{{ row.missing_fields.join('、') || '—' }}</td>
          <td>{{ row.status }}</td>
          <td>
            <span v-for="item in row.field_results" :key="item.field" class="field-chip">
              {{ item.field }}={{ item.value ?? '∅' }}（{{ item.status }}）
            </span>
          </td>
        </tr>
        <tr v-if="!cleanRows.length">
          <td colspan="8" class="empty-state">暂无正式清洗行</td>
        </tr>
      </tbody>
    </table>

    <h3 class="section-title">④ 补采任务（只面向本页未覆盖字段，回填进入对应正式行）</h3>
    <table class="data-table">
      <thead>
        <tr>
          <th>补采项</th>
          <th>原页</th>
          <th>关联正式行</th>
          <th>补采字段</th>
          <th>状态</th>
          <th>回填值</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="task in tasks" :key="task.task_id" :data-testid="`task-${task.task_id}`">
          <td>{{ task.task_id }}</td>
          <td>{{ task.page_id }}</td>
          <td>{{ task.row_id }}</td>
          <td>{{ task.field }}</td>
          <td>{{ task.status }}</td>
          <td>{{ task.value ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-if="task.status === '待领取'"
              class="link"
              type="button"
              :data-testid="`claim-${task.task_id}`"
              @click="claim(task.task_id)"
            >
              领取
            </button>
            <template v-if="task.status === '已领取'">
              <input
                v-model="backfillValues[task.task_id]"
                class="backfill-input"
                :data-testid="`backfill-input-${task.task_id}`"
                placeholder="补采值"
              />
              <button
                class="link"
                type="button"
                :data-testid="`backfill-${task.task_id}`"
                @click="backfill(task.task_id)"
              >
                回填
              </button>
            </template>
          </td>
        </tr>
        <tr v-if="!tasks.length">
          <td colspan="7" class="empty-state">没有待处理补采项（已取得的字段不会生成任务）</td>
        </tr>
      </tbody>
    </table>

    <div v-if="showRegister" class="modal-backdrop" data-testid="register-modal">
      <form class="modal" @submit.prevent="submitRegister">
        <h3>登记采集页面</h3>
        <label class="create-field">
          <span>原页编号</span>
          <input v-model="registerForm.page_id" data-testid="reg-page-id" required />
        </label>
        <label class="create-field">
          <span>页面类型</span>
          <input v-model="registerForm.page_type" data-testid="reg-page-type" placeholder="如 商品详情页" required />
        </label>
        <label class="create-field">
          <span>页面版本</span>
          <input v-model="registerForm.page_version" data-testid="reg-page-version" required />
        </label>
        <label class="create-field">
          <span>来源标识</span>
          <input v-model="registerForm.source" data-testid="reg-source" />
        </label>
        <label class="create-field">
          <span>可解析字段（字段=值，每行一个）</span>
          <textarea
            v-model="registerForm.resolved_text"
            data-testid="reg-resolved"
            rows="4"
            placeholder="名称=示例商品&#10;价格=99.00"
          ></textarea>
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="showRegister = false">取消</button>
          <button class="btn primary" data-testid="submit-register" type="submit">确认登记</button>
        </div>
      </form>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import {
  backfillTask,
  claimTask,
  computeScopeSet,
  confirmPage,
  demoSeed,
  listCleanRows,
  listPages,
  listScopeSets,
  listSupplementTasks,
  registerPage,
  startCleaning,
  type CleanRow,
  type CollectedPage,
  type ScopeSet,
  type SupplementTask,
} from '@/api/extract-service'

const pages = ref<CollectedPage[]>([])
const scopeSets = ref<ScopeSet[]>([])
const cleanRows = ref<CleanRow[]>([])
const tasks = ref<SupplementTask[]>([])
const selectedPageId = ref('')
const message = ref('')
const showRegister = ref(false)
const backfillValues = ref<Record<string, string>>({})
const registerForm = ref({
  page_id: '',
  page_type: '',
  page_version: '',
  source: '',
  resolved_text: '',
})

const latestScope = computed<ScopeSet | null>(() => {
  const sets = selectedPageId.value
    ? scopeSets.value.filter((item) => item.page_id === selectedPageId.value)
    : scopeSets.value
  return sets.length ? sets[sets.length - 1] : null
})

const openTaskCount = computed(() => tasks.value.filter((task) => task.status === '待领取').length)

async function refresh() {
  pages.value = await listPages()
  scopeSets.value = await listScopeSets(selectedPageId.value || undefined)
  cleanRows.value = await listCleanRows(
    selectedPageId.value ? { page_id: selectedPageId.value } : {},
  )
  tasks.value = await listSupplementTasks(
    selectedPageId.value ? { page_id: selectedPageId.value } : {},
  )
}

async function seedDemo() {
  const result = await demoSeed()
  message.value = result.message
  await refresh()
}

function openRegister() {
  registerForm.value = { page_id: '', page_type: '', page_version: '', source: '', resolved_text: '' }
  showRegister.value = true
}

async function submitRegister() {
  const resolved_fields: Record<string, unknown> = {}
  for (const line of registerForm.value.resolved_text.split('\n')) {
    const [key, ...rest] = line.split('=')
    if (key && rest.length) {
      resolved_fields[key.trim()] = rest.join('=').trim()
    }
  }
  const result = await registerPage({
    page_id: registerForm.value.page_id,
    page_type: registerForm.value.page_type,
    page_version: registerForm.value.page_version,
    source: registerForm.value.source,
    resolved_fields,
  })
  message.value = result.message
  showRegister.value = false
  await refresh()
}

async function confirm(pageId: string) {
  const result = await confirmPage(pageId)
  message.value = result.message
  await refresh()
}

function selectPage(pageId: string) {
  selectedPageId.value = pageId
  void refresh()
}

async function computeScope(recompute: boolean) {
  if (!selectedPageId.value) return
  const result = await computeScopeSet(selectedPageId.value, recompute)
  message.value = result.message
  await refresh()
}

async function cleanWithSelected() {
  if (!selectedPageId.value) return
  const result = await startCleaning({ page_id: selectedPageId.value })
  message.value = result.message
  await refresh()
}

async function cleanWithTemplate(templateId: number) {
  if (!selectedPageId.value) return
  const result = await startCleaning({
    page_id: selectedPageId.value,
    template_id: templateId,
  })
  message.value = result.message
  await refresh()
}

async function claim(taskId: string) {
  const result = await claimTask(taskId)
  message.value = result.message
  await refresh()
}

async function backfill(taskId: string) {
  const value = backfillValues.value[taskId]
  const result = await backfillTask(taskId, value)
  message.value = result.message
  await refresh()
}

onMounted(refresh)
</script>

<style scoped>
.section-title {
  margin: 20px 0 8px;
  font-size: 15px;
}

.section-actions {
  margin: 10px 0 4px;
}

.decision-tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 12px;
}

.decision-tag[data-decision='选中'] {
  background: #e6f7ec;
  color: #1a7f37;
}

.decision-tag[data-decision='不足'] {
  background: #fff4e5;
  color: #b26a00;
}

.decision-tag[data-decision='未用'] {
  background: #eef0f3;
  color: #57606a;
}

.decision-reason {
  display: block;
  color: #6b7280;
  margin-top: 2px;
}

.field-chip {
  display: inline-block;
  margin: 1px 4px 1px 0;
  padding: 1px 6px;
  background: #f3f6fb;
  border-radius: 8px;
  font-size: 12px;
}

.backfill-input {
  width: 110px;
  margin-right: 6px;
}
</style>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import {
  approveStrategyVersion,
  createStrategyVersion,
  deleteStrategyDraft,
  exportStrategyVersion,
  getResearchEntity,
  getStrategyBacktestCount,
  getStrategyVersions,
  listStrategies,
  saveStrategyDraft,
  validateStrategy,
} from "@/api/quant";
import { listArtifacts, listTasks } from "@/api/research";
import { useAuthStore } from "@/stores/auth";
import { formatChinaTime } from "@/time";
import { statusLabel } from "@/display";
import EntityPagination from "@/components/ui/EntityPagination.vue";
import AppStateBlock from "@/components/ui/AppStateBlock.vue";
import ManagementWorkspace from "@/components/layout/ManagementWorkspace.vue";
import { useUnsavedChanges } from "@/composables/useUnsavedChanges";

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();
const loading = ref(true);
const error = ref("");
const busy = ref("");
const artifacts = ref<Array<Record<string, unknown>>>([]);
const approvals = ref<Array<Record<string, unknown>>>([]);
const tasks = ref<Array<Record<string, unknown>>>([]);
const selected = ref<Record<string, unknown> | null>(null);
const detail = ref<Record<string, unknown> | null>(null);
const taskId = ref("");
const filter = ref<"all" | "draft" | "version">("all");
const lifecycle = ref<"active" | "superseded">("active");
const page = ref(1);
const total = ref(0);
const PAGE_SIZE = 50;
const search = ref("");
const script = ref("");
const strategyId = ref("CustomStrategy");
const strategyName = ref("自定义策略");
const description = ref("用户自定义策略");
const parametersJson = ref("{}");
const parameterSchemaJson = ref("{}");
const templateId = ref("");
const lastDraftId = ref("");
const saving = ref(false);
const versionHistory = ref<Array<Record<string, unknown>>>([]);
const backtestCount = ref(0);
const versionCount = ref(0);
const editorBaseline = ref("");

function editorState() {
  return JSON.stringify({
    taskId: taskId.value,
    strategyId: strategyId.value,
    strategyName: strategyName.value,
    description: description.value,
    parametersJson: parametersJson.value,
    parameterSchemaJson: parameterSchemaJson.value,
    script: script.value,
  });
}

function syncEditorBaseline() {
  editorBaseline.value = editorState();
}

const editorDirty = computed(() =>
  Boolean(editorBaseline.value)
  && selected.value?.kind !== "strategy_version"
  && editorState() !== editorBaseline.value,
);
const { confirmDiscard } = useUnsavedChanges(editorDirty);

const STRATEGY_TEMPLATES = [
  {
    id: "momentum",
    label: "动量轮动模板",
    script:
      "class CustomStrategy:\n" +
      '    """Momentum rotation skeleton. Signals: 1 buy, 0 hold, -1 sell."""\n' +
      "    def generate_signals(self, data, parameters=None):\n" +
      "        return {}\n",
  },
  {
    id: "ma_cross",
    label: "均线交叉模板",
    script:
      "class CustomStrategy:\n" +
      '    """Moving-average cross skeleton. Replace with a real indicator."""\n' +
      "    def generate_signals(self, data, parameters=None):\n" +
      "        return {}\n",
  },
];

function strategyPayload() {
  const parameters = JSON.parse(parametersJson.value || "{}") as unknown;
  const parameterSchema = JSON.parse(parameterSchemaJson.value || "{}") as unknown;
  if (!parameters || Array.isArray(parameters) || typeof parameters !== "object") {
    throw new Error("参数默认值必须是 JSON 对象");
  }
  if (!parameterSchema || Array.isArray(parameterSchema) || typeof parameterSchema !== "object") {
    throw new Error("参数规范必须是 JSON 对象");
  }
  return {
    strategy_id: strategyId.value,
    name: strategyName.value,
    category: "custom",
    description: description.value,
    parameters,
    parameter_schema: parameterSchema,
    source_type: "python_script",
    script: script.value,
  };
}

const SIGNAL_SNIPPET =
  "# 信号约定: 1 买入, 0 持有, -1 卖出\n" +
  "# signals[symbol] = 1 if close > ma20 else -1\n";

const filteredArtifacts = computed(() =>
  artifacts.value.filter((row) => {
    const matchesKind =
      filter.value === "all" ||
      (filter.value === "draft" && row.kind === "strategy_draft") ||
      (filter.value === "version" && row.kind === "strategy_version");
    const snapshot = (row.content as Record<string, unknown> | undefined)?.snapshot as Record<string, unknown> | undefined;
    const matchesSearch =
      !search.value ||
      String(row.artifact_id ?? "").includes(search.value) ||
      String(snapshot?.strategy_id ?? "").includes(search.value);
    return matchesKind && matchesSearch;
  }),
);

const approval = computed(() => {
  if (!selected.value) return null;
  const id = selected.value.artifact_id;
  const found = approvals.value.find((row) => {
    const content = row.content as Record<string, unknown> | undefined;
    return content?.strategy_version_artifact_id === id;
  });
  if (!found) return null;
  return (found.content as Record<string, unknown>) ?? null;
});

const isReadonly = computed(() => selected.value?.kind === "strategy_version");

const selectedStrategyId = computed(() => {
  const content = selected.value?.content as Record<string, unknown> | undefined;
  const snapshot = content?.snapshot as Record<string, unknown> | undefined;
  strategyId.value = String(snapshot?.strategy_id ?? "CustomStrategy");
  strategyName.value = String(snapshot?.name ?? "自定义策略");
  description.value = String(snapshot?.description ?? "");
  parametersJson.value = JSON.stringify(snapshot?.parameters ?? {}, null, 2);
  parameterSchemaJson.value = JSON.stringify(snapshot?.parameter_schema ?? {}, null, 2);
  return String(snapshot?.strategy_id ?? "");
});

async function loadList() {
  loading.value = true;
  error.value = "";
  try {
    const [strategyBody, taskBody, artifactBody] = await Promise.all([
      listStrategies(auth.token, {
        lifecycle: lifecycle.value,
        limit: PAGE_SIZE,
        offset: (page.value - 1) * PAGE_SIZE,
      }),
      listTasks(),
      listArtifacts(),
    ]);
    artifacts.value = strategyBody.strategies;
    total.value = strategyBody.total ?? artifacts.value.length;
    approvals.value = artifactBody.artifacts.filter((row) => row.kind === "strategy_approval");
    tasks.value = taskBody.tasks ?? [];
    if (tasks.value.length) {
      taskId.value = String(tasks.value[0].task_id ?? "");
    }
    const requested = typeof route.query.artifact === "string" ? route.query.artifact : "";
    const target = requested
      ? artifacts.value.find((row) => String(row.artifact_id) === requested)
      : selected.value
        ? artifacts.value.find((row) => row.artifact_id === selected.value?.artifact_id)
        : artifacts.value.find((row) => row.kind === "strategy_version") ?? artifacts.value[0];
    if (target) await select(target, false);
    else if (requested) await viewHistoryVersion({ artifact_id: requested });
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载失败";
  } finally {
    loading.value = false;
  }
}

async function changeLifecycle(value: "active" | "superseded") {
  if (!confirmDiscard()) return;
  lifecycle.value = value;
  page.value = 1;
  selected.value = null;
  detail.value = null;
  await loadList();
}

async function changePage(value: number) {
  if (!confirmDiscard()) return;
  page.value = value;
  selected.value = null;
  detail.value = null;
  await loadList();
}

async function select(row: Record<string, unknown>, updateRoute = true) {
  if (updateRoute && !confirmDiscard()) return;
  selected.value = row;
  detail.value = null;
  error.value = "";
  const content = row.content as Record<string, unknown> | undefined;
  const snapshot = content?.snapshot as Record<string, unknown> | undefined;
  if (row.kind === "strategy_draft") {
    script.value = String(snapshot?.script ?? "");
    lastDraftId.value = String(row.artifact_id ?? "");
  } else {
    script.value = String(snapshot?.script ?? "");
  }
  try {
    const id = String(row.artifact_id);
    detail.value = await getResearchEntity("artifacts", id, auth.token);
    await refreshStrategyMeta();
    syncEditorBaseline();
    if (updateRoute && route.query.artifact !== id) {
      await router.replace({ path: route.path, query: { ...route.query, artifact: id } });
    }
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "读取失败";
  }
}

async function refreshStrategyMeta() {
  const sid = selectedStrategyId.value;
  if (!sid) {
    versionHistory.value = [];
    backtestCount.value = 0;
    versionCount.value = 0;
    return;
  }
  try {
    const [history, counts] = await Promise.all([
      getStrategyVersions(sid, auth.token),
      getStrategyBacktestCount(sid, auth.token),
    ]);
    versionHistory.value = (history.versions ?? []) as Array<Record<string, unknown>>;
    backtestCount.value = Number(counts.backtest_count ?? 0);
    versionCount.value = Number(counts.version_count ?? 0);
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载策略统计失败";
  }
}

async function viewHistoryVersion(row: Record<string, unknown>) {
  const found = artifacts.value.find((item) => item.artifact_id === row.artifact_id);
  if (found) {
    await select(found);
    return;
  }
  if (!confirmDiscard()) return;
  try {
    const id = String(row.artifact_id);
    const entity = await getResearchEntity("artifacts", id, auth.token);
    selected.value = entity;
    detail.value = entity;
    const content = entity.content as Record<string, unknown> | undefined;
    const snapshot = content?.snapshot as Record<string, unknown> | undefined;
    script.value = String(snapshot?.script ?? "");
    lastDraftId.value = "";
    await refreshStrategyMeta();
    syncEditorBaseline();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "读取版本失败";
  }
}

async function saveDraft() {
  if (!script.value.trim()) {
    ElMessage.warning("请先编写策略脚本");
    return;
  }
  if (!taskId.value) {
    ElMessage.warning("请选择研究任务");
    return;
  }
  saving.value = true;
  error.value = "";
  try {
    const result = await saveStrategyDraft(
      {
        task_id: taskId.value,
        strategy: strategyPayload(),
        trace_id: `strategy-${crypto.randomUUID()}`,
        idempotency_key: crypto.randomUUID(),
      },
      auth.token,
    );
    lastDraftId.value = String((result as { artifact?: { artifact_id?: string } }).artifact?.artifact_id ?? "");
    syncEditorBaseline();
    ElMessage.success("草稿已保存");
    await loadList();
    const savedId = String((result as { artifact?: { artifact_id?: string } }).artifact?.artifact_id ?? "");
    const savedArtifact = artifacts.value.find((item) => item.artifact_id === savedId);
    if (savedArtifact) await select(savedArtifact);
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "保存草稿失败";
    ElMessage.error(error.value);
  } finally {
    saving.value = false;
  }
}

async function removeDraft() {
  if (!lastDraftId.value) {
    ElMessage.warning("没有可删除的草稿");
    return;
  }
  try {
    await deleteStrategyDraft(lastDraftId.value, auth.token);
    ElMessage.success("草稿已删除");
    lastDraftId.value = "";
    await loadList();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "删除草稿失败";
    ElMessage.error(error.value);
  }
}

function insertTemplate() {
  const template = STRATEGY_TEMPLATES.find((item) => item.id === templateId.value);
  if (template) {
    script.value = template.script;
  }
}

function insertSnippet() {
  script.value = script.value ? `${script.value}\n\n${SIGNAL_SNIPPET}` : SIGNAL_SNIPPET;
}

async function validateDraft() {
  if (!script.value.trim()) {
    ElMessage.warning("请先编写策略脚本");
    return;
  }
  if (!taskId.value) {
    ElMessage.warning("请选择研究任务");
    return;
  }
  busy.value = "validate";
  error.value = "";
  try {
    const result = await validateStrategy(
      {
        task_id: taskId.value,
        strategy: strategyPayload(),
        trace_id: `strategy-${crypto.randomUUID()}`,
        idempotency_key: crypto.randomUUID(),
      },
      auth.token,
    );
    detail.value = result as Record<string, unknown>;
    lastDraftId.value = String((result as { artifact?: { artifact_id?: string } }).artifact?.artifact_id ?? "");
    syncEditorBaseline();
    ElMessage.success("草稿验证通过，已保存为策略草稿");
    await loadList();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "验证失败";
    ElMessage.error(error.value);
  } finally {
    busy.value = "";
  }
}

async function createVersion() {
  if (!lastDraftId.value) {
    ElMessage.warning("请先保存并验证草稿");
    return;
  }
  if (!taskId.value) {
    ElMessage.warning("请选择研究任务");
    return;
  }
  busy.value = "version";
  error.value = "";
  try {
    const result = await createStrategyVersion(
      {
        task_id: taskId.value,
        draft_artifact_id: lastDraftId.value,
        trace_id: `strategy-${crypto.randomUUID()}`,
        idempotency_key: crypto.randomUUID(),
      },
      auth.token,
    );
    detail.value = result as Record<string, unknown>;
    ElMessage.success("已创建不可变策略版本");
    await loadList();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "创建版本失败";
    ElMessage.error(error.value);
  } finally {
    busy.value = "";
  }
}

async function exportVersion() {
  if (!selected.value) return;
  busy.value = "export";
  error.value = "";
  try {
    const result = await exportStrategyVersion(String(selected.value.artifact_id), auth.token);
    detail.value = result as Record<string, unknown>;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "导出失败";
  } finally {
    busy.value = "";
  }
}

async function approveVersion() {
  if (!selected.value || selected.value.kind !== "strategy_version") return;
  busy.value = "approval";
  error.value = "";
  try {
    await approveStrategyVersion(
      {
        task_id: selected.value.task_id,
        strategy_version_artifact_id: selected.value.artifact_id,
        decision: "approved",
        rationale: "策略所有者已在产品界面确认该不可变版本用于信号生成与回测。",
        trace_id: `strategy-approval-${crypto.randomUUID()}`,
        idempotency_key: crypto.randomUUID(),
      },
      auth.token,
    );
    ElMessage.success("策略版本已批准，可进入信号生成与回测");
    await loadList();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "批准失败";
    ElMessage.error(error.value);
  } finally {
    busy.value = "";
  }
}

function returnToConversation() {
  const session = typeof route.query.session === "string" ? route.query.session : "";
  void router.push({ path: "/agent", query: session ? { session } : {} });
}

async function refreshList() {
  if (confirmDiscard()) await loadList();
}

onMounted(loadList);
</script>

<template>
  <section class="strategy-page">
    <AppStateBlock :loading="loading" :error="!selected ? error : ''" @retry="loadList">
      <ManagementWorkspace
        eyebrow="核心研究资产"
        title="策略目录与版本谱系"
        description="从可编辑草稿推进到不可变版本、人工审批、信号快照与回测。"
        catalog-label="策略资产"
        :count="total"
        @return="returnToConversation"
      >
      <template #return>返回投研对话</template>
      <template #actions><el-button @click="refreshList">刷新目录</el-button></template>
      <template #summary>审批只授权精确的不可变版本</template>
      <template #catalog>
      <el-card shadow="never" class="strategy-list-pane">
        <template #header>
          <div class="card-heading">
            <span class="card-title">策略</span>
            <small class="card-sub">草稿与不可变版本</small>
          </div>
        </template>
        <div class="list-toolbar">
          <el-input v-model="search" placeholder="搜索 Artifact ID / 策略 ID" clearable />
          <el-radio-group :model-value="lifecycle" size="small" @update:model-value="changeLifecycle">
            <el-radio-button value="active">当前</el-radio-button>
            <el-radio-button value="superseded">已归档</el-radio-button>
          </el-radio-group>
          <el-radio-group v-model="filter" size="small">
            <el-radio-button value="all">全部</el-radio-button>
            <el-radio-button value="draft">草稿</el-radio-button>
            <el-radio-button value="version">版本</el-radio-button>
          </el-radio-group>
        </div>
        <el-empty v-if="!filteredArtifacts.length" description="暂无策略" />
        <el-table
          v-else
          class="desktop-catalog-table"
          :data="filteredArtifacts"
          highlight-current-row
          @current-change="select"
        >
          <el-table-column prop="artifact_id" label="Artifact ID" min-width="220" show-overflow-tooltip />
          <el-table-column prop="kind" label="类型" width="140" />
          <el-table-column label="状态" width="100"><template #default="{ row }">{{ statusLabel(row.status) }}</template></el-table-column>
          <el-table-column label="创建时间" min-width="170">
            <template #default="{ row }">{{ formatChinaTime(row.created_at) }}</template>
          </el-table-column>
        </el-table>

        <div class="mobile-list">
          <el-card
            v-for="row in filteredArtifacts"
            :key="String(row.artifact_id)"
            shadow="never"
            class="mobile-card"
            @click="select(row)"
          >
            <div class="mobile-card-head">
              <strong>{{ row.artifact_id }}</strong>
              <el-tag size="small">{{ row.kind === "strategy_version" ? "版本" : "草稿" }}</el-tag>
            </div>
            <div class="mobile-card-meta">
              <span>{{ statusLabel(row.status) }}</span>
              <span>{{ formatChinaTime(row.created_at) }}</span>
            </div>
          </el-card>
        </div>
        <EntityPagination
          :total="total"
          :page="page"
          :page-size="PAGE_SIZE"
          label="策略分页"
          @update:page="changePage"
        />
      </el-card>
      </template>

      <template #detail>
      <div class="strategy-detail-column">
        <el-card shadow="never" class="strategy-editor-pane">
          <template #header>
            <div class="panel-heading">
              <div>
                <div class="panel-title">策略编辑器</div>
                <div class="panel-sub">{{ isReadonly ? "版本只读" : "草稿可编辑" }}</div>
              </div>
              <div class="editor-actions">
                <el-select v-model="templateId" placeholder="选择模板" size="small" :disabled="isReadonly">
                  <el-option v-for="item in STRATEGY_TEMPLATES" :key="item.id" :label="item.label" :value="item.id" />
                </el-select>
                <el-button size="small" :disabled="isReadonly" @click="insertTemplate">插入模板</el-button>
                <el-button size="small" :disabled="isReadonly" @click="insertSnippet">插入信号片段</el-button>
              </div>
            </div>
          </template>
          <el-select v-model="taskId" placeholder="研究任务" class="task-select" :disabled="isReadonly">
            <el-option v-for="task in tasks" :key="String(task.task_id)" :label="String(task.task_id)" :value="String(task.task_id)" />
          </el-select>
          <div class="strategy-meta-grid">
            <el-input v-model="strategyId" placeholder="策略 ID" :disabled="isReadonly" />
            <el-input v-model="strategyName" placeholder="策略名称" :disabled="isReadonly" />
          </div>
          <el-input v-model="description" placeholder="策略说明" :disabled="isReadonly" class="strategy-description" />
          <div class="strategy-meta-grid">
            <el-input
              v-model="parametersJson"
              type="textarea"
              :rows="4"
              :disabled="isReadonly"
              spellcheck="false"
              placeholder="参数默认值 JSON，例如 {&quot;lookback&quot;: 20}"
            />
            <el-input
              v-model="parameterSchemaJson"
              type="textarea"
              :rows="4"
              :disabled="isReadonly"
              spellcheck="false"
              placeholder="参数规范 JSON"
            />
          </div>
          <el-input
            v-model="script"
            type="textarea"
            :rows="14"
            :disabled="isReadonly"
            spellcheck="false"
            placeholder="在这里编写 Python 策略脚本"
          />
          <div class="editor-actions">
            <el-button type="primary" :loading="busy === 'validate'" :disabled="isReadonly" @click="validateDraft">
              验证并保存草稿
            </el-button>
            <el-button :loading="saving" :disabled="isReadonly" @click="saveDraft">
              保存草稿
            </el-button>
            <el-button type="danger" plain :disabled="isReadonly || !lastDraftId" @click="removeDraft">
              删除草稿
            </el-button>
            <el-button :loading="busy === 'version'" :disabled="isReadonly" @click="createVersion">
              创建不可变版本
            </el-button>
          </div>
          <p v-if="!isReadonly" class="editor-save-state" aria-live="polite">{{ editorDirty ? "有未保存更改" : "编辑内容已保存" }}</p>
        </el-card>

        <el-card shadow="never" class="strategy-detail-pane">
          <template #header>
            <div class="panel-heading">
              <div>
                <div class="panel-title">策略详情</div>
                <div class="panel-sub">{{ selected?.artifact_id ?? "未选择策略" }}</div>
              </div>
              <el-button type="primary" :loading="busy === 'export'" :disabled="!selected || selected.kind !== 'strategy_version'" @click="exportVersion">
                导出版本
              </el-button>
              <el-button
                type="success"
                :loading="busy === 'approval'"
                :disabled="!selected || selected.kind !== 'strategy_version' || Boolean(approval)"
                @click="approveVersion"
              >
                {{ approval ? "已批准" : "批准此版本" }}
              </el-button>
            </div>
          </template>
          <div v-if="approval" class="approval-banner">
            <span>审批状态</span>
            <el-tag :type="approval.decision === 'approved' ? 'success' : 'danger'">
              {{ approval.decision === "approved" ? "已批准" : String(approval.decision ?? "-") }}
            </el-tag>
            <small>{{ approval.execution_authorized ? "已授权执行" : "未授权执行" }}</small>
          </div>
          <div v-if="selectedStrategyId" class="strategy-stats">
            <el-descriptions :column="3" size="small" border>
              <el-descriptions-item label="回测任务数">{{ backtestCount }}</el-descriptions-item>
              <el-descriptions-item label="版本数">{{ versionCount }}</el-descriptions-item>
              <el-descriptions-item label="策略 ID">{{ selectedStrategyId }}</el-descriptions-item>
            </el-descriptions>
          </div>
          <el-divider v-if="versionHistory.length" content-position="left">版本历史</el-divider>
          <el-table v-if="versionHistory.length" :data="versionHistory" size="small" highlight-current-row @current-change="viewHistoryVersion">
            <el-table-column prop="artifact_id" label="版本 Artifact" min-width="200" show-overflow-tooltip />
            <el-table-column prop="version_id" label="Version ID" min-width="160" show-overflow-tooltip />
            <el-table-column label="状态" width="100"><template #default="{ row }">{{ statusLabel(row.status) }}</template></el-table-column>
            <el-table-column label="创建时间" min-width="150">
              <template #default="{ row }">{{ formatChinaTime(row.created_at) }}</template>
            </el-table-column>
          </el-table>
          <p v-if="error" class="page-error">{{ error }}</p>
          <el-empty v-else-if="!detail" description="请选择左侧策略" />
          <pre v-else class="quant-result">{{ JSON.stringify(detail, null, 2) }}</pre>
        </el-card>
      </div>
      </template>
      </ManagementWorkspace>
    </AppStateBlock>
  </section>
</template>

<style scoped>
.list-toolbar {
  display: grid;
  gap: 0.6rem;
  grid-template-columns: 1fr;
  margin-bottom: 0.75rem;
}

.strategy-detail-column {
  display: grid;
  gap: 1rem;
  min-width: 0;
}

.panel-heading {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  justify-content: space-between;
}

.panel-title {
  font-size: 15px;
  font-weight: 700;
}

.panel-sub {
  color: var(--byq-text-muted);
  font-size: 12px;
  margin-top: 0.2rem;
}

.editor-save-state { color: var(--byq-text-muted); font-size: 12px; margin: 10px 0 0; text-align: right; }

.editor-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-top: 0.5rem;
}

.task-select {
  margin-bottom: 0.6rem;
  width: 100%;
}

.strategy-meta-grid {
  display: grid;
  gap: 0.6rem;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  margin-bottom: 0.6rem;
}

.strategy-description {
  margin-bottom: 0.6rem;
}

.strategy-stats {
  margin-bottom: 0.75rem;
}

.approval-banner {
  align-items: center;
  background: var(--byq-surface-subtle);
  border-radius: var(--byq-radius-sm);
  display: flex;
  gap: 0.75rem;
  margin-bottom: 0.75rem;
  padding: 0.6rem 0.75rem;
}

.approval-banner small {
  color: var(--byq-text-muted);
}

.quant-result {
  background: var(--byq-surface-subtle);
  border-radius: var(--byq-radius-sm);
  font-size: 12px;
  margin-top: 0.5rem;
  max-height: 420px;
  overflow: auto;
  padding: 0.75rem;
  white-space: pre-wrap;
}

.mobile-list {
  display: none;
}

@media (max-width: 900px) {
  .desktop-catalog-table {
    display: none;
  }

  .strategy-meta-grid {
    grid-template-columns: 1fr;
  }

  .mobile-list {
    display: grid;
    gap: 0.6rem;
    margin-top: 0.75rem;
  }

  .mobile-card {
    cursor: pointer;
  }

  .mobile-card-head {
    align-items: center;
    display: flex;
    gap: 0.5rem;
    justify-content: space-between;
    min-width: 0;
  }

  .mobile-card-head strong { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

  .mobile-card-meta {
    color: var(--byq-text-muted);
    display: flex;
    font-size: 12px;
    gap: 0.75rem;
    justify-content: space-between;
    margin-top: 0.4rem;
  }
}
</style>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { createTask, getApproval, getResearchEntity, listApprovals, listArtifacts, listTasks } from "@/api/research";
import { formatChinaTime } from "@/time";
import ListFilterPagination from "@/components/ui/ListFilterPagination.vue";
import { useFilteredPagination } from "@/composables/useFilteredPagination";

const tab = ref<"tasks" | "research" | "approval" | "assets" | "inbox">("tasks");
const entityType = ref<"tasks" | "experiments" | "artifacts">("artifacts");
const entityId = ref("");
const approvalId = ref("");
const result = ref<Record<string, unknown> | null>(null);
const error = ref("");
const busy = ref(false);
const artifacts = ref<Array<Record<string, unknown>>>([]);
const approvals = ref<Array<Record<string, unknown>>>([]);
const tasks = ref<Array<Record<string, unknown>>>([]);
const taskTitle = ref("");
const taskObjective = ref("");
const taskPages = useFilteredPagination(computed(() => tasks.value), (row) => `${row.title ?? ""} ${row.objective ?? ""} ${row.status ?? ""}`, 20);
const artifactPages = useFilteredPagination(computed(() => artifacts.value), (row) => `${row.kind ?? ""} ${row.artifact_id ?? ""} ${row.status ?? ""}`, 20);
const approvalPages = useFilteredPagination(computed(() => approvals.value), (row) => `${row.approval_id ?? ""} ${row.action ?? ""} ${row.status ?? ""}`, 20);

async function loadTasks() {
  busy.value = true;
  error.value = "";
  try {
    tasks.value = (await listTasks()).tasks;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载失败";
  } finally {
    busy.value = false;
  }
}

async function submitTask() {
  if (!taskTitle.value.trim() || !taskObjective.value.trim()) {
    error.value = "请填写任务名称和研究目标";
    return;
  }
  busy.value = true;
  error.value = "";
  try {
    await createTask(taskTitle.value.trim(), taskObjective.value.trim());
    taskTitle.value = "";
    taskObjective.value = "";
    await loadTasks();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "创建失败";
  } finally {
    busy.value = false;
  }
}

async function loadAssets() {
  busy.value = true;
  error.value = "";
  try {
    artifacts.value = (await listArtifacts()).artifacts;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载失败";
  } finally {
    busy.value = false;
  }
}

async function loadInbox() {
  busy.value = true;
  error.value = "";
  try {
    approvals.value = (await listApprovals()).approvals;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载失败";
  } finally {
    busy.value = false;
  }
}

async function loadEntity() {
  busy.value = true;
  error.value = "";
  try {
    result.value = await getResearchEntity(entityType.value, entityId.value);
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载失败";
  } finally {
    busy.value = false;
  }
}

async function loadApproval() {
  busy.value = true;
  error.value = "";
  try {
    result.value = await getApproval(approvalId.value);
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载失败";
  } finally {
    busy.value = false;
  }
}

onMounted(async () => {
  await Promise.allSettled([loadTasks(), loadAssets(), loadInbox()]);
});
</script>

<template>
  <section class="research-page">
    <el-card shadow="never" class="top-band">
      <el-tabs v-model="tab">
        <el-tab-pane label="研究任务" name="tasks" lazy>
          <div class="quant-panel">
            <el-input v-model="taskTitle" placeholder="任务名称" maxlength="200" style="width: 240px" />
            <el-input v-model="taskObjective" placeholder="研究目标" maxlength="4000" style="width: 420px" />
            <el-button type="primary" :loading="busy" @click="submitTask">创建任务</el-button>
          </div>
          <ListFilterPagination v-model:query="taskPages.query.value" v-model:page="taskPages.page.value" :page-size="taskPages.pageSize.value" :total="taskPages.total.value" placeholder="筛选任务名称、目标或状态" label="研究任务分页">
          <el-table :data="taskPages.pageItems.value" v-loading="busy">
            <el-table-column prop="title" label="任务名称" min-width="180" />
            <el-table-column prop="objective" label="研究目标" min-width="300" show-overflow-tooltip />
            <el-table-column prop="status" label="状态" width="120" />
            <el-table-column prop="task_id" label="Task ID" min-width="260" show-overflow-tooltip />
          </el-table>
          </ListFilterPagination>
          <el-empty v-if="!tasks.length && !busy" description="暂无研究任务，请先创建一个任务" />
        </el-tab-pane>

        <el-tab-pane label="研究资产" name="assets" lazy>
          <ListFilterPagination v-model:query="artifactPages.query.value" v-model:page="artifactPages.page.value" :page-size="artifactPages.pageSize.value" :total="artifactPages.total.value" placeholder="筛选资产类型、编号或状态" label="研究资产分页">
          <el-table :data="artifactPages.pageItems.value" v-loading="busy">
            <el-table-column label="类型" width="150">
              <template #default="{ row }">
                <el-tag effect="light">{{ row.kind }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="artifact_id" label="Artifact ID" min-width="260" show-overflow-tooltip />
            <el-table-column prop="status" label="状态" width="120" />
            <el-table-column label="创建时间" min-width="190">
              <template #default="{ row }">{{ formatChinaTime(row.created_at) }}</template>
            </el-table-column>
          </el-table>
          </ListFilterPagination>
          <el-empty v-if="!artifacts.length && !busy" description="暂无研究资产" />
        </el-tab-pane>

        <el-tab-pane label="审批收件箱" name="inbox" lazy>
          <ListFilterPagination v-model:query="approvalPages.query.value" v-model:page="approvalPages.page.value" :page-size="approvalPages.pageSize.value" :total="approvalPages.total.value" placeholder="筛选审批编号、动作或状态" label="审批记录分页">
          <el-table :data="approvalPages.pageItems.value" v-loading="busy">
            <el-table-column prop="approval_id" label="Approval ID" min-width="260" show-overflow-tooltip />
            <el-table-column prop="action" label="动作" width="180" />
            <el-table-column prop="status" label="状态" width="120" />
          </el-table>
          </ListFilterPagination>
          <el-empty v-if="!approvals.length && !busy" description="暂无待处理审批" />
        </el-tab-pane>

        <el-tab-pane label="实体查询" name="research" lazy>
          <div class="quant-panel">
            <el-select v-model="entityType" style="width: 180px">
              <el-option label="Task" value="tasks" />
              <el-option label="Experiment" value="experiments" />
              <el-option label="Artifact" value="artifacts" />
            </el-select>
            <el-input v-model="entityId" placeholder="Entity ID" style="width: 320px" />
            <el-button type="primary" :loading="busy" @click="loadEntity">查看</el-button>
          </div>
          <pre v-if="result" class="quant-result">{{ JSON.stringify(result, null, 2) }}</pre>
        </el-tab-pane>

        <el-tab-pane label="审批查询" name="approval" lazy>
          <div class="quant-panel">
            <el-input v-model="approvalId" placeholder="Approval ID" style="width: 320px" />
            <el-button type="primary" :loading="busy" @click="loadApproval">查看</el-button>
          </div>
          <pre v-if="result" class="quant-result">{{ JSON.stringify(result, null, 2) }}</pre>
        </el-tab-pane>
      </el-tabs>

      <p v-if="error" class="page-error">{{ error }}</p>
    </el-card>
  </section>
</template>

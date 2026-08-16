<script setup lang="ts">
import { onMounted, ref } from "vue";
import { getApproval, getResearchEntity, listApprovals, listArtifacts } from "@/api/research";

const tab = ref<"research" | "approval" | "assets" | "inbox">("assets");
const entityType = ref<"tasks" | "experiments" | "artifacts">("artifacts");
const entityId = ref("");
const approvalId = ref("");
const result = ref<Record<string, unknown> | null>(null);
const error = ref("");
const busy = ref(false);
const artifacts = ref<Array<Record<string, unknown>>>([]);
const approvals = ref<Array<Record<string, unknown>>>([]);

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
  await Promise.allSettled([loadAssets(), loadInbox()]);
});
</script>

<template>
  <section class="research-page">
    <el-card shadow="never" class="top-band">
      <el-tabs v-model="tab">
        <el-tab-pane label="研究资产" name="assets">
          <el-table :data="artifacts" v-loading="busy">
            <el-table-column label="类型" width="150">
              <template #default="{ row }">
                <el-tag effect="light">{{ row.kind }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="artifact_id" label="Artifact ID" min-width="260" show-overflow-tooltip />
            <el-table-column prop="status" label="状态" width="120" />
            <el-table-column prop="created_at" label="创建时间" min-width="190" />
          </el-table>
          <el-empty v-if="!artifacts.length && !busy" description="暂无研究资产" />
        </el-tab-pane>

        <el-tab-pane label="审批收件箱" name="inbox">
          <el-table :data="approvals" v-loading="busy">
            <el-table-column prop="approval_id" label="Approval ID" min-width="260" show-overflow-tooltip />
            <el-table-column prop="action" label="动作" width="180" />
            <el-table-column prop="status" label="状态" width="120" />
          </el-table>
          <el-empty v-if="!approvals.length && !busy" description="暂无待处理审批" />
        </el-tab-pane>

        <el-tab-pane label="实体查询" name="research">
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

        <el-tab-pane label="审批查询" name="approval">
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

<script setup lang="ts">
import { ref } from "vue";
import { getApproval, getResearchEntity, listApprovals, listArtifacts } from "@/api/research";
import BaseCard from "@/components/ui/BaseCard.vue";
import BaseError from "@/components/ui/BaseError.vue";

const tab = ref<"research" | "approval" | "assets" | "inbox">("research");
const entityType = ref<"tasks" | "experiments" | "artifacts">("tasks");
const entityId = ref("");
const approvalId = ref("");
const result = ref<Record<string, unknown> | null>(null);
const error = ref("");
const busy = ref(false);
const artifacts = ref<Array<Record<string, unknown>>>([]);
const approvals = ref<Array<Record<string, unknown>>>([]);

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
</script>

<template>
  <section class="page-card">
    <h2>Research / Approval Center</h2>
    <div class="research-tabs">
      <button type="button" :class="{ active: tab === 'research' }" @click="tab = 'research'">Research</button>
      <button type="button" :class="{ active: tab === 'approval' }" @click="tab = 'approval'">Approval</button>
      <button type="button" :class="{ active: tab === 'assets' }" @click="tab = 'assets'; loadAssets()">Assets</button>
      <button type="button" :class="{ active: tab === 'inbox' }" @click="tab = 'inbox'; loadInbox()">Inbox</button>
    </div>

    <div v-if="tab === 'research'" class="research-form">
      <select v-model="entityType">
        <option value="tasks">Task</option>
        <option value="experiments">Experiment</option>
        <option value="artifacts">Artifact</option>
      </select>
      <input v-model="entityId" placeholder="Entity ID" />
      <button type="button" :disabled="busy" @click="loadEntity">查看</button>
    </div>
    <div v-else-if="tab === 'approval'" class="research-form">
      <input v-model="approvalId" placeholder="Approval ID" />
      <button type="button" :disabled="busy" @click="loadApproval">查看</button>
    </div>
    <div v-else-if="tab === 'assets'" class="research-form">
      <button type="button" :disabled="busy" @click="loadAssets">刷新 Artifacts</button>
    </div>
    <div v-else class="research-form">
      <button type="button" :disabled="busy" @click="loadInbox">刷新 Approvals</button>
    </div>

    <BaseError v-if="error" :message="error" />
    <BaseCard v-else-if="result" title="结果">
      <pre class="quant-result">{{ JSON.stringify(result, null, 2) }}</pre>
    </BaseCard>
    <BaseCard v-else-if="tab === 'assets'" title="Artifacts">
      <ul>
        <li v-for="artifact in artifacts" :key="String(artifact.artifact_id)">
          {{ artifact.kind }} - {{ artifact.status }} - {{ artifact.artifact_id }}
        </li>
      </ul>
    </BaseCard>
    <BaseCard v-else-if="tab === 'inbox'" title="Approvals">
      <ul>
        <li v-for="approval in approvals" :key="String(approval.approval_id)">
          {{ approval.action }} - {{ approval.status }} - {{ approval.approval_id }}
        </li>
      </ul>
    </BaseCard>
  </section>
</template>

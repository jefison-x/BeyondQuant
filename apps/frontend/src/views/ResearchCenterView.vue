<script setup lang="ts">
import { ref } from "vue";
import { getApproval, getResearchEntity } from "@/api/research";
import BaseCard from "@/components/ui/BaseCard.vue";
import BaseError from "@/components/ui/BaseError.vue";

const tab = ref<"research" | "approval">("research");
const entityType = ref<"tasks" | "experiments" | "artifacts">("tasks");
const entityId = ref("");
const approvalId = ref("");
const result = ref<Record<string, unknown> | null>(null);
const error = ref("");
const busy = ref(false);

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
</script>

<template>
  <section class="page-card">
    <h2>Research / Approval Center</h2>
    <div class="research-tabs">
      <button type="button" :class="{ active: tab === 'research' }" @click="tab = 'research'">Research</button>
      <button type="button" :class="{ active: tab === 'approval' }" @click="tab = 'approval'">Approval</button>
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
    <div v-else class="research-form">
      <input v-model="approvalId" placeholder="Approval ID" />
      <button type="button" :disabled="busy" @click="loadApproval">查看</button>
    </div>

    <BaseError v-if="error" :message="error" />
    <BaseCard v-else-if="result" title="结果">
      <pre class="quant-result">{{ JSON.stringify(result, null, 2) }}</pre>
    </BaseCard>
  </section>
</template>

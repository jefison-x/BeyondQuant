<script setup lang="ts">
import { computed } from "vue";
import type { OperationsStatus } from "@/api/types";
import ListFilterPagination from "@/components/ui/ListFilterPagination.vue";
import { useFilteredPagination } from "@/composables/useFilteredPagination";

const props = withDefaults(defineProps<{ data: OperationsStatus; mode?: "all" | "access" | "audit" }>(), {
  mode: "all",
});
const operationsAudit = computed(() => props.data.access.operations_audit);
const agentAudit = computed(() => props.data.access.agent_audit);
const operationsPages = useFilteredPagination(operationsAudit, (entry) => `${entry.actor_principal} ${entry.action} ${entry.outcome}`, 15);
const agentPages = useFilteredPagination(agentAudit, (entry) => `${entry.actor_principal} ${entry.action} ${entry.outcome} ${entry.resource_type}`, 15);
</script>

<template>
  <div class="ops-workbench">
    <div v-if="mode !== 'audit'" class="ops-metrics">
      <el-card v-for="group in data.access.principal_groups" :key="`${group.role}-${group.status}`" shadow="never">
        <span>{{ group.role }} · {{ group.status }}</span><strong>{{ group.count }}</strong><small>durable BYQ identity</small>
      </el-card>
    </div>
    <template v-if="mode !== 'access'">
      <el-card shadow="never">
        <template #header><strong>运维写操作审计</strong></template>
        <ListFilterPagination v-if="data.access.operations_audit.length" v-model:query="operationsPages.query.value" v-model:page="operationsPages.page.value" :page-size="operationsPages.pageSize.value" :total="operationsPages.total.value" placeholder="筛选操作者、动作或结果" label="运维审计分页">
        <div class="audit-table-scroll">
          <table>
            <caption>运维写操作审计记录</caption>
            <thead><tr><th scope="col">时间</th><th scope="col">操作者</th><th scope="col">动作</th><th scope="col">结果</th></tr></thead>
            <tbody>
              <tr v-for="entry in operationsPages.pageItems.value" :key="`${entry.created_at}-${entry.action}`">
                <td>{{ entry.created_at }}</td><td>{{ entry.actor_principal }}</td><td>{{ entry.action }}</td><td>{{ entry.outcome }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        </ListFilterPagination>
        <p v-else class="audit-empty">暂无运维写操作</p>
      </el-card>
      <el-card shadow="never">
        <template #header><strong>Agent 领域访问审计</strong></template>
        <ListFilterPagination v-if="data.access.agent_audit.length" v-model:query="agentPages.query.value" v-model:page="agentPages.page.value" :page-size="agentPages.pageSize.value" :total="agentPages.total.value" placeholder="筛选操作者、动作、结果或资源" label="Agent 审计分页">
        <div class="audit-table-scroll">
          <table>
            <caption>Agent 领域访问审计记录</caption>
            <thead><tr><th scope="col">时间</th><th scope="col">操作者</th><th scope="col">动作</th><th scope="col">结果</th><th scope="col">资源</th></tr></thead>
            <tbody>
              <tr v-for="entry in agentPages.pageItems.value" :key="`${entry.created_at}-${entry.action}`">
                <td>{{ entry.created_at }}</td><td>{{ entry.actor_principal }}</td><td>{{ entry.action }}</td><td>{{ entry.outcome }}</td><td>{{ entry.resource_type }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        </ListFilterPagination>
        <p v-else class="audit-empty">暂无 Agent 访问审计</p>
      </el-card>
    </template>
  </div>
</template>

<style scoped>
.audit-table-scroll { max-height: 360px; overflow: auto; }
table { border-collapse: collapse; min-width: 760px; width: 100%; }
caption { height: 1px; margin: -1px; overflow: hidden; padding: 0; position: absolute; width: 1px; clip: rect(0 0 0 0); white-space: nowrap; }
th, td { border-bottom: 1px solid var(--byq-border); padding: 10px 12px; text-align: left; vertical-align: top; }
th { background: var(--byq-surface-subtle); color: var(--byq-text-muted); font-size: 12px; font-weight: 750; position: sticky; top: 0; }
td { color: var(--byq-text); font-size: 12px; overflow-wrap: anywhere; }
.audit-empty { color: var(--byq-text-muted); font-size: 13px; margin: 0; padding: 28px 12px; text-align: center; }
</style>

<script setup lang="ts">
import type { OperationsStatus } from "@/api/types";

withDefaults(defineProps<{ data: OperationsStatus; mode?: "all" | "access" | "audit" }>(), {
  mode: "all",
});
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
        <div v-if="data.access.operations_audit.length" class="audit-table-scroll">
          <table>
            <caption>运维写操作审计记录</caption>
            <thead><tr><th scope="col">时间</th><th scope="col">操作者</th><th scope="col">动作</th><th scope="col">结果</th></tr></thead>
            <tbody>
              <tr v-for="entry in data.access.operations_audit" :key="`${entry.created_at}-${entry.action}`">
                <td>{{ entry.created_at }}</td><td>{{ entry.actor_principal }}</td><td>{{ entry.action }}</td><td>{{ entry.outcome }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="audit-empty">暂无运维写操作</p>
      </el-card>
      <el-card shadow="never">
        <template #header><strong>Agent 领域访问审计</strong></template>
        <div v-if="data.access.agent_audit.length" class="audit-table-scroll">
          <table>
            <caption>Agent 领域访问审计记录</caption>
            <thead><tr><th scope="col">时间</th><th scope="col">操作者</th><th scope="col">动作</th><th scope="col">结果</th><th scope="col">资源</th></tr></thead>
            <tbody>
              <tr v-for="entry in data.access.agent_audit" :key="`${entry.created_at}-${entry.action}`">
                <td>{{ entry.created_at }}</td><td>{{ entry.actor_principal }}</td><td>{{ entry.action }}</td><td>{{ entry.outcome }}</td><td>{{ entry.resource_type }}</td>
              </tr>
            </tbody>
          </table>
        </div>
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

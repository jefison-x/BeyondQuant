<script setup lang="ts">
import { onMounted, ref } from "vue";
import { getAgentPolicyStatus, updateAgentPolicy } from "@/api/settings";
import { listApprovals } from "@/api/research";
import type { AgentPolicyStatus } from "@/api/types";

const loading = ref(true);
const error = ref("");
const policy = ref<AgentPolicyStatus | null>(null);
const approvals = ref<Array<Record<string, unknown>>>([]);
const saving = ref(false);
const personal = ref<AgentPolicyStatus["personal_policy"]>({
  automation_enabled: false,
  paused: false,
  default_decision_mode: "manual",
  max_auto_executions_per_hour: 20,
  max_auto_failures_per_hour: 3,
});

onMounted(async () => {
  try {
    const [policyBody, approvalBody] = await Promise.all([getAgentPolicyStatus(), listApprovals()]);
    policy.value = policyBody;
    personal.value = { ...personal.value, ...(policyBody.personal_policy ?? {}) };
    approvals.value = approvalBody.approvals ?? [];
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载智能体策略失败";
  } finally {
    loading.value = false;
  }
});

async function savePersonal() {
  saving.value = true;
  try {
    const { owner_principal: _owner, ...payload } = personal.value;
    const body = await updateAgentPolicy(payload);
    personal.value = { ...personal.value, ...body.personal_policy };
    const policyBody = await getAgentPolicyStatus();
    policy.value = policyBody;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "保存审批偏好失败";
  } finally {
    saving.value = false;
  }
}

const STATUS_LABELS: Record<string, string> = {
  pending: "待审批",
  approved: "已批准",
  denied: "已拒绝",
  executed: "已执行",
  failed: "失败",
};

function statusLabel(value: unknown) {
  return STATUS_LABELS[String(value)] ?? (typeof value === "string" ? value : "-");
}
</script>

<template>
  <section class="my-space-page">
    <el-alert
      title="平台规则优先"
      description="你可以查看个人审批偏好和自动化规则；平台强制人工确认、自动拒绝、暂停和关闭自动审批的设置不可被个人配置绕过。"
      type="info"
      show-icon
      :closable="false"
    />

    <div v-if="loading" class="base-loading">加载中...</div>
    <div v-else-if="error" class="base-error">{{ error }}</div>
    <template v-else>
      <el-card shadow="never">
        <template #header><div><strong>我的审批偏好</strong><p class="muted">平台默认策略，当前账号不覆盖自动审批。</p></div></template>
        <div class="settings-grid">
          <div class="setting-item"><span>启用个人自动审批</span><el-tag :type="policy?.platform_policy.automation_enabled ? 'success' : 'info'">{{ policy?.platform_policy.automation_enabled ? "启用" : "停用" }}</el-tag></div>
          <div class="setting-item"><span>个人暂停自动审批</span><el-tag :type="policy?.platform_policy.paused ? 'warning' : 'info'">{{ policy?.platform_policy.paused ? "已暂停" : "未暂停" }}</el-tag></div>
          <div class="setting-item"><span>无匹配规则</span><el-tag type="info">{{ policy?.platform_policy.default_decision_mode === "manual" ? "转人工审批" : policy?.platform_policy.default_decision_mode }}</el-tag></div>
          <div class="setting-item"><span>每小时自动执行上限</span><strong>{{ policy?.platform_policy.max_auto_executions_per_hour }}</strong></div>
          <div class="setting-item"><span>每小时失败熔断</span><strong>{{ policy?.platform_policy.max_auto_failures_per_hour }}</strong></div>
          <div class="setting-item"><span>待处理审批</span><strong>{{ policy?.approval_inbox.pending }}</strong></div>
        </div>
      </el-card>

      <el-card shadow="never">
        <template #header>
          <div class="card-header">
            <div><strong>个人审批偏好</strong><p class="muted">仅影响当前账号发起的智能体操作。</p></div>
            <el-button type="primary" :loading="saving" @click="savePersonal">保存</el-button>
          </div>
        </template>
        <div class="settings-grid">
          <div class="setting-item"><span>启用个人自动审批</span><el-switch v-model="personal.automation_enabled" /></div>
          <div class="setting-item"><span>个人暂停自动审批</span><el-switch v-model="personal.paused" /></div>
          <div class="setting-item">
            <span>无匹配规则</span>
            <el-select v-model="personal.default_decision_mode" size="small">
              <el-option label="转人工审批" value="manual" />
              <el-option label="自动批准" value="auto_approve" />
              <el-option label="自动拒绝" value="auto_deny" />
            </el-select>
          </div>
          <div class="setting-item"><span>每小时自动执行上限</span><el-input-number v-model="personal.max_auto_executions_per_hour" :min="1" :max="1000" size="small" /></div>
          <div class="setting-item"><span>每小时失败熔断</span><el-input-number v-model="personal.max_auto_failures_per_hour" :min="1" :max="100" size="small" /></div>
        </div>
      </el-card>

      <el-card shadow="never">
        <template #header><div><strong>我的审批历史</strong><p class="muted">只展示当前账号的审批请求和执行结果。</p></div></template>
        <el-table :data="approvals" size="small" empty-text="暂无审批记录">
          <el-table-column label="操作" min-width="170">
            <template #default="scope"><strong>{{ scope.row.action }}</strong></template>
          </el-table-column>
          <el-table-column label="处理方式" width="120">
            <template #default="scope"><el-tag size="small">{{ scope.row.decision_reason || scope.row.status || "-" }}</el-tag></template>
          </el-table-column>
          <el-table-column label="状态" width="110">
            <template #default="scope">{{ statusLabel(scope.row.status) }}</template>
          </el-table-column>
          <el-table-column label="执行结果" min-width="160" show-overflow-tooltip prop="execution_outcome" />
          <el-table-column label="时间" width="170">
            <template #default="scope">{{ scope.row.created_at }}</template>
          </el-table-column>
        </el-table>
      </el-card>
    </template>
  </section>
</template>

<style scoped>
.my-space-page {
  display: grid;
  gap: 1rem;
  min-width: 0;
}

.muted {
  color: var(--byq-text-muted);
  font-size: 12px;
  margin: 0.3rem 0 0;
}

.card-header {
  align-items: center;
  display: flex;
  gap: 1rem;
  justify-content: space-between;
}

.settings-grid {
  display: grid;
  gap: 0.8rem;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.setting-item {
  align-items: center;
  background: var(--byq-surface-subtle);
  border-radius: var(--byq-radius-sm);
  display: flex;
  gap: 0.75rem;
  justify-content: space-between;
  min-height: 44px;
  padding: 0.55rem 0.7rem;
}

@media (max-width: 900px) {
  .settings-grid {
    grid-template-columns: 1fr;
  }
}
</style>

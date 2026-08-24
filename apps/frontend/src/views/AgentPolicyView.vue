<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { applyAgentPolicyPreset, createAgentPolicyRule, deleteAgentPolicyRule, getAgentPolicyStatus, updateAgentPolicy, updateAgentPolicyRule } from "@/api/settings";
import { listApprovals } from "@/api/research";
import type { AgentPolicyRule, AgentPolicyStatus } from "@/api/types";

const loading = ref(true);
const error = ref("");
const policy = ref<AgentPolicyStatus | null>(null);
const approvals = ref<Array<Record<string, unknown>>>([]);
const saving = ref(false);
const ruleDialog = ref(false);
const editingRule = ref<AgentPolicyRule | null>(null);
const ruleForm = reactive({ name: "", description: "", action: "byq_backtest_submit", agent_id: "*", decision_mode: "manual", risk_level: "medium", priority: 100, enabled: true });
const personal = ref<AgentPolicyStatus["personal_policy"]>({
  automation_enabled: false,
  paused: false,
  default_decision_mode: "manual",
  max_auto_executions_per_hour: 20,
  max_auto_failures_per_hour: 3,
});

async function load() {
  loading.value = true;
  error.value = "";
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
}

onMounted(load);

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

async function applyPreset(presetId: string) {
  try {
    await ElMessageBox.confirm("应用预设会替换当前个人规则。", "应用策略预设", { type: "warning" });
    await applyAgentPolicyPreset(presetId);
    ElMessage.success("策略预设已应用");
    await load();
  } catch (exc) { if (exc !== "cancel" && exc !== "close") ElMessage.error(exc instanceof Error ? exc.message : "应用预设失败"); }
}

function openRule(item: AgentPolicyRule | null = null) {
  editingRule.value = item;
  Object.assign(ruleForm, item ? {
    name: item.name, description: item.description, action: item.action, agent_id: item.agent_id,
    decision_mode: item.decision_mode, risk_level: item.risk_level, priority: item.priority, enabled: item.enabled,
  } : { name: "", description: "", action: "byq_backtest_submit", agent_id: "*", decision_mode: "manual", risk_level: "medium", priority: 100, enabled: true });
  ruleDialog.value = true;
}

async function saveRule() {
  if (!ruleForm.name.trim()) return ElMessage.warning("请输入规则名称");
  saving.value = true;
  try {
    if (editingRule.value) await updateAgentPolicyRule(editingRule.value.rule_id, { ...ruleForm, expected_version: editingRule.value.version });
    else await createAgentPolicyRule({ ...ruleForm });
    ruleDialog.value = false;
    ElMessage.success(editingRule.value ? "规则已更新" : "规则已创建");
    await load();
  } catch (exc) { ElMessage.error(exc instanceof Error ? exc.message : "保存规则失败"); }
  finally { saving.value = false; }
}

async function removeRule(item: AgentPolicyRule) {
  try {
    await ElMessageBox.confirm(`删除规则“${item.name}”？`, "删除规则", { type: "warning" });
    await deleteAgentPolicyRule(item.rule_id, item.version);
    await load();
  } catch (exc) { if (exc !== "cancel" && exc !== "close") ElMessage.error(exc instanceof Error ? exc.message : "删除失败"); }
}

const DECISION_LABELS: Record<string, string> = { manual: "人工审批", auto_approve: "自动批准（受平台门禁约束）", auto_deny: "自动拒绝" };

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

    <div v-if="loading" class="base-loading" role="status" aria-live="polite">加载中...</div>
    <div v-else-if="error" class="base-error" role="alert">{{ error }}</div>
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
        <template #header><div><strong>策略预设</strong><p class="muted">预设只包含 BYQ 支持的 Agent 与动作；应用前会明确确认。</p></div></template>
        <div class="preset-grid">
          <div v-for="preset in policy?.presets" :key="preset.preset_id" class="preset-card">
            <div><strong>{{ preset.name }}</strong><p class="muted">{{ preset.description }}</p></div>
            <el-button @click="applyPreset(preset.preset_id)">应用</el-button>
          </div>
        </div>
      </el-card>

      <el-card shadow="never">
        <template #header><div class="card-header"><div><strong>个人规则</strong><p class="muted">按优先级匹配。个人自动批准不能绕过平台人工审批边界。</p></div><el-button type="primary" @click="openRule()">新建规则</el-button></div></template>
        <el-table :data="policy?.rules ?? []" size="small" empty-text="暂无个人规则">
          <el-table-column prop="priority" label="优先级" width="80" />
          <el-table-column prop="name" label="规则" min-width="150" />
          <el-table-column prop="action" label="动作" min-width="170" />
          <el-table-column prop="agent_id" label="Agent" min-width="150" />
          <el-table-column label="决策" min-width="180"><template #default="scope"><el-tag :type="scope.row.decision_mode === 'auto_deny' ? 'danger' : 'info'">{{ DECISION_LABELS[scope.row.decision_mode] }}</el-tag></template></el-table-column>
          <el-table-column label="启用" width="75"><template #default="scope">{{ scope.row.enabled ? "是" : "否" }}</template></el-table-column>
          <el-table-column label="操作" width="130"><template #default="scope"><el-button link type="primary" @click="openRule(scope.row)">编辑</el-button><el-button link type="danger" @click="removeRule(scope.row)">删除</el-button></template></el-table-column>
        </el-table>
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
        <template #header><div><strong>规则变更历史</strong><p class="muted">规则和预设变更保留所有者、动作与时间证据。</p></div></template>
        <el-table :data="policy?.audit ?? []" size="small" empty-text="暂无规则变更">
          <el-table-column prop="action" label="动作" min-width="150" />
          <el-table-column prop="resource_id" label="资源" min-width="200" show-overflow-tooltip />
          <el-table-column prop="actor_principal" label="操作者" min-width="140" />
          <el-table-column prop="created_at" label="时间" min-width="180" />
        </el-table>
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

    <el-dialog v-model="ruleDialog" :title="editingRule ? '编辑个人规则' : '新建个人规则'" width="min(620px, 94vw)" destroy-on-close>
      <el-form label-position="top">
        <el-form-item label="名称"><el-input v-model="ruleForm.name" maxlength="120" /></el-form-item>
        <el-form-item label="说明"><el-input v-model="ruleForm.description" type="textarea" maxlength="500" /></el-form-item>
        <div class="form-grid"><el-form-item label="动作"><el-select v-model="ruleForm.action"><el-option label="提交回测" value="byq_backtest_submit" /><el-option label="执行回测" value="byq_backtest_run" /></el-select></el-form-item><el-form-item label="Agent"><el-select v-model="ruleForm.agent_id"><el-option label="所有支持的 Agent" value="*" /><el-option label="首席量化研究员" value="chief_quant_researcher" /><el-option label="策略研究员" value="strategy_researcher" /></el-select></el-form-item></div>
        <div class="form-grid"><el-form-item label="决策"><el-select v-model="ruleForm.decision_mode"><el-option label="人工审批" value="manual" /><el-option label="自动批准（受平台门禁约束）" value="auto_approve" /><el-option label="自动拒绝" value="auto_deny" /></el-select></el-form-item><el-form-item label="风险"><el-select v-model="ruleForm.risk_level"><el-option label="低" value="low" /><el-option label="中" value="medium" /><el-option label="高" value="high" /><el-option label="关键" value="critical" /></el-select></el-form-item></div>
        <div class="form-grid"><el-form-item label="优先级"><el-input-number v-model="ruleForm.priority" :min="1" :max="10000" /></el-form-item><el-form-item label="启用"><el-switch v-model="ruleForm.enabled" /></el-form-item></div>
      </el-form>
      <template #footer><el-button @click="ruleDialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveRule">保存规则</el-button></template>
    </el-dialog>
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

.preset-grid { display: grid; gap: .75rem; grid-template-columns: repeat(2, minmax(0, 1fr)); }
.preset-card { align-items: center; background: var(--byq-surface-subtle); border-radius: var(--byq-radius-sm); display: flex; gap: 1rem; justify-content: space-between; padding: .8rem; }
.form-grid { display: grid; gap: 1rem; grid-template-columns: repeat(2, minmax(0, 1fr)); }
.form-grid .el-select { width: 100%; }

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
  .preset-grid, .form-grid { grid-template-columns: 1fr; }
}
</style>

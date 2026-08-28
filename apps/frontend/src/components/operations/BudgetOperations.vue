<script setup lang="ts">
import { reactive, ref, watch } from "vue";
import { updateOperationsBudget } from "@/api/operations";
import type { OperationsStatus } from "@/api/types";
import { createRequestId } from "@/utils/requestId";
const props = defineProps<{ data: OperationsStatus }>();
const emit = defineEmits<{ changed: [] }>();
const saving = ref(false);
const message = ref("");
const form = reactive({ enabled: false, alert_total_tokens: 400000, alert_requests: 48 });
watch(() => props.data.budget, (budget) => { form.enabled = budget.enabled; form.alert_total_tokens = budget.alert_total_tokens; form.alert_requests = budget.alert_requests; }, { immediate: true });
async function save() {
  saving.value = true; message.value = "";
  try { await updateOperationsBudget({ ...form, expected_version: props.data.budget.version, idempotency_key: `budget-${props.data.budget.version}-${createRequestId()}` }); message.value = "监控阈值已更新并写入追加审计"; emit("changed"); }
  catch (exc) { message.value = exc instanceof Error ? exc.message : "保存失败"; }
  finally { saving.value = false; }
}
</script>
<template><div class="ops-workbench"><el-alert title="阈值用于告警观察，不会直接终止 DSH、修改模型或扩大 Product Agent 权限。统计范围为当前 Runtime Adapter 进程生命周期。" type="warning" show-icon :closable="false" /><div class="ops-metrics"><el-card shadow="never"><span>累计 tokens</span><strong>{{ data.runtime.usage.total_tokens }}</strong><small>输入/输出/缓存写入分离计数</small></el-card><el-card shadow="never"><span>模型调用</span><strong>{{ data.runtime.usage.model_calls }}</strong><small>成功产生 usage 的调用</small></el-card><el-card shadow="never"><span>推理 tokens</span><strong>{{ data.runtime.usage.reasoning_tokens }}</strong><small>单列诊断</small></el-card></div><el-card shadow="never"><template #header><strong>Product Agent 用量监控阈值</strong></template><el-form label-position="top" class="budget-form"><el-form-item label="启用告警"><el-switch v-model="form.enabled" /></el-form-item><el-form-item label="总 token 告警线"><el-input-number v-model="form.alert_total_tokens" :min="1000" :max="100000000" :step="10000" /></el-form-item><el-form-item label="模型调用告警线"><el-input-number v-model="form.alert_requests" :min="1" :max="1000000" /></el-form-item><el-button type="primary" :loading="saving" @click="save">保存并审计</el-button><span v-if="message" class="budget-message">{{ message }}</span></el-form></el-card></div></template>
<style scoped>.budget-form{max-width:520px}.budget-message{margin-left:12px;color:var(--byq-text-muted)}</style>

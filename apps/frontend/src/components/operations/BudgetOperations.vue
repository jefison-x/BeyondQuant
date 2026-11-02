<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import { updateOperationsBudget } from "@/api/operations";
import type { OperationsStatus } from "@/api/types";
import { createRequestId } from "@/utils/requestId";
const props = defineProps<{ data: OperationsStatus }>();
const emit = defineEmits<{ changed: [] }>();
const saving = ref(false);
const message = ref("");
const usage = computed(() => props.data.usage?.schema_version === "operations-usage.v1" ? props.data.usage : undefined);
const totals = computed(() => usage.value && usage.value.known_requests > 0 ? usage.value.known_totals : undefined);
const formatCount = (value: number | undefined) => value === undefined ? "暂无已知回执" : value.toLocaleString("zh-CN");
const form = reactive({ enabled: false, alert_total_tokens: 400000, alert_requests: 48 });
watch(() => props.data.budget, (budget) => { form.enabled = budget.enabled; form.alert_total_tokens = budget.alert_total_tokens; form.alert_requests = budget.alert_requests; }, { immediate: true });
async function save() {
  saving.value = true; message.value = "";
  try { await updateOperationsBudget({ ...form, expected_version: props.data.budget.version, idempotency_key: `budget-${props.data.budget.version}-${createRequestId()}` }); message.value = "监控阈值已更新并写入追加审计"; emit("changed"); }
  catch (exc) { message.value = exc instanceof Error ? exc.message : "保存失败"; }
  finally { saving.value = false; }
}
</script>
<template>
  <div class="ops-workbench">
    <el-alert title="按现存已结算接续回执汇总已知用量。普通回合和研究判断尚未计入，因此不是完整总量。阈值只用于告警观察，不限制执行。" type="warning" show-icon :closable="false" />
    <p v-if="!usage" role="status">用量汇总暂不可用；进程计数不能替代持久回执。</p>
    <p v-if="usage?.truncated" role="status">当前只汇总了部分记录。</p>
    <div class="ops-metrics">
      <el-card shadow="never"><span>已知 tokens 小计</span><strong>{{ formatCount(totals?.total_tokens) }}</strong><small>非缓存输入、缓存读取、输出各计一次</small></el-card>
      <el-card shadow="never"><span>已知提供方请求次数</span><strong>{{ formatCount(totals?.provider_attempts) }}</strong><small>来自已结算回执，不是 Agent 回合数</small></el-card>
      <el-card shadow="never"><span>已知回执</span><strong>{{ usage ? usage.known_requests : "未知" }}</strong><small v-if="usage">未确认 {{ usage.unknown_requests }}；异常 {{ usage.invalid_requests }}</small></el-card>
    </div>
    <p v-if="totals" class="usage-breakdown">非缓存输入 {{ formatCount(totals.input_tokens) }} · 缓存读取 {{ formatCount(totals.cache_read_tokens) }} · 输出 {{ formatCount(totals.output_tokens) }}</p>
    <el-card shadow="never">
      <template #header><strong>Product Agent 用量监控阈值</strong></template>
      <el-form label-position="top" class="budget-form">
        <el-form-item label="启用告警"><el-switch v-model="form.enabled" /></el-form-item>
        <el-form-item label="总 token 告警线"><el-input-number v-model="form.alert_total_tokens" :min="1000" :max="100000000" :step="10000" /></el-form-item>
        <el-form-item label="模型调用告警线"><el-input-number v-model="form.alert_requests" :min="1" :max="1000000" /></el-form-item>
        <el-button type="primary" :loading="saving" @click="save">保存并审计</el-button>
        <span v-if="message" class="budget-message">{{ message }}</span>
      </el-form>
    </el-card>
  </div>
</template>
<style scoped>.budget-form{max-width:520px}.budget-message{margin-left:12px;color:var(--byq-text-muted)}</style>

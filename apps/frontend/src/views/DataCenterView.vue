<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  createDataSourceCredential,
  createDataSyncJob,
  getDataSyncJob,
  getDataCenterStatus,
  revokeDataSourceCredential,
  testDataSource,
  updateDataSourceCredential,
} from "@/api/dataCenter";
import type { DataCenterStatus, DataSourceCredential, DataSyncJob } from "@/api/types";

const loading = ref(true);
const busy = ref(false);
const error = ref("");
const activeTab = ref("source");
const status = ref<DataCenterStatus | null>(null);
const credentialDialog = ref(false);
const editingCredential = ref<DataSourceCredential | null>(null);
const credentialForm = reactive({ label: "Tushare 系统数据源", secret: "" });
const testForm = reactive({ symbol: "000001.SZ", trade_date: "20240102" });
const testResult = ref<Record<string, unknown> | null>(null);
const syncForm = reactive({ mode: "range", symbols: "000001.SZ", start_date: "20240102", end_date: "20240112" });
const selectedJob = ref<DataSyncJob | null>(null);

const credentials = computed(() => status.value?.source.credentials ?? []);
const canAddCredential = computed(() => !credentials.value.some((item) => item.status !== "revoked"));

async function load() {
  loading.value = true;
  error.value = "";
  try {
    status.value = await getDataCenterStatus();
    if (selectedJob.value) {
      selectedJob.value = status.value.jobs.find((item) => item.job_id === selectedJob.value?.job_id) ?? selectedJob.value;
    }
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "数据中心加载失败";
  } finally {
    loading.value = false;
  }
}

onMounted(load);

function openCredential(item: DataSourceCredential | null = null) {
  editingCredential.value = item;
  credentialForm.label = item?.label ?? "Tushare 系统数据源";
  credentialForm.secret = "";
  credentialDialog.value = true;
}

async function saveCredential() {
  if (!credentialForm.label.trim() || !credentialForm.secret.trim()) return ElMessage.warning("请输入名称和 Tushare Token");
  busy.value = true;
  try {
    if (editingCredential.value) {
      await updateDataSourceCredential(editingCredential.value.credential_id, {
        label: credentialForm.label,
        secret: credentialForm.secret,
        expected_version: editingCredential.value.version,
        request_id: `browser-tushare-replace-${Date.now()}`,
      });
      ElMessage.success("Tushare Token 已安全替换");
    } else {
      await createDataSourceCredential({
        label: credentialForm.label,
        secret: credentialForm.secret,
        idempotency_key: `browser-tushare-create-${Date.now()}`,
      });
      ElMessage.success("Tushare 数据源已配置");
    }
    credentialDialog.value = false;
    credentialForm.secret = "";
    await load();
  } catch (exc) {
    ElMessage.error(exc instanceof Error ? exc.message : "保存数据源失败");
  } finally {
    busy.value = false;
  }
}

async function setCredentialStatus(item: DataSourceCredential, next: "active" | "disabled") {
  busy.value = true;
  try {
    await updateDataSourceCredential(item.credential_id, {
      label: item.label,
      status: next,
      expected_version: item.version,
      request_id: `browser-tushare-status-${Date.now()}`,
    });
    await load();
  } catch (exc) {
    ElMessage.error(exc instanceof Error ? exc.message : "更新数据源失败");
  } finally {
    busy.value = false;
  }
}

async function revoke(item: DataSourceCredential) {
  try {
    await ElMessageBox.confirm("撤销后加密密文会被清除，后续同步无法使用该 Token。", "撤销 Tushare 凭据", { type: "warning" });
    await revokeDataSourceCredential(item.credential_id, {
      expected_version: item.version,
      request_id: `browser-tushare-revoke-${Date.now()}`,
    });
    ElMessage.success("Tushare 凭据已撤销");
    await load();
  } catch (exc) {
    if (exc !== "cancel" && exc !== "close") ElMessage.error(exc instanceof Error ? exc.message : "撤销失败");
  }
}

async function runConnectionTest() {
  busy.value = true;
  testResult.value = null;
  try {
    testResult.value = (await testDataSource({ ...testForm })).test;
    ElMessage.success("连接测试通过");
  } catch (exc) {
    ElMessage.error(exc instanceof Error ? exc.message : "连接测试失败");
  } finally {
    busy.value = false;
  }
}

async function submitSync() {
  const symbols = syncForm.symbols.split(/[\s,，]+/).map((item) => item.trim().toUpperCase()).filter(Boolean);
  if (!symbols.length) return ElMessage.warning("请输入至少一个股票代码");
  busy.value = true;
  try {
    const response = await createDataSyncJob({
      mode: syncForm.mode,
      symbols,
      start_date: syncForm.start_date,
      end_date: syncForm.end_date,
      idempotency_key: `browser-sync-${Date.now()}`,
    });
    selectedJob.value = response.job;
    ElMessage.success("同步任务已创建");
    await load();
    if (!["completed", "partial", "failed"].includes(response.job.status)) void pollJob(response.job.job_id);
  } catch (exc) {
    ElMessage.error(exc instanceof Error ? exc.message : "创建同步任务失败");
  } finally {
    busy.value = false;
  }
}

async function pollJob(jobId: string) {
  for (let attempt = 0; attempt < 60; attempt += 1) {
    await new Promise((resolve) => window.setTimeout(resolve, 1000));
    try {
      const response = await getDataSyncJob(jobId);
      selectedJob.value = response.job;
      const index = status.value?.jobs.findIndex((item) => item.job_id === jobId) ?? -1;
      if (status.value && index >= 0) status.value.jobs[index] = response.job;
      if (["completed", "partial", "failed"].includes(response.job.status)) {
        await load();
        ElMessage.success(response.job.status === "completed" ? "同步完成" : "同步任务已结束，请查看明细");
        return;
      }
    } catch {
      return;
    }
  }
}

function sourceLabel(value: string | undefined) {
  return ({ credential_store: "加密凭据库", environment: "环境引导配置", ambiguous: "配置冲突", none: "未配置" } as Record<string, string>)[value ?? "none"];
}

function qualityLabel(value: string | undefined) {
  return ({ empty: "暂无数据", observed: "已审计", issues: "发现问题" } as Record<string, string>)[value ?? "empty"] ?? value;
}
</script>

<template>
  <section class="data-center-page">
    <div class="page-heading">
      <div><p class="eyebrow">Data Plane</p><h1>数据中心</h1><p>管理 Tushare 数据源、执行有界同步，并审计 PostgreSQL 中的真实覆盖范围。</p></div>
      <el-button :loading="loading" @click="load">刷新状态</el-button>
    </div>

    <div v-if="loading" class="base-loading" role="status" aria-live="polite">正在读取数据平面...</div>
    <div v-else-if="error" class="base-error" role="alert">{{ error }}</div>

    <template v-else-if="status">
      <div class="stats-strip">
        <div class="stat-item"><span>数据源</span><strong>Tushare</strong><small>唯一支持的 Provider</small></div>
        <div class="stat-item"><span>凭据</span><strong>{{ status.source.configured ? "已配置" : "未配置" }}</strong><small>{{ sourceLabel(status.source.effective_source) }}</small></div>
        <div class="stat-item"><span>数据行</span><strong>{{ status.coverage.row_count.toLocaleString() }}</strong><small>{{ status.coverage.symbol_count }} 个标的</small></div>
        <div class="stat-item"><span>质量</span><strong>{{ qualityLabel(status.quality) }}</strong><small>{{ status.coverage.checked_at.slice(0, 19).replace("T", " ") }}</small></div>
      </div>

      <el-alert title="BaoStock、AKShare 与任意自定义 Provider 已按架构决策移除；Token 仅写入 Backend 加密凭据库，不会返回浏览器。" type="info" show-icon :closable="false" />

      <el-tabs v-model="activeTab" class="workspace-tabs">
        <el-tab-pane label="数据源配置" name="source">
          <el-card shadow="never">
            <template #header><div class="card-header"><div><strong>Tushare 系统数据源</strong><p>固定官方协议端点 · AES-256-GCM 信封加密 · 管理员专用</p></div><el-button v-if="status.source.can_manage" type="primary" :disabled="!status.source.encryption.configured || !canAddCredential" @click="openCredential()">添加 Token</el-button></div></template>
            <el-table :data="credentials" empty-text="尚未保存数据库凭据；可继续使用显式环境引导配置">
              <el-table-column prop="label" label="名称" min-width="180" />
              <el-table-column prop="masked" label="掩码" min-width="130" />
              <el-table-column label="状态" width="100"><template #default="scope"><el-tag :type="scope.row.status === 'active' ? 'success' : scope.row.status === 'revoked' ? 'danger' : 'info'">{{ scope.row.status }}</el-tag></template></el-table-column>
              <el-table-column prop="version" label="版本" width="80" />
              <el-table-column prop="updated_at" label="更新时间" min-width="180" />
              <el-table-column v-if="status.source.can_manage" label="操作" min-width="250"><template #default="scope"><el-button link type="primary" :disabled="scope.row.status === 'revoked'" @click="openCredential(scope.row)">替换</el-button><el-button v-if="scope.row.status === 'active'" link @click="setCredentialStatus(scope.row, 'disabled')">停用</el-button><el-button v-else-if="scope.row.status === 'disabled'" link @click="setCredentialStatus(scope.row, 'active')">启用</el-button><el-button link type="danger" :disabled="scope.row.status === 'revoked'" @click="revoke(scope.row)">撤销</el-button></template></el-table-column>
            </el-table>
          </el-card>

          <el-card v-if="status.source.can_manage" shadow="never">
            <template #header><div><strong>连接测试</strong><p>使用一个标的、一个交易日执行有界 daily 请求；响应只显示结果元数据。</p></div></template>
            <el-form inline class="inline-form"><el-form-item label="股票代码"><el-input v-model="testForm.symbol" maxlength="9" /></el-form-item><el-form-item label="交易日"><el-input v-model="testForm.trade_date" maxlength="8" /></el-form-item><el-form-item><el-button type="primary" :loading="busy" :disabled="!status.source.configured" @click="runConnectionTest">测试连接</el-button></el-form-item></el-form>
            <el-descriptions v-if="testResult" :column="3" border><el-descriptions-item label="结果">{{ testResult.status }}</el-descriptions-item><el-descriptions-item label="凭据来源">{{ sourceLabel(String(testResult.credential_source)) }}</el-descriptions-item><el-descriptions-item label="返回行数">{{ testResult.row_count }}</el-descriptions-item><el-descriptions-item label="延迟">{{ testResult.latency_ms }} ms</el-descriptions-item><el-descriptions-item label="端点">{{ testResult.endpoint }}</el-descriptions-item><el-descriptions-item label="检查时间">{{ testResult.checked_at }}</el-descriptions-item></el-descriptions>
          </el-card>
        </el-tab-pane>

        <el-tab-pane label="同步任务" name="sync">
          <el-card v-if="status.source.can_manage" shadow="never">
            <template #header><div><strong>创建有界同步</strong><p>每次最多 20 个规范 A 股代码、366 个自然日；重复写入保持现有 BYQ 数据。</p></div></template>
            <el-form label-position="top" class="sync-form"><el-form-item label="股票代码"><el-input v-model="syncForm.symbols" type="textarea" :rows="2" placeholder="000001.SZ, 600000.SH" /></el-form-item><div class="form-grid"><el-form-item label="模式"><el-select v-model="syncForm.mode"><el-option label="区间同步" value="range" /><el-option label="增量补齐" value="incremental" /></el-select></el-form-item><el-form-item label="开始日期"><el-input v-model="syncForm.start_date" maxlength="8" /></el-form-item><el-form-item label="结束日期"><el-input v-model="syncForm.end_date" maxlength="8" /></el-form-item></div><el-button type="primary" :loading="busy" :disabled="!status.source.configured" @click="submitSync">立即同步</el-button></el-form>
          </el-card>
          <el-card shadow="never">
            <template #header><div><strong>同步历史</strong><p>任务与逐标的结果持久化在 BYQ PostgreSQL，页面刷新后仍可追踪。</p></div></template>
            <el-table :data="status.jobs" empty-text="暂无同步任务" @row-click="selectedJob = $event"><el-table-column prop="job_id" label="任务" min-width="220" show-overflow-tooltip /><el-table-column prop="mode" label="模式" width="110" /><el-table-column label="标的" width="90"><template #default="scope">{{ scope.row.symbols.length }}</template></el-table-column><el-table-column prop="status" label="状态" width="110" /><el-table-column prop="rows_inserted" label="新增行" width="100" /><el-table-column prop="rows_kept" label="保留行" width="100" /><el-table-column prop="created_at" label="创建时间" min-width="180" /></el-table>
          </el-card>
          <el-card v-if="selectedJob" shadow="never"><template #header><strong>任务明细 · {{ selectedJob.job_id }}</strong></template><el-progress :percentage="selectedJob.progress" :status="selectedJob.status === 'failed' ? 'exception' : selectedJob.status === 'completed' ? 'success' : undefined" /><el-table :data="selectedJob.symbol_results" size="small"><el-table-column prop="symbol" label="标的" width="120" /><el-table-column prop="status" label="状态" width="100" /><el-table-column prop="rows_received" label="获取" width="90" /><el-table-column prop="rows_inserted" label="新增" width="90" /><el-table-column prop="date_min" label="起始" width="110" /><el-table-column prop="date_max" label="结束" width="110" /><el-table-column prop="message" label="说明" min-width="180" /></el-table></el-card>
        </el-tab-pane>

        <el-tab-pane label="覆盖审计" name="coverage">
          <el-alert title="覆盖范围只陈述 PostgreSQL 中已观察到的数据，不在缺少交易日历证据时宣称历史数据完整。" type="warning" show-icon :closable="false" />
          <div class="coverage-grid"><el-card shadow="never"><strong>总体覆盖</strong><el-descriptions :column="1" border><el-descriptions-item label="数据行">{{ status.coverage.row_count.toLocaleString() }}</el-descriptions-item><el-descriptions-item label="标的数">{{ status.coverage.symbol_count }}</el-descriptions-item><el-descriptions-item label="日期范围">{{ status.coverage.date_min ?? "-" }} — {{ status.coverage.date_max ?? "-" }}</el-descriptions-item><el-descriptions-item label="来源问题">{{ status.coverage.source_issues }}</el-descriptions-item><el-descriptions-item label="OHLC 问题">{{ status.coverage.ohlc_issues }}</el-descriptions-item></el-descriptions></el-card><el-card shadow="never"><strong>数据集分组</strong><el-table :data="status.coverage.groups" empty-text="暂无数据"><el-table-column prop="data_source" label="来源" /><el-table-column prop="asset_type" label="资产" /><el-table-column prop="row_count" label="行数" /><el-table-column prop="symbol_count" label="标的" /></el-table></el-card></div>
          <el-card shadow="never"><template #header><strong>标的覆盖</strong></template><el-table :data="status.coverage.symbols" empty-text="暂无覆盖记录"><el-table-column prop="symbol" label="股票代码" /><el-table-column prop="row_count" label="数据行" /><el-table-column prop="date_min" label="最早日期" /><el-table-column prop="date_max" label="最晚日期" /></el-table></el-card>
        </el-tab-pane>
      </el-tabs>
    </template>

    <el-dialog v-model="credentialDialog" :title="editingCredential ? '替换 Tushare Token' : '配置 Tushare Token'" width="min(520px, 92vw)" destroy-on-close><el-form label-position="top"><el-form-item label="名称"><el-input v-model="credentialForm.label" maxlength="120" /></el-form-item><el-form-item label="Tushare Token"><el-input v-model="credentialForm.secret" type="password" show-password autocomplete="new-password" placeholder="写入后仅显示掩码" /></el-form-item></el-form><template #footer><el-button @click="credentialDialog = false">取消</el-button><el-button type="primary" :loading="busy" @click="saveCredential">安全保存</el-button></template></el-dialog>
  </section>
</template>

<style scoped>
.data-center-page { display: grid; gap: 1rem; min-width: 0; }
.page-heading, .card-header { align-items: center; display: flex; gap: 1rem; justify-content: space-between; }
.page-heading h1 { font-size: clamp(24px, 3vw, 34px); margin: 0; }
.page-heading p, .card-header p { color: var(--byq-text-muted); margin: .35rem 0 0; }
.eyebrow { color: var(--byq-brand) !important; font-size: 11px; font-weight: 800; letter-spacing: .14em; text-transform: uppercase; }
.stat-item small { color: var(--byq-text-muted); display: block; font-size: 11px; margin-top: .25rem; }
.workspace-tabs :deep(.el-tabs__content) { overflow: visible; }
.workspace-tabs :deep(.el-tab-pane) { display: grid; gap: 1rem; }
.inline-form { align-items: end; }
.sync-form { max-width: 900px; }
.form-grid { display: grid; gap: 1rem; grid-template-columns: repeat(3, minmax(0, 1fr)); }
.form-grid .el-select { width: 100%; }
.coverage-grid { display: grid; gap: 1rem; grid-template-columns: minmax(260px, .7fr) minmax(0, 1.3fr); }
.coverage-grid :deep(.el-descriptions) { margin-top: 1rem; }
@media (max-width: 760px) { .page-heading, .card-header { align-items: flex-start; flex-direction: column; } .form-grid, .coverage-grid { grid-template-columns: 1fr; } .stats-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>

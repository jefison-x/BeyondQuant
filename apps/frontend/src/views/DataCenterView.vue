<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  createDataSourceCredential,
  createSecurityMasterSyncJob,
  getDataCenterStatus,
  getSecurityMasterSyncJob,
  listSecurities,
  queryDataReadiness,
  runMarketSyncNow,
  revokeDataSourceCredential,
  testDataSource,
  updateDataSourceCredential,
  updateMarketSyncAutomation,
} from "@/api/dataCenter";
import type {
  DataCenterStatus,
  DataReadinessResult,
  DataSourceCredential,
  DataSyncJob,
  SecurityCataloguePage,
  SecurityMasterSyncJob,
} from "@/api/types";

const loading = ref(true);
const busy = ref(false);
const error = ref("");
const activeTab = ref("coverage");
const status = ref<DataCenterStatus | null>(null);
const credentialDialog = ref(false);
const editingCredential = ref<DataSourceCredential | null>(null);
const credentialForm = reactive({ label: "Tushare 系统数据源", secret: "" });
const testForm = reactive({ symbol: "000001.SZ", trade_date: "20240102" });
const testResult = ref<Record<string, unknown> | null>(null);
const automationForm = reactive({
  enabled: false,
  schedule_time: "18:30",
  catchup_days: 7,
  security_master_enabled: true,
  version: 1,
});
const selectedJob = ref<DataSyncJob | null>(null);
const selectedSecurityJob = ref<SecurityMasterSyncJob | null>(null);
const catalogue = ref<SecurityCataloguePage>({ securities: [], total: 0, limit: 50, offset: 0, snapshot: null });
const catalogueLoading = ref(false);
const catalogueFilters = reactive({ query: "", statuses: ["L"], exchanges: [] as string[] });
const cataloguePage = ref(1);
const cataloguePageSize = 50;
const readinessBusy = ref(false);
const readinessResult = ref<DataReadinessResult | null>(null);
const readinessForm = reactive({
  symbols: "000001.SZ,600036.SH", start_date: "20260101",
  end_date: new Date().toISOString().slice(0, 10).replaceAll("-", ""),
  use_case: "research" as "research" | "backtest",
});

const credentials = computed(() => status.value?.source.credentials ?? []);
const canAddCredential = computed(() => !credentials.value.some((item) => item.status !== "revoked"));

async function loadCatalogue() {
  catalogueLoading.value = true;
  try {
    catalogue.value = await listSecurities({
      query: catalogueFilters.query.trim(),
      statuses: catalogueFilters.statuses,
      exchanges: catalogueFilters.exchanges,
      limit: cataloguePageSize,
      offset: (cataloguePage.value - 1) * cataloguePageSize,
    });
  } finally {
    catalogueLoading.value = false;
  }
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    status.value = await getDataCenterStatus();
    Object.assign(automationForm, {
      enabled: status.value.automation.config.enabled,
      schedule_time: status.value.automation.config.schedule_time,
      catchup_days: status.value.automation.config.catchup_days,
      security_master_enabled: status.value.automation.config.security_master_enabled,
      version: status.value.automation.config.version,
    });
    if (selectedJob.value) {
      selectedJob.value = status.value.jobs.find((item) => item.job_id === selectedJob.value?.job_id) ?? selectedJob.value;
    }
    if (selectedSecurityJob.value) {
      selectedSecurityJob.value = status.value.security_master_jobs.find((item) => item.job_id === selectedSecurityJob.value?.job_id) ?? selectedSecurityJob.value;
    }
    if (status.value.security_master.latest_snapshot) await loadCatalogue();
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

async function syncSecurityMaster() {
  busy.value = true;
  try {
    const response = await createSecurityMasterSyncJob();
    selectedSecurityJob.value = response.job;
    ElMessage.success("股票基本资料同步已创建");
    if (!["completed", "failed"].includes(response.job.status)) void pollSecurityJob(response.job.job_id);
    else await load();
  } catch (exc) {
    ElMessage.error(exc instanceof Error ? exc.message : "股票基本资料同步失败");
  } finally {
    busy.value = false;
  }
}

async function pollSecurityJob(jobId: string) {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    await new Promise((resolve) => setTimeout(resolve, 1000));
    const job = (await getSecurityMasterSyncJob(jobId)).job;
    selectedSecurityJob.value = job;
    if (["completed", "failed"].includes(job.status)) {
      await load();
      return;
    }
  }
}

async function saveAutomation() {
  busy.value = true;
  try {
    const response = await updateMarketSyncAutomation({
      enabled: automationForm.enabled,
      schedule_time: automationForm.schedule_time,
      catchup_days: automationForm.catchup_days,
      security_master_enabled: automationForm.security_master_enabled,
      expected_version: automationForm.version,
      idempotency_key: `browser-market-config-${Date.now()}`,
    });
    automationForm.version = response.config.version;
    ElMessage.success("每日自动同步设置已保存");
    await load();
  } catch (exc) {
    ElMessage.error(exc instanceof Error ? exc.message : "保存自动同步设置失败");
  } finally {
    busy.value = false;
  }
}

async function triggerAutomation() {
  busy.value = true;
  try {
    await runMarketSyncNow();
    ElMessage.success("已提交立即同步请求，数据 Worker 将按交易日执行");
    await load();
  } catch (exc) {
    ElMessage.error(exc instanceof Error ? exc.message : "提交立即同步失败");
  } finally {
    busy.value = false;
  }
}

async function checkReadiness() {
  const symbols = readinessForm.symbols.split(/[，,\s]+/).map((item) => item.trim().toUpperCase()).filter(Boolean);
  if (!symbols.length) return ElMessage.warning("请输入至少一个股票代码");
  readinessBusy.value = true;
  readinessResult.value = null;
  try {
    readinessResult.value = await queryDataReadiness({
      symbols, start_date: readinessForm.start_date, end_date: readinessForm.end_date,
      use_case: readinessForm.use_case,
    });
  } catch (exc) {
    ElMessage.error(exc instanceof Error ? exc.message : "数据可用性检查失败");
  } finally {
    readinessBusy.value = false;
  }
}

function readinessLabel(value: DataReadinessResult["verdict"]) {
  return ({ usable: "可以使用", limited: "部分受限", unavailable: "暂不可用" } as const)[value];
}

function readinessType(value: DataReadinessResult["verdict"]) {
  return ({ usable: "success", limited: "warning", unavailable: "error" } as const)[value];
}

function goToSync() { activeTab.value = "sync"; }

async function changeCataloguePage(page: number) {
  cataloguePage.value = page;
  await loadCatalogue();
}

async function applyCatalogueFilters() {
  cataloguePage.value = 1;
  await loadCatalogue();
}

function qualityLabel(value: string) {
  return ({ empty: "暂无数据", observed: "已观察", issues: "需检查" } as Record<string, string>)[value] ?? value;
}

function sourceLabel(value: string) {
  return ({ credential_store: "数据库加密凭据", environment: "环境引导配置", ambiguous: "配置冲突", none: "未配置" } as Record<string, string>)[value] ?? value;
}

function securityStatusLabel(value: string) {
  return ({ L: "上市", P: "暂停上市", D: "退市" } as Record<string, string>)[value] ?? value;
}
</script>

<template>
  <section class="data-center-page">
    <div class="page-heading">
      <div><p class="eyebrow">市场数据</p><h1>数据中心</h1><p>检查研究和回测所需数据是否齐全，并在缺失时继续同步。</p></div>
      <el-button :loading="loading" @click="load">刷新状态</el-button>
    </div>

    <div v-if="loading" class="base-loading" role="status" aria-live="polite">正在读取数据平面...</div>
    <div v-else-if="error" class="base-error" role="alert">{{ error }}</div>

    <template v-else-if="status">
      <div class="stats-strip">
        <div class="stat-item"><span>数据源</span><strong>Tushare</strong><small>当前唯一支持的数据源</small></div>
        <div class="stat-item"><span>证券目录</span><strong>{{ status.security_master.total.toLocaleString() }}</strong><small>{{ status.security_master.status_counts.L }} 只上市</small></div>
        <div class="stat-item"><span>日线数据</span><strong>{{ status.coverage.row_count.toLocaleString() }}</strong><small>{{ status.coverage.symbol_count }} 个标的</small></div>
        <div class="stat-item"><span>质量</span><strong>{{ qualityLabel(status.quality) }}</strong><small>{{ status.coverage.checked_at.slice(0, 19).replace("T", " ") }}</small></div>
      </div>

      <el-alert title="BaoStock、AKShare 与任意自定义 Provider 已移除；Token 只在 Backend 解密，股票目录和日线数据均为平台级数据。" type="info" show-icon :closable="false" />

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

        <el-tab-pane label="股票清单" name="securities">
          <el-card shadow="never">
            <template #header><div class="card-header"><div><strong>股票基本资料</strong><p>一次原子同步上市、暂停上市和退市证券；失败不会替换当前目录。</p></div><el-button type="primary" :loading="busy" :disabled="!status.source.configured" @click="syncSecurityMaster">同步基本资料</el-button></div></template>
            <el-descriptions :column="4" border>
              <el-descriptions-item label="总计">{{ status.security_master.total }}</el-descriptions-item>
              <el-descriptions-item label="上市">{{ status.security_master.status_counts.L }}</el-descriptions-item>
              <el-descriptions-item label="暂停上市">{{ status.security_master.status_counts.P }}</el-descriptions-item>
              <el-descriptions-item label="退市">{{ status.security_master.status_counts.D }}</el-descriptions-item>
              <el-descriptions-item label="快照" :span="4">{{ status.security_master.latest_snapshot?.snapshot_id ?? "尚未同步" }}</el-descriptions-item>
            </el-descriptions>
            <el-progress v-if="selectedSecurityJob" class="job-progress" :percentage="selectedSecurityJob.progress" :status="selectedSecurityJob.status === 'failed' ? 'exception' : selectedSecurityJob.status === 'completed' ? 'success' : undefined" />
            <el-alert
              v-if="selectedSecurityJob?.status === 'completed' && selectedSecurityJob.records_quarantined > 0"
              :title="`同步完成：已隔离 ${selectedSecurityJob.records_quarantined} 条非规范 Tushare 历史别名，未写入权威股票清单。`"
              type="warning"
              show-icon
              :closable="false"
            />
          </el-card>
          <el-card shadow="never">
            <template #header><div><strong>规范证券目录</strong><p>可搜索和筛选股票；结果来自当前不可变目录快照。</p></div></template>
            <div class="catalogue-toolbar">
              <el-input v-model="catalogueFilters.query" clearable placeholder="代码 / 名称" @keyup.enter="applyCatalogueFilters" />
              <el-select v-model="catalogueFilters.statuses" multiple collapse-tags placeholder="上市状态"><el-option label="上市" value="L" /><el-option label="暂停上市" value="P" /><el-option label="退市" value="D" /></el-select>
              <el-select v-model="catalogueFilters.exchanges" multiple collapse-tags placeholder="交易所"><el-option label="上交所" value="SSE" /><el-option label="深交所" value="SZSE" /><el-option label="北交所" value="BSE" /></el-select>
              <el-button :loading="catalogueLoading" @click="applyCatalogueFilters">查询</el-button>
            </div>
            <el-table v-loading="catalogueLoading" :data="catalogue.securities" empty-text="请先同步股票基本资料">
              <el-table-column prop="symbol" label="代码" width="120" />
              <el-table-column prop="name" label="名称" min-width="140" />
              <el-table-column prop="exchange" label="交易所" width="90" />
              <el-table-column prop="market" label="板块" width="100" />
              <el-table-column prop="industry" label="行业" min-width="120" />
              <el-table-column label="状态" width="100"><template #default="scope"><el-tag :type="scope.row.list_status === 'L' ? 'success' : scope.row.list_status === 'D' ? 'info' : 'warning'">{{ securityStatusLabel(scope.row.list_status) }}</el-tag></template></el-table-column>
              <el-table-column prop="list_date" label="上市日期" width="110" />
              <el-table-column prop="delist_date" label="退市日期" width="110" />
            </el-table>
            <div class="catalogue-footer"><span>当前目录快照 {{ catalogue.snapshot?.snapshot_id ?? "-" }}</span><el-pagination background layout="prev, pager, next, total" :page-size="cataloguePageSize" :total="catalogue.total" :current-page="cataloguePage" @current-change="changeCataloguePage" /></div>
          </el-card>
        </el-tab-pane>

        <el-tab-pane label="行情同步" name="sync">
          <el-card v-if="status.source.can_manage" shadow="never">
            <template #header><div class="card-header"><div><strong>每日自动同步</strong><p>按 Asia/Shanghai 交易日历，在盘后一次获取全市场日线并追赶遗漏交易日。</p></div><el-button type="primary" plain :loading="busy" :disabled="!status.source.configured" @click="triggerAutomation">立即检查并同步</el-button></div></template>
            <el-alert
              :title="status.automation.worker.healthy ? '数据 Worker 运行正常' : '数据 Worker 未运行或心跳已过期'"
              :type="status.automation.worker.healthy ? 'success' : 'warning'"
              show-icon
              :closable="false"
            />
            <el-form label-position="top" class="automation-form">
              <div class="automation-grid">
                <el-form-item label="自动同步"><el-switch v-model="automationForm.enabled" active-text="启用" inactive-text="关闭" /></el-form-item>
                <el-form-item label="盘后执行时间"><el-time-picker v-model="automationForm.schedule_time" format="HH:mm" value-format="HH:mm" placeholder="18:30" /></el-form-item>
                <el-form-item label="重启追赶天数"><el-input-number v-model="automationForm.catchup_days" :min="1" :max="30" /></el-form-item>
                <el-form-item label="同步前刷新股票清单"><el-switch v-model="automationForm.security_master_enabled" active-text="启用" inactive-text="关闭" /></el-form-item>
              </div>
              <div class="automation-actions"><div><el-tag effect="plain">交易日历</el-tag><el-tag effect="plain">未复权全市场日线</el-tag><el-tag effect="plain">停复牌与涨跌停</el-tag><el-tag effect="plain">复权因子</el-tag><el-tag effect="plain">实施公司行动</el-tag><el-tag effect="plain">每日估值因子</el-tag><el-tag effect="plain">沪深300基准/成分</el-tag><el-tag effect="plain">策略声明财务指标</el-tag><span>固定时区：Asia/Shanghai</span></div><el-button type="primary" :loading="busy" @click="saveAutomation">保存设置</el-button></div>
            </el-form>
            <el-descriptions :column="3" border class="automation-status">
              <el-descriptions-item label="最新开市日">{{ status.automation.latest_calendar_open_date ?? "尚未获取" }}</el-descriptions-item>
              <el-descriptions-item label="最新完整行情">{{ status.automation.latest_complete_session?.trade_date ?? "尚未完成" }}</el-descriptions-item>
              <el-descriptions-item label="下次检查">{{ status.automation.next_run_at }}</el-descriptions-item>
              <el-descriptions-item label="完整快照行数">{{ status.automation.latest_complete_session?.row_count?.toLocaleString() ?? "-" }}</el-descriptions-item>
              <el-descriptions-item label="最近心跳">{{ status.automation.worker.heartbeat_at ?? "-" }}</el-descriptions-item>
              <el-descriptions-item label="最近错误">{{ status.automation.worker.last_error ?? "无" }}</el-descriptions-item>
            </el-descriptions>
            <el-table :data="status.automation.jobs" empty-text="暂无自动同步任务" size="small">
              <el-table-column prop="trade_date" label="交易日" width="110" /><el-table-column prop="status" label="状态" width="100" /><el-table-column prop="attempts" label="尝试" width="80" /><el-table-column prop="rows_received" label="获取" width="100" /><el-table-column prop="rows_inserted" label="新增" width="100" /><el-table-column prop="rows_kept" label="保留" width="100" /><el-table-column prop="error_message" label="说明" min-width="180" />
            </el-table>
          </el-card>
          <el-card shadow="never">
            <template #header><div><strong>同步历史</strong><p>任务与逐标的结果持久化；增量模式从每只股票最后一个已存日期之后继续。</p></div></template>
            <el-table :data="status.jobs" empty-text="暂无同步任务" @row-click="selectedJob = $event"><el-table-column prop="job_id" label="任务" min-width="220" show-overflow-tooltip /><el-table-column prop="mode" label="模式" width="110" /><el-table-column prop="symbol_count" label="标的" width="90" /><el-table-column prop="status" label="状态" width="110" /><el-table-column prop="rows_inserted" label="新增行" width="100" /><el-table-column prop="rows_kept" label="保留行" width="100" /><el-table-column prop="created_at" label="创建时间" min-width="180" /></el-table>
          </el-card>
          <el-card v-if="selectedJob" shadow="never"><template #header><strong>任务明细 · {{ selectedJob.job_id }}</strong></template><el-progress :percentage="selectedJob.progress" :status="selectedJob.status === 'failed' ? 'exception' : selectedJob.status === 'completed' ? 'success' : undefined" /><p v-if="selectedJob.results_truncated" class="bounded-note">逐标的结果已按公开合同截断：显示 {{ selectedJob.symbol_results.length }} / {{ selectedJob.result_count }}</p><el-table :data="selectedJob.symbol_results" size="small"><el-table-column prop="symbol" label="标的" width="120" /><el-table-column prop="status" label="状态" width="100" /><el-table-column prop="rows_received" label="获取" width="90" /><el-table-column prop="rows_inserted" label="新增" width="90" /><el-table-column prop="date_min" label="起始" width="110" /><el-table-column prop="date_max" label="结束" width="110" /><el-table-column prop="message" label="说明" min-width="180" /></el-table></el-card>
        </el-tab-pane>

        <el-tab-pane label="覆盖审计" name="coverage">
          <el-card shadow="never" class="readiness-card">
            <template #header><div><strong>这批数据现在能用吗？</strong><p>按股票、日期和用途检查已同步数据；小巴研究和回测都使用这里的持久数据，不会临时向数据源取数。</p></div></template>
            <el-form label-position="top">
              <div class="readiness-form">
                <el-form-item label="股票代码"><el-input v-model="readinessForm.symbols" placeholder="多个代码用逗号分隔，最多 20 个" /></el-form-item>
                <el-form-item label="开始日期"><el-input v-model="readinessForm.start_date" maxlength="8" /></el-form-item>
                <el-form-item label="结束日期"><el-input v-model="readinessForm.end_date" maxlength="8" /></el-form-item>
                <el-form-item label="准备做什么"><el-select v-model="readinessForm.use_case"><el-option label="研究走势" value="research" /><el-option label="运行回测" value="backtest" /></el-select></el-form-item>
              </div>
              <el-button type="primary" :loading="readinessBusy" @click="checkReadiness">检查可用性</el-button>
            </el-form>
            <div v-if="readinessResult" class="readiness-result">
              <el-alert :title="readinessLabel(readinessResult.verdict)" :type="readinessType(readinessResult.verdict)" show-icon :closable="false"
                :description="`已核对 ${readinessResult.scope.symbol_count} 只股票、${readinessResult.summary.required_sessions} 个交易日；缺少 ${readinessResult.summary.missing_items} 项必要数据。`" />
              <div v-if="readinessResult.datasets.length" class="dataset-tags"><el-tag v-for="item in readinessResult.datasets" :key="item.label" type="warning">{{ item.label }} · 缺 {{ item.missing_count }}</el-tag></div>
              <el-table v-if="readinessResult.issues.length" :data="readinessResult.issues" size="small">
                <el-table-column prop="symbol" label="股票" width="120" /><el-table-column prop="trade_date" label="交易日" width="110" />
                <el-table-column prop="label" label="缺少内容" min-width="150" /><el-table-column prop="impact" label="影响" min-width="190" />
                <el-table-column prop="recommended_action" label="下一步" min-width="160" />
              </el-table>
              <div v-if="readinessResult.verdict !== 'usable'" class="readiness-next"><span>{{ status.source.can_manage ? "可以前往行情同步补齐，再重新检查。" : "请联系管理员同步缺失范围，再重新检查。" }}</span><el-button v-if="status.source.can_manage" @click="goToSync">前往行情同步</el-button></div>
            </div>
          </el-card>
          <el-alert title="下方全局概览只说明已存数据量，不能代替上面的任务可用性检查。" type="info" show-icon :closable="false" />
          <div class="coverage-grid"><el-card shadow="never"><strong>总体覆盖</strong><el-descriptions :column="1" border><el-descriptions-item label="数据行">{{ status.coverage.row_count.toLocaleString() }}</el-descriptions-item><el-descriptions-item label="标的数">{{ status.coverage.symbol_count }}</el-descriptions-item><el-descriptions-item label="日期范围">{{ status.coverage.date_min ?? "-" }} — {{ status.coverage.date_max ?? "-" }}</el-descriptions-item><el-descriptions-item label="来源问题">{{ status.coverage.source_issues }}</el-descriptions-item><el-descriptions-item label="OHLC 问题">{{ status.coverage.ohlc_issues }}</el-descriptions-item></el-descriptions></el-card><el-card shadow="never"><strong>数据集分组</strong><el-table :data="status.coverage.groups" empty-text="暂无数据"><el-table-column prop="data_source" label="来源" /><el-table-column prop="asset_type" label="资产" /><el-table-column prop="row_count" label="数据行" /><el-table-column prop="symbol_count" label="标的" /></el-table></el-card></div>
          <el-card shadow="never"><template #header><strong>已同步标的覆盖</strong></template><el-table :data="status.coverage.symbols" empty-text="暂无覆盖记录"><el-table-column prop="symbol" label="股票代码" /><el-table-column prop="row_count" label="数据行" /><el-table-column prop="date_min" label="最早日期" /><el-table-column prop="date_max" label="最晚日期" /></el-table></el-card>
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
.stat-item small, .bounded-note, .catalogue-footer { color: var(--byq-text-muted); }
.stat-item small { display: block; font-size: 11px; margin-top: .25rem; }
.workspace-tabs :deep(.el-tabs__content) { overflow: visible; }
.workspace-tabs :deep(.el-tab-pane) { display: grid; gap: 1rem; }
.inline-form { align-items: end; }
.automation-form { margin-top: 1rem; }
.automation-grid { display: grid; gap: 1rem; grid-template-columns: repeat(4, minmax(0, 1fr)); }
.automation-actions { align-items: center; display: flex; gap: 1rem; justify-content: space-between; }
.automation-actions > div { align-items: center; color: var(--byq-text-muted); display: flex; flex-wrap: wrap; gap: .5rem; }
.automation-status { margin: 1rem 0; }
.catalogue-toolbar .el-select { width: 100%; }
.coverage-grid { display: grid; gap: 1rem; grid-template-columns: minmax(260px, .7fr) minmax(0, 1.3fr); }
.readiness-form { display: grid; gap: .75rem; grid-template-columns: minmax(220px, 1.4fr) repeat(3, minmax(130px, .6fr)); }.readiness-result { display: grid; gap: .75rem; margin-top: 1rem; }.dataset-tags { display: flex; flex-wrap: wrap; gap: .5rem; }.readiness-next { align-items: center; color: var(--byq-text-muted); display: flex; justify-content: space-between; }
.coverage-grid :deep(.el-descriptions) { margin-top: 1rem; }
.catalogue-toolbar { display: grid; gap: .75rem; grid-template-columns: minmax(180px, 1fr) minmax(160px, .7fr) minmax(160px, .7fr) auto; margin-bottom: 1rem; }
.catalogue-footer { align-items: center; display: flex; font-size: 12px; gap: 1rem; justify-content: space-between; margin-top: 1rem; }
.job-progress { margin-top: 1rem; }
.bounded-note { font-size: 12px; }
@media (max-width: 760px) {
  .page-heading, .card-header, .catalogue-footer { align-items: flex-start; flex-direction: column; }
  .automation-grid, .coverage-grid, .catalogue-toolbar, .readiness-form { grid-template-columns: 1fr; }
  .automation-actions { align-items: stretch; flex-direction: column; }
  .stats-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .catalogue-footer :deep(.el-pagination) { flex-wrap: wrap; }
}
</style>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { Close, Plus } from "@element-plus/icons-vue";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  createFeedback, getFeedback, getFeedbackOptions, listFeedback, previewFeedback,
  submitFeedback, updateFeedback, withdrawFeedback,
} from "@/api/feedback";
import type { FeedbackPublicationPreview, ProductFeedbackContent, ProductFeedbackDetail, ProductFeedbackOptions, ProductFeedbackSummary } from "@/api/types";

const route = useRoute();
const router = useRouter();
const isMobile = ref(false);
const loading = ref(true);
const listLoading = ref(false);
const saving = ref(false);
const error = ref("");
const options = ref<ProductFeedbackOptions | null>(null);
const items = ref<ProductFeedbackSummary[]>([]);
const total = ref(0);
const selected = ref<ProductFeedbackDetail | null>(null);
const preview = ref<FeedbackPublicationPreview | null>(null);
const editorOpen = ref(false);
const filter = reactive({ status: "all", category: "all", query: "", page: 1, limit: 12 });
const form = reactive({
  category: "bug", component: "other", severity: "normal", title: "", description: "",
  steps: "", expected: "", actual: "", diagnostics: [] as string[],
});
let listController: AbortController | undefined;
let detailController: AbortController | undefined;
let filterTimer: number | undefined;

const categoryLabels: Record<string, string> = { bug: "缺陷", feature: "功能建议", performance: "性能", usability: "易用性", other: "其他" };
const componentLabels: Record<string, string> = { xiaoba: "小巴", stock_pool: "股票池", strategy: "策略管理", model_research: "模型研究", backtest: "回测管理", data_center: "数据管理", system_settings: "系统设置", auth: "登录与账户", runtime: "运行环境", other: "其他" };
const statusLabels: Record<string, string> = { draft: "草稿", submitted: "待审核", triaged: "已分诊", accepted: "已采纳", rejected: "未采纳", duplicate: "重复", withdrawn: "已撤回" };
const publisherHint = computed(() => options.value?.publisher.configured
  ? "平台发布服务已就绪；采纳后可能同步到项目 GitHub Issue。"
  : "平台尚未配置 GitHub 发布服务；反馈仍会安全保存并进入审核队列，你无需配置 GitHub 账号。");

function resize() { isMobile.value = window.innerWidth <= 767; }
function close() {
  const returnTo = typeof route.query.returnTo === "string" && route.query.returnTo.startsWith("/") && !route.query.returnTo.startsWith("//") ? route.query.returnTo : "/agent";
  void router.push(returnTo === "/feedback" ? "/agent" : returnTo);
}
function message(exc: unknown) { return exc instanceof Error ? exc.message : "反馈服务暂时不可用"; }
function dismissed(exc: unknown) { return exc === "cancel" || exc === "close"; }
function resetForm(item?: ProductFeedbackDetail) {
  const content = item?.content;
  form.category = content?.category ?? "bug";
  form.component = content?.component ?? "other";
  form.severity = content?.severity ?? "normal";
  form.title = content?.title ?? "";
  form.description = content?.description ?? "";
  form.steps = content?.reproduction_steps.join("\n") ?? "";
  form.expected = content?.expected_behavior ?? "";
  form.actual = content?.actual_behavior ?? "";
  form.diagnostics = content ? Object.entries(content.diagnostics).filter(([, value]) => value).map(([key]) => key) : [];
  preview.value = null;
}
function content(): ProductFeedbackContent {
  const diagnostics = Object.fromEntries([
    "include_product_version", "include_deployment_kind", "include_browser_family", "include_os_family", "include_performance_summary",
  ].map((key) => [key, form.diagnostics.includes(key)]));
  return {
    schema_version: "product-feedback.v1", category: form.category as ProductFeedbackContent["category"],
    component: form.component as ProductFeedbackContent["component"], severity: form.severity as ProductFeedbackContent["severity"],
    title: form.title, description: form.description,
    reproduction_steps: form.steps.split("\n").map((step) => step.trim()).filter(Boolean),
    expected_behavior: form.expected, actual_behavior: form.actual, diagnostics,
  };
}
async function loadList() {
  listController?.abort();
  listController = new AbortController();
  listLoading.value = true;
  try {
    const page = await listFeedback({ ...filter, offset: (filter.page - 1) * filter.limit }, listController.signal);
    items.value = page.items; total.value = page.total;
  } catch (exc) { if (!(exc instanceof DOMException && exc.name === "AbortError")) error.value = message(exc); }
  finally { listLoading.value = false; }
}
async function bootstrap() {
  loading.value = true; error.value = "";
  try {
    const [choices, page] = await Promise.all([
      getFeedbackOptions(), listFeedback({ status: "all", category: "all", query: "", limit: filter.limit, offset: 0 }),
    ]);
    options.value = choices; items.value = page.items; total.value = page.total;
  } catch (exc) { error.value = message(exc); }
  finally { loading.value = false; }
}
async function selectItem(item: ProductFeedbackSummary) {
  detailController?.abort(); detailController = new AbortController();
  try { selected.value = (await getFeedback(item.feedback_id, detailController.signal)).feedback; }
  catch (exc) { if (!(exc instanceof DOMException && exc.name === "AbortError")) ElMessage.error(message(exc)); }
}
function newDraft() { selected.value = null; resetForm(); editorOpen.value = true; }
function editDraft() { if (selected.value?.status === "draft") { resetForm(selected.value); editorOpen.value = true; } }
async function save() {
  saving.value = true;
  try {
    const result = selected.value ? await updateFeedback(selected.value, content()) : await createFeedback(content());
    selected.value = result.feedback; editorOpen.value = false; await loadList(); ElMessage.success("草稿已保存");
  } catch (exc) { ElMessage.error(message(exc)); } finally { saving.value = false; }
}
async function buildPreview() {
  if (!selected.value) return;
  try { preview.value = await previewFeedback(selected.value); }
  catch (exc) { ElMessage.error(message(exc)); }
}
async function confirmSubmit() {
  if (!selected.value || !preview.value) return;
  try {
    await ElMessageBox.confirm(preview.value.disclosure, "确认提交公开候选快照", { confirmButtonText: "我已检查并提交", cancelButtonText: "继续修改", type: "warning" });
    const result = await submitFeedback(selected.value, preview.value.preview_hash);
    await selectItem(result.feedback); preview.value = null; await loadList(); ElMessage.success("反馈已提交审核");
  } catch (exc) { if (!dismissed(exc)) ElMessage.error(message(exc)); }
}
async function withdraw() {
  if (!selected.value) return;
  try {
    await ElMessageBox.confirm("撤回后此反馈不会继续审核，确定撤回？", "撤回反馈", { confirmButtonText: "确定撤回", cancelButtonText: "取消" });
    const result = await withdrawFeedback(selected.value); await selectItem(result.feedback); await loadList(); ElMessage.success("反馈已撤回");
  } catch (exc) { if (!dismissed(exc)) ElMessage.error(message(exc)); }
}

watch(() => [filter.status, filter.category, filter.query], () => {
  filter.page = 1; window.clearTimeout(filterTimer); filterTimer = window.setTimeout(() => void loadList(), 250);
});
watch(() => filter.page, () => void loadList());
onMounted(() => { resize(); window.addEventListener("resize", resize); void bootstrap(); });
onBeforeUnmount(() => { window.removeEventListener("resize", resize); listController?.abort(); detailController?.abort(); window.clearTimeout(filterTimer); });
</script>

<template>
  <el-dialog :model-value="true" :fullscreen="isMobile" :show-close="false" append-to-body class="feedback-dialog" width="min(1180px, 94vw)" @close="close">
    <template #header="{ titleId }"><header class="feedback-header"><div><span>产品共建</span><h1 :id="titleId">反馈与建议</h1><p>先预览将提交的公开候选内容，再由你明确确认</p></div><el-button circle aria-label="关闭反馈与建议" @click="close"><el-icon><Close /></el-icon></el-button></header></template>
    <div v-if="loading" class="state" aria-live="polite">正在加载反馈工作区…</div>
    <div v-else-if="error && !options" class="state error" role="alert">{{ error }} <el-button link @click="bootstrap">重试</el-button></div>
    <div v-else class="feedback-workspace">
      <aside class="catalogue">
        <div class="catalogue-actions"><el-input v-model="filter.query" clearable placeholder="搜索标题或模块" aria-label="搜索反馈"/><el-button type="primary" :icon="Plus" @click="newDraft">新建</el-button></div>
        <div class="filters"><el-select v-model="filter.status" aria-label="状态过滤"><el-option label="全部状态" value="all"/><el-option v-for="(_, key) in statusLabels" :key="key" :label="statusLabels[key]" :value="key"/></el-select><el-select v-model="filter.category" aria-label="类型过滤"><el-option label="全部类型" value="all"/><el-option v-for="(_, key) in categoryLabels" :key="key" :label="categoryLabels[key]" :value="key"/></el-select></div>
        <div v-loading="listLoading" class="feedback-list" aria-live="polite">
          <button v-for="item in items" :key="item.feedback_id" type="button" :class="{ active: selected?.feedback_id === item.feedback_id }" @click="selectItem(item)"><strong>{{ item.title }}</strong><span>{{ componentLabels[item.component] }} · {{ statusLabels[item.status] }}</span><small>{{ new Date(item.updated_at).toLocaleString() }}</small></button>
          <p v-if="!items.length" class="empty">暂无匹配反馈</p>
        </div>
        <el-pagination v-if="total > filter.limit" v-model:current-page="filter.page" small background layout="prev, pager, next" :page-size="filter.limit" :total="total"/>
      </aside>
      <main class="detail">
        <div v-if="!selected && !editorOpen" class="empty detail-empty"><strong>选择一条反馈查看详情</strong><span>{{ publisherHint }}</span></div>
        <section v-else-if="editorOpen" class="editor" aria-label="反馈草稿编辑器">
          <div class="section-title"><div><span>私有草稿</span><h2>{{ selected ? "编辑反馈" : "新建反馈" }}</h2></div><el-button @click="editorOpen=false">取消</el-button></div>
          <el-form label-position="top" @submit.prevent="save"><div class="form-grid"><el-form-item label="类型"><el-select v-model="form.category"><el-option v-for="value in options?.categories" :key="value" :label="categoryLabels[value]" :value="value"/></el-select></el-form-item><el-form-item label="模块"><el-select v-model="form.component"><el-option v-for="value in options?.components" :key="value" :label="componentLabels[value]" :value="value"/></el-select></el-form-item><el-form-item label="影响程度"><el-select v-model="form.severity"><el-option label="低" value="low"/><el-option label="一般" value="normal"/><el-option label="高" value="high"/></el-select></el-form-item></div><el-form-item label="标题"><el-input v-model="form.title" maxlength="160" show-word-limit/></el-form-item><el-form-item label="问题或建议描述"><el-input v-model="form.description" type="textarea" :rows="4" maxlength="8000" show-word-limit/></el-form-item><el-form-item label="复现步骤（每行一步，最多 12 步）"><el-input v-model="form.steps" type="textarea" :rows="3"/></el-form-item><div class="two-column"><el-form-item label="期望行为"><el-input v-model="form.expected" type="textarea" :rows="2"/></el-form-item><el-form-item label="实际行为"><el-input v-model="form.actual" type="textarea" :rows="2"/></el-form-item></div><el-form-item label="可选环境信息"><el-checkbox-group v-model="form.diagnostics"><el-checkbox value="include_product_version">产品版本</el-checkbox><el-checkbox value="include_deployment_kind">部署类型</el-checkbox><el-checkbox value="include_browser_family">浏览器类型</el-checkbox><el-checkbox value="include_os_family">操作系统</el-checkbox><el-checkbox value="include_performance_summary">性能摘要</el-checkbox></el-checkbox-group></el-form-item><el-alert title="请勿填写密钥、邮箱、外部链接或安全漏洞；安全问题应使用项目私密安全通道。" type="warning" :closable="false"/><div class="form-actions"><el-button type="primary" native-type="submit" :loading="saving">保存草稿</el-button></div></el-form>
        </section>
        <section v-else-if="selected" class="selected-detail">
          <div class="section-title"><div><span>{{ statusLabels[selected.status] }}</span><h2>{{ selected.title }}</h2><p>{{ categoryLabels[selected.category] }} · {{ componentLabels[selected.component] }} · 版本 {{ selected.version }}</p></div><el-button v-if="selected.status==='draft'" @click="editDraft">编辑</el-button></div>
          <p class="description">{{ selected.content.description }}</p>
          <dl><template v-if="selected.content.reproduction_steps.length"><dt>复现步骤</dt><dd><ol><li v-for="step in selected.content.reproduction_steps" :key="step">{{ step }}</li></ol></dd></template><dt>期望行为</dt><dd>{{ selected.content.expected_behavior || "未填写" }}</dd><dt>实际行为</dt><dd>{{ selected.content.actual_behavior || "未填写" }}</dd></dl>
          <el-alert :title="publisherHint" :type="options?.publisher.configured ? 'success' : 'info'" :closable="false"/>
          <template v-if="selected.github_issue"><a class="issue-link" :href="selected.github_issue.html_url" target="_blank" rel="noopener noreferrer">查看 GitHub Issue #{{ selected.github_issue.issue_number }}</a></template>
          <div v-if="selected.status==='draft'" class="submit-zone"><el-button @click="buildPreview">生成提交预览</el-button><section v-if="preview" class="preview"><h3>公开候选快照</h3><pre>{{ JSON.stringify(preview.public_content, null, 2) }}</pre><p>{{ preview.disclosure }}</p><el-button type="primary" @click="confirmSubmit">检查无误，确认提交</el-button></section></div>
          <el-button v-if="selected.status==='submitted'" type="danger" plain @click="withdraw">撤回反馈</el-button>
        </section>
      </main>
    </div>
  </el-dialog>
</template>

<style scoped>
.feedback-header,.section-title,.catalogue-actions,.filters,.form-actions{display:flex;align-items:center;justify-content:space-between;gap:10px}.feedback-header span,.section-title span{color:var(--byq-brand);font-size:11px;font-weight:850;letter-spacing:.1em}.feedback-header h1,.section-title h2{color:var(--byq-text);margin:3px 0}.feedback-header h1{font-size:22px}.feedback-header p,.section-title p{color:var(--byq-text-muted);font-size:12px;margin:0}.feedback-workspace{display:grid;grid-template-columns:340px minmax(0,1fr);height:min(74vh,800px);min-height:580px}.catalogue{border-right:1px solid var(--byq-border);display:flex;flex-direction:column;gap:10px;min-height:0;padding:14px 14px 14px 0}.catalogue-actions .el-input{min-width:0}.filters .el-select{width:50%}.feedback-list{display:grid;align-content:start;gap:6px;flex:1;min-height:0;overflow-y:auto}.feedback-list button{background:transparent;border:1px solid transparent;border-radius:8px;color:var(--byq-text);cursor:pointer;display:grid;gap:3px;padding:10px;text-align:left}.feedback-list button:hover,.feedback-list button.active{background:var(--byq-brand-soft);border-color:var(--byq-border)}.feedback-list span,.feedback-list small,.empty{color:var(--byq-text-muted);font-size:12px}.detail{min-width:0;overflow-y:auto;padding:18px 4px 18px 20px}.detail-empty{display:flex;flex-direction:column;gap:8px;justify-content:center;min-height:100%;text-align:center}.editor,.selected-detail{display:grid;gap:16px}.form-grid{display:grid;gap:12px;grid-template-columns:repeat(3,1fr)}.two-column{display:grid;gap:12px;grid-template-columns:1fr 1fr}.el-select{width:100%}.description{line-height:1.7;white-space:pre-wrap}dl{display:grid;gap:8px;margin:0}dt{color:var(--byq-text-muted);font-size:12px;font-weight:800}dd{line-height:1.6;margin:0;white-space:pre-wrap}.submit-zone,.preview{display:grid;gap:10px}.preview{background:var(--byq-surface-subtle);border:1px solid var(--byq-border);border-radius:10px;padding:14px}.preview pre{font-size:12px;max-height:260px;overflow:auto;white-space:pre-wrap}.issue-link{color:var(--byq-brand);font-weight:750}.state{padding:80px;text-align:center}.error{color:var(--el-color-danger)}
@media(max-width:767px){.feedback-workspace{display:block;height:auto;min-height:0}.catalogue{border-bottom:1px solid var(--byq-border);border-right:0;height:42vh;padding:12px}.detail{height:calc(58vh - 112px);padding:14px}.form-grid,.two-column{grid-template-columns:1fr}.feedback-header h1{font-size:20px}.feedback-header p{max-width:260px}}
</style>

<style>
.feedback-dialog{--el-dialog-bg-color:var(--byq-surface);background:var(--byq-surface);border:1px solid var(--byq-border);border-radius:14px;margin-top:5vh;overflow:hidden}.feedback-dialog .el-dialog__header{border-bottom:1px solid var(--byq-border);margin:0;padding:14px 18px}.feedback-dialog .el-dialog__body{padding:0 18px}@media(max-width:767px){.feedback-dialog{border:0;border-radius:0;margin:0}.feedback-dialog .el-dialog__header{padding:10px 14px}.feedback-dialog .el-dialog__body{padding:0}}
</style>

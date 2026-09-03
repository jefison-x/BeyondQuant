<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { getFeedbackAudit, getFeedbackModeration, getFeedbackPublisherStatus, listFeedbackModeration, moderateFeedback } from "@/api/feedback";
import type { FeedbackAuditPage, FeedbackModerationItem, FeedbackPublisherStatus } from "@/api/types";

const items = ref<FeedbackModerationItem[]>([]);
const selected = ref<FeedbackModerationItem | null>(null);
const publisher = ref<FeedbackPublisherStatus | null>(null);
const audit = ref<FeedbackAuditPage | null>(null);
const loading = ref(true);
const error = ref("");
const total = ref(0);
const filters = reactive({ status: "submitted", category: "all", query: "", page: 1, limit: 15 });
let catalogueController: AbortController | undefined;
let detailController: AbortController | undefined;
let timer: number | undefined;
const statusLabels: Record<string, string> = { submitted: "待审核", triaged: "已分诊", accepted: "已采纳", rejected: "未采纳", duplicate: "重复" };
const categoryLabels: Record<string, string> = { bug: "缺陷", feature: "功能建议", performance: "性能", usability: "易用性", other: "其他" };
const componentLabels: Record<string, string> = { xiaoba: "小巴", stock_pool: "股票池", strategy: "策略管理", model_research: "模型研究", backtest: "回测管理", data_center: "数据管理", system_settings: "系统设置", auth: "登录与账户", runtime: "运行环境", other: "其他" };
function detail(exc: unknown) { return exc instanceof Error ? exc.message : "审核列表暂时不可用"; }
function dismissed(exc: unknown) { return exc === "cancel" || exc === "close"; }
async function load() {
  catalogueController?.abort(); catalogueController = new AbortController(); loading.value = true; error.value = "";
  try {
    const page = await listFeedbackModeration({ ...filters, offset: (filters.page - 1) * filters.limit }, catalogueController.signal);
    items.value = page.items; total.value = page.total;
  } catch (exc) { if (!(exc instanceof DOMException && exc.name === "AbortError")) error.value = detail(exc); }
  finally { loading.value = false; }
}
async function bootstrap() {
  try {
    const [page, status] = await Promise.all([
      listFeedbackModeration({ status: filters.status, category: filters.category, query: filters.query, limit: filters.limit, offset: 0 }),
      getFeedbackPublisherStatus(),
    ]);
    items.value = page.items; total.value = page.total; publisher.value = status;
  } catch (exc) { error.value = detail(exc); } finally { loading.value = false; }
}
async function open(item: FeedbackModerationItem) {
  detailController?.abort(); detailController = new AbortController(); audit.value = null;
  try { selected.value = (await getFeedbackModeration(item.feedback_id, detailController.signal)).feedback; }
  catch (exc) { if (!(exc instanceof DOMException && exc.name === "AbortError")) ElMessage.error(detail(exc)); }
}
async function loadAudit(offset = 0) {
  if (!selected.value) return;
  try { audit.value = await getFeedbackAudit(selected.value.feedback_id, offset); }
  catch (exc) { ElMessage.error(detail(exc)); }
}
async function act(action: "triage" | "accept" | "reject" | "duplicate") {
  if (!selected.value) return;
  const title = { triage: "标记已分诊", accept: "采纳并进入发布队列", reject: "不采纳", duplicate: "标记为重复" }[action];
  try {
    const rationale = await ElMessageBox.prompt("填写审核理由（会进入审计记录）", title, {
      confirmButtonText: "确定", cancelButtonText: "取消",
      inputPattern: /.{2,}/, inputErrorMessage: "至少填写 2 个字符",
    });
    let canonical = "";
    if (action === "duplicate") canonical = (await ElMessageBox.prompt("填写已分诊或已采纳反馈的反馈编号", "关联主反馈", {
      confirmButtonText: "确定", cancelButtonText: "取消",
      inputPattern: /^feedback_[0-9a-f]{32}$/, inputErrorMessage: "反馈编号格式不正确",
    })).value;
    selected.value = (await moderateFeedback(selected.value, action, rationale.value, canonical)).feedback;
    await Promise.all([load(), getFeedbackPublisherStatus().then((value) => { publisher.value = value; })]);
    ElMessage.success(`${title}完成`);
  } catch (exc) { if (!dismissed(exc)) ElMessage.error(detail(exc)); }
}
watch(() => [filters.status, filters.category, filters.query], () => { filters.page = 1; clearTimeout(timer); timer = window.setTimeout(() => void load(), 250); });
watch(() => filters.page, () => void load());
onMounted(() => void bootstrap());
onBeforeUnmount(() => { catalogueController?.abort(); detailController?.abort(); clearTimeout(timer); });
</script>

<template>
  <div class="admin-feedback">
    <el-alert v-if="publisher" :type="publisher.configured && publisher.status==='ready' ? 'success' : 'warning'" :closable="false" show-icon>
      <template #title>{{ publisher.configured ? `GitHub 发布服务：${publisher.status === 'ready' ? '就绪' : '状态陈旧'}` : "GitHub 发布服务未配置" }}</template>
      <p>{{ publisher.configured ? `目标仓库 ${publisher.repository}；队列 ${publisher.queue.queued}，重试 ${publisher.queue.retry_wait}。` : "反馈审核功能可正常使用；采纳项会安全排队，部署管理员配置平台凭据后自动发布。普通用户无需配置。" }}</p>
    </el-alert>
    <div class="toolbar"><el-input v-model="filters.query" clearable placeholder="搜索标题或模块" aria-label="搜索审核反馈"/><el-select v-model="filters.status" aria-label="审核状态"><el-option label="全部状态" value="all"/><el-option v-for="(_, key) in statusLabels" :key="key" :label="statusLabels[key]" :value="key"/></el-select><el-select v-model="filters.category" aria-label="反馈类型"><el-option label="全部类型" value="all"/><el-option v-for="(_, key) in categoryLabels" :key="key" :label="categoryLabels[key]" :value="key"/></el-select></div>
    <div v-if="error" class="error" role="alert">{{ error }} <el-button link @click="load">重试</el-button></div>
    <div class="moderation-grid">
      <section v-loading="loading" class="inbox" aria-label="反馈审核列表">
        <button v-for="item in items" :key="item.feedback_id" type="button" :class="{ active: selected?.feedback_id===item.feedback_id }" @click="open(item)"><strong>{{ item.title }}</strong><span>{{ categoryLabels[item.category] }} · {{ componentLabels[item.component] }} · {{ statusLabels[item.status] }}</span><small>{{ item.feedback_id }}</small></button>
        <p v-if="!loading && !items.length" class="empty">当前筛选条件下没有反馈</p>
        <el-pagination v-if="total > filters.limit" v-model:current-page="filters.page" small background layout="prev, pager, next" :page-size="filters.limit" :total="total"/>
      </section>
      <section class="moderation-detail">
        <p v-if="!selected" class="empty">选择一条反馈查看经用户确认的公开候选快照</p>
        <template v-else><div class="title"><div><el-tag effect="plain">{{ statusLabels[selected.status] }}</el-tag><h3>{{ selected.title }}</h3><p>{{ selected.feedback_id }} · 版本 {{ selected.version }}</p></div></div><dl><template v-for="(value,key) in selected.submitted_snapshot.public_content" :key="key"><dt>{{ key }}</dt><dd><pre>{{ typeof value === 'string' ? value : JSON.stringify(value, null, 2) }}</pre></dd></template></dl><div class="actions"><el-button v-if="selected.status==='submitted'" type="primary" @click="act('triage')">完成分诊</el-button><template v-if="selected.status==='triaged'"><el-button type="success" @click="act('accept')">采纳</el-button><el-button @click="act('duplicate')">标记重复</el-button><el-button type="danger" plain @click="act('reject')">不采纳</el-button></template><a v-if="selected.github_issue" :href="selected.github_issue.html_url" target="_blank" rel="noopener noreferrer">GitHub Issue #{{ selected.github_issue.issue_number }}</a></div><el-button link @click="loadAudit(0)">加载审计记录</el-button><div v-if="audit" class="audit"><div v-for="row in audit.audit" :key="row.audit_id"><strong>{{ row.action }}</strong><span>{{ row.from_status || '创建' }} → {{ row.to_status }}</span><small>{{ row.rationale || '无补充理由' }} · {{ new Date(row.created_at).toLocaleString() }}</small></div><el-button v-if="audit.has_more" link @click="loadAudit(audit.offset + audit.limit)">下一页审计</el-button></div></template>
      </section>
    </div>
  </div>
</template>

<style scoped>
.admin-feedback{display:grid;gap:14px}.admin-feedback :deep(.el-alert__content p){margin:4px 0 0}.toolbar{display:grid;gap:10px;grid-template-columns:minmax(180px,1fr) 160px 160px}.moderation-grid{border:1px solid var(--byq-border);border-radius:10px;display:grid;grid-template-columns:300px minmax(0,1fr);min-height:430px;overflow:hidden}.inbox{border-right:1px solid var(--byq-border);display:grid;align-content:start;gap:5px;max-height:560px;overflow-y:auto;padding:10px}.inbox button{background:transparent;border:1px solid transparent;border-radius:8px;color:var(--byq-text);cursor:pointer;display:grid;gap:3px;padding:9px;text-align:left}.inbox button:hover,.inbox button.active{background:var(--byq-brand-soft);border-color:var(--byq-border)}.inbox span,.inbox small,.title p,.empty{color:var(--byq-text-muted);font-size:11px}.moderation-detail{max-height:560px;overflow-y:auto;padding:14px}.title h3{margin:8px 0 3px}.title p{margin:0}dl{display:grid;gap:4px}dt{color:var(--byq-text-muted);font-size:11px;font-weight:800}dd{margin:0}pre{font:inherit;line-height:1.55;margin:0;overflow-wrap:anywhere;white-space:pre-wrap}.actions{align-items:center;display:flex;flex-wrap:wrap;gap:8px;margin:16px 0}.actions a{color:var(--byq-brand);font-weight:750}.audit{border-top:1px solid var(--byq-border);display:grid;gap:8px;margin-top:8px;padding-top:10px}.audit>div{display:grid;gap:2px}.audit span,.audit small{color:var(--byq-text-muted);font-size:11px}.error{color:var(--el-color-danger)}
@media(max-width:767px){.toolbar{grid-template-columns:1fr}.moderation-grid{display:block}.inbox{border-bottom:1px solid var(--byq-border);border-right:0;max-height:240px}.moderation-detail{max-height:none}}
</style>

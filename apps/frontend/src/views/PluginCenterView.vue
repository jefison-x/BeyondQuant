<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { getPluginCenter, getPluginDetail, requestPluginChange, requestPluginQualification } from "@/api/plugins";
import type { PluginCatalogItem, PluginCenter, PluginDetail } from "@/api/types";

const loading = ref(true);
const error = ref("");
const data = ref<PluginCenter | null>(null);
const detail = ref<PluginDetail | null>(null);
const detailOpen = ref(false);
const submitting = ref(false);
const reason = ref("");
const selectedAgents = ref<string[]>([]);

const metrics = computed(() => ["AVAILABLE", "QUALIFIED", "ENABLED", "BLOCKED"].map((state) => ({ state, count: data.value?.counts[state] ?? 0 })));

function tagType(state: string): "success" | "warning" | "danger" | "info" {
  if (state === "ENABLED" || state === "QUALIFIED" || state === "ready") return "success";
  if (state === "BLOCKED" || state === "partial" || state.includes("awaiting")) return "warning";
  if (state === "REJECTED" || state === "PROHIBITED" || state === "HIGH") return "danger";
  return "info";
}

async function load() {
  loading.value = true; error.value = "";
  try { data.value = await getPluginCenter(); }
  catch (exc) { error.value = exc instanceof Error ? exc.message : "插件中心加载失败"; }
  finally { loading.value = false; }
}

async function openDetail(plugin: PluginCatalogItem) {
  detailOpen.value = true; detail.value = null; reason.value = ""; selectedAgents.value = [...plugin.desired_agents];
  try { detail.value = await getPluginDetail(plugin.id); }
  catch (exc) { ElMessage.error(exc instanceof Error ? exc.message : "插件详情加载失败"); }
}

function key() { return `plugin-ui-${Date.now()}-${Math.random().toString(16).slice(2)}`; }

async function change(action: "enable" | "disable" | "assign") {
  if (!data.value || !detail.value) return;
  if (!reason.value.trim()) { ElMessage.warning("请填写变更原因"); return; }
  const plugin = detail.value.plugin;
  const verb = action === "enable" ? "启用" : action === "disable" ? "停用" : "修改 Agent 授权";
  await ElMessageBox.confirm(`${verb} ${plugin.display_name} 会创建部署变更请求，不会在线修改运行时。`, "确认受控变更", { type: "warning", confirmButtonText: "创建请求", cancelButtonText: "取消" });
  submitting.value = true;
  try {
    await requestPluginChange({ action, plugin_id: plugin.id, ...(action === "assign" ? { allowed_agents: selectedAgents.value } : {}), expected_version: data.value.policy.version, idempotency_key: key(), reason: reason.value.trim() });
    ElMessage.success("请求已验证，等待正常组合生成与部署；当前运行版本未被修改");
    detailOpen.value = false; await load();
  } catch (exc) { ElMessage.error(exc instanceof Error ? exc.message : "请求失败"); }
  finally { submitting.value = false; }
}

async function qualify() {
  if (!data.value || !detail.value) return;
  if (!reason.value.trim()) { ElMessage.warning("请填写 Qualification 原因"); return; }
  submitting.value = true;
  try {
    await requestPluginQualification({ plugin_id: detail.value.plugin.id, version: detail.value.plugin.qualified_version, expected_version: data.value.policy.version, idempotency_key: key(), reason: reason.value.trim() });
    ElMessage.success("Qualification 已排队，不会自动启用插件"); detailOpen.value = false; await load();
  } catch (exc) { ElMessage.error(exc instanceof Error ? exc.message : "请求失败"); }
  finally { submitting.value = false; }
}

onMounted(load);
</script>

<template>
  <section class="plugin-center">
    <div class="toolbar">
      <el-alert title="Plugin Center 只创建受审计的策略与资格请求；不执行 npm install、热安装或运行时修改。" type="info" show-icon :closable="false" />
      <el-button :loading="loading" @click="load">刷新</el-button>
    </div>
    <div v-if="loading && !data" class="base-loading" role="status">正在读取真实 Registry 与 Runtime identity...</div>
    <div v-else-if="error && !data" class="base-error" role="alert">{{ error }} <el-button link type="primary" @click="load">重试</el-button></div>
    <template v-else-if="data">
      <el-alert v-if="data.projection_status === 'partial'" title="Runtime Adapter 暂不可用；Registry 可查看，但 Active 状态不作推断。" type="warning" show-icon :closable="false" />
      <div class="metrics">
        <el-card v-for="metric in metrics" :key="metric.state" shadow="never"><span>{{ metric.state }}</span><strong>{{ metric.count }}</strong></el-card>
      </div>
      <el-card shadow="never" class="identity">
        <template #header><strong>Runtime 与组合身份</strong></template>
        <el-descriptions :column="2" border>
          <el-descriptions-item label="DSH SDK">{{ data.runtime.sdk ?? data.runtime_baseline.python_sdk }}</el-descriptions-item>
          <el-descriptions-item label="runtime-bin">{{ data.runtime.runtime_bin ?? data.runtime_baseline.runtime_bin }}</el-descriptions-item>
          <el-descriptions-item label="Active profile">{{ data.runtime.active_profile ?? "不可用" }}</el-descriptions-item>
          <el-descriptions-item label="Policy version">v{{ data.policy.version }}</el-descriptions-item>
          <el-descriptions-item label="Composition hash" :span="2"><code>{{ data.runtime.active_composition_hash ?? "不可用" }}</code></el-descriptions-item>
          <el-descriptions-item label="Desired / Active">
            <el-tag :type="data.runtime.desired_matches_active_plugins ? 'success' : 'warning'">{{ data.runtime.desired_matches_active_plugins ? "一致 · Active" : "待生成/部署" }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="安全边界">无在线安装 · 无运行时修改 · 无 secret 投影</el-descriptions-item>
        </el-descriptions>
      </el-card>
      <el-card shadow="never">
        <template #header><strong>官方插件目录</strong></template>
        <el-empty v-if="!data.plugins.length" description="Registry 中暂无插件" />
        <el-table v-else :data="data.plugins" row-key="id" @row-click="openDetail">
          <el-table-column label="插件" min-width="210"><template #default="{ row }"><strong>{{ row.display_name }}</strong><small class="block">{{ row.packages[0]?.name ?? row.id }}</small></template></el-table-column>
          <el-table-column label="资格 / 生效" min-width="165"><template #default="{ row }"><el-tag :type="tagType(row.qualification_state)">{{ row.qualification_state }}</el-tag> <el-tag v-if="row.active" type="success" effect="plain">ACTIVE</el-tag><el-tag v-else-if="row.desired_enabled" type="warning" effect="plain">DESIRED</el-tag></template></el-table-column>
          <el-table-column label="风险" width="110"><template #default="{ row }"><el-tag :type="tagType(row.risk.level)" effect="plain">{{ row.risk.level }}</el-tag></template></el-table-column>
          <el-table-column label="能力" min-width="180"><template #default="{ row }">{{ row.capabilities.join(", ") || "无外部能力" }}</template></el-table-column>
          <el-table-column label="Agent" min-width="180"><template #default="{ row }">{{ row.desired_agents.join(", ") || "未分配" }}</template></el-table-column>
          <el-table-column label="凭证" width="110"><template #default="{ row }">{{ row.credential_required ? (row.credential_configured ? "已配置" : "未配置") : "不需要" }}</template></el-table-column>
          <el-table-column label="操作" width="84" fixed="right"><template #default="{ row }"><el-button link type="primary" :aria-label="`查看 ${row.display_name} 详情`" @click.stop="openDetail(row)">查看</el-button></template></el-table-column>
        </el-table>
      </el-card>
      <el-card shadow="never">
        <template #header><strong>最近治理请求</strong></template>
        <el-empty v-if="!data.requests.length" description="暂无变更或 Qualification 请求" />
        <el-table v-else :data="data.requests" size="small">
          <el-table-column prop="plugin_id" label="Plugin" min-width="130" />
          <el-table-column prop="request_kind" label="动作" width="100" />
          <el-table-column label="状态" min-width="190"><template #default="{ row }"><el-tag :type="tagType(row.status)">{{ row.status }}</el-tag> <span class="block">{{ row.deployment_state }}</span></template></el-table-column>
          <el-table-column prop="actor_principal" label="Actor" min-width="130" />
          <el-table-column prop="reason" label="原因" min-width="220" show-overflow-tooltip />
        </el-table>
      </el-card>
    </template>

    <el-drawer v-model="detailOpen" title="Plugin Qualification 与策略" size="min(680px, 96vw)">
      <div v-if="!detail" class="base-loading" role="status">正在读取资格证据...</div>
      <div v-else class="detail">
        <div><h3>{{ detail.plugin.display_name }}</h3><p>{{ detail.plugin.description }}</p></div>
        <el-descriptions :column="1" border>
          <el-descriptions-item label="Package"><code>{{ detail.plugin.packages.map(item => `${item.name}@${item.version}`).join(" · ") }}</code></el-descriptions-item>
          <el-descriptions-item label="状态"><el-tag :type="tagType(detail.plugin.qualification_state)">{{ detail.plugin.qualification_state }}</el-tag> <el-tag v-if="detail.plugin.active" type="success">ACTIVE</el-tag></el-descriptions-item>
          <el-descriptions-item label="兼容性">{{ detail.plugin.compatibility.status }}</el-descriptions-item>
          <el-descriptions-item label="风险">{{ detail.plugin.risk.level }} · {{ detail.plugin.risk.reasons.join("；") }}</el-descriptions-item>
          <el-descriptions-item label="能力">{{ detail.plugin.capabilities.join(", ") || "无外部能力" }}</el-descriptions-item>
          <el-descriptions-item label="证据 ID">{{ detail.plugin.evidence_refs.join(", ") }}</el-descriptions-item>
          <el-descriptions-item label="原因">{{ detail.plugin.qualification_reason }}</el-descriptions-item>
        </el-descriptions>
        <el-form label-position="top">
          <el-form-item label="Agent assignment">
            <el-checkbox-group v-model="selectedAgents"><el-checkbox v-for="agent in detail.plugin.allowed_agents" :key="agent" :value="agent">{{ agent }}</el-checkbox></el-checkbox-group>
          </el-form-item>
          <el-form-item label="审计原因"><el-input v-model="reason" type="textarea" :rows="3" maxlength="500" show-word-limit placeholder="说明为什么需要这次策略或资格变更" /></el-form-item>
        </el-form>
        <div class="actions">
          <el-button :loading="submitting" @click="qualify">发起 Qualification</el-button>
          <el-button v-if="detail.plugin.desired_enabled" :loading="submitting" @click="change('assign')">保存 Agent assignment</el-button>
          <el-button v-if="detail.plugin.desired_enabled" type="danger" plain :loading="submitting" @click="change('disable')">创建停用部署请求</el-button>
          <el-button v-else type="primary" :disabled="detail.plugin.qualification_state !== 'QUALIFIED' || ['HIGH', 'PROHIBITED'].includes(detail.plugin.risk.level)" :loading="submitting" @click="change('enable')">创建启用部署请求</el-button>
        </div>
      </div>
    </el-drawer>
  </section>
</template>

<style scoped>
.plugin-center,.detail{display:grid;gap:16px}.toolbar{align-items:start;display:grid;gap:12px;grid-template-columns:minmax(0,1fr) auto}.metrics{display:grid;gap:12px;grid-template-columns:repeat(4,minmax(0,1fr))}.metrics span,.block{color:var(--byq-text-muted);display:block;font-size:12px}.metrics strong{display:block;font-size:25px;margin-top:6px}.identity code,td code{overflow-wrap:anywhere}.detail h3{margin:0}.detail p{color:var(--byq-text-muted);margin:5px 0 0}.actions{display:flex;flex-wrap:wrap;gap:8px}@media(max-width:800px){.metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.toolbar{grid-template-columns:1fr}.toolbar .el-button{width:100%}.identity :deep(.el-descriptions__body){overflow-x:auto}}
</style>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { getPluginCenter, getPluginDetail, requestPluginChange, requestPluginQualification } from "@/api/plugins";
import type { PluginCatalogItem, PluginCenter, PluginDetail } from "@/api/types";
import {
  pluginActionLabel,
  pluginAgentLabel,
  pluginCapabilityLabel,
  pluginCompatibilityLabel,
  pluginRiskLabel,
  pluginStatusLabel,
} from "@/utils/pluginLabels";

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
  if (!reason.value.trim()) { ElMessage.warning("请填写资格认证原因"); return; }
  submitting.value = true;
  try {
    await requestPluginQualification({ plugin_id: detail.value.plugin.id, version: detail.value.plugin.qualified_version, expected_version: data.value.policy.version, idempotency_key: key(), reason: reason.value.trim() });
    ElMessage.success("资格认证已排队，不会自动启用插件"); detailOpen.value = false; await load();
  } catch (exc) { ElMessage.error(exc instanceof Error ? exc.message : "请求失败"); }
  finally { submitting.value = false; }
}

onMounted(load);
</script>

<template>
  <section class="plugin-center">
    <div class="toolbar">
      <el-alert title="插件中心只创建受审计的策略与资格请求；不执行 npm install、热安装或运行时修改。" type="info" show-icon :closable="false" />
      <el-button :loading="loading" @click="load">刷新</el-button>
    </div>
    <div v-if="loading && !data" class="base-loading" role="status">正在读取真实 Registry 与 Runtime identity...</div>
    <div v-else-if="error && !data" class="base-error" role="alert">{{ error }} <el-button link type="primary" @click="load">重试</el-button></div>
    <template v-else-if="data">
      <el-alert v-if="data.projection_status === 'partial'" title="Runtime Adapter 暂不可用；Registry 可查看，但 Active 状态不作推断。" type="warning" show-icon :closable="false" />
      <div class="metrics">
        <el-card v-for="metric in metrics" :key="metric.state" shadow="never"><span>{{ pluginStatusLabel(metric.state) }}</span><strong>{{ metric.count }}</strong></el-card>
      </div>
      <el-card shadow="never" class="identity">
        <template #header><strong>Runtime 与组合身份</strong></template>
        <dl class="identity-grid">
          <div><dt>DSH SDK</dt><dd>{{ data.runtime.sdk ?? data.runtime_baseline.python_sdk }}</dd></div>
          <div><dt>runtime-bin</dt><dd>{{ data.runtime.runtime_bin ?? data.runtime_baseline.runtime_bin }}</dd></div>
          <div><dt>Active profile</dt><dd>{{ data.runtime.active_profile ?? "不可用" }}</dd></div>
          <div><dt>Policy version</dt><dd>v{{ data.policy.version }}</dd></div>
          <div class="wide"><dt>Composition hash</dt><dd><code>{{ data.runtime.active_composition_hash ?? "不可用" }}</code></dd></div>
          <div><dt>Desired / Active</dt><dd><el-tag :type="data.runtime.desired_matches_active_plugins ? 'success' : 'warning'">{{ data.runtime.desired_matches_active_plugins ? "一致 · Active" : "待生成/部署" }}</el-tag></dd></div>
          <div><dt>安全边界</dt><dd>无在线安装 · 无运行时修改 · 无 secret 投影</dd></div>
        </dl>
      </el-card>
      <el-card shadow="never">
        <template #header><strong>官方插件目录</strong></template>
        <el-empty v-if="!data.plugins.length" description="Registry 中暂无插件" />
        <el-table v-else class="desktop-table" :data="data.plugins" row-key="id" @row-click="openDetail">
          <el-table-column label="插件" min-width="210"><template #default="{ row }"><strong>{{ row.display_name }}</strong><small class="block">{{ row.packages[0]?.name ?? row.id }}</small></template></el-table-column>
          <el-table-column label="资格 / 生效" min-width="165"><template #default="{ row }"><el-tag :type="tagType(row.qualification_state)">{{ pluginStatusLabel(row.qualification_state) }}</el-tag> <el-tag v-if="row.active" type="success" effect="plain">运行中</el-tag><el-tag v-else-if="row.desired_enabled" type="warning" effect="plain">待部署</el-tag></template></el-table-column>
          <el-table-column label="风险" width="110"><template #default="{ row }"><el-tag :type="tagType(row.risk.level)" effect="plain">{{ pluginRiskLabel(row.risk.level) }}</el-tag></template></el-table-column>
          <el-table-column label="能力" min-width="180"><template #default="{ row }">{{ row.capabilities.map(pluginCapabilityLabel).join("、") || "无外部能力" }}</template></el-table-column>
          <el-table-column label="Agent" min-width="180"><template #default="{ row }">{{ row.desired_agents.map(pluginAgentLabel).join("、") || "未分配" }}</template></el-table-column>
          <el-table-column label="凭证" width="110"><template #default="{ row }">{{ row.credential_required ? (row.credential_configured ? "已配置" : "未配置") : "不需要" }}</template></el-table-column>
          <el-table-column label="操作" width="84" fixed="right"><template #default="{ row }"><el-button link type="primary" :aria-label="`查看 ${row.display_name} 详情`" @click.stop="openDetail(row)">查看</el-button></template></el-table-column>
        </el-table>
        <div v-if="data.plugins.length" class="mobile-list" aria-label="官方插件目录">
          <article v-for="plugin in data.plugins" :key="plugin.id" class="mobile-card">
            <div><strong>{{ plugin.display_name }}</strong><small>{{ plugin.packages[0]?.name ?? plugin.id }}</small></div>
            <dl>
              <div><dt>资格 / 生效</dt><dd><el-tag :type="tagType(plugin.qualification_state)">{{ pluginStatusLabel(plugin.qualification_state) }}</el-tag> <el-tag v-if="plugin.active" type="success" effect="plain">运行中</el-tag><el-tag v-else-if="plugin.desired_enabled" type="warning" effect="plain">待部署</el-tag></dd></div>
              <div><dt>风险</dt><dd><el-tag :type="tagType(plugin.risk.level)" effect="plain">{{ pluginRiskLabel(plugin.risk.level) }}</el-tag></dd></div>
              <div><dt>能力</dt><dd>{{ plugin.capabilities.map(pluginCapabilityLabel).join("、") || "无外部能力" }}</dd></div>
              <div><dt>Agent</dt><dd>{{ plugin.desired_agents.map(pluginAgentLabel).join("、") || "未分配" }}</dd></div>
              <div><dt>凭证</dt><dd>{{ plugin.credential_required ? (plugin.credential_configured ? "已配置" : "未配置") : "不需要" }}</dd></div>
            </dl>
            <el-button type="primary" plain @click="openDetail(plugin)">查看详情</el-button>
          </article>
        </div>
      </el-card>
      <el-card shadow="never">
        <template #header><strong>最近治理请求</strong></template>
        <el-empty v-if="!data.requests.length" description="暂无变更或资格认证请求" />
        <el-table v-else class="desktop-table" :data="data.requests" size="small">
          <el-table-column prop="plugin_id" label="插件" min-width="130" />
          <el-table-column label="动作" width="130"><template #default="{ row }">{{ pluginActionLabel(row.request_kind) }}</template></el-table-column>
          <el-table-column label="状态" min-width="190"><template #default="{ row }"><el-tag :type="tagType(row.status)">{{ pluginStatusLabel(row.status) }}</el-tag> <span class="block">{{ pluginStatusLabel(row.deployment_state) }}</span></template></el-table-column>
          <el-table-column prop="actor_principal" label="Actor" min-width="130" />
          <el-table-column prop="reason" label="原因" min-width="220" show-overflow-tooltip />
        </el-table>
        <div v-if="data.requests.length" class="mobile-list" aria-label="最近治理请求">
          <article v-for="request in data.requests" :key="request.request_id" class="mobile-card request-card">
            <strong>{{ request.plugin_id }}</strong>
            <dl>
              <div><dt>动作</dt><dd>{{ pluginActionLabel(request.request_kind) }}</dd></div>
              <div><dt>状态</dt><dd>{{ pluginStatusLabel(request.status) }} · {{ pluginStatusLabel(request.deployment_state) }}</dd></div>
              <div><dt>Actor</dt><dd>{{ request.actor_principal }}</dd></div>
              <div><dt>原因</dt><dd>{{ request.reason }}</dd></div>
            </dl>
          </article>
        </div>
      </el-card>
    </template>

    <el-drawer v-model="detailOpen" title="插件资格认证与策略" size="min(680px, 96vw)">
      <div v-if="!detail" class="base-loading" role="status">正在读取资格证据...</div>
      <div v-else class="detail">
        <div><h3>{{ detail.plugin.display_name }}</h3><p>{{ detail.plugin.description }}</p></div>
        <el-descriptions :column="1" border>
          <el-descriptions-item label="软件包"><code>{{ detail.plugin.packages.map(item => `${item.name}@${item.version}`).join(" · ") }}</code></el-descriptions-item>
          <el-descriptions-item label="状态"><el-tag :type="tagType(detail.plugin.qualification_state)">{{ pluginStatusLabel(detail.plugin.qualification_state) }}</el-tag> <el-tag v-if="detail.plugin.active" type="success">运行中</el-tag></el-descriptions-item>
          <el-descriptions-item label="兼容性">{{ pluginCompatibilityLabel(detail.plugin.compatibility.status) }}</el-descriptions-item>
          <el-descriptions-item label="风险">{{ pluginRiskLabel(detail.plugin.risk.level) }} · {{ detail.plugin.risk.reasons.join("；") }}</el-descriptions-item>
          <el-descriptions-item label="能力">{{ detail.plugin.capabilities.map(pluginCapabilityLabel).join("、") || "无外部能力" }}</el-descriptions-item>
          <el-descriptions-item label="证据 ID">{{ detail.plugin.evidence_refs.join(", ") }}</el-descriptions-item>
          <el-descriptions-item label="原因">{{ detail.plugin.qualification_reason }}</el-descriptions-item>
        </el-descriptions>
        <el-form label-position="top">
          <el-form-item label="Agent 授权">
            <el-checkbox-group v-model="selectedAgents"><el-checkbox v-for="agent in detail.plugin.allowed_agents" :key="agent" :value="agent">{{ pluginAgentLabel(agent) }}</el-checkbox></el-checkbox-group>
          </el-form-item>
          <el-form-item label="审计原因"><el-input v-model="reason" type="textarea" :rows="3" maxlength="500" show-word-limit placeholder="说明为什么需要这次策略或资格变更" /></el-form-item>
        </el-form>
        <div class="actions">
          <el-button :loading="submitting" @click="qualify">发起资格认证</el-button>
          <el-button v-if="detail.plugin.desired_enabled" :loading="submitting" @click="change('assign')">保存 Agent 授权</el-button>
          <el-button v-if="detail.plugin.desired_enabled" type="danger" plain :loading="submitting" @click="change('disable')">创建停用部署请求</el-button>
          <el-button v-else type="primary" :disabled="detail.plugin.qualification_state !== 'QUALIFIED' || ['HIGH', 'PROHIBITED'].includes(detail.plugin.risk.level)" :loading="submitting" @click="change('enable')">创建启用部署请求</el-button>
        </div>
      </div>
    </el-drawer>
  </section>
</template>

<style scoped>
.plugin-center,.detail{display:grid;gap:16px}.toolbar{align-items:start;display:grid;gap:12px;grid-template-columns:minmax(0,1fr) auto}.metrics{display:grid;gap:12px;grid-template-columns:repeat(4,minmax(0,1fr))}.metrics span,.block{color:var(--byq-text-muted);display:block;font-size:12px}.metrics strong{display:block;font-size:25px;margin-top:6px}.identity-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));margin:0}.identity-grid>div{border-bottom:1px solid var(--byq-border);display:grid;gap:5px;padding:12px}.identity-grid>div:nth-child(odd){border-right:1px solid var(--byq-border)}.identity-grid .wide{grid-column:1/-1}.identity-grid dt,.mobile-card dt{color:var(--byq-text-muted);font-size:12px;font-weight:700}.identity-grid dd,.mobile-card dd{margin:0;min-width:0;overflow-wrap:anywhere}.identity code,td code{overflow-wrap:anywhere}.mobile-list{display:none}.detail h3{margin:0}.detail p{color:var(--byq-text-muted);margin:5px 0 0}.actions{display:flex;flex-wrap:wrap;gap:8px}@media(max-width:800px){.metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.toolbar{grid-template-columns:1fr}.toolbar .el-button{width:100%}.identity-grid{grid-template-columns:1fr}.identity-grid>div,.identity-grid>div:nth-child(odd){border-right:0}.identity-grid .wide{grid-column:auto}.desktop-table{display:none}.mobile-list{display:grid;gap:12px}.mobile-card{border:1px solid var(--byq-border);border-radius:10px;display:grid;gap:12px;padding:14px}.mobile-card>div{display:grid;gap:3px}.mobile-card small{color:var(--byq-text-muted);overflow-wrap:anywhere}.mobile-card dl{display:grid;gap:8px;margin:0}.mobile-card dl>div{display:grid;gap:3px}.mobile-card .el-button{width:100%}.request-card{gap:8px}}
</style>

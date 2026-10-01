<script setup lang="ts">
import { computed, ref } from "vue";
import { ElMessageBox } from "element-plus";
import { resetCurrentWorkspace, resetCurrentWorkspaceRuntime, WorkspaceResetRequestError, type WorkspaceResetReceipt } from "@/api/workspaceReset";
import { applyUiPreferences, DEFAULT_UI_PREFERENCES, useAppearanceStore } from "@/stores/appearance";
import { useAgentStore } from "@/stores/agent";
import { useAuthStore } from "@/stores/auth";
import { createRequestId } from "@/utils/requestId";

type ResetOperation = "runtime" | "workspace";

const auth = useAuthStore();
const workspaceId = computed(() => auth.user?.workspace.workspace_id ?? "");
const workspaceName = computed(() => auth.user?.workspace.display_name ?? "当前工作区");
const confirmationPhrase = "重置工作区";
const confirmation = ref("");
const pending = ref<ResetOperation | null>(null);
const runtimeError = ref("");
const runtimeResult = ref("");
const workspaceError = ref("");
const workspaceResult = ref<WorkspaceResetReceipt | null>(null);
const workspaceRequestKey = ref("");
const workspaceRequestKeyOwner = ref("");

const canConfirmWorkspaceReset = computed(() =>
  confirmation.value === confirmationPhrase && pending.value === null,
);
const deletedRecordCount = computed(() => {
  const deleted = workspaceResult.value?.deleted;
  return deleted ? Object.values(deleted).reduce((total, count) => total + count, 0) : 0;
});

function storageKey(ownerWorkspaceId: string) {
  return `byq.workspace-reset.idempotency-key.v1:${ownerWorkspaceId}`;
}

function currentWorkspaceRequestKey(): string {
  if (!workspaceId.value) throw new Error("当前账户的工作区信息尚未就绪，请刷新后重试。");
  if (workspaceRequestKeyOwner.value === workspaceId.value && workspaceRequestKey.value) {
    return workspaceRequestKey.value;
  }

  const keyName = storageKey(workspaceId.value);
  try {
    const saved = window.sessionStorage.getItem(keyName);
    if (saved) {
      workspaceRequestKey.value = saved;
      workspaceRequestKeyOwner.value = workspaceId.value;
      return saved;
    }
  } catch {
    // The in-memory key still keeps retries stable when browser storage is unavailable.
  }

  const key = createRequestId();
  workspaceRequestKey.value = key;
  workspaceRequestKeyOwner.value = workspaceId.value;
  try {
    window.sessionStorage.setItem(keyName, key);
  } catch {
    // Keep this request usable in the current view if browser storage is unavailable.
  }
  return key;
}

function clearWorkspaceRequestKey() {
  if (workspaceRequestKeyOwner.value) {
    try {
      window.sessionStorage.removeItem(storageKey(workspaceRequestKeyOwner.value));
    } catch {
      // Storage cleanup is best effort after the server has confirmed completion.
    }
  }
  workspaceRequestKey.value = "";
  workspaceRequestKeyOwner.value = "";
}

function messageFor(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

async function resetRuntime() {
  if (pending.value) return;
  if (!workspaceId.value) {
    runtimeError.value = "当前账户的工作区信息尚未就绪，请刷新后重试。";
    return;
  }
  pending.value = "runtime";
  runtimeError.value = "";
  runtimeResult.value = "";
  try {
    await ElMessageBox.confirm(
      "这会结束当前工作区的运行时会话，并归档相关对话；研究成果和任务记录会保留。",
      "确认重置运行时",
      { confirmButtonText: "确认重置", cancelButtonText: "取消", type: "warning" },
    );
    const receipt = await resetCurrentWorkspaceRuntime(workspaceId.value);
    runtimeResult.value = `运行时已重置，并归档了 ${receipt.archived_conversation_count} 段对话。`;
  } catch (error) {
    if (error === "cancel" || error === "close") return;
    runtimeError.value = messageFor(error, "结果未确认，请检查会话状态后再重试。");
  } finally {
    pending.value = null;
  }
}

async function resetWorkspace() {
  if (pending.value || !canConfirmWorkspaceReset.value) return;
  if (!workspaceId.value) {
    workspaceError.value = "当前账户的工作区信息尚未就绪，请刷新后重试。";
    return;
  }
  pending.value = "workspace";
  workspaceError.value = "";
  workspaceResult.value = null;
  try {
    const requestKey = currentWorkspaceRequestKey();
    const receipt = await resetCurrentWorkspace(workspaceId.value, requestKey);
    workspaceResult.value = receipt;
    confirmation.value = "";
    clearWorkspaceRequestKey();
    useAgentStore().$reset();
    applyUiPreferences(DEFAULT_UI_PREFERENCES, true);
    const appearance = useAppearanceStore();
    appearance.$reset();
    try {
      await appearance.load();
    } catch {
      workspaceError.value = "重置已完成；外观默认状态读取失败，请刷新页面。";
    }
  } catch (error) {
    workspaceError.value = messageFor(error, "结果尚未确认。重试会使用同一请求编号继续核对。");
    if (error instanceof WorkspaceResetRequestError && error.terminal) {
      clearWorkspaceRequestKey();
    }
  } finally {
    pending.value = null;
  }
}
</script>

<template>
  <main class="workspace-reset-page">
    <header class="page-heading">
      <div>
        <span class="eyebrow">账户维护</span>
        <h2>重置工作区</h2>
        <p>为 {{ workspaceName }} 选择重置范围。每项操作只作用于当前个人工作区。</p>
      </div>
    </header>

    <section class="reset-card" aria-labelledby="runtime-reset-title">
      <div class="card-heading">
        <div>
          <span class="scope-label">范围较小</span>
          <h3 id="runtime-reset-title">重置运行时</h3>
          <p>结束当前工作区的运行时会话，并归档相关对话，便于从干净的执行环境重新开始。</p>
        </div>
        <button type="button" class="action-button secondary" :disabled="pending !== null" @click="resetRuntime">
          {{ pending === "runtime" ? "正在重置…" : runtimeError ? "重试运行时重置" : "重置运行时" }}
        </button>
      </div>
      <ul class="kept-list">
        <li>保留任务、生成的研究成果、金融事实和审计记录。</li>
        <li>相关对话会归档，归档数量会在完成后显示。</li>
      </ul>
      <p v-if="runtimeError" class="operation-message error" role="alert">
        {{ runtimeError }}
      </p>
      <p v-if="runtimeResult" class="operation-message success" role="status" aria-live="polite">
        {{ runtimeResult }}
      </p>
    </section>

    <section class="reset-card destructive-card" aria-labelledby="workspace-reset-title">
      <div class="card-heading">
        <div>
          <span class="scope-label danger-label">范围较大</span>
          <h3 id="workspace-reset-title">重置整个工作区</h3>
          <p>将 {{ workspaceName }} 的个人数据和设置重置为新用户默认状态。原数据只读归档保留七天，到期清理；归档不会自动恢复或继续旧任务。</p>
        </div>
      </div>

      <div class="impact-grid">
        <div>
          <h4>将清理</h4>
          <ul>
            <li>研究任务、对话和临时实验</li>
            <li>生成的成果、任务历史、股票池和模拟账户</li>
            <li>学习、反馈、个人偏好、Agent 配置和用户模型凭据</li>
          </ul>
        </div>
        <div>
          <h4>会保留</h4>
          <ul>
            <li>工作区、账户、登录身份与权限</li>
            <li>全局设置、凭据和共享数据源</li>
            <li>必要的重置凭据；已结束的个人审计和模拟账本归档七天</li>
          </ul>
        </div>
      </div>

      <p class="blocker-note">
        运行中的任务需要先结束；存在未确认的外部操作时，系统会停止重置并保留数据。已发布到外部的反馈不会被撤回。
      </p>

      <div class="confirmation-row">
        <label for="workspace-reset-confirmation">输入“{{ confirmationPhrase }}”以确认</label>
        <input
          id="workspace-reset-confirmation"
          v-model="confirmation"
          autocomplete="off"
          :disabled="pending !== null"
          :placeholder="confirmationPhrase"
          aria-describedby="workspace-reset-confirmation-help"
        />
        <button
          type="button"
          class="action-button danger"
          :disabled="!canConfirmWorkspaceReset"
          @click="resetWorkspace"
        >
          {{ pending === "workspace" ? "正在重置…" : workspaceError ? "重试重置整个工作区" : "确认重置整个工作区" }}
        </button>
      </div>
      <small id="workspace-reset-confirmation-help" class="confirmation-help">
        重试会沿用同一个请求编号；只有服务确认完成后，才会清除该编号。
      </small>
      <p v-if="workspaceError" class="operation-message error" role="alert">
        {{ workspaceError }}
      </p>
      <p v-if="workspaceResult" class="operation-message success" role="status" aria-live="polite">
        工作区重置已完成。{{ workspaceResult.already_empty ? "工作区原本已为空。" : `已清理 ${deletedRecordCount} 条记录。` }}账户和工作区身份已保留，个人设置已恢复默认；原数据归档保留七天。
      </p>
    </section>
  </main>
</template>

<style scoped>
.workspace-reset-page { display: grid; gap: 14px; min-width: 0; }
.page-heading, .reset-card { background: var(--byq-surface); border: 1px solid var(--byq-border); border-radius: 12px; padding: 18px 20px; }
.eyebrow, .scope-label { color: var(--byq-brand); font-size: 10px; font-weight: 850; letter-spacing: .08em; text-transform: uppercase; }
.page-heading h2 { color: var(--byq-text); font-size: 20px; margin: 4px 0; }
.page-heading p, .card-heading p { color: var(--byq-text-muted); font-size: 12px; line-height: 1.6; margin: 0; }
.card-heading { align-items: flex-start; display: flex; gap: 18px; justify-content: space-between; }
.card-heading h3 { color: var(--byq-text); font-size: 16px; margin: 5px 0 4px; }
.danger-label { color: var(--byq-danger, #c2413a); }
.kept-list, .impact-grid ul { color: var(--byq-text-muted); font-size: 12px; line-height: 1.8; margin: 12px 0 0; padding-left: 18px; }
.impact-grid { border-top: 1px solid var(--byq-border-subtle); display: grid; gap: 12px; grid-template-columns: repeat(2, minmax(0, 1fr)); margin-top: 15px; padding-top: 14px; }
.impact-grid h4 { color: var(--byq-text); font-size: 12px; margin: 0; }
.impact-grid ul { margin-top: 5px; }
.blocker-note { background: var(--byq-surface-muted); border-radius: 8px; color: var(--byq-text-muted); font-size: 11px; line-height: 1.6; margin: 14px 0; padding: 10px 12px; }
.confirmation-row { align-items: end; display: grid; gap: 9px; grid-template-columns: minmax(180px, 1fr) auto; }
.confirmation-row label { color: var(--byq-text); font-size: 12px; font-weight: 700; grid-column: 1 / -1; }
.confirmation-row input { background: var(--byq-surface); border: 1px solid var(--byq-border); border-radius: 7px; color: var(--byq-text); font: inherit; min-width: 0; padding: 9px 10px; }
.confirmation-row input:focus { border-color: var(--byq-brand); outline: 2px solid color-mix(in srgb, var(--byq-brand) 20%, transparent); }
.action-button { border: 1px solid transparent; border-radius: 7px; cursor: pointer; font: inherit; font-size: 12px; font-weight: 750; min-height: 38px; padding: 8px 13px; }
.action-button:disabled { cursor: not-allowed; opacity: .55; }
.action-button.secondary { background: var(--byq-brand-soft); border-color: var(--byq-border); color: var(--byq-brand); }
.action-button.danger { background: var(--byq-danger, #c2413a); color: white; }
.confirmation-help { color: var(--byq-text-soft); display: block; font-size: 10px; line-height: 1.5; margin-top: 7px; }
.operation-message { border-radius: 7px; font-size: 12px; line-height: 1.55; margin: 12px 0 0; padding: 9px 11px; }
.operation-message.error { background: color-mix(in srgb, var(--byq-danger, #c2413a) 10%, var(--byq-surface)); color: var(--byq-danger, #c2413a); }
.operation-message.success { background: var(--byq-brand-soft); color: var(--byq-brand); }
@media (max-width: 650px) {
  .page-heading, .reset-card { padding: 15px; }
  .card-heading { align-items: stretch; flex-direction: column; }
  .card-heading .action-button { align-self: flex-start; }
  .impact-grid { grid-template-columns: 1fr; }
  .confirmation-row { grid-template-columns: 1fr; }
  .confirmation-row label { grid-column: auto; }
  .confirmation-row .action-button { width: 100%; }
}
</style>

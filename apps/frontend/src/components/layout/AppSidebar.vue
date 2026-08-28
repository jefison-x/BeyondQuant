<script setup lang="ts">
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ChatLineRound, Menu, Plus } from "@element-plus/icons-vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { deleteAgentSession, updateAgentSession } from "@/api/agent";
import { findActiveNavItem, primaryNavItems } from "@/router/navigation";
import { useAgentStore } from "@/stores/agent";
import { useAuthStore } from "@/stores/auth";
import UserSettingsMenu from "./UserSettingsMenu.vue";

const props = withDefaults(defineProps<{ isCollapsed: boolean; mobile?: boolean }>(), { mobile: false });
const emit = defineEmits<{
  (event: "toggle-collapse"): void;
  (event: "navigate"): void;
}>();

const route = useRoute();
const router = useRouter();
const agent = useAgentStore();
const auth = useAuthStore();
const activeIndex = computed(() => findActiveNavItem(route.path));
const recentSessions = computed(() => agent.sessions.slice(0, 20));

function navigate(path: string) {
  emit("navigate");
  if (route.path !== path) void router.push(path);
}

function newConversation() {
  emit("navigate");
  void router.push({ path: "/agent", query: { new: String(Date.now()) } });
}

function showHistory() {
  emit("navigate");
  void router.push({ path: "/agent", query: { history: "recent" } });
}

function openSession(sessionId: string) {
  emit("navigate");
  void router.push({ path: "/agent", query: { session: sessionId } });
}

async function sessionCommand(command: string, session: typeof agent.sessions[number]) {
  if (command === "rename") {
    const result = await ElMessageBox.prompt("输入新的会话标题", "重命名会话", {
      inputValue: session.title ?? "", inputPattern: /\S+/, inputErrorMessage: "标题不能为空",
    });
    const response = await updateAgentSession(session.session_id, { title: result.value.trim() }, auth.token);
    agent.replaceSession(response.session);
    ElMessage.success("会话已重命名");
    return;
  }
  if (command === "delete") {
    await ElMessageBox.confirm(
      `永久删除会话“${session.title ?? "新投研对话"}”？删除后无法恢复。`,
      "删除会话",
      { type: "warning", confirmButtonText: "删除", cancelButtonText: "取消" },
    );
    const wasActive = agent.activeSessionId === session.session_id;
    await deleteAgentSession(session.session_id, auth.token);
    agent.removeSession(session.session_id);
    if (wasActive) await router.push({ path: "/agent", query: { new: String(Date.now()) } });
    ElMessage.success("会话已删除");
    return;
  }
  const payload = command === "pin"
    ? { pinned: !session.pinned }
    : { status: "archived" as const };
  if (command === "archive") {
    await ElMessageBox.confirm(`归档会话“${session.title ?? "新投研对话"}”？`, "归档会话");
  }
  const response = await updateAgentSession(session.session_id, payload, auth.token);
  if (command === "archive") agent.replaceSessions(agent.sessions.filter((item) => item.session_id !== session.session_id));
  else agent.replaceSession(response.session);
  ElMessage.success(command === "pin" ? (session.pinned ? "已取消置顶" : "已置顶") : "会话已归档");
}
</script>

<template>
  <aside class="app-sidebar" :class="{ collapsed: props.isCollapsed, mobile: props.mobile }">
    <div class="sidebar-header">
      <div class="brand-mark" aria-hidden="true">B</div>
      <div v-if="!props.isCollapsed" class="brand-copy">
        <span class="logo-text">BeyondQuant</span>
        <span class="logo-subtitle">Research OS</span>
      </div>
      <el-button
        v-if="!props.mobile"
        class="collapse-toggle"
        size="small"
        :aria-label="props.isCollapsed ? '展开菜单' : '折叠菜单'"
        @click="emit('toggle-collapse')"
      >
        <el-icon><Menu /></el-icon>
      </el-button>
    </div>

    <div class="sidebar-scroll">
      <nav class="primary-navigation" aria-label="产品主导航">
        <el-tooltip content="新投研对话" placement="right" :disabled="!props.isCollapsed">
          <button type="button" class="new-conversation" @click="newConversation">
            <el-icon><Plus /></el-icon>
            <span v-if="!props.isCollapsed">新投研对话</span>
          </button>
        </el-tooltip>

        <el-tooltip
          v-for="item in primaryNavItems"
          :key="item.to"
          :content="item.label"
          placement="right"
          :disabled="!props.isCollapsed"
        >
          <button
            type="button"
            class="nav-row"
            :class="{ active: activeIndex === item.to }"
            :aria-current="activeIndex === item.to ? 'page' : undefined"
            @click="navigate(item.to)"
          >
            <el-icon><component :is="item.icon" /></el-icon>
            <span v-if="!props.isCollapsed">{{ item.label }}</span>
          </button>
        </el-tooltip>

      </nav>

      <section v-if="!props.isCollapsed" class="sidebar-history" aria-labelledby="conversation-heading">
        <div class="history-heading-row">
          <div id="conversation-heading" class="history-heading">投研对话</div>
          <button type="button" class="history-link" @click="showHistory">历史</button>
        </div>
        <p v-if="!recentSessions.length" class="history-empty">开始一次投研后，会话会显示在这里</p>
        <div v-else class="history-list">
          <div
            v-for="session in recentSessions"
            :key="session.session_id"
            type="button"
            class="history-row"
            :class="{ active: agent.activeSessionId === session.session_id && route.path === '/agent' }"
            :aria-current="agent.activeSessionId === session.session_id && route.path === '/agent' ? 'page' : undefined"
            @click="openSession(session.session_id)"
          >
            <el-icon><ChatLineRound /></el-icon>
            <span>{{ session.title || `研究会话 · ${session.session_id.slice(-8)}` }}</span>
            <el-dropdown trigger="click" @command="(command: string) => sessionCommand(command, session)">
              <button class="history-more" type="button" aria-label="会话操作" @click.stop>···</button>
              <template #dropdown><el-dropdown-menu>
                <el-dropdown-item command="pin">{{ session.pinned ? "取消置顶" : "置顶" }}</el-dropdown-item>
                <el-dropdown-item command="rename">重命名</el-dropdown-item>
                <el-dropdown-item command="archive" divided>归档</el-dropdown-item>
                <el-dropdown-item command="delete" divided>删除</el-dropdown-item>
              </el-dropdown-menu></template>
            </el-dropdown>
          </div>
        </div>
      </section>
    </div>

    <div class="sidebar-user-bar">
      <UserSettingsMenu class="sidebar-user-menu" :compact="props.isCollapsed" @navigate="emit('navigate')" />
    </div>
  </aside>
</template>

<style scoped>
.app-sidebar { background: var(--byq-surface); border-right: 1px solid var(--byq-border); display: flex; flex: 0 0 auto; flex-direction: column; height: 100vh; transition: width .2s ease; width: 260px; z-index: 50; }
.app-sidebar.collapsed { width: 68px; }
.app-sidebar.mobile { border-right: 0; height: 100%; width: 100%; }
.sidebar-header { align-items: center; border-bottom: 1px solid var(--byq-border-subtle); display: flex; gap: .7rem; height: 56px; min-height: 56px; padding: 0 .75rem; }
.brand-mark { align-items: center; background: var(--byq-brand-contrast); border-radius: 8px; color: var(--byq-on-brand); display: inline-flex; flex: 0 0 auto; font-size: 15px; font-weight: 900; height: 32px; justify-content: center; width: 32px; }
.brand-copy { display: grid; line-height: 1.15; min-width: 0; }
.logo-text { color: var(--byq-text); font-size: 14px; font-weight: 850; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.logo-subtitle { color: var(--byq-text-soft); font-size: 10px; font-weight: 700; margin-top: 2px; }
.collapse-toggle { height: 32px; margin-left: auto; padding: 0; width: 32px; }
.sidebar-scroll { display: flex; flex: 1; flex-direction: column; min-height: 0; overflow: hidden; padding: .7rem .55rem; }
.primary-navigation, .history-list { display: grid; gap: 3px; }
.new-conversation, .nav-row, .history-row { align-items: center; border: 0; border-radius: var(--byq-radius-sm); cursor: pointer; display: flex; font: inherit; text-align: left; width: 100%; }
.new-conversation { background: var(--byq-brand-contrast); color: var(--byq-on-brand); font-size: 13px; font-weight: 800; gap: .65rem; height: 40px; margin-bottom: .55rem; padding: 0 .75rem; }
.new-conversation:hover { background: var(--byq-brand-contrast-hover); }
.nav-row { background: transparent; color: var(--byq-text-muted); font-size: 13px; font-weight: 650; gap: .65rem; height: 40px; padding: 0 .75rem; }
.nav-row:hover, .nav-row.active { background: var(--byq-brand-soft); color: var(--byq-brand-contrast); }
.nav-row:focus-visible, .new-conversation:focus-visible, .history-row:focus-visible { outline: 2px solid var(--byq-brand-contrast); outline-offset: 2px; }
.new-conversation .el-icon, .nav-row .el-icon { flex: 0 0 auto; font-size: 17px; }
.collapsed .new-conversation, .collapsed .nav-row { justify-content: center; padding: 0; }
.sidebar-history { border-top: 1px solid var(--byq-border-subtle); display: flex; flex: 1; flex-direction: column; margin-top: .75rem; min-height: 0; padding: .75rem .2rem 0; }
.history-heading-row { align-items: center; display: flex; justify-content: space-between; padding: 0 .35rem .35rem .55rem; }
.history-heading { color: var(--byq-text-soft); font-size: 12px; font-weight: 850; letter-spacing: .04em; text-transform: uppercase; }
.history-link { background: transparent; border: 0; border-radius: var(--byq-radius-sm); color: var(--byq-brand-contrast); cursor: pointer; font: inherit; font-size: 12px; font-weight: 750; padding: .25rem .35rem; }
.history-link:hover { background: var(--byq-brand-soft); }
.history-link:focus-visible { outline: 2px solid var(--byq-brand-contrast); outline-offset: 2px; }
.history-empty { color: var(--byq-text-soft); font-size: 11px; line-height: 1.45; margin: .2rem .55rem; }
.history-list { flex: 1; min-height: 0; overflow-y: auto; overscroll-behavior: contain; padding-right: .1rem; scrollbar-gutter: stable; }
.history-row { align-items: center; background: transparent; border-radius: var(--byq-radius-sm); color: var(--byq-text-muted); cursor: pointer; display: flex; font-size: 14px; gap: .5rem; line-height: 1.35; overflow: hidden; padding: .55rem; }
.history-row span { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.history-row .el-icon { flex: 0 0 auto; }
.history-row:hover, .history-row.active { background: var(--byq-surface-muted); color: var(--byq-text); }
.history-more { background: transparent; border: 0; color: inherit; cursor: pointer; font-weight: 800; opacity: 0; padding: 0 .2rem; }
.history-row:hover .history-more, .history-more:focus-visible { opacity: 1; }
.sidebar-user-bar { border-top: 1px solid var(--byq-border-subtle); margin-top: auto; padding: .55rem; }
.sidebar-user-menu { min-width: 0; }
@media (prefers-reduced-motion: reduce) { .app-sidebar { transition: none; } }
</style>

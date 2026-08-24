<script setup lang="ts">
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";

const route = useRoute();
const router = useRouter();
const sections = [
  { path: "/user/profile", label: "个人资料", description: "昵称与投研偏好" },
  { path: "/user/appearance", label: "外观与主题", description: "显示模式与主题颜色" },
  { path: "/user/assets", label: "资产管理", description: "资产清单与安全迁移" },
  { path: "/user/paper-trading", label: "模拟操盘", description: "纸面账户与风控" },
  { path: "/user/models", label: "模型配置", description: "凭据、档案与绑定" },
  { path: "/user/agent-policy", label: "Agent 策略", description: "个人审批与自动化边界" },
  { path: "/user/research", label: "研究与审批", description: "研究谱系与审批历史" },
];
const activePath = computed(() => route.path);
</script>

<template>
  <div class="user-center">
    <header class="user-center-heading">
      <div>
        <span>用户中心</span>
        <h1>你的 BeyondQuant 空间</h1>
        <p>个人资料、资产、模型与自动化策略均由当前产品账户独立持有。</p>
      </div>
    </header>
    <div class="user-center-mobile-nav">
      <label for="user-center-section">设置分区</label>
      <el-select id="user-center-section" :model-value="activePath" @change="router.push(String($event))">
        <el-option v-for="section in sections" :key="section.path" :label="section.label" :value="section.path" />
      </el-select>
    </div>
    <div class="user-center-grid">
      <nav class="user-center-nav" aria-label="用户中心导航">
        <RouterLink
          v-for="section in sections"
          :key="section.path"
          :to="section.path"
          :class="{ active: activePath === section.path }"
        >
          <strong>{{ section.label }}</strong>
          <small>{{ section.description }}</small>
        </RouterLink>
      </nav>
      <section class="user-center-content">
        <RouterView />
      </section>
    </div>
  </div>
</template>

<style scoped>
.user-center { margin: 0 auto; max-width: 1380px; min-width: 0; }
.user-center-heading { align-items: center; background: var(--byq-surface); border: 1px solid var(--byq-border); border-radius: 14px; display: flex; justify-content: space-between; margin-bottom: 14px; padding: 18px 22px; }
.user-center-heading span { color: var(--byq-brand); font-size: 11px; font-weight: 850; letter-spacing: .12em; text-transform: uppercase; }
.user-center-heading h1 { color: var(--byq-text); font-size: 24px; margin: 4px 0; }
.user-center-heading p { color: var(--byq-text-muted); font-size: 12px; margin: 0; }
.user-center-grid { align-items: start; display: grid; gap: 14px; grid-template-columns: 230px minmax(0, 1fr); }
.user-center-nav { background: var(--byq-surface); border: 1px solid var(--byq-border); border-radius: 12px; display: grid; gap: 3px; padding: 7px; position: sticky; top: 0; }
.user-center-nav a { border-radius: 8px; color: var(--byq-text-muted); display: grid; gap: 2px; padding: 10px 11px; text-decoration: none; }
.user-center-nav a:hover, .user-center-nav a.active { background: var(--byq-brand-soft); color: var(--byq-brand); }
.user-center-nav strong { font-size: 13px; }
.user-center-nav small { color: var(--byq-text-soft); font-size: 10px; }
.user-center-content { min-width: 0; }
.user-center-mobile-nav { display: none; }
@media (max-width: 900px) {
  .user-center-heading { padding: 15px 16px; }
  .user-center-heading h1 { font-size: 20px; }
  .user-center-grid { grid-template-columns: 1fr; }
  .user-center-nav { display: none; }
  .user-center-mobile-nav { align-items: center; background: var(--byq-surface); border: 1px solid var(--byq-border); border-radius: 10px; display: grid; gap: 6px; margin-bottom: 12px; padding: 10px; }
  .user-center-mobile-nav label { color: var(--byq-text-muted); font-size: 11px; font-weight: 750; }
}
</style>

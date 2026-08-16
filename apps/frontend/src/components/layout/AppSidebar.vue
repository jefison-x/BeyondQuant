<script setup lang="ts">
const links = [
  { name: "dashboard", label: "首页", to: "/" },
  { name: "system-status", label: "系统状态", to: "/system-status" },
  { name: "agent", label: "研究工作台", to: "/agent" },
  { name: "quant", label: "量化工作台", to: "/quant" },
  { name: "settings", label: "设置", to: "/settings" },
  { name: "stock-pool", label: "股票池", to: "/stock-pool" },
  { name: "paper-trading", label: "模拟交易", to: "/paper-trading" },
  { name: "operations", label: "Operations", to: "/operations" },
];
</script>

<template>
  <aside class="app-sidebar">
    <nav>
      <RouterLink
        v-for="link in links"
        :key="link.name"
        :to="link.to"
        class="app-nav-link"
        active-class="active"
      >
        {{ link.label }}
      </RouterLink>
    </nav>
  </aside>
</template>

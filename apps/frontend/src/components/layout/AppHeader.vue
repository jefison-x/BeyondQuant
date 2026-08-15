<script setup lang="ts">
import { useAuthStore } from "@/stores/auth";
import { useRouter } from "vue-router";

const auth = useAuthStore();
const router = useRouter();

function logout() {
  auth.logout();
  router.push({ name: "login" });
}
</script>

<template>
  <header class="app-header">
    <div class="app-brand">BeyondQuant Next</div>
    <div class="app-header-actions">
      <span class="app-principal">{{ auth.isAuthenticated ? "product-user" : "" }}</span>
      <button type="button" class="app-logout" @click="logout">退出</button>
    </div>
  </header>
</template>

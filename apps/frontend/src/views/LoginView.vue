<script setup lang="ts">
import { ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();
const token = ref("");
const error = ref("");

function submit() {
  if (!token.value.trim()) {
    error.value = "请输入产品访问令牌";
    return;
  }
  auth.setToken(token.value);
  router.push((route.query.redirect as string) || "/");
}
</script>

<template>
  <div class="login-page">
    <form class="login-card" @submit.prevent="submit">
      <h1>BeyondQuant Next</h1>
      <p>输入产品访问令牌以进入研究工作台</p>
      <input v-model="token" type="password" placeholder="Product Token" aria-label="产品访问令牌" />
      <p v-if="error" class="login-error">{{ error }}</p>
      <button type="submit">进入</button>
    </form>
  </div>
</template>

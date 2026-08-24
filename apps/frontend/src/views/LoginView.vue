<script setup lang="ts">
import { ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useAuthStore } from "@/stores/auth";
import { useAppearanceStore } from "@/stores/appearance";

const auth = useAuthStore();
const appearance = useAppearanceStore();
const route = useRoute();
const router = useRouter();
const username = ref("");
const password = ref("");
const error = ref("");

async function submit() {
  if (!username.value.trim() || !password.value) {
    error.value = "请输入用户名和密码";
    return;
  }
  try {
    await auth.login(username.value, password.value);
    await appearance.load().catch(() => undefined);
    router.push((route.query.redirect as string) || "/");
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "登录失败";
  }
}
</script>

<template>
  <div class="login-page">
    <form class="login-card" @submit.prevent="submit">
      <h1>BeyondQuant Next</h1>
      <p>使用用户名和密码登录研究工作台</p>
      <input v-model="username" placeholder="用户名" aria-label="用户名" />
      <input v-model="password" type="password" placeholder="密码" aria-label="密码" />
      <p v-if="error" class="login-error">{{ error }}</p>
      <button type="submit">进入</button>
    </form>
  </div>
</template>

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
const submitting = ref(false);

async function submit() {
  if (!username.value.trim() || !password.value) {
    error.value = "请输入用户名和密码";
    return;
  }
  if (submitting.value) return;
  submitting.value = true;
  error.value = "";
  try {
    await auth.login(username.value, password.value);
    await appearance.load().catch(() => undefined);
    router.push((route.query.redirect as string) || "/");
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "登录失败";
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <div class="login-page">
    <form class="login-card" :aria-busy="submitting" @submit.prevent="submit">
      <h1>BeyondQuant Next</h1>
      <p>使用用户名和密码登录研究工作台</p>
      <label for="username">用户名</label>
      <input id="username" v-model="username" name="username" autocomplete="username"
        autocapitalize="none" spellcheck="false" placeholder="用户名" :disabled="submitting" />
      <label for="password">密码</label>
      <input id="password" v-model="password" name="password" type="password"
        autocomplete="current-password" placeholder="密码" :disabled="submitting" />
      <p v-if="error" class="login-error">{{ error }}</p>
      <button type="submit" :disabled="submitting">{{ submitting ? "正在登录…" : "进入" }}</button>
    </form>
  </div>
</template>

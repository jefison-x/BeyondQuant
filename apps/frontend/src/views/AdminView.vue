<script setup lang="ts">
import { onMounted, ref } from "vue";
import { disableUser, listUsers } from "@/api/admin";
import BaseError from "@/components/ui/BaseError.vue";

const users = ref<Array<Record<string, unknown>>>([]);
const error = ref("");

async function refresh() {
  error.value = "";
  try {
    users.value = (await listUsers()).users;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载失败";
  }
}

async function disable(userId: unknown) {
  await disableUser(String(userId));
  await refresh();
}

onMounted(refresh);
</script>

<template>
  <section class="page-card">
    <h2>用户管理</h2>
    <BaseError v-if="error" :message="error" />
    <table class="admin-table">
      <thead><tr><th>Username</th><th>Role</th><th>Status</th><th></th></tr></thead>
      <tbody>
        <tr v-for="user in users" :key="String(user.user_id)">
          <td>{{ user.username }}</td>
          <td>{{ user.role }}</td>
          <td>{{ user.status }}</td>
          <td><button type="button" @click="disable(user.user_id)">禁用</button></td>
        </tr>
      </tbody>
    </table>
  </section>
</template>

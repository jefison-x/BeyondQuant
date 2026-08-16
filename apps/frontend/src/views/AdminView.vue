<script setup lang="ts">
import { onMounted, ref } from "vue";
import { disableUser, listUsers } from "@/api/admin";

const users = ref<Array<Record<string, unknown>>>([]);
const error = ref("");
const busy = ref(false);

async function refresh() {
  error.value = "";
  busy.value = true;
  try {
    users.value = (await listUsers()).users;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载失败";
  } finally {
    busy.value = false;
  }
}

async function disable(userId: unknown) {
  busy.value = true;
  try {
    await disableUser(String(userId));
    await refresh();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "禁用失败";
  } finally {
    busy.value = false;
  }
}

onMounted(refresh);
</script>

<template>
  <section class="system-page">
    <el-card shadow="never" class="top-band">
      <template #header>
        <div class="panel-heading">
          <div class="card-title">用户管理</div>
          <el-button :loading="busy" @click="refresh">刷新</el-button>
        </div>
      </template>
      <p v-if="error" class="page-error">{{ error }}</p>
      <el-table :data="users" v-loading="busy">
        <el-table-column prop="username" label="Username" min-width="180" />
        <el-table-column prop="role" label="Role" width="140" />
        <el-table-column prop="status" label="Status" width="140" />
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button type="danger" plain size="small" @click="disable(row.user_id)">禁用</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </section>
</template>

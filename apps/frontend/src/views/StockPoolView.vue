<script setup lang="ts">
import { onMounted, ref } from "vue";
import { createStockPool, listStockPools } from "@/api/paper";
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
const name = ref("");
const symbols = ref("");
const result = ref<Record<string, unknown> | null>(null);
const error = ref("");
const busy = ref(false);
const pools = ref<Array<Record<string, unknown>>>([]);

async function loadPools() {
  try {
    pools.value = (await listStockPools(auth.token)).pools;
  } catch {
    pools.value = [];
  }
}

onMounted(loadPools);

async function submit() {
  error.value = "";
  busy.value = true;
  try {
    const created = await createStockPool(
      name.value,
      symbols.value.split(",").map((item) => item.trim()).filter(Boolean),
      auth.token,
    );
    result.value = created.pool as unknown as Record<string, unknown>;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "创建失败";
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <section class="stock-page">
    <el-card shadow="never" class="top-band">
      <template #header>
        <div class="card-heading">
          <span class="card-title">创建版本化股票池</span>
          <small class="card-sub">Symbol 以逗号分隔，例如 000001.SZ,600000.SH</small>
        </div>
      </template>
      <el-form label-position="top">
        <el-form-item label="股票池名称">
          <el-input v-model="name" placeholder="Pool name" />
        </el-form-item>
        <el-form-item label="成分股">
          <el-input v-model="symbols" type="textarea" placeholder="000001.SZ,600000.SH" />
        </el-form-item>
        <el-button type="primary" :loading="busy" @click="submit">创建股票池</el-button>
      </el-form>
    </el-card>

    <p v-if="error" class="page-error">{{ error }}</p>
    <el-card v-if="result" shadow="never" class="top-band">
      <template #header>
        <div class="card-title">创建结果</div>
      </template>
      <pre class="quant-result">{{ JSON.stringify(result, null, 2) }}</pre>
    </el-card>

    <el-card shadow="never" class="top-band">
      <template #header>
        <div class="panel-heading">
          <span class="card-title">股票池列表</span>
          <el-button size="small" @click="loadPools">刷新</el-button>
        </div>
      </template>
      <el-empty v-if="!pools.length" description="暂无股票池" />
      <el-table v-else :data="pools">
        <el-table-column prop="pool_id" label="Pool ID" min-width="240" show-overflow-tooltip />
        <el-table-column prop="name" label="名称" min-width="160" />
        <el-table-column prop="version" label="版本" width="100" />
        <el-table-column label="成分股" min-width="220">
          <template #default="{ row }">{{ Array.isArray(row.symbols) ? row.symbols.join(", ") : "-" }}</template>
        </el-table-column>
      </el-table>
    </el-card>
  </section>
</template>

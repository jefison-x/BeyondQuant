<script setup lang="ts">
import { ref } from "vue";
import { createStockPool } from "@/api/paper";
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
const name = ref("");
const symbols = ref("");
const result = ref<Record<string, unknown> | null>(null);
const error = ref("");

async function submit() {
  error.value = "";
  try {
    const created = await createStockPool(name.value, symbols.value.split(",").map((item) => item.trim()), auth.token);
    result.value = created.pool as unknown as Record<string, unknown>;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "创建失败";
  }
}
</script>

<template>
  <section class="page-card">
    <h2>股票池</h2>
    <div class="paper-form">
      <input v-model="name" placeholder="Pool name" />
      <input v-model="symbols" placeholder="000001.SZ,600000.SH" />
      <button type="button" @click="submit">创建版本化股票池</button>
    </div>
    <p v-if="error" class="page-error">{{ error }}</p>
    <pre v-if="result" class="quant-result">{{ JSON.stringify(result, null, 2) }}</pre>
  </section>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { createPaperAccount, listPaperOrders, submitPaperOrder } from "@/api/paper";
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
const account = ref<{ account_id?: string; cash?: number } | null>(null);
const accountName = ref("sim");
const cash = ref(100000);
const accountId = ref("");
const poolId = ref("");
const symbol = ref("");
const side = ref<"buy" | "sell">("buy");
const quantity = ref(100);
const price = ref(10);
const tradeDate = ref("20240102");
const orders = ref<Awaited<ReturnType<typeof listPaperOrders>>["orders"]>([]);
const error = ref("");
const busy = ref(false);

async function createAccount() {
  error.value = "";
  busy.value = true;
  try {
    const created = await createPaperAccount(accountName.value, cash.value, auth.token);
    account.value = created.account;
    accountId.value = created.account.account_id ?? "";
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "创建账户失败";
  } finally {
    busy.value = false;
  }
}

async function placeOrder() {
  error.value = "";
  busy.value = true;
  try {
    await submitPaperOrder(
      {
        account_id: accountId.value,
        pool_id: poolId.value,
        symbol: symbol.value,
        side: side.value,
        quantity: quantity.value,
        price: price.value,
        trade_date: tradeDate.value,
        idempotency_key: crypto.randomUUID(),
      },
      auth.token,
    );
    orders.value = (await listPaperOrders(accountId.value, auth.token)).orders;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "下单失败";
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <section class="paper-page">
    <el-card shadow="never" class="top-band">
      <template #header>
        <div class="card-heading">
          <span class="card-title">模拟账户</span>
          <small class="card-sub">创建纸面账户并提交受控模拟订单</small>
        </div>
      </template>
      <div class="quant-panel">
        <el-input v-model="accountName" placeholder="账户名称" style="width: 220px" />
        <el-input-number v-model="cash" :min="0" :step="10000" />
        <el-button type="primary" :loading="busy" @click="createAccount">创建账户</el-button>
      </div>
    </el-card>

    <el-card v-if="account" shadow="never" class="top-band">
      <template #header>
        <div class="card-heading">
          <span class="card-title">提交订单</span>
          <small class="card-sub">Account: {{ account.account_id }}</small>
        </div>
      </template>
      <div class="paper-form">
        <el-input v-model="accountId" placeholder="Account ID" style="width: 240px" />
        <el-input v-model="poolId" placeholder="Stock Pool ID" style="width: 240px" />
        <el-input v-model="symbol" placeholder="000001.SZ" style="width: 160px" />
        <el-select v-model="side" style="width: 120px">
          <el-option label="buy" value="buy" />
          <el-option label="sell" value="sell" />
        </el-select>
        <el-input-number v-model="quantity" :min="0" />
        <el-input-number v-model="price" :min="0" :precision="2" :step="0.01" />
        <el-input v-model="tradeDate" placeholder="YYYYMMDD" style="width: 160px" />
        <el-button type="primary" :loading="busy" @click="placeOrder">提交订单</el-button>
      </div>
    </el-card>

    <p v-if="error" class="page-error">{{ error }}</p>

    <el-card v-if="orders.length" shadow="never" class="top-band">
      <template #header>
        <div class="card-title">订单流水</div>
      </template>
      <el-table :data="orders">
        <el-table-column prop="symbol" label="Symbol" width="140" />
        <el-table-column prop="side" label="方向" width="90" />
        <el-table-column prop="quantity" label="数量" width="100" />
        <el-table-column prop="price" label="价格" width="110" />
        <el-table-column prop="status" label="状态" width="120" />
        <el-table-column prop="blocked_reason" label="拦截原因" min-width="180" show-overflow-tooltip />
      </el-table>
    </el-card>
  </section>
</template>

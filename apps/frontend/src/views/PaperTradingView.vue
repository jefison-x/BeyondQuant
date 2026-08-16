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

async function createAccount() {
  try {
    const created = await createPaperAccount(accountName.value, cash.value, auth.token);
    account.value = created.account;
    accountId.value = created.account.account_id ?? "";
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "创建失败";
  }
}

async function placeOrder() {
  error.value = "";
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
  }
}
</script>

<template>
  <section class="page-card">
    <h2>模拟交易</h2>
    <div class="paper-form">
      <input v-model="accountName" placeholder="账户名称" />
      <input v-model.number="cash" type="number" placeholder="初始资金" />
      <button type="button" @click="createAccount">创建模拟账户</button>
    </div>
    <div v-if="account" class="paper-form">
      <input v-model="accountId" placeholder="Account ID" />
      <input v-model="poolId" placeholder="Stock Pool ID" />
      <input v-model="symbol" placeholder="000001.SZ" />
      <select v-model="side"><option value="buy">buy</option><option value="sell">sell</option></select>
      <input v-model.number="quantity" type="number" placeholder="数量" />
      <input v-model.number="price" type="number" placeholder="价格" />
      <input v-model="tradeDate" placeholder="YYYYMMDD" />
      <button type="button" @click="placeOrder">提交模拟订单</button>
    </div>
    <p v-if="error" class="page-error">{{ error }}</p>
    <ul>
      <li v-for="order in orders" :key="order.order_id">
        {{ order.symbol }} {{ order.side }} {{ order.quantity }} @ {{ order.price }} - {{ order.status }}
        <span v-if="order.blocked_reason">{{ order.blocked_reason }}</span>
      </li>
    </ul>
  </section>
</template>

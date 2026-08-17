<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import {
  createPaperAccount,
  listPaperAccounts,
  listPaperFills,
  listPaperLedger,
  listPaperOrders,
  listPaperPositions,
  submitPaperOrder,
} from "@/api/paper";
import type { PaperLedgerEntry } from "@/api/types";
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
const loading = ref(true);
const error = ref("");
const busy = ref("");
const accounts = ref<Array<Record<string, unknown>>>([]);
const selected = ref<Record<string, unknown> | null>(null);
const accountName = ref("sim");
const cash = ref(100000);
const poolId = ref("");
const symbol = ref("");
const side = ref<"buy" | "sell">("buy");
const quantity = ref(100);
const price = ref(10);
const tradeDate = ref("20240102");
const positions = ref<Array<Record<string, unknown>>>([]);
const orders = ref<Array<Record<string, unknown>>>([]);
const fills = ref<Array<Record<string, unknown>>>([]);
const ledger = ref<PaperLedgerEntry[]>([]);
const activeTab = ref("overview");

const overview = computed(() => ({
  cash: Number(selected.value?.cash ?? 0),
  positions: positions.value.length,
  orders: orders.value.length,
  fills: fills.value.length,
}));

async function loadDetail(accountId: string) {
  error.value = "";
  try {
    const [positionBody, orderBody, fillBody, ledgerBody] = await Promise.all([
      listPaperPositions(accountId, auth.token),
      listPaperOrders(accountId, auth.token),
      listPaperFills(accountId, auth.token),
      listPaperLedger(accountId, auth.token),
    ]);
    positions.value = positionBody.positions;
    orders.value = orderBody.orders as Array<Record<string, unknown>>;
    fills.value = fillBody.fills;
    ledger.value = ledgerBody.ledger;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "读取账户失败";
  }
}

async function loadAccounts() {
  loading.value = true;
  error.value = "";
  try {
    accounts.value = (await listPaperAccounts(auth.token)).accounts;
    if (accounts.value.length) {
      selected.value = accounts.value[0];
      await loadDetail(String(selected.value.account_id));
    } else {
      selected.value = null;
    }
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载账户失败";
  } finally {
    loading.value = false;
  }
}

async function selectAccount(row: Record<string, unknown>) {
  selected.value = row;
  const id = String(row.account_id ?? "");
  if (id) await loadDetail(id);
}

async function createAccount() {
  busy.value = "create";
  error.value = "";
  try {
    const created = await createPaperAccount(accountName.value.trim() || "sim", cash.value, auth.token);
    selected.value = created.account as unknown as Record<string, unknown>;
    accountName.value = "sim";
    await loadAccounts();
    ElMessage.success("模拟账户已创建");
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "创建账户失败";
  } finally {
    busy.value = "";
  }
}

async function placeOrder() {
  if (!selected.value) return;
  if (!symbol.value.trim() || !poolId.value.trim()) {
    ElMessage.warning("请填写股票池 ID 和标的");
    return;
  }
  busy.value = "order";
  error.value = "";
  try {
    await submitPaperOrder(
      {
        account_id: String(selected.value.account_id),
        pool_id: poolId.value.trim(),
        symbol: symbol.value.trim(),
        side: side.value,
        quantity: quantity.value,
        price: price.value,
        trade_date: tradeDate.value,
        idempotency_key: crypto.randomUUID(),
      },
      auth.token,
    );
    await loadDetail(String(selected.value.account_id));
    ElMessage.success("模拟订单已提交");
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "下单失败";
  } finally {
    busy.value = "";
  }
}

onMounted(loadAccounts);
</script>

<template>
  <section class="paper-page">
    <div v-if="loading" class="base-loading">加载中...</div>
    <p v-if="error" class="page-error">{{ error }}</p>

    <el-card shadow="never" class="top-band">
      <template #header>
        <div class="panel-heading">
          <span class="card-title">模拟账户</span>
          <el-button size="small" @click="loadAccounts">刷新</el-button>
        </div>
      </template>
      <div class="account-grid">
        <el-card
          v-for="account in accounts"
          :key="String(account.account_id)"
          shadow="never"
          class="account-card"
          :class="{ active: selected?.account_id === account.account_id }"
          @click="selectAccount(account)"
        >
          <div class="account-name">{{ account.name }}</div>
          <div class="account-meta">{{ account.account_id }}</div>
          <div class="account-cash">¥ {{ Number(account.cash ?? 0).toLocaleString("zh-CN") }}</div>
          <el-tag size="small">{{ account.status }}</el-tag>
        </el-card>
        <el-empty v-if="!accounts.length" description="暂无模拟账户" />
      </div>
    </el-card>

    <el-card shadow="never" class="top-band">
      <template #header><span class="card-title">新建模拟账户</span></template>
      <div class="paper-form">
        <el-input v-model="accountName" placeholder="账户名称" style="width: 200px" />
        <el-input-number v-model="cash" :min="0" :step="10000" />
        <el-button type="primary" :loading="busy === 'create'" @click="createAccount">创建账户</el-button>
      </div>
    </el-card>

    <template v-if="selected">
      <el-card shadow="never" class="top-band">
        <template #header><span class="card-title">提交订单</span></template>
        <div class="paper-form">
          <el-input v-model="poolId" placeholder="Stock Pool ID" style="width: 220px" />
          <el-input v-model="symbol" placeholder="000001.SZ" style="width: 150px" />
          <el-select v-model="side" style="width: 110px">
            <el-option label="buy" value="buy" />
            <el-option label="sell" value="sell" />
          </el-select>
          <el-input-number v-model="quantity" :min="0" />
          <el-input-number v-model="price" :min="0" :precision="2" :step="0.01" />
          <el-input v-model="tradeDate" placeholder="YYYYMMDD" style="width: 140px" />
          <el-button type="primary" :loading="busy === 'order'" @click="placeOrder">提交订单</el-button>
        </div>
      </el-card>

      <el-card shadow="never" class="top-band">
        <template #header><span class="card-title">账户详情</span></template>
        <el-tabs v-model="activeTab">
          <el-tab-pane label="总览" name="overview">
            <div class="metric-grid">
              <el-card shadow="never"><div class="stat-label">现金</div><strong>¥ {{ overview.cash.toLocaleString("zh-CN") }}</strong></el-card>
              <el-card shadow="never"><div class="stat-label">持仓</div><strong>{{ overview.positions }}</strong></el-card>
              <el-card shadow="never"><div class="stat-label">订单</div><strong>{{ overview.orders }}</strong></el-card>
              <el-card shadow="never"><div class="stat-label">成交</div><strong>{{ overview.fills }}</strong></el-card>
            </div>
          </el-tab-pane>
          <el-tab-pane label="持仓" name="positions">
            <el-table :data="positions" size="small" empty-text="暂无持仓">
              <el-table-column prop="symbol" label="Symbol" width="140" />
              <el-table-column prop="quantity" label="数量" width="120" />
              <el-table-column prop="last_buy_date" label="最后买入日期" min-width="160" />
            </el-table>
          </el-tab-pane>
          <el-tab-pane label="订单" name="orders">
            <el-table :data="orders" size="small" empty-text="暂无订单">
              <el-table-column prop="symbol" label="Symbol" width="140" />
              <el-table-column prop="side" label="方向" width="90" />
              <el-table-column prop="quantity" label="数量" width="100" />
              <el-table-column prop="price" label="价格" width="110" />
              <el-table-column prop="status" label="状态" width="110" />
              <el-table-column prop="blocked_reason" label="拦截原因" min-width="180" show-overflow-tooltip />
            </el-table>
          </el-tab-pane>
          <el-tab-pane label="成交" name="fills">
            <el-table :data="fills" size="small" empty-text="暂无成交">
              <el-table-column prop="symbol" label="Symbol" width="140" />
              <el-table-column prop="side" label="方向" width="90" />
              <el-table-column prop="quantity" label="数量" width="100" />
              <el-table-column prop="price" label="价格" width="110" />
              <el-table-column prop="fees" label="费用" width="100" />
              <el-table-column prop="trade_date" label="交易日" width="110" />
            </el-table>
          </el-tab-pane>
          <el-tab-pane label="资金流水" name="ledger">
            <el-table :data="ledger" size="small" empty-text="暂无资金流水">
              <el-table-column prop="trade_date" label="交易日" width="110" />
              <el-table-column prop="symbol" label="Symbol" width="140" />
              <el-table-column prop="side" label="方向" width="90" />
              <el-table-column prop="quantity" label="数量" width="100" />
              <el-table-column label="现金变动" width="120" align="right">
                <template #default="{ row }">{{ row.cash_delta ?? "-" }}</template>
              </el-table-column>
              <el-table-column label="费用" width="100" align="right">
                <template #default="{ row }">{{ row.fees ?? "-" }}</template>
              </el-table-column>
              <el-table-column label="已实现盈亏" width="120" align="right">
                <template #default="{ row }">{{ row.realized_pnl ?? "-" }}</template>
              </el-table-column>
            </el-table>
          </el-tab-pane>
        </el-tabs>
      </el-card>
    </template>
  </section>
</template>

<style scoped>
.account-grid {
  display: grid;
  gap: 0.75rem;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
}

.account-card {
  cursor: pointer;
}

.account-card.active {
  border-color: var(--byq-brand);
}

.account-name {
  font-weight: 700;
}

.account-meta {
  color: var(--byq-text-muted);
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.account-cash {
  font-size: 18px;
  font-weight: 800;
  margin: 0.4rem 0;
}

.paper-form {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.metric-grid {
  display: grid;
  gap: 0.75rem;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.stat-label {
  color: var(--byq-text-muted);
  font-size: 12px;
}

@media (max-width: 900px) {
  .metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>

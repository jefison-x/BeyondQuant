<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import {
  createPaperAccount, exportPaperAccount, getPaperAccount, getPaperControls,
  getPaperOrder, importPaperAccount, listPaperAccounts, listPaperFills,
  listPaperLedger, listPaperOrders, listPaperPositions, listPaperSnapshots,
  listStockPools, rebindPaperAccount, settlePaperAccount, submitPaperOrder,
  updatePaperControls,
} from "@/api/paper";
import type { PaperAccount, PaperControls, PaperLedgerEntry, PaperOrder, PaperSnapshot } from "@/api/types";
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
const loading = ref(true);
const busy = ref("");
const error = ref("");
const accounts = ref<PaperAccount[]>([]);
const selected = ref<PaperAccount | null>(null);
const pools = ref<Array<Record<string, unknown>>>([]);
const positions = ref<Array<Record<string, unknown>>>([]);
const orders = ref<PaperOrder[]>([]);
const fills = ref<Array<Record<string, unknown>>>([]);
const ledger = ref<PaperLedgerEntry[]>([]);
const snapshots = ref<PaperSnapshot[]>([]);
const controls = ref<PaperControls | null>(null);
const activeTab = ref("overview");

const accountName = ref("模拟账户");
const initialCash = ref(100000);
const poolId = ref("");
const symbol = ref("");
const side = ref<"buy" | "sell">("buy");
const quantity = ref(100);
const price = ref(10);
const tradeDate = ref(new Date().toISOString().slice(0, 10).replaceAll("-", ""));
const orderDialog = ref(false);
const orderDetail = ref<PaperOrder | null>(null);
const settlementDialog = ref(false);
const settlementDate = ref(new Date().toISOString().slice(0, 10).replaceAll("-", ""));
const settlementMarks = ref<Record<string, number>>({});
const killSwitch = ref(false);
const killReason = ref("");
const maxOrderNotional = ref<number | undefined>();
const importInput = ref<HTMLInputElement | null>(null);

const overview = computed(() => ({
  cash: Number(selected.value?.cash ?? 0),
  equity: Number(selected.value?.equity ?? selected.value?.cash ?? 0),
  marketValue: Math.max(0, Number(selected.value?.equity ?? selected.value?.cash ?? 0) - Number(selected.value?.cash ?? 0)),
  realizedPnl: Number(selected.value?.realized_pnl ?? 0),
}));

function money(value: unknown) {
  return Number(value ?? 0).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function statusLabel(value: unknown) {
  const labels: Record<string, string> = { filled: "已成交", blocked: "已拦截", active: "运行中" };
  return labels[String(value)] ?? String(value ?? "-");
}

function reasonLabel(value: unknown) {
  const labels: Record<string, string> = {
    lot_size: "非整手", suspended: "停牌", limit_up: "超过涨停价", limit_down: "低于跌停价",
    insufficient_position: "持仓不足", t_plus_one: "T+1 可卖不足", insufficient_cash: "现金不足",
    risk_kill_switch: "风险总开关已开启", risk_max_order_notional: "超过单笔金额上限",
  };
  return labels[String(value)] ?? String(value ?? "-");
}

async function loadDetail(accountId: string) {
  error.value = "";
  try {
    const [accountBody, positionBody, orderBody, fillBody, ledgerBody, snapshotBody, controlBody] = await Promise.all([
      getPaperAccount(accountId, auth.token), listPaperPositions(accountId, auth.token),
      listPaperOrders(accountId, auth.token), listPaperFills(accountId, auth.token),
      listPaperLedger(accountId, auth.token), listPaperSnapshots(accountId, auth.token),
      getPaperControls(accountId, auth.token),
    ]);
    selected.value = accountBody.account;
    positions.value = positionBody.positions;
    orders.value = orderBody.orders;
    fills.value = fillBody.fills;
    ledger.value = ledgerBody.ledger;
    snapshots.value = snapshotBody.snapshots;
    controls.value = controlBody.controls;
    killSwitch.value = controlBody.controls.kill_switch_engaged;
    killReason.value = controlBody.controls.kill_switch_reason ?? "";
    maxOrderNotional.value = controlBody.controls.max_order_notional == null ? undefined : Number(controlBody.controls.max_order_notional);
    poolId.value = String(accountBody.account.bound_pool_id ?? poolId.value ?? "");
  } catch (exc) { error.value = exc instanceof Error ? exc.message : "读取账户失败"; }
}

async function loadAccounts(preferredId?: string) {
  loading.value = true;
  error.value = "";
  try {
    const [accountBody, poolBody] = await Promise.all([listPaperAccounts(auth.token), listStockPools(auth.token)]);
    accounts.value = accountBody.accounts as PaperAccount[];
    pools.value = poolBody.pools.filter((item) => item.status === "active");
    const next = accounts.value.find((item) => item.account_id === preferredId)
      ?? accounts.value.find((item) => item.account_id === selected.value?.account_id)
      ?? accounts.value[0];
    selected.value = next ?? null;
    if (next?.account_id) await loadDetail(next.account_id);
  } catch (exc) { error.value = exc instanceof Error ? exc.message : "加载模拟账户失败"; }
  finally { loading.value = false; }
}

async function selectAccount(account: PaperAccount) {
  if (!account.account_id) return;
  selected.value = account;
  await loadDetail(account.account_id);
}

async function createAccount() {
  busy.value = "create";
  try {
    const body = await createPaperAccount(accountName.value.trim(), initialCash.value, auth.token);
    await loadAccounts(body.account.account_id);
    ElMessage.success("模拟账户已创建");
  } catch (exc) { error.value = exc instanceof Error ? exc.message : "创建账户失败"; }
  finally { busy.value = ""; }
}

async function placeOrder() {
  if (!selected.value?.account_id || !poolId.value || !symbol.value.trim()) {
    ElMessage.warning("请选择股票池并填写标的"); return;
  }
  busy.value = "order";
  try {
    const body = await submitPaperOrder({
      account_id: selected.value.account_id, pool_id: poolId.value,
      symbol: symbol.value.trim().toUpperCase(), side: side.value,
      quantity: quantity.value, price: price.value, trade_date: tradeDate.value,
      idempotency_key: crypto.randomUUID(),
    }, auth.token);
    await loadDetail(selected.value.account_id);
    if (body.order.status === "blocked") ElMessage.warning(`订单已拦截：${reasonLabel(body.order.blocked_reason)}`);
    else ElMessage.success("模拟订单已成交");
  } catch (exc) { error.value = exc instanceof Error ? exc.message : "提交订单失败"; }
  finally { busy.value = ""; }
}

async function showOrder(order: PaperOrder) {
  if (!selected.value?.account_id || !order.order_id) return;
  busy.value = "detail";
  try { orderDetail.value = (await getPaperOrder(selected.value.account_id, order.order_id, auth.token)).order; orderDialog.value = true; }
  catch (exc) { error.value = exc instanceof Error ? exc.message : "读取订单详情失败"; }
  finally { busy.value = ""; }
}

function openSettlement() {
  settlementMarks.value = Object.fromEntries(positions.value.map((item) => [String(item.symbol), Number(item.market_price ?? item.average_cost ?? price.value)]));
  settlementDialog.value = true;
}

async function settle() {
  if (!selected.value?.account_id || !selected.value.version) return;
  busy.value = "settle";
  try {
    await settlePaperAccount(selected.value.account_id, { trade_date: settlementDate.value,
      expected_version: selected.value.version, idempotency_key: crypto.randomUUID(), marks: settlementMarks.value }, auth.token);
    settlementDialog.value = false;
    await loadDetail(selected.value.account_id);
    activeTab.value = "snapshots";
    ElMessage.success("日终结算已完成，快照不可改写");
  } catch (exc) { error.value = exc instanceof Error ? exc.message : "结算失败"; }
  finally { busy.value = ""; }
}

async function saveControls() {
  if (!selected.value?.account_id || !controls.value) return;
  busy.value = "controls";
  try {
    controls.value = (await updatePaperControls(selected.value.account_id, {
      kill_switch_engaged: killSwitch.value, kill_switch_reason: killReason.value,
      max_order_notional: maxOrderNotional.value ?? null,
      expected_version: controls.value.version, idempotency_key: crypto.randomUUID(),
    }, auth.token)).controls;
    ElMessage.success("风险控制已保存");
  } catch (exc) { error.value = exc instanceof Error ? exc.message : "保存风险控制失败"; }
  finally { busy.value = ""; }
}

async function rebind() {
  if (!selected.value?.account_id || !selected.value.version || !poolId.value) return;
  busy.value = "binding";
  try {
    await rebindPaperAccount(selected.value.account_id, { pool_id: poolId.value, expected_version: selected.value.version, idempotency_key: crypto.randomUUID() }, auth.token);
    await loadDetail(selected.value.account_id); ElMessage.success("账户股票池快照已重新绑定");
  } catch (exc) { error.value = exc instanceof Error ? exc.message : "重新绑定失败"; }
  finally { busy.value = ""; }
}

async function downloadBundle() {
  if (!selected.value?.account_id) return;
  busy.value = "export";
  try {
    const body = await exportPaperAccount(selected.value.account_id, auth.token);
    const blob = new Blob([JSON.stringify(body.bundle, null, 2)], { type: "application/json" });
    const link = document.createElement("a"); link.href = URL.createObjectURL(blob);
    link.download = `${selected.value.name ?? "paper-account"}.paper-account-bundle.json`; link.click(); URL.revokeObjectURL(link.href);
    ElMessage.success("BYQ 账户资产包已导出");
  } catch (exc) { error.value = exc instanceof Error ? exc.message : "导出失败"; }
  finally { busy.value = ""; }
}

async function onImportFile(event: Event) {
  const input = event.target as HTMLInputElement; const file = input.files?.[0]; if (!file) return;
  busy.value = "import";
  try {
    const parsed = JSON.parse(await file.text()) as Record<string, unknown>;
    const body = await importPaperAccount((parsed.bundle as Record<string, unknown>) ?? parsed, auth.token);
    await loadAccounts(body.account.account_id); ElMessage.success("账户资产包已校验并导入为新账户");
  } catch (exc) { error.value = exc instanceof Error ? exc.message : "导入失败"; }
  finally { busy.value = ""; input.value = ""; }
}

onMounted(loadAccounts);
</script>

<template>
  <section class="paper-page">
    <header class="page-hero">
      <div><p class="eyebrow">SIMULATION · CNY · A-SHARE</p><h1>模拟操盘</h1><p>独立于回测的持仓、成交、结算与风险工作台；所有状态均由 BYQ Product API 持久化。</p></div>
      <div class="hero-actions"><el-button :loading="busy === 'import'" @click="importInput?.click()">导入账户资产包</el-button><input ref="importInput" data-testid="paper-import-input" class="hidden-input" type="file" accept="application/json,.json" @change="onImportFile" /><el-button @click="loadAccounts()">刷新</el-button></div>
    </header>
    <div v-if="loading" class="base-loading">加载中...</div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="top-band" />

    <div class="account-layout">
      <el-card shadow="never" class="account-rail">
        <template #header><div class="panel-heading"><strong>模拟账户</strong><el-tag>{{ accounts.length }}</el-tag></div></template>
        <button v-for="account in accounts" :key="account.account_id" class="account-item" :class="{ active: selected?.account_id === account.account_id }" @click="selectAccount(account)"><span><strong>{{ account.name }}</strong><small>{{ account.account_id }}</small></span><span class="account-value">¥ {{ money(account.cash) }}</span></button>
        <el-empty v-if="!accounts.length" description="暂无模拟账户" :image-size="72" /><el-divider />
        <div class="create-grid"><el-input v-model="accountName" data-testid="paper-account-name" placeholder="账户名称" /><el-input-number v-model="initialCash" data-testid="paper-initial-cash" :min="1000" :step="10000" controls-position="right" /><el-button data-testid="paper-create-account" type="primary" :loading="busy === 'create'" @click="createAccount">新建账户</el-button></div>
      </el-card>

      <main v-if="selected" class="workspace">
        <section class="summary-strip"><div><span>现金</span><strong>¥ {{ money(overview.cash) }}</strong></div><div><span>总权益</span><strong>¥ {{ money(overview.equity) }}</strong></div><div><span>持仓市值</span><strong>¥ {{ money(overview.marketValue) }}</strong></div><div><span>已实现盈亏</span><strong :class="{ positive: overview.realizedPnl > 0, negative: overview.realizedPnl < 0 }">¥ {{ money(overview.realizedPnl) }}</strong></div></section>
        <el-card shadow="never" class="trade-ticket"><template #header><div class="panel-heading"><strong>模拟委托</strong><span class="muted">即时确定性成交 · 非实盘</span></div></template>
          <div class="trade-form"><el-select v-model="poolId" data-testid="paper-trade-pool" placeholder="选择授权股票池" filterable><el-option v-for="pool in pools" :key="String(pool.pool_id)" :label="`${pool.name} · ${pool.version ?? ''}`" :value="String(pool.pool_id)" /></el-select><el-input v-model="symbol" data-testid="paper-symbol" placeholder="000001.SZ" /><el-segmented v-model="side" :options="[{ label: '买入', value: 'buy' }, { label: '卖出', value: 'sell' }]" /><el-input-number v-model="quantity" data-testid="paper-quantity" :min="100" :step="100" controls-position="right" /><el-input-number v-model="price" data-testid="paper-price" :min="0.01" :precision="2" :step="0.01" controls-position="right" /><el-input v-model="tradeDate" data-testid="paper-trade-date" placeholder="YYYYMMDD" /><el-button data-testid="paper-submit-order" type="primary" :loading="busy === 'order'" @click="placeOrder">提交模拟订单</el-button></div>
          <p class="binding-note">冻结股票池快照：{{ selected.bound_snapshot_id ?? "首笔成交时绑定" }}</p>
        </el-card>

        <el-card shadow="never" class="detail-card"><el-tabs v-model="activeTab">
          <el-tab-pane label="总览" name="overview"><div class="overview-grid"><div class="info-panel"><span>账户版本</span><strong>v{{ selected.version }}</strong></div><div class="info-panel"><span>最后结算日</span><strong>{{ selected.last_settlement_date ?? "尚未结算" }}</strong></div><div class="info-panel"><span>持仓 / 订单 / 成交</span><strong>{{ positions.length }} / {{ orders.length }} / {{ fills.length }}</strong></div><div class="info-panel"><span>风险状态</span><strong>{{ controls?.kill_switch_engaged ? "已暂停新订单" : "允许委托" }}</strong></div></div></el-tab-pane>
          <el-tab-pane label="持仓" name="positions"><div class="tab-toolbar"><span class="muted">总数量、可卖数量与当日锁定数量分开记录</span><el-button type="primary" plain :disabled="!positions.length" @click="openSettlement">日终结算</el-button></div><el-table :data="positions" empty-text="暂无持仓"><el-table-column prop="symbol" label="标的" min-width="130" /><el-table-column prop="quantity" label="总数量" min-width="95" /><el-table-column prop="sellable_quantity" label="可卖" min-width="95" /><el-table-column prop="locked_quantity" label="T+1 锁定" min-width="105" /><el-table-column label="平均成本" min-width="110"><template #default="{ row }">¥ {{ money(row.average_cost) }}</template></el-table-column><el-table-column label="最新标记" min-width="110"><template #default="{ row }">{{ row.market_price == null ? '-' : `¥ ${money(row.market_price)}` }}</template></el-table-column></el-table></el-tab-pane>
          <el-tab-pane label="订单与成交" name="orders"><el-table :data="orders" empty-text="暂无订单" @row-click="showOrder"><el-table-column prop="trade_date" label="交易日" min-width="105" /><el-table-column prop="symbol" label="标的" min-width="125" /><el-table-column label="方向" min-width="80"><template #default="{ row }">{{ row.side === 'buy' ? '买入' : '卖出' }}</template></el-table-column><el-table-column prop="quantity" label="数量" min-width="90" /><el-table-column label="价格" min-width="100"><template #default="{ row }">¥ {{ money(row.price) }}</template></el-table-column><el-table-column label="状态" min-width="100"><template #default="{ row }"><el-tag :type="row.status === 'filled' ? 'success' : 'warning'">{{ statusLabel(row.status) }}</el-tag></template></el-table-column><el-table-column label="结果" min-width="170"><template #default="{ row }">{{ row.blocked_reason ? reasonLabel(row.blocked_reason) : `费用 ¥ ${money(Number(row.fees ?? 0) + Number(row.tax ?? 0))}` }}</template></el-table-column></el-table></el-tab-pane>
          <el-tab-pane label="资金流水" name="ledger"><el-table :data="ledger" empty-text="暂无资金流水"><el-table-column prop="created_at" label="时间" min-width="180" /><el-table-column prop="entry_type" label="类型" min-width="120" /><el-table-column prop="symbol" label="标的" min-width="120" /><el-table-column label="现金变动" min-width="130" align="right"><template #default="{ row }"><span :class="{ positive: Number(row.cash_delta) > 0, negative: Number(row.cash_delta) < 0 }">¥ {{ money(row.cash_delta) }}</span></template></el-table-column><el-table-column label="费用" min-width="100" align="right"><template #default="{ row }">¥ {{ money(row.fees) }}</template></el-table-column><el-table-column prop="snapshot_id" label="关联快照" min-width="220" show-overflow-tooltip /></el-table></el-tab-pane>
          <el-tab-pane label="结算快照" name="snapshots"><div class="tab-toolbar"><span class="muted">每日快照不可改写；估值变动不伪装成现金流水</span><el-button type="primary" plain :disabled="!positions.length" @click="openSettlement">执行结算</el-button></div><el-table :data="snapshots" empty-text="暂无结算快照"><el-table-column prop="trade_date" label="交易日" min-width="110" /><el-table-column label="权益" min-width="120"><template #default="{ row }">¥ {{ money(row.equity) }}</template></el-table-column><el-table-column label="市值" min-width="120"><template #default="{ row }">¥ {{ money(row.market_value) }}</template></el-table-column><el-table-column label="当日盈亏" min-width="120"><template #default="{ row }">¥ {{ money(row.daily_pnl) }}</template></el-table-column><el-table-column label="当日收益" min-width="110"><template #default="{ row }">{{ row.daily_return == null ? '-' : `${(Number(row.daily_return) * 100).toFixed(2)}%` }}</template></el-table-column><el-table-column prop="snapshot_fingerprint" label="快照指纹" min-width="220" show-overflow-tooltip /></el-table></el-tab-pane>
          <el-tab-pane label="风险与迁移" name="risk"><div class="risk-grid"><section class="risk-panel"><h3>显式风险控制</h3><el-form label-position="top"><el-form-item label="暂停全部新订单"><el-switch v-model="killSwitch" /></el-form-item><el-form-item label="开关原因"><el-input v-model="killReason" maxlength="256" show-word-limit /></el-form-item><el-form-item label="单笔最大金额（CNY）"><el-input-number v-model="maxOrderNotional" :min="100" :step="10000" controls-position="right" /></el-form-item><el-button type="primary" :loading="busy === 'controls'" @click="saveControls">保存风险控制</el-button></el-form></section><section class="risk-panel"><h3>冻结股票池</h3><p class="muted">仅空仓账户可显式重绑；股票池编辑不会改变既有账户。</p><el-select v-model="poolId" placeholder="选择股票池" class="wide-select"><el-option v-for="pool in pools" :key="String(pool.pool_id)" :label="String(pool.name)" :value="String(pool.pool_id)" /></el-select><el-button :disabled="positions.length > 0" :loading="busy === 'binding'" @click="rebind">重新绑定当前快照</el-button></section><section class="risk-panel"><h3>BYQ 账户资产包</h3><p class="muted">导入会校验摘要与引用，并生成新账户 ID；不会覆盖现有账户或导入所有权。</p><div class="button-row"><el-button :loading="busy === 'export'" @click="downloadBundle">导出 JSON</el-button><el-button :loading="busy === 'import'" @click="importInput?.click()">导入为新账户</el-button></div></section></div></el-tab-pane>
        </el-tabs></el-card>
      </main>
    </div>

    <el-dialog v-model="orderDialog" title="订单审计详情" width="min(720px, 94vw)"><div v-if="orderDetail" class="detail-list"><div><span>订单</span><code>{{ orderDetail.order_id }}</code></div><div><span>冻结快照</span><code>{{ orderDetail.stock_pool_snapshot_id }}</code></div><div><span>结果</span><strong>{{ orderDetail.blocked_reason ? reasonLabel(orderDetail.blocked_reason) : statusLabel(orderDetail.status) }}</strong></div><div><span>风险评估</span><pre>{{ JSON.stringify(orderDetail.risk_evaluation_json, null, 2) }}</pre></div><div><span>决策来源</span><pre>{{ JSON.stringify(orderDetail.decision_provenance_json, null, 2) }}</pre></div><div><span>事件</span><pre>{{ JSON.stringify(orderDetail.events_json, null, 2) }}</pre></div></div></el-dialog>
    <el-dialog v-model="settlementDialog" title="手动日终结算" width="min(620px, 94vw)"><el-alert title="所有持仓必须提供正数标记价；同一交易日的快照不可改写。" type="warning" :closable="false" show-icon /><el-form label-position="top" class="settlement-form"><el-form-item label="交易日"><el-input v-model="settlementDate" placeholder="YYYYMMDD" /></el-form-item><el-form-item v-for="position in positions" :key="String(position.symbol)" :label="`${position.symbol} 标记价`"><el-input-number v-model="settlementMarks[String(position.symbol)]" :min="0.01" :precision="4" :step="0.01" controls-position="right" /></el-form-item></el-form><template #footer><el-button @click="settlementDialog = false">取消</el-button><el-button type="primary" :loading="busy === 'settle'" @click="settle">确认结算</el-button></template></el-dialog>
  </section>
</template>

<style scoped>
.paper-page{display:grid;gap:16px}.page-hero{align-items:flex-end;background:linear-gradient(135deg,#0c2332,#143b43 65%,#1e5d55);border-radius:16px;color:#fff;display:flex;justify-content:space-between;padding:24px 28px}.page-hero h1{font-size:28px;margin:2px 0 6px}.page-hero p{margin:0;opacity:.82}.eyebrow{color:#86e0ca;font-size:11px;font-weight:800;letter-spacing:.16em}.hero-actions,.button-row,.panel-heading,.tab-toolbar{align-items:center;display:flex;gap:10px;justify-content:space-between}.hidden-input{display:none}.account-layout{align-items:start;display:grid;gap:16px;grid-template-columns:260px minmax(0,1fr)}.account-rail{position:sticky;top:12px}.account-item{align-items:center;background:transparent;border:1px solid transparent;border-radius:10px;color:inherit;cursor:pointer;display:flex;justify-content:space-between;margin-bottom:6px;padding:10px;text-align:left;width:100%}.account-item:hover,.account-item.active{background:color-mix(in srgb,var(--byq-brand) 9%,transparent);border-color:color-mix(in srgb,var(--byq-brand) 38%,transparent)}.account-item small{color:var(--byq-text-muted);display:block;font-size:10px;max-width:130px;overflow:hidden;text-overflow:ellipsis}.account-value{font-size:12px;font-weight:700}.create-grid,.workspace{display:grid;gap:10px}.summary-strip{display:grid;gap:10px;grid-template-columns:repeat(4,minmax(0,1fr))}.summary-strip>div,.info-panel,.risk-panel{background:var(--el-bg-color);border:1px solid var(--el-border-color-lighter);border-radius:12px;padding:16px}.summary-strip span,.info-panel span{color:var(--byq-text-muted);display:block;font-size:12px;margin-bottom:6px}.summary-strip strong{font-size:20px}.trade-form{display:grid;gap:9px;grid-template-columns:1.5fr 1fr auto 1fr 1fr 1fr auto}.binding-note,.muted{color:var(--byq-text-muted);font-size:12px}.binding-note{margin:10px 0 0;overflow-wrap:anywhere}.overview-grid{display:grid;gap:12px;grid-template-columns:repeat(4,minmax(0,1fr))}.tab-toolbar{margin-bottom:12px}.risk-grid{display:grid;gap:14px;grid-template-columns:repeat(3,minmax(0,1fr))}.risk-panel h3{margin-top:0}.wide-select{margin-bottom:12px;width:100%}.positive{color:var(--el-color-success)}.negative{color:var(--el-color-danger)}.detail-list{display:grid;gap:12px}.detail-list>div{display:grid;gap:6px}.detail-list span{color:var(--byq-text-muted);font-size:12px}.detail-list code,.detail-list pre{background:var(--el-fill-color-light);border-radius:8px;margin:0;overflow:auto;padding:10px;white-space:pre-wrap}.settlement-form{display:grid;gap:0 12px;grid-template-columns:repeat(2,minmax(0,1fr));margin-top:14px}@media(max-width:1100px){.account-layout{grid-template-columns:1fr}.account-rail{position:static}.trade-form{grid-template-columns:repeat(2,minmax(0,1fr))}.risk-grid{grid-template-columns:1fr}}@media(max-width:720px){.page-hero{align-items:flex-start;flex-direction:column;gap:18px;padding:20px}.hero-actions{width:100%}.summary-strip,.overview-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.trade-form,.settlement-form{grid-template-columns:1fr}.summary-strip strong{font-size:16px}}
</style>

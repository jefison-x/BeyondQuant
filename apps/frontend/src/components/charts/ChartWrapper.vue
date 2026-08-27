<script setup lang="ts">
import { LineChart } from "echarts/charts";
import { AriaComponent, GridComponent, LegendComponent, TitleComponent, TooltipComponent } from "echarts/components";
import { init, use, type ECharts, type EChartsCoreOption } from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import BaseEmpty from "@/components/ui/BaseEmpty.vue";
import BaseLoading from "@/components/ui/BaseLoading.vue";

const props = withDefaults(defineProps<{
  option: EChartsCoreOption;
  loading?: boolean;
  empty?: boolean;
  ariaLabel?: string;
  summary?: string;
  emptyMessage?: string;
}>(), {
  loading: false,
  empty: false,
  ariaLabel: "数据图表",
  summary: "",
  emptyMessage: "暂无可绘制数据",
});

const chartEl = ref<HTMLDivElement | null>(null);
use([LineChart, AriaComponent, GridComponent, LegendComponent, TitleComponent, TooltipComponent, CanvasRenderer]);

let chart: ECharts | null = null;
let themeObserver: MutationObserver | null = null;
let resizeObserver: ResizeObserver | null = null;
let mediaQuery: MediaQueryList | null = null;

const reducedMotion = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
const accessibleSummary = computed(() => props.summary || `${props.ariaLabel}。图表使用当前账户主题，可通过相邻数据表读取精确数值。`);

function semanticChartTheme() {
  const styles = getComputedStyle(document.documentElement);
  const read = (name: string) => styles.getPropertyValue(name).trim();
  const text = read("--byq-text");
  const muted = read("--byq-text-muted");
  const border = read("--byq-border-subtle");
  const axis = {
    axisLine: { lineStyle: { color: border } },
    axisTick: { lineStyle: { color: border } },
    axisLabel: { color: muted },
    splitLine: { lineStyle: { color: border } },
  };
  return {
    color: [1, 2, 3, 4, 5, 6].map((index) => read(`--byq-chart-${index}`)),
    backgroundColor: "transparent",
    textStyle: { color: text },
    title: { textStyle: { color: text }, subtextStyle: { color: muted } },
    legend: { textStyle: { color: muted } },
    categoryAxis: axis,
    valueAxis: axis,
  };
}

async function render() {
  await nextTick();
  if (!chartEl.value || props.loading || props.empty) {
    chart?.clear();
    return;
  }
  if (!chart) chart = init(chartEl.value, semanticChartTheme());
  chart.setOption({
    ...props.option,
    animation: !reducedMotion(),
    aria: { enabled: true, decal: { show: true }, ...((props.option.aria as object | undefined) ?? {}) },
  }, true);
}

function rebuild() {
  chart?.dispose();
  chart = null;
  void render();
}

function resize() {
  chart?.resize();
}

onMounted(() => {
  void render();
  themeObserver = new MutationObserver(rebuild);
  themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["data-accent", "data-resolved-mode"] });
  if (window.ResizeObserver && chartEl.value) {
    resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(chartEl.value);
  }
  mediaQuery = window.matchMedia?.("(prefers-reduced-motion: reduce)") ?? null;
  mediaQuery?.addEventListener?.("change", rebuild);
  window.addEventListener("resize", resize);
});

watch(() => [props.option, props.loading, props.empty], () => void render(), { deep: true });
onBeforeUnmount(() => {
  window.removeEventListener("resize", resize);
  mediaQuery?.removeEventListener?.("change", rebuild);
  resizeObserver?.disconnect();
  themeObserver?.disconnect();
  chart?.dispose();
});
</script>

<template>
  <figure class="chart-figure" :aria-busy="loading">
    <BaseLoading v-if="loading" compact message="正在加载图表" />
    <BaseEmpty v-else-if="empty" compact :message="emptyMessage" description="选择其他结果或等待数据生成后重试。" />
    <div v-show="!loading && !empty" ref="chartEl" class="chart-wrapper" role="img" :aria-label="ariaLabel" />
    <figcaption class="sr-only">{{ accessibleSummary }}</figcaption>
  </figure>
</template>

<style scoped>
.chart-figure { margin: 0; min-width: 0; width: 100%; }
</style>

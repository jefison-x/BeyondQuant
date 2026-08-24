<script setup lang="ts">
import * as echarts from "echarts";
import { onBeforeUnmount, onMounted, ref, watch } from "vue";

const props = defineProps<{
  option: echarts.EChartsOption;
  loading?: boolean;
  empty?: boolean;
}>();

const chartEl = ref<HTMLDivElement | null>(null);
let chart: echarts.ECharts | null = null;
let themeObserver: MutationObserver | null = null;

function semanticChartTheme() {
  const styles = getComputedStyle(document.documentElement);
  const text = styles.getPropertyValue("--byq-text").trim();
  const muted = styles.getPropertyValue("--byq-text-muted").trim();
  const border = styles.getPropertyValue("--byq-border-subtle").trim();
  const brand = styles.getPropertyValue("--byq-brand").trim();
  const axis = {
    axisLine: { lineStyle: { color: border } },
    axisTick: { lineStyle: { color: border } },
    axisLabel: { color: muted },
    splitLine: { lineStyle: { color: border } },
  };
  return {
    color: [brand], backgroundColor: "transparent", textStyle: { color: text },
    title: { textStyle: { color: text }, subtextStyle: { color: muted } },
    legend: { textStyle: { color: muted } }, categoryAxis: axis, valueAxis: axis,
  };
}

function render() {
  if (!chartEl.value) return;
  if (!chart) {
    chart = echarts.init(chartEl.value, semanticChartTheme());
  }
  if (props.loading) {
    chart.showLoading();
    return;
  }
  chart.hideLoading();
  if (props.empty) {
    chart.clear();
    return;
  }
  chart.setOption(props.option, true);
}

onMounted(() => {
  render();
  window.addEventListener("resize", resize);
  themeObserver = new MutationObserver(() => {
    chart?.dispose();
    chart = null;
    render();
  });
  themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["data-accent", "data-resolved-mode"] });
});
watch(() => [props.option, props.loading, props.empty], render, { deep: true });
onBeforeUnmount(() => {
  window.removeEventListener("resize", resize);
  themeObserver?.disconnect();
  chart?.dispose();
});

function resize() {
  chart?.resize();
}
</script>

<template>
  <div ref="chartEl" class="chart-wrapper" />
</template>

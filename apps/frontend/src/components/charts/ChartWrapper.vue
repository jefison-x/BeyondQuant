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

function render() {
  if (!chartEl.value) return;
  if (!chart) {
    chart = echarts.init(chartEl.value);
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
});
watch(() => [props.option, props.loading, props.empty], render, { deep: true });
onBeforeUnmount(() => {
  window.removeEventListener("resize", resize);
  chart?.dispose();
});

function resize() {
  chart?.resize();
}
</script>

<template>
  <div ref="chartEl" class="chart-wrapper" />
</template>

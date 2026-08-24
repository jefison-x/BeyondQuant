<script setup lang="ts">
import { useRouter } from "vue-router";
import BaseEmpty from "@/components/ui/BaseEmpty.vue";

const router = useRouter();
</script>

<template>
  <section class="not-found-page" aria-labelledby="not-found-heading">
    <h2 id="not-found-heading" class="sr-only">页面未找到</h2>
    <BaseEmpty
      message="没有找到这个页面"
      description="地址可能已过期。你的数据没有受到影响，可以返回小巴或使用左侧菜单继续。"
    >
      <template #actions>
        <el-button type="primary" @click="router.push('/agent')">返回小巴</el-button>
        <el-button @click="router.back()">返回上一页</el-button>
      </template>
    </BaseEmpty>
  </section>
</template>

<style scoped>
.not-found-page { background: var(--byq-surface); border: 1px solid var(--byq-border); border-radius: 12px; min-height: min(560px, 70vh); }
</style>

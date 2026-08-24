<script setup lang="ts">
defineProps<{
  total: number;
  page: number;
  pageSize?: number;
  label?: string;
}>();

defineEmits<{
  "update:page": [page: number];
}>();
</script>

<template>
  <nav v-if="total > (pageSize ?? 50)" class="entity-pagination" :aria-label="label ?? '实体分页'">
    <span class="entity-pagination__total" aria-live="polite">共 {{ total.toLocaleString("zh-CN") }} 项，第 {{ page }} 页</span>
    <el-pagination
      background
      :pager-count="5"
      layout="prev, pager, next"
      :current-page="page"
      :page-size="pageSize ?? 50"
      :total="total"
      @update:current-page="$emit('update:page', $event)"
    />
  </nav>
</template>

<style scoped>
.entity-pagination {
  align-items: center;
  display: flex;
  gap: 0.75rem;
  justify-content: space-between;
  margin-top: 0.75rem;
}

.entity-pagination__total {
  color: var(--byq-text-muted);
  font-size: 12px;
}

@media (max-width: 520px) {
  .entity-pagination {
    align-items: stretch;
    flex-direction: column;
  }

  .entity-pagination__total {
    text-align: center;
  }

  .entity-pagination :deep(.el-pagination) {
    justify-content: center;
    overflow-x: auto;
    padding-bottom: 2px;
  }
}
</style>

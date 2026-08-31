<script setup lang="ts">
import EntityPagination from "./EntityPagination.vue";

withDefaults(defineProps<{
  query: string;
  page: number;
  pageSize: number;
  total: number;
  placeholder?: string;
  label?: string;
  hideSearch?: boolean;
}>(), {
  placeholder: "筛选当前列表",
  label: "列表分页",
  hideSearch: false,
});

defineEmits<{
  "update:query": [value: string];
  "update:page": [value: number];
}>();
</script>

<template>
  <section class="filtered-list">
    <div v-if="!hideSearch || $slots.filters" class="filtered-list__toolbar">
      <el-input
        v-if="!hideSearch"
        :model-value="query"
        :aria-label="placeholder"
        :placeholder="placeholder"
        clearable
        @update:model-value="$emit('update:query', String($event))"
      />
      <slot name="filters" />
    </div>
    <slot />
    <EntityPagination
      :total="total"
      :page="page"
      :page-size="pageSize"
      :label="label"
      @update:page="$emit('update:page', $event)"
    />
  </section>
</template>

<style scoped>
.filtered-list { display: grid; gap: 12px; min-width: 0; }
.filtered-list__toolbar { align-items: center; display: flex; flex-wrap: wrap; gap: 8px; }
.filtered-list__toolbar > :deep(.el-input) { flex: 1 1 220px; min-width: min(220px, 100%); }
@media (max-width: 560px) {
  .filtered-list__toolbar { align-items: stretch; flex-direction: column; }
  .filtered-list__toolbar > :deep(*) { width: 100%; }
}
</style>

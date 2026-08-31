import { computed, ref, watch, type ComputedRef, type Ref } from "vue";

export interface FilteredPagination<T> {
  query: Ref<string>;
  page: Ref<number>;
  pageSize: Ref<number>;
  filteredItems: ComputedRef<T[]>;
  pageItems: ComputedRef<T[]>;
  total: ComputedRef<number>;
}

export function useFilteredPagination<T>(
  source: ComputedRef<readonly T[]>,
  searchText: (item: T) => string,
  initialPageSize = 20,
): FilteredPagination<T> {
  const query = ref("");
  const page = ref(1);
  const pageSize = ref(initialPageSize);
  const filteredItems = computed(() => {
    const normalized = query.value.trim().toLocaleLowerCase("zh-CN");
    if (!normalized) return [...source.value];
    return source.value.filter((item) => searchText(item).toLocaleLowerCase("zh-CN").includes(normalized));
  });
  const total = computed(() => filteredItems.value.length);
  const pageItems = computed(() => {
    const start = (page.value - 1) * pageSize.value;
    return filteredItems.value.slice(start, start + pageSize.value);
  });

  watch([query, pageSize, source], () => {
    const lastPage = Math.max(1, Math.ceil(total.value / pageSize.value));
    if (page.value > lastPage || query.value) page.value = 1;
  });

  return { query, page, pageSize, filteredItems, pageItems, total };
}

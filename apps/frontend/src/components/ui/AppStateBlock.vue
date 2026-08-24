<script setup lang="ts">
import BaseEmpty from "./BaseEmpty.vue";
import BaseError from "./BaseError.vue";
import BaseLoading from "./BaseLoading.vue";

defineProps<{
  loading?: boolean;
  loadingMessage?: string;
  error?: string;
  empty?: boolean;
  emptyMessage?: string;
  emptyDescription?: string;
  retryLabel?: string;
  compact?: boolean;
}>();

defineEmits<{ retry: [] }>();
</script>

<template>
  <BaseLoading v-if="loading" :message="loadingMessage" :compact="compact" />
  <BaseError v-else-if="error" :message="error" :retry-label="retryLabel" :compact="compact" @retry="$emit('retry')">
    <template v-if="$slots.errorActions" #actions><slot name="errorActions" /></template>
  </BaseError>
  <BaseEmpty v-else-if="empty" :message="emptyMessage" :description="emptyDescription" :compact="compact">
    <template v-if="$slots.emptyActions" #actions><slot name="emptyActions" /></template>
  </BaseEmpty>
  <slot v-else />
</template>

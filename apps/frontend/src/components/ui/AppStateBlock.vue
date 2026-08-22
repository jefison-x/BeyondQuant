<script setup lang="ts">
import BaseEmpty from "./BaseEmpty.vue";
import BaseError from "./BaseError.vue";
import BaseLoading from "./BaseLoading.vue";

defineProps<{
  loading?: boolean;
  error?: string;
  empty?: boolean;
  emptyMessage?: string;
}>();
</script>

<template>
  <BaseLoading v-if="loading" />
  <BaseError v-else-if="error" :message="error" />
  <BaseEmpty v-else-if="empty" :message="emptyMessage" />
  <slot v-else />
</template>

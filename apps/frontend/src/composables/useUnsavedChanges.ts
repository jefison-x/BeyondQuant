import { onBeforeUnmount, onMounted, toValue, type MaybeRefOrGetter } from "vue";
import { onBeforeRouteLeave } from "vue-router";

const DEFAULT_MESSAGE = "存在尚未保存的更改，确定要离开吗？";

export function useUnsavedChanges(
  dirty: MaybeRefOrGetter<boolean>,
  options: { message?: string; onDiscard?: () => void } = {},
) {
  const message = options.message ?? DEFAULT_MESSAGE;

  function confirmDiscard(): boolean {
    if (!toValue(dirty)) return true;
    const confirmed = window.confirm(message);
    if (confirmed) options.onDiscard?.();
    return confirmed;
  }

  function beforeUnload(event: BeforeUnloadEvent) {
    if (!toValue(dirty)) return;
    event.preventDefault();
    event.returnValue = "";
  }

  onMounted(() => window.addEventListener("beforeunload", beforeUnload));
  onBeforeUnmount(() => window.removeEventListener("beforeunload", beforeUnload));
  onBeforeRouteLeave((_to, _from, next) => {
    if (confirmDiscard()) next();
    else next(false);
  });

  return { confirmDiscard };
}

<script setup lang="ts">
import { computed } from "vue";
import DOMPurify from "dompurify";
import MarkdownIt from "markdown-it";

const props = defineProps<{ content: string }>();

const markdown = new MarkdownIt({
  breaks: true,
  html: false,
  linkify: true,
  typographer: false,
});

markdown.validateLink = (url) => /^https?:\/\//i.test(url);
markdown.renderer.rules.link_open = (tokens, index, options, _environment, renderer) => {
  tokens[index].attrSet("target", "_blank");
  tokens[index].attrSet("rel", "noopener noreferrer nofollow");
  return renderer.renderToken(tokens, index, options);
};

const renderedContent = computed(() => DOMPurify.sanitize(markdown.render(props.content), {
  ALLOWED_ATTR: ["class", "href", "rel", "target"],
  ALLOWED_TAGS: [
    "a", "blockquote", "br", "code", "del", "em", "h1", "h2", "h3", "h4", "h5", "h6", "hr",
    "li", "ol", "p", "pre", "strong", "table", "tbody", "td", "th", "thead", "tr", "ul",
  ],
}));
</script>

<template>
  <div class="rich-message" v-html="renderedContent"></div>
</template>

<style scoped>
.rich-message { color: inherit; min-width: 0; overflow-wrap: anywhere; white-space: normal; }
.rich-message :deep(> :first-child) { margin-top: 0; }
.rich-message :deep(> :last-child) { margin-bottom: 0; }
.rich-message :deep(p) { margin: 0 0 .8rem; }
.rich-message :deep(h1),
.rich-message :deep(h2),
.rich-message :deep(h3),
.rich-message :deep(h4),
.rich-message :deep(h5),
.rich-message :deep(h6) { color: var(--byq-text); line-height: 1.35; margin: 1.15rem 0 .55rem; }
.rich-message :deep(h1) { font-size: 1.45rem; }
.rich-message :deep(h2) { font-size: 1.25rem; }
.rich-message :deep(h3) { font-size: 1.08rem; }
.rich-message :deep(h4),
.rich-message :deep(h5),
.rich-message :deep(h6) { font-size: 1rem; }
.rich-message :deep(ul),
.rich-message :deep(ol) { margin: 0 0 .8rem; padding-left: 1.45rem; }
.rich-message :deep(li + li) { margin-top: .25rem; }
.rich-message :deep(blockquote) { border-left: 3px solid var(--byq-brand); color: var(--byq-text-muted); margin: .8rem 0; padding: .1rem 0 .1rem .9rem; }
.rich-message :deep(blockquote p) { margin: 0; }
.rich-message :deep(code) { background: var(--byq-surface-muted); border-radius: 5px; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: .88em; padding: .12em .32em; }
.rich-message :deep(pre) { background: var(--byq-surface-muted); border: 1px solid var(--byq-border-subtle); border-radius: 10px; margin: .8rem 0; overflow-x: auto; padding: .85rem 1rem; }
.rich-message :deep(pre code) { background: transparent; border-radius: 0; padding: 0; }
.rich-message :deep(a) { color: var(--byq-brand); text-decoration: underline; text-underline-offset: 2px; }
.rich-message :deep(hr) { border: 0; border-top: 1px solid var(--byq-border); margin: 1rem 0; }
.rich-message :deep(table) { border-collapse: collapse; display: block; margin: .8rem 0; max-width: 100%; overflow-x: auto; width: max-content; }
.rich-message :deep(th),
.rich-message :deep(td) { border: 1px solid var(--byq-border); padding: .45rem .65rem; text-align: left; white-space: nowrap; }
.rich-message :deep(th) { background: var(--byq-surface-muted); font-weight: 750; }
</style>

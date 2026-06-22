<template>
  <!-- eslint-disable vue/no-v-html -- rendered markdown is sanitized before assignment -->
  <div
    class="markdown-body"
    v-html="html"
  />
  <!-- eslint-enable vue/no-v-html -->
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import MarkdownIt from "markdown-it";
import type { HighlighterCore, LanguageInput, ThemeInput } from "@shikijs/types";

const props = defineProps<{
  content: string;
}>();

const html = ref("<p class='text-muted'>没有内容。</p>");
const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
});

const languageAlias: Record<string, string> = {
  js: "javascript",
  jsx: "tsx",
  ts: "typescript",
  tsx: "tsx",
  sh: "bash",
  shell: "bash",
  bash: "bash",
  json: "json",
  py: "python",
  txt: "text",
};

// Only these languages are loaded — keeps the shiki chunk small
const ALLOWED_LANGUAGES = new Set([
  "javascript",
  "typescript",
  "python",
  "json",
  "bash",
  "text",
]);

// Lazy singleton highlighter — created once, reused
let _highlighterPromise: Promise<HighlighterCore | null> | null = null;

function getHighlighter(): Promise<HighlighterCore | null> {
  if (!_highlighterPromise) {
    _highlighterPromise = (async () => {
      try {
        const [
          { createHighlighterCore },
          { createJavaScriptRegexEngine },
          theme,
          javascript,
          typescript,
          python,
          json,
          bash,
        ] = await Promise.all([
          import("shiki/core"),
          import("@shikijs/engine-javascript"),
          import("@shikijs/themes/github-dark"),
          import("@shikijs/langs/javascript"),
          import("@shikijs/langs/typescript"),
          import("@shikijs/langs/python"),
          import("@shikijs/langs/json"),
          import("@shikijs/langs/bash"),
        ]);

        return await createHighlighterCore({
          engine: createJavaScriptRegexEngine(),
          themes: [theme.default as ThemeInput],
          langs: [
            javascript.default,
            typescript.default,
            python.default,
            json.default,
            bash.default,
          ] as LanguageInput[],
          warnings: false,
        });
      } catch {
        return null;
      }
    })();
  }
  return _highlighterPromise;
}

function normalizeLanguage(language?: string): string {
  if (!language) {
    return "text";
  }
  const normalized =
    languageAlias[language.toLowerCase()] ?? language.toLowerCase();
  return ALLOWED_LANGUAGES.has(normalized) ? normalized : "text";
}

async function renderMarkdown(content: string) {
  const blocks: Array<{ placeholder: string; code: string; lang: string }> = [];
  const transformed = content.replace(
    /```([a-zA-Z0-9_-]+)?\n([\s\S]*?)```/g,
    (_, lang: string, code: string) => {
      const placeholder = `__STEAM_CODE_${blocks.length}__`;
      blocks.push({
        placeholder,
        code,
        lang: normalizeLanguage(lang),
      });
      return `\n${placeholder}\n`;
    },
  );

  let rendered = md.render(transformed);

  // Highlight code blocks with Shiki (fine-grained bundle, only requested langs)
  if (blocks.length > 0) {
    const highlighter = await getHighlighter();
    for (const block of blocks) {
      let codeHtml = "";
      if (highlighter && block.lang !== "text") {
        try {
          codeHtml = highlighter.codeToHtml(block.code, {
            lang: block.lang,
            theme: "github-dark",
          });
        } catch {
          codeHtml = _plainPre(block.code);
        }
      } else {
        codeHtml = _plainPre(block.code);
      }
      rendered = rendered.replace(`<p>${block.placeholder}</p>`, codeHtml);
    }
  }

  html.value = sanitizeRenderedHtml(rendered);
}

function _plainPre(code: string): string {
  return `<pre class="panel-soft p-3 overflow-auto mono">${code
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")}</pre>`;
}

function sanitizeRenderedHtml(rendered: string): string {
  if (typeof DOMParser === "undefined") {
    return rendered;
  }

  const parser = new DOMParser();
  const document = parser.parseFromString(rendered, "text/html");
  const blockedTags = new Set(["script", "style", "iframe", "object", "embed", "link", "meta"]);

  for (const element of Array.from(document.body.querySelectorAll("*"))) {
    const tagName = element.tagName.toLowerCase();
    if (blockedTags.has(tagName)) {
      element.remove();
      continue;
    }

    for (const attr of Array.from(element.attributes)) {
      const name = attr.name.toLowerCase();
      const value = attr.value.trim().toLowerCase();
      if (name.startsWith("on")) {
        element.removeAttribute(attr.name);
      }
      if ((name === "href" || name === "src") && !isSafeUrl(value)) {
        element.removeAttribute(attr.name);
      }
    }
  }

  return document.body.innerHTML;
}

function isSafeUrl(value: string): boolean {
  if (!value || value.startsWith("#") || value.startsWith("/")) {
    return true;
  }
  return value.startsWith("http://") || value.startsWith("https://") || value.startsWith("mailto:");
}

watch(
  () => props.content,
  (value) => {
    void renderMarkdown(value || "");
  },
  { immediate: true },
);

onMounted(() => {
  void renderMarkdown(props.content || "");
});
</script>

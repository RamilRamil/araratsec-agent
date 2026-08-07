import { vitePreprocess } from "@sveltejs/vite-plugin-svelte";

// vitePreprocess enables `<script lang="ts">` in .svelte files (strips types
// via esbuild — no separate type-check at build; run `npm run check` for that).
export default {
  preprocess: vitePreprocess(),
};

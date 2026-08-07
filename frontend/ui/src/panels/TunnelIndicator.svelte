<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { api, type Heartbeat } from "../lib/api";

  // Live model/tunnel indicator. The BACKEND runs the actual keep-alive ping loop
  // (so the tunnel stays warm even with no tab open); here we just poll the stored
  // state cheaply for display.
  let hb: Heartbeat | null = null;
  let timer: ReturnType<typeof setInterval>;

  async function poll() {
    try {
      hb = await api.heartbeat();
    } catch {
      hb = { state: "unknown", endpoint: null, model: null, checked_at: null, fails: 0 };
    }
  }

  onMount(() => {
    poll();
    timer = setInterval(poll, 5000);
  });
  onDestroy(() => clearInterval(timer));

  $: dot = hb?.state === "up" ? "ok" : hb?.state === "down" ? "bad" : "unknown";
  $: title = hb
    ? `${hb.model ?? "model"} @ ${hb.endpoint ?? "?"} — ${hb.state}` +
      (hb.age_s != null ? ` (checked ${hb.age_s}s ago)` : "") +
      (hb.fails ? ` · ${hb.fails} consecutive fails` : "")
    : "checking…";
</script>

<span class="hb" title={title}>
  <span class="hbdot {dot}"></span>
  <span class="muted mono">
    {#if hb?.state === "up"}tunnel up{:else if hb?.state === "down"}tunnel down{:else}tunnel ?{/if}
  </span>
</span>

<style>
  .hb { display: inline-flex; align-items: center; gap: 6px; }
  .hbdot { width: 9px; height: 9px; border-radius: 999px; background: var(--muted); }
  .hbdot.ok { background: var(--ok); box-shadow: 0 0 6px var(--ok); }
  .hbdot.bad { background: var(--danger); box-shadow: 0 0 6px var(--danger); animation: pulse 1.2s infinite; }
  .hbdot.unknown { background: var(--muted); }
  @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }
</style>

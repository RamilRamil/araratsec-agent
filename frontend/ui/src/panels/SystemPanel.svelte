<script lang="ts">
  import { api, type HealthStatus, type ModuleDescriptor } from "../lib/api";

  let health: HealthStatus | null = null;
  let mods: ModuleDescriptor | null = null;
  let error = "";

  async function load() {
    error = "";
    try {
      [health, mods] = await Promise.all([api.health(), api.modules()]);
    } catch (e) {
      error = (e as Error).message;
    }
  }
  load();
</script>

<div class="panel">
  <h2>System</h2>
  <div class="row" style="justify-content: space-between;">
    <span class="muted">Model readiness &amp; active modules</span>
    <button on:click={load}>Refresh</button>
  </div>

  {#if health}
    <div class="stack" style="margin-top: 10px;">
      <div class="row" style="justify-content: space-between;">
        <span class="mono">{health.model_name} @ {health.endpoint}</span>
        <span class="badge {health.model_ready ? 'ok' : health.model_available ? 'warn' : 'bad'}">
          {health.model_ready ? "ready" : health.model_available ? "reachable, not ready" : "unreachable"}
        </span>
      </div>
      <span class="muted mono">backend: {health.backend}</span>
    </div>
  {/if}

  {#if mods}
    <div style="margin-top: 12px;">
      <div class="muted">active pack: <span class="badge">{mods.active_pack}</span></div>
      <div class="stack" style="margin-top: 8px;">
        {#each mods.pack_tools as t}
          <div class="mono"><span class="tier tier-unknown">{t.action_class}</span> {t.name} — <span class="muted">{t.description}</span></div>
        {/each}
      </div>
      <h2 style="margin-top: 14px;">Kernel invariants a pack cannot weaken</h2>
      <ul class="muted" style="margin: 0; padding-left: 18px;">
        {#each mods.kernel_invariants as inv}<li>{inv}</li>{/each}
      </ul>
    </div>
  {/if}
  {#if error}<div class="badge bad" style="margin-top: 8px;">{error}</div>{/if}
</div>

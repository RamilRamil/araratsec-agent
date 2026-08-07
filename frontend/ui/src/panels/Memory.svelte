<script lang="ts">
  import { api, type MemoryRecordView } from "../lib/api";
  import { trustClass, trustLabel } from "../lib/trust";

  export let projectId: string | null = null;

  let records: MemoryRecordView[] = [];
  let error = "";

  // Read-only: this panel NEVER writes memory. Reload when the project changes.
  $: if (projectId) load(projectId);

  async function load(pid: string) {
    error = "";
    try {
      records = await api.memory(pid);
    } catch (e) {
      error = (e as Error).message;
    }
  }
</script>

<div class="panel">
  <h2>Memory (read-only, HMAC-verified)</h2>
  {#if !projectId}
    <div class="muted">Start a session to browse its project memory.</div>
  {:else if records.length === 0}
    <div class="muted">No verified records yet for <span class="mono">{projectId}</span>.</div>
  {:else}
    <div class="stack" style="max-height: 320px; overflow-y: auto;">
      {#each records as r}
        <div class="stack" style="gap: 2px; border-bottom: 1px solid var(--border); padding-bottom: 6px;">
          <div class="row" style="gap: 6px;">
            <span class="badge">{r.kind}</span>
            <span class={trustClass(r.source_type)}>{trustLabel(r.source_type)}</span>
            <span class="mono muted">{r.target}</span>
          </div>
          <!-- inert: record body is DATA, escaped by the text binding (R7) -->
          <div class="mono" style="white-space: pre-wrap;">{JSON.stringify(r.body)}</div>
        </div>
      {/each}
    </div>
  {/if}
  {#if error}<div class="badge bad" style="margin-top: 8px;">{error}</div>{/if}
</div>

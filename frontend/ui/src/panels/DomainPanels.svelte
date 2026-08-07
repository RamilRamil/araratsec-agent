<script lang="ts">
  import { api, type DomainPanels } from "../lib/api";

  export let sessionId: string | null = null;
  export let projectId: string | null = null;

  let data: DomainPanels | null = null;
  let error = "";

  // Pack-produced panels (SC-008): this generic panel renders whatever the
  // active pack contributes, tagged by pack — it has no audit-specific logic.
  $: if (sessionId && projectId) load(sessionId, projectId);

  async function load(sid: string, pid: string) {
    error = "";
    try {
      data = await api.domainPanels(sid, pid);
    } catch (e) {
      error = (e as Error).message;
    }
  }
</script>

<div class="panel">
  <h2>Domain panels{#if data} · <span class="badge">{data.pack}</span>{/if}</h2>
  {#if !sessionId}
    <div class="muted">Start a session to see pack-contributed domain data.</div>
  {:else if data}
    {#each data.panels as p}
      <div style="margin-bottom: 10px;">
        <div class="muted">{p.title}</div>
        <!-- inert: pack body is DATA (memory-derived), rendered as escaped text (R7) -->
        <pre class="mono" style="white-space: pre-wrap; margin: 4px 0 0;">{p.body}</pre>
      </div>
    {/each}
  {/if}
  {#if error}<div class="badge bad">{error}</div>{/if}
</div>

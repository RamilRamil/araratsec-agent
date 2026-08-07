<script lang="ts">
  import { connectTrace, type TraceEvent } from "../lib/ws";
  import { trustClass, trustLabel } from "../lib/trust";

  export let sessionId: string | null = null;

  let events: TraceEvent[] = [];
  let conn: { close: () => void } | null = null;

  // (Re)connect whenever the bound session changes.
  $: {
    conn?.close();
    events = [];
    if (sessionId) {
      conn = connectTrace(sessionId, (e) => {
        events = [...events.slice(-199), e]; // cap the buffer
      });
    }
  }

  const summarize = (e: TraceEvent): string => {
    switch (e.type) {
      case "turn_start": return `▶ turn: ${e.user_message ?? ""}`;
      case "routing": return `routing → ${e.tier ?? "?"}`;
      case "reasoning": return `reasoning: ${e.summary ?? e.next_action ?? ""}`;
      case "tool": return `tool ${e.name ?? e.action_type ?? ""}: ${e.summary ?? ""}`;
      case "escalation": return `⚠ escalation: ${e.reason ?? ""}`;
      case "outcome": return `■ ${e.status ?? "done"}`;
      default: return e.type;
    }
  };
</script>

<div class="panel">
  <h2>Live trace</h2>
  {#if !sessionId}
    <div class="muted">Start a session to watch its ReAct steps stream live.</div>
  {:else if events.length === 0}
    <div class="muted">Waiting for the next turn…</div>
  {:else}
    <div class="stack" style="max-height: 360px; overflow-y: auto;">
      {#each events as e}
        <div class="row" style="gap: 6px; align-items: baseline;">
          {#if e.source_type}
            <span class={trustClass(e.source_type)}>{trustLabel(e.source_type)}</span>
          {/if}
          <!-- inert: event fields are DATA, rendered as escaped text (R7) -->
          <span class="mono">{summarize(e)}</span>
        </div>
      {/each}
    </div>
  {/if}
</div>

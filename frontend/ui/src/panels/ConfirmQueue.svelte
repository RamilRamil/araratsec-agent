<script lang="ts">
  import { api, type ConfirmationItem, type ConfirmationNotice } from "../lib/api";

  let items: ConfirmationItem[] = [];
  // The reviewed item: its notice was fetched, which issued the confirm_token.
  // Approval is possible ONLY after this deliberate review step (FR-009).
  let reviewing: ConfirmationNotice | null = null;
  let error = "";
  let busy = false;

  export async function refresh() {
    try {
      items = await api.confirmations();
    } catch (e) {
      error = (e as Error).message;
    }
  }
  refresh();

  async function review(id: string) {
    error = "";
    try {
      reviewing = await api.notice(id); // fetch notice → issues the one-shot token
    } catch (e) {
      error = (e as Error).message;
    }
  }

  async function decide(decision: "approve" | "reject") {
    if (!reviewing) return;
    busy = true;
    error = "";
    try {
      await api.decide(reviewing.id, reviewing.confirm_token, decision);
      reviewing = null;
      await refresh();
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }
</script>

<div class="panel">
  <h2>Confirmation queue 🔒</h2>
  <div class="row" style="justify-content: space-between;">
    <span class="muted">Consequential actions pause here and never auto-run.</span>
    <button on:click={refresh}>Refresh</button>
  </div>

  {#if items.length === 0}
    <div class="muted" style="margin-top: 10px;">Nothing pending.</div>
  {:else}
    <div class="stack" style="margin-top: 10px;">
      {#each items as it}
        <div class="row" style="justify-content: space-between; border-bottom: 1px solid var(--border); padding-bottom: 6px;">
          <span class="mono">{it.action_type} · <span class="muted">{it.id.slice(0, 8)}</span></span>
          <button on:click={() => review(it.id)}>Review…</button>
        </div>
      {/each}
    </div>
  {/if}

  {#if reviewing}
    <div class="panel" style="background: var(--panel-2); margin-top: 12px;">
      <h2>Review before approving</h2>
      <div class="muted">This is what would run. Approval is a deliberate act — a bare click cannot approve.</div>
      <div class="mono" style="margin: 8px 0;">
        action: {reviewing.action_type}<br />
        <!-- inert: params are DATA, escaped by the text binding (R7) -->
        params: {JSON.stringify(reviewing.params)}
      </div>
      <div class="row">
        <button class="primary" on:click={() => decide("approve")} disabled={busy}>Approve &amp; run</button>
        <button class="danger" on:click={() => decide("reject")} disabled={busy}>Reject</button>
        <button on:click={() => (reviewing = null)} disabled={busy}>Cancel</button>
      </div>
      <div class="muted mono" style="margin-top: 8px;">
        CLI fallback: sr-agent confirm {reviewing.id} --approve
      </div>
    </div>
  {/if}
  {#if error}<div class="badge bad" style="margin-top: 8px;">{error}</div>{/if}
</div>

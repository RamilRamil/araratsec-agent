<script lang="ts">
  import ChatSession from "./panels/ChatSession.svelte";
  import LiveTrace from "./panels/LiveTrace.svelte";
  import ConfirmQueue from "./panels/ConfirmQueue.svelte";
  import Settings from "./panels/Settings.svelte";
  import SystemPanel from "./panels/SystemPanel.svelte";
  import Memory from "./panels/Memory.svelte";
  import DomainPanels from "./panels/DomainPanels.svelte";
  import TunnelIndicator from "./panels/TunnelIndicator.svelte";

  let sessionId: string | null = null;
  let projectId: string | null = null;
  let queue: ConfirmQueue;

  function onStarted(e: CustomEvent<{ sessionId: string; projectId: string }>) {
    sessionId = e.detail.sessionId;
    projectId = e.detail.projectId;
  }
  async function onTurn() {
    // A turn may have paused a consequential action → surface it in the queue.
    await queue?.refresh();
  }
</script>

<header>
  <div class="row" style="justify-content: space-between; align-items: baseline;">
    <h1 style="margin: 0; font-size: 18px;">SR-agent · <span class="muted">operator console</span></h1>
    <div class="row" style="gap: 14px;">
      <TunnelIndicator />
      <span class="muted mono">single operator · local model · no paid API</span>
    </div>
  </div>
</header>

<main>
  <section>
    <ChatSession {sessionId} on:started={onStarted} on:turn={onTurn} />
    <LiveTrace {sessionId} />
    <DomainPanels {sessionId} {projectId} />
    <Memory {projectId} />
  </section>
  <aside>
    <ConfirmQueue bind:this={queue} />
    <Settings />
    <SystemPanel />
  </aside>
</main>

<style>
  header {
    padding: 14px 18px;
    border-bottom: 1px solid var(--border);
  }
  main {
    display: grid;
    grid-template-columns: 1.4fr 1fr;
    gap: 16px;
    padding: 16px 18px;
    max-width: 1280px;
    margin: 0 auto;
  }
  @media (max-width: 900px) {
    main { grid-template-columns: 1fr; }
  }
</style>

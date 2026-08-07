<script lang="ts">
  import { createEventDispatcher } from "svelte";
  import { api, type TurnResult } from "../lib/api";

  export let sessionId: string | null = null;

  const dispatch = createEventDispatcher<{
    started: { sessionId: string; projectId: string };
    turn: TurnResult;
  }>();

  let target = "";  // explicit external target folder — no default (never the agent repo)
  let repoUrl = ""; // OR a git repo URL to clone (spec 021) — provide one, not both
  let projectId = "";
  let auditFile = ""; // optional external audit-report file (spec 019) — reference only
  let text = "";
  let scopeRoot = "";
  let status = "";
  let busy = false;
  let error = "";
  // Transcript of this operator's turns. Model output is UNTRUSTED — rendered
  // inert via a text binding (never {@html}).
  let transcript: { role: "operator" | "agent"; text: string; tier?: string }[] = [];

  async function start() {
    error = "";
    busy = true;
    try {
      const s = await api.startSession(
        target.trim(), projectId.trim() || undefined, auditFile.trim() || undefined,
        repoUrl.trim() || undefined,
      );
      dispatch("started", { sessionId: s.session_id, projectId: s.project_id });
      scopeRoot = s.scope_root;   // the resolved external target the session is bound to
      status = "active";
      transcript = [];
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }

  async function send() {
    if (!sessionId || !text.trim()) return;
    const msg = text.trim();
    transcript = [...transcript, { role: "operator", text: msg }];
    text = "";
    error = "";
    busy = true;
    try {
      const r = await api.sendMessage(sessionId, msg);
      status = r.status;
      transcript = [
        ...transcript,
        {
          role: "agent",
          text:
            r.answer ??
            (r.status === "paused_confirmation"
              ? "⏸ paused — a consequential action is awaiting your approval (see the queue)."
              : `(${r.status})`),
          tier: r.tier,
        },
      ];
      dispatch("turn", r);
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }
</script>

<div class="panel">
  <h2>Session</h2>
  {#if !sessionId}
    <div class="stack">
      <label class="stack">
        <span class="muted">External target folder (absolute path — binds the working scope; never the agent repo)</span>
        <input bind:value={target} placeholder="/path/to/target/contracts" disabled={!!repoUrl.trim()} />
      </label>
      <label class="stack">
        <span class="muted">…or a git repo URL to clone (provide one — a path OR a URL). Public, or private via GITHUB_TOKEN.</span>
        <input bind:value={repoUrl} placeholder="https://github.com/org/repo.git" disabled={!!target.trim()} />
      </label>
      <label class="stack">
        <span class="muted">Audit file (optional — external report path; reference only, never obeyed)</span>
        <input bind:value={auditFile} placeholder="/path/to/audit-report.md" />
      </label>
      <label class="stack">
        <span class="muted">Project id (optional — memory namespace)</span>
        <input bind:value={projectId} placeholder="defaults to the folder name" />
      </label>
      <button class="primary" on:click={start} disabled={busy || (!target.trim() && !repoUrl.trim())}>Start session</button>
    </div>
  {:else}
    <div class="row" style="justify-content: space-between;">
      <span class="mono muted">scope: {scopeRoot}</span>
      <span class="badge {status.startsWith('paused') ? 'warn' : status.startsWith('blocked') ? 'bad' : 'ok'}">{status || "active"}</span>
    </div>

    <div class="stack" style="margin: 10px 0; max-height: 320px; overflow-y: auto;">
      {#each transcript as t}
        <div class="stack" style="gap: 2px;">
          <span class="muted mono">
            {t.role === "operator" ? "you" : "agent"}
            {#if t.tier}<span class="tier tier-{t.tier === 'local' ? 'llm_inference' : 'unknown'}">{t.tier}</span>{/if}
          </span>
          <!-- inert: text binding auto-escapes untrusted model output (R7) -->
          <div style="white-space: pre-wrap;">{t.text}</div>
        </div>
      {/each}
    </div>

    <div class="row">
      <input
        bind:value={text}
        placeholder="ask the agent…"
        on:keydown={(e) => e.key === "Enter" && send()}
      />
      <button class="primary" on:click={send} disabled={busy || !text.trim()}>Send</button>
    </div>
  {/if}
  {#if error}<div class="badge bad" style="margin-top: 8px;">{error}</div>{/if}
</div>

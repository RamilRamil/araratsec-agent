<script lang="ts">
  import { api, type ModelConfig, type WarmResult } from "../lib/api";

  // ── Main agent (serves every non-escalated turn) ───────────────────────────
  let cfg: ModelConfig | null = null;
  let endpoint = "";
  let model = "";
  let backend = "local";
  let paidKey = ""; // write-only; the backend never returns it
  let warm: WarmResult | null = null;
  let busy = false;
  let error = "";
  let geminiModels: string[] = []; // populated from /api/model/models
  let openrouterModels: string[] = []; // OpenRouter tier (GLM), spec 020

  // ── Additional agent (consulted automatically on escalation, spec 019) ──────
  let addCfg: ModelConfig | null = null;
  let addEndpoint = "";
  let addModel = "";
  let addBackend = "off"; // "off" | "local" | "paid" — off → escalation uses the file relay
  let addKey = "";
  let addError = "";

  async function load() {
    cfg = await api.getModelConfig();
    endpoint = cfg.endpoint;
    model = cfg.model ?? "";
    backend = cfg.backend;
    addCfg = await api.getAdditional();
    addEndpoint = addCfg.endpoint;
    addModel = addCfg.model ?? "";
    addBackend = addCfg.backend;
    try {
      const m = await api.getModelModels();
      geminiModels = m.models;
      openrouterModels = m.openrouter;
    } catch {
      geminiModels = [];
      openrouterModels = [];
    }
  }
  load();

  async function save() {
    error = "";
    busy = true;
    try {
      cfg = await api.setModelConfig({
        endpoint,
        model,
        backend,
        paid_key: paidKey || undefined,
      });
      paidKey = "";
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }

  async function saveAdditional() {
    addError = "";
    busy = true;
    try {
      addCfg = await api.setAdditional({
        endpoint: addEndpoint,
        model: addModel,
        backend: addBackend,
        paid_key: addKey || undefined,
      });
      addKey = "";
    } catch (e) {
      addError = (e as Error).message;
    } finally {
      busy = false;
    }
  }

  async function doWarm() {
    error = "";
    busy = true;
    warm = null;
    try {
      warm = await api.warm();
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }
</script>

<div class="panel">
  <h2>Main agent</h2>
  <div class="stack">
    <label class="stack">
      <span class="muted">Backend (explicit — the hosted backend is never a silent fallback)</span>
      <select bind:value={backend}>
        <option value="local">Local (free, Ollama)</option>
        <option value="paid">Gemini (hosted, explicit opt-in)</option>
        <option value="openrouter">OpenRouter (GLM, hosted)</option>
      </select>
    </label>
    {#if backend === "local"}
      <label class="stack">
        <span class="muted">Local endpoint (localhost or a cloud-GPU tunnel URL)</span>
        <input bind:value={endpoint} placeholder="http://localhost:11434" />
      </label>
      <label class="stack">
        <span class="muted">Model (blank → auto-pick a stage-2 model)</span>
        <input bind:value={model} placeholder="e.g. qwen2.5-coder:14b" />
      </label>
    {:else if backend === "paid"}
      <label class="stack">
        <span class="muted">Gemini model (simpler/cheaper first)</span>
        <select bind:value={model}>
          {#each geminiModels as m}
            <option value={m}>{m}</option>
          {/each}
        </select>
      </label>
      <label class="stack">
        <span class="muted">Gemini API key (held in memory only — never stored or returned; overrides GEMINI_API_KEY)</span>
        <input type="password" bind:value={paidKey} placeholder={cfg?.has_paid_key ? "•••••• (set)" : "AIza…"} />
      </label>
    {:else}
      <label class="stack">
        <span class="muted">OpenRouter model (GLM)</span>
        <select bind:value={model}>
          {#each openrouterModels as m}
            <option value={m}>{m}</option>
          {/each}
        </select>
      </label>
      <p class="muted">Key comes from <code>OPENROUTER_API_KEY</code> (env / .env). The field below is an optional override.</p>
      <label class="stack">
        <span class="muted">OpenRouter API key (optional; in-memory only, never stored/returned; overrides env)</span>
        <input type="password" bind:value={paidKey} placeholder={cfg?.has_paid_key ? "•••••• (set)" : "sk-or-…"} />
      </label>
    {/if}
    <div class="row">
      <button class="primary" on:click={save} disabled={busy}>Save main</button>
      <button on:click={doWarm} disabled={busy}>Warm model</button>
      {#if cfg}<span class="badge {cfg.has_paid_key ? 'warn' : 'ok'}">key: {cfg.has_paid_key ? "set" : "none"}</span>{/if}
    </div>
    {#if warm}
      <div class="badge {warm.state === 'ready' ? 'ok' : warm.state === 'warming' ? 'warn' : 'bad'}">
        {warm.state}{warm.reason ? ` — ${warm.reason}` : ""} ({warm.elapsed_s}s)
      </div>
    {/if}
    {#if error}<div class="badge bad">{error}</div>{/if}
  </div>
</div>

<div class="panel">
  <h2>Additional agent</h2>
  <p class="muted">Consulted automatically when a turn escalates. Its answers are untrusted — anything privileged it proposes still pauses for your confirmation. <b>Off</b> keeps the manual relay hand-off.</p>
  <div class="stack">
    <label class="stack">
      <span class="muted">Connection</span>
      <select bind:value={addBackend}>
        <option value="off">Off (manual relay hand-off)</option>
        <option value="local">Local (Ollama)</option>
        <option value="paid">Gemini (hosted)</option>
        <option value="openrouter">OpenRouter (GLM, hosted)</option>
      </select>
    </label>
    {#if addBackend === "local"}
      <label class="stack">
        <span class="muted">Local endpoint</span>
        <input bind:value={addEndpoint} placeholder="http://localhost:11434" />
      </label>
      <label class="stack">
        <span class="muted">Model</span>
        <input bind:value={addModel} placeholder="e.g. qwen2.5-coder:14b" />
      </label>
    {:else if addBackend === "paid"}
      <label class="stack">
        <span class="muted">Gemini model</span>
        <select bind:value={addModel}>
          {#each geminiModels as m}
            <option value={m}>{m}</option>
          {/each}
        </select>
      </label>
      <label class="stack">
        <span class="muted">Gemini API key (write-only; overrides GEMINI_API_KEY)</span>
        <input type="password" bind:value={addKey} placeholder={addCfg?.has_paid_key ? "•••••• (set)" : "AIza…"} />
      </label>
    {:else if addBackend === "openrouter"}
      <label class="stack">
        <span class="muted">OpenRouter model (GLM)</span>
        <select bind:value={addModel}>
          {#each openrouterModels as m}
            <option value={m}>{m}</option>
          {/each}
        </select>
      </label>
      <label class="stack">
        <span class="muted">OpenRouter API key (optional; write-only; overrides OPENROUTER_API_KEY)</span>
        <input type="password" bind:value={addKey} placeholder={addCfg?.has_paid_key ? "•••••• (set)" : "sk-or-…"} />
      </label>
    {/if}
    <div class="row">
      <button class="primary" on:click={saveAdditional} disabled={busy}>Save additional</button>
      {#if addCfg}<span class="badge {addCfg.has_paid_key ? 'warn' : 'ok'}">key: {addCfg.has_paid_key ? "set" : "none"}</span>{/if}
    </div>
    {#if addError}<div class="badge bad">{addError}</div>{/if}
  </div>
</div>

// Typed REST client for the operator backend. Thin wrapper over fetch — the
// backend routes are documented in contracts/http-api.md.

async function j<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

const post = (path: string, body: unknown) =>
  fetch(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });

export interface HealthStatus {
  model_name: string;
  endpoint: string;
  backend: string;
  model_available: boolean;
  model_ready: boolean;
  ollama_reachable: boolean;
}

export interface ModuleDescriptor {
  kernel: string;
  active_pack: string;
  pack_tools: { name: string; action_class: string; description: string }[];
  kernel_invariants: string[];
}

export interface ModelConfig {
  endpoint: string;
  model: string | null;
  backend: string;
  has_paid_key: boolean;
}

export interface WarmResult {
  state: "ready" | "warming" | "failed";
  reason: string | null;
  model: string;
  elapsed_s: number;
}

export interface Heartbeat {
  state: "up" | "down" | "unknown";
  endpoint: string | null;
  model: string | null;
  checked_at: number | null;
  fails: number;
  age_s?: number;
}

export interface SessionView {
  session_id: string;
  project_id: string;
  scope_root: string;
  status: string;
  pending_confirmation_id: string | null;
}

export interface TurnResult {
  status: string;
  answer: string | null;
  tier: string;
  pending_confirmation_id: string | null;
  pending_action_type: string | null;
  pending_action_params: Record<string, unknown> | null;
  tool_summaries: string[];
}

export interface ConfirmationItem {
  id: string;
  action_type: string | null;
  params: Record<string, unknown>;
  created_at?: string;
  state: string;
}

export interface ConfirmationNotice extends ConfirmationItem {
  confirm_token: string;
}

export interface DomainPanels {
  pack: string;
  panels: { title: string; kind: string; body: string }[];
}

export interface MemoryRecordView {
  kind: string;
  source_type: string;
  target: string;
  session_id: string;
  body: unknown;
}

export const api = {
  health: () => fetch("/api/health").then(j<HealthStatus>),
  modules: () => fetch("/api/modules").then(j<ModuleDescriptor>),

  getModelConfig: () => fetch("/api/model/config").then(j<ModelConfig>),
  getModelModels: () =>
    fetch("/api/model/models").then(
      j<{ models: string[]; openrouter: string[]; selected: string }>,
    ),
  setModelConfig: (b: {
    endpoint?: string;
    model?: string;
    backend?: string;
    paid_key?: string;
  }) => post("/api/model/config", b).then(j<ModelConfig>),
  // Additional-agent slot (spec 019) — consulted automatically on escalation.
  getAdditional: () => fetch("/api/model/additional").then(j<ModelConfig>),
  setAdditional: (b: {
    endpoint?: string;
    model?: string;
    backend?: string;
    paid_key?: string;
  }) => post("/api/model/additional", b).then(j<ModelConfig>),
  warm: () => post("/api/model/warm", {}).then(j<WarmResult>),
  heartbeat: () => fetch("/api/model/heartbeat").then(j<Heartbeat>),

  startSession: (
    project_path: string, project_id?: string, audit_path?: string, repo_url?: string,
  ) =>
    post("/api/session", { project_path, project_id, audit_path, repo_url }).then(
      j<{ session_id: string; project_id: string; scope_root: string; has_report: boolean }>,
    ),
  getSession: (id: string) => fetch(`/api/session/${id}`).then(j<SessionView>),
  sendMessage: (id: string, text: string) =>
    post(`/api/session/${id}/message`, { text }).then(j<TurnResult>),

  memory: (project: string) =>
    fetch(`/api/memory?project=${encodeURIComponent(project)}`).then(
      j<MemoryRecordView[]>,
    ),
  domainPanels: (session: string, project: string) =>
    fetch(
      `/api/domain/panels?session=${encodeURIComponent(session)}&project=${encodeURIComponent(project)}`,
    ).then(j<DomainPanels>),

  confirmations: () => fetch("/api/confirmations").then(j<ConfirmationItem[]>),
  // Fetching an item's notice ISSUES the one-shot confirm_token (FR-009).
  notice: (id: string) =>
    fetch(`/api/confirmations/${id}`).then(j<ConfirmationNotice>),
  decide: (id: string, confirm_token: string, decision: "approve" | "reject") =>
    post(`/api/confirm/${id}`, { confirm_token, decision }).then(
      j<{ confirmation_id: string; status: string }>,
    ),
};

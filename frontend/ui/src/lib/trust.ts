// The trust boundary, made legible (US4 / research R7).
//
// Mirrors the kernel's SourceType trust hierarchy (models/memory.py TRUST_LEVELS)
// for DISPLAY ONLY — this is not an authority, just labels + styling. The actual
// enforcement lives in the kernel. The security rule this file supports: content
// from anything below human_input is UNTRUSTED and must be rendered INERT. Svelte
// text bindings (`{value}`) auto-escape, so panels bind text — NEVER `{@html}` —
// on any field that could carry model/relay/tool output.

export type SourceType =
  | "human_input"
  | "tool_output"
  | "external_llm_output"
  | "human_relayed_tool"
  | "llm_inference";

const LEVEL: Record<SourceType, number> = {
  human_input: 4,
  tool_output: 3,
  external_llm_output: 2,
  human_relayed_tool: 2,
  llm_inference: 1,
};

const LABEL: Record<SourceType, string> = {
  human_input: "human",
  tool_output: "tool",
  external_llm_output: "external-llm",
  human_relayed_tool: "human-relayed",
  llm_inference: "local-inference",
};

export const trustLevel = (s: string): number => LEVEL[s as SourceType] ?? 0;
export const trustLabel = (s: string): string => LABEL[s as SourceType] ?? s;

// Only human_input is trusted; everything else is DATA and must render inert.
export const isUntrusted = (s: string): boolean =>
  (s as SourceType) !== "human_input";

// A CSS class per tier so the operator SEES provenance at a glance.
export const trustClass = (s: string): string =>
  `tier tier-${(s as SourceType) in LEVEL ? s : "unknown"}`;

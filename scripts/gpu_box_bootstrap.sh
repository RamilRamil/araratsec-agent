#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# GPU-box bootstrap for the SR-bot PoC harness model backend.
# Run this ON the cloud GPU host (Colab / Kaggle / any CUDA box). Idempotent.
#
# Bakes in roadmap gotcha #4: `pciutils` (lspci) MUST be present *before*
# `ollama serve` starts, or Ollama silently falls back to CPU on a CUDA box
# → slow decode → cloudflared 524s on long generations. This script installs
# pciutils first, (re)starts serve, and FAILS LOUD if the model lands on CPU.
#
# Usage:   MODEL=qwen3-coder:30b  bash gpu_box_bootstrap.sh
#          MODEL=qwen2.5-coder:7b bash gpu_box_bootstrap.sh   # smaller/faster
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

MODEL="${MODEL:-qwen3-coder:30b}"
KEEP_ALIVE="${OLLAMA_KEEP_ALIVE:-30m}"   # keep the model resident in VRAM

log(){ printf '\n\033[1;36m[bootstrap]\033[0m %s\n' "$*"; }
die(){ printf '\n\033[1;31m[FATAL]\033[0m %s\n' "$*" >&2; exit 1; }
SUDO=""; [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1 && SUDO="sudo"

# 0. GPU actually present? ------------------------------------------------------
log "checking for an NVIDIA GPU…"
command -v nvidia-smi >/dev/null 2>&1 || die "nvidia-smi not found — no usable NVIDIA GPU on this box."
nvidia-smi --query-gpu=name,memory.total,memory.used --format=csv,noheader \
  || die "nvidia-smi failed — GPU driver not available."

# 1. pciutils (gotcha #4) + zstd (ollama installer needs it) BEFORE serve. ------
log "installing pciutils + zstd (GPU detection needs lspci; ollama installer needs zstd)…"
if ! command -v lspci >/dev/null 2>&1 || ! command -v zstd >/dev/null 2>&1; then
  $SUDO apt-get update -y && $SUDO apt-get install -y pciutils zstd || die "could not install pciutils/zstd"
fi
lspci | grep -iq nvidia || die "lspci sees no NVIDIA device — GPU passthrough is missing."

# 2. install ollama if missing --------------------------------------------------
if ! command -v ollama >/dev/null 2>&1; then
  log "installing ollama…"
  curl -fsSL https://ollama.com/install.sh | sh
fi

# 3. (re)start ollama serve so GPU is (re)detected AFTER pciutils is present -----
log "restarting ollama serve (GPU detection happens at serve start, not lazily)…"
pkill -f "ollama serve" 2>/dev/null || true
sleep 2
export OLLAMA_KEEP_ALIVE="$KEEP_ALIVE"
export OLLAMA_HOST="0.0.0.0:11434"     # bind all interfaces so the tunnel reaches it
nohup ollama serve >/tmp/ollama.log 2>&1 &
for _ in $(seq 1 40); do
  curl -sf http://localhost:11434/api/tags >/dev/null 2>&1 && break
  sleep 1
done
curl -sf http://localhost:11434/api/tags >/dev/null 2>&1 \
  || die "ollama serve did not come up — see /tmp/ollama.log"

# 4. pull + warm the model (quiet — ollama's progress spinner floods non-TTY logs) --
log "pulling $MODEL (progress in /tmp/pull.log; cached pulls are instant)…"
ollama pull "$MODEL" >/tmp/pull.log 2>&1
log "warming $MODEL (first load into VRAM)…"
curl -s http://localhost:11434/api/generate \
  -d "{\"model\":\"$MODEL\",\"prompt\":\"ok\",\"stream\":false,\"options\":{\"num_predict\":4}}" >/dev/null

# 5. VERIFY GPU engagement — the whole point. Fail loud on CPU fallback. ---------
log "verifying GPU engagement:"
PS="$(ollama ps)"; echo "$PS"
if echo "$PS" | grep -qi "100% GPU"; then
  log "GPU fully engaged ✓  (expect ~40 tok/s)"
elif echo "$PS" | grep -qi "GPU"; then
  log "WARNING: partial CPU/GPU split — decode will be slower; long generations may still 524. Consider a smaller MODEL or a bigger GPU."
else
  die "model is on CPU (ollama ps shows no GPU) — gotcha #4. Fix: ensure pciutils+nvidia-smi work, then rerun this script (it restarts serve)."
fi

# 6. cloudflared quick tunnel ---------------------------------------------------
if ! command -v cloudflared >/dev/null 2>&1; then
  log "installing cloudflared…"
  $SUDO curl -fsSL -o /usr/local/bin/cloudflared \
     https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
  $SUDO chmod +x /usr/local/bin/cloudflared
fi
log "opening cloudflared quick tunnel → localhost:11434…"
pkill -f "cloudflared tunnel" 2>/dev/null || true
nohup cloudflared tunnel --url http://localhost:11434 --no-autoupdate >/tmp/cloudflared.log 2>&1 &
URL=""
for _ in $(seq 1 40); do
  URL="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' /tmp/cloudflared.log | head -1 || true)"
  [ -n "$URL" ] && break
  sleep 1
done
[ -n "$URL" ] || die "cloudflared did not print a tunnel URL — see /tmp/cloudflared.log"

# 7. sanity: timed TTFB through the tunnel (healthy = TTFB < ~5s) ----------------
log "timed TTFB probe through the tunnel…"
python3 - "$URL" "$MODEL" <<'PY' || true
import json, sys, time, urllib.request
host, model = sys.argv[1], sys.argv[2]
body = json.dumps({"model": model, "prompt": "ok", "stream": True,
                   "options": {"num_predict": 8}}).encode()
req = urllib.request.Request(f"{host}/api/generate", data=body,
                             headers={"Content-Type": "application/json"})
t0 = time.time(); first = None; n = 0
with urllib.request.urlopen(req, timeout=60) as r:
    for line in r:
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        if first is None:
            first = time.time() - t0
        n += 1
        if d.get("done"):
            break
dur = time.time() - t0
print(f"  TTFB {first:.1f}s | {n} toks in {dur:.1f}s | ~{n/max(dur-(first or 0),0.1):.1f} tok/s")
print("  >>> HEALTHY if TTFB < ~5s. Tens of seconds ⇒ GPU not really engaged (gotcha #4).")
PY

cat <<EOF

==================================================================
 READY.  Tunnel URL:  $URL

 On the SR-agent (operator) side:
   export OLLAMA_HOST=$URL
   # SR_SECRET_KEY / POC_PROJECT / POC_REPORT as in TESTRUN.local.md
   python scripts/poc_queue_runner.py --model $MODEL --only H-01 \\
       --attempts 6 --lookup-budget 3 --lookup-protocol auto
==================================================================
EOF

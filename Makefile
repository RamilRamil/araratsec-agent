.PHONY: eval traces

VENV_PY := .venv/bin/python

# T084 — run the eval dataset (T080-082), gate on regression thresholds
# (T083). Non-zero exit on any failed threshold or a regressed metric vs.
# the saved baseline; pass SKIP_LANGFUSE=1 to compute metrics locally only
# (no Langfuse required) — the exit code still reflects the real result.
eval:
	$(VENV_PY) -c "\
import sys; \
from eval.runner import run_eval; \
from eval.regression import compare_to_baseline; \
push = not bool('$(SKIP_LANGFUSE)'); \
report = run_eval(push_scores=push); \
result = compare_to_baseline(report); \
print('recall=%.2f fpr=%.2f loop_completion=%.2f' % (report.recall, report.fpr, report.loop_completion_rate)); \
[print('FAIL:', f) for f in result.failures]; \
print('PASS' if result.passed else 'REGRESSION'); \
sys.exit(0 if result.passed else 1)"

# Open the Langfuse UI (defaults to the docker-compose service on :3000).
traces:
	$(VENV_PY) -c "import os, webbrowser; webbrowser.open(os.environ.get('LANGFUSE_HOST', 'http://localhost:3000'))"

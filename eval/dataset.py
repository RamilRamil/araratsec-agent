"""Eval dataset — Damn Vulnerable DeFi cases + Langfuse Datasets sync (T081).

Ground truth for each case lives in `eval/contracts/README.md` (source +
per-finding rationale); `EVAL_CASES` below only encodes the machine-checkable
part of it (bastet_tag / location / function / minimum severity) that
`eval/runner.py` matches reported findings against.

This module has a HARD dependency on the `langfuse` package (decided
explicitly, unlike `sr_agent/eval/tracer.py`'s graceful no-op): importing it
without `langfuse` installed, or calling `push_dataset()` without a running
Langfuse instance + `LANGFUSE_SECRET_KEY`/`LANGFUSE_PUBLIC_KEY` configured,
is expected to fail loudly rather than silently skip.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from langfuse import Langfuse

CONTRACTS_ROOT = Path(__file__).parent / "contracts"


@dataclass
class EvalCriterion:
    """One known, ground-truth vulnerability a case's contracts must surface."""

    bastet_tag: str
    function_name: str
    min_severity: str = "medium"
    location_contains: str = ""  # substring expected in Finding.location, e.g. a filename
    description: str = ""


@dataclass
class EvalCase:
    case_id: str
    contract_dir: str  # relative to eval/contracts/
    focus_files: list[str]  # .sol filenames (relative to contract_dir) to audit
    criteria: list[EvalCriterion] = field(default_factory=list)
    source_url: str = ""

    @property
    def path(self) -> Path:
        return CONTRACTS_ROOT / self.contract_dir


EVAL_CASES: list[EvalCase] = [
    EvalCase(
        case_id="DVD-truster",
        contract_dir="truster",
        focus_files=["TrusterLenderPool.sol", "DamnValuableToken.sol"],
        source_url="https://github.com/theredguild/damn-vulnerable-defi/tree/master/src/truster",
        criteria=[
            EvalCriterion(
                bastet_tag="arbitrary-external-call",
                function_name="flashLoan",
                min_severity="critical",
                location_contains="TrusterLenderPool.sol",
                description="flashLoan lets the caller pick target+data for an "
                "unrestricted pool-context external call (approve() theft).",
            ),
        ],
    ),
    EvalCase(
        case_id="DVD-side-entrance",
        contract_dir="side-entrance",
        focus_files=["SideEntranceLenderPool.sol"],
        source_url="https://github.com/theredguild/damn-vulnerable-defi/tree/master/src/side-entrance",
        criteria=[
            EvalCriterion(
                bastet_tag="flash-loan-attack",
                function_name="flashLoan",
                min_severity="critical",
                location_contains="SideEntranceLenderPool.sol",
                description="Flash-loan repayment check is satisfiable by "
                "depositing the borrowed funds back via deposit().",
            ),
        ],
    ),
    EvalCase(
        case_id="DVD-unstoppable",
        contract_dir="unstoppable",
        focus_files=["UnstoppableVault.sol", "UnstoppableMonitor.sol"],
        source_url="https://github.com/theredguild/damn-vulnerable-defi/tree/master/src/unstoppable",
        criteria=[
            EvalCriterion(
                bastet_tag="denial-of-service",
                function_name="flashLoan",
                min_severity="high",
                location_contains="UnstoppableVault.sol",
                description="A direct token donation breaks the "
                "shares==assets invariant, permanently reverting flashLoan.",
            ),
        ],
    ),
    EvalCase(
        case_id="DVD-naive-receiver",
        contract_dir="naive-receiver",
        focus_files=[
            "NaiveReceiverPool.sol", "FlashLoanReceiver.sol",
            "Multicall.sol", "BasicForwarder.sol",
        ],
        source_url="https://github.com/theredguild/damn-vulnerable-defi/tree/master/src/naive-receiver",
        criteria=[
            EvalCriterion(
                bastet_tag="missing-check",
                function_name="onFlashLoan",
                min_severity="medium",
                location_contains="FlashLoanReceiver.sol",
                description="initiator is never validated — anyone can force "
                "fee-costing flash loans against the receiver.",
            ),
            EvalCriterion(
                bastet_tag="missing-access-control",
                function_name="withdraw",
                min_severity="high",
                location_contains="NaiveReceiverPool.sol",
                description="Trusted-forwarder meta-tx sender is trusted "
                "without further authorization on a balance-draining function.",
            ),
        ],
    ),
    EvalCase(
        case_id="DVD-the-rewarder",
        contract_dir="the-rewarder",
        focus_files=["TheRewarderDistributor.sol"],
        source_url="https://github.com/theredguild/damn-vulnerable-defi/tree/master/src/the-rewarder",
        criteria=[
            EvalCriterion(
                bastet_tag="incorrect-state-update",
                function_name="claimRewards",
                min_severity="high",
                location_contains="TheRewarderDistributor.sol",
                description="The claimed-bitmap check runs once per grouped "
                "batch while the token payout runs once per claim entry, "
                "allowing the same reward to be paid out multiple times.",
            ),
        ],
    ),
]


def push_dataset(dataset_name: str = "sr-agent-eval") -> None:
    """Create/refresh the Langfuse dataset and its items from EVAL_CASES.

    Requires a reachable Langfuse instance and LANGFUSE_SECRET_KEY/
    LANGFUSE_PUBLIC_KEY in the environment — this is a deliberate hard
    dependency, unlike the tracer's graceful degradation.
    """
    client = Langfuse()
    client.create_dataset(name=dataset_name)
    for case in EVAL_CASES:
        client.create_dataset_item(
            dataset_name=dataset_name,
            input={"case_id": case.case_id, "contract_dir": case.contract_dir,
                   "focus_files": case.focus_files},
            expected_output={
                "criteria": [
                    {
                        "bastet_tag": c.bastet_tag,
                        "function_name": c.function_name,
                        "min_severity": c.min_severity,
                        "location_contains": c.location_contains,
                    }
                    for c in case.criteria
                ]
            },
            metadata={"source_url": case.source_url},
            id=case.case_id,
        )

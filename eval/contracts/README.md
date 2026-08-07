# Eval contracts — Damn Vulnerable DeFi (T080)

Five challenges from [Damn Vulnerable DeFi v4](https://damnvulnerabledefi.xyz)
([theredguild/damn-vulnerable-defi](https://github.com/theredguild/damn-vulnerable-defi),
`master`, MIT licensed). Sources are fetched verbatim (each file keeps its
original `// Damn Vulnerable DeFi v4` header for provenance) — this is real,
professionally-authored DeFi code with a real, publicly-documented bug, not a
synthetic fixture.

DVD challenges are CTF-style (they don't carry CVE numbers); each entry below
uses `DVD-<challenge-name>` as its case ID and cites the upstream challenge
page instead. Contracts reference external libraries (`solady`, `solmate`,
`@openzeppelin/contracts`) that are **not vendored here** — Stage 1 (regex/AST
State Interference Graph) and the LLM-based Stage 2 engines work directly on
the Solidity source text and don't need it to compile; Slither/Mythril (which
do need a successful `solc` compile) will fail to resolve these imports and
are auto-skipped by the pipeline (best-effort, non-gating) — see
`sr_agent/orchestrator/pipeline.py::_run_static_analysis`.

## DVD-truster — [Truster](https://github.com/theredguild/damn-vulnerable-defi/tree/master/src/truster)

`TrusterLenderPool.flashLoan` executes `target.functionCall(data)` with a
caller-supplied `target`/`data`, as the pool itself, with **no restriction on
what `target` can be**. An attacker's "borrower" contract calls `flashLoan`
with `amount=0`, `target=<DVT token>`, `data=encode(approve(attacker, MAX))` —
the pool approves the attacker to spend its own balance; no loan was even
outstanding, so the repayment check trivially passes. Ground truth: an
arbitrary external call made in a privileged (funds-holding) context.

- Files: `truster/TrusterLenderPool.sol`, `truster/DamnValuableToken.sol`
- Expected: `bastet_tag=arbitrary-external-call`, `severity>=critical`,
  function `flashLoan`

## DVD-side-entrance — [Side Entrance](https://github.com/theredguild/damn-vulnerable-defi/tree/master/src/side-entrance)

`SideEntranceLenderPool.flashLoan` only checks that its own ETH balance did
not decrease — it never checks *who* the balance came back from. A borrower's
callback can call the pool's own `deposit()` with the borrowed ETH, which
satisfies the balance check while crediting the caller's `balances[]` entry;
the attacker then calls `withdraw()` to walk away with funds that were never
theirs. Ground truth: a flash-loan repayment invariant that is satisfiable by
routing the borrowed funds back through an unrelated privileged function.

- Files: `side-entrance/SideEntranceLenderPool.sol`
- Expected: `bastet_tag=flash-loan-attack`, `severity>=critical`,
  function `flashLoan`

## DVD-unstoppable — [Unstoppable](https://github.com/theredguild/damn-vulnerable-defi/tree/master/src/unstoppable)

`UnstoppableVault.flashLoan` enforces `convertToShares(totalSupply) ==
totalAssets()` as an ERC4626 sanity check. Because `totalAssets()` reads the
raw token balance, anyone can break this invariant *permanently* by
transferring DVT directly to the vault (bypassing `deposit()`, which is the
only path that keeps shares and assets in sync) — after that single donation,
every future `flashLoan()` call reverts with `InvalidBalance`, and the
"unstoppable" flash-loan feature is halted. Ground truth: an externally
triggerable, irreversible denial of service via a share/asset accounting
invariant that assumes deposits are the only way assets enter the vault.

- Files: `unstoppable/UnstoppableVault.sol`, `unstoppable/UnstoppableMonitor.sol`
- Expected: `bastet_tag=denial-of-service`, `severity>=high`,
  function `flashLoan`

## DVD-naive-receiver — [Naive Receiver](https://github.com/theredguild/damn-vulnerable-defi/tree/master/src/naive-receiver)

Two independent findings:

1. `FlashLoanReceiver.onFlashLoan` ignores its `initiator` parameter (the
   first, unnamed argument) and only checks `msg.sender == pool`. Anyone —
   not just the receiver's owner — can force `NaiveReceiverPool.flashLoan`
   against the receiver, and each unsolicited loan costs it the pool's fixed
   1 WETH fee. Ten forced loans drain the receiver's entire 10 WETH balance
   with nothing borrowed for its own benefit.
2. `NaiveReceiverPool._msgSender()` implements the ERC-2771 trusted-forwarder
   pattern (the caller identity is whatever 20 bytes are appended to calldata
   when `msg.sender == trustedForwarder`) on `withdraw()`, a
   balance-draining function, without any additional check that the appended
   address actually authorized *this specific call*. Combining the
   inherited `Multicall` with the forwarder path is the documented route to
   draining the pool's `feeReceiver` balance.

- Files: `naive-receiver/NaiveReceiverPool.sol`, `FlashLoanReceiver.sol`,
  `Multicall.sol`, `BasicForwarder.sol`
- Expected:
  - `bastet_tag=missing-check`, `severity>=medium`, function `onFlashLoan` (finding 1)
  - `bastet_tag=missing-access-control`, `severity>=high`, function `withdraw` (finding 2)

## DVD-the-rewarder — [The Rewarder](https://github.com/theredguild/damn-vulnerable-defi/tree/master/src/the-rewarder)

`claimRewards` accepts an array of `Claim` entries and pays out
`inputClaim.amount` for **every entry in the loop**, but only calls
`_setClaimed` (the bitmap check-and-mark that prevents double-claiming) once
per contiguous run of same-token claims, using the **accumulated total**
rather than per-entry. Submitting several claim entries for the same
already-valid leaf/proof in one batch passes the single grouped bitmap check
while `token.transfer` still fires once per entry — the same reward is paid
out multiple times in one transaction. Ground truth: a claimed/paid
mismatch where the anti-double-claim check operates at a coarser granularity
than the payout it's supposed to guard.

- Files: `the-rewarder/TheRewarderDistributor.sol`
- Expected: `bastet_tag=incorrect-state-update`, `severity>=high`,
  function `claimRewards`

## License

All `.sol` files under this directory retain their original MIT license from
`theredguild/damn-vulnerable-defi`.

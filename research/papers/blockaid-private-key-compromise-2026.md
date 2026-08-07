# Compromised Private Keys Remain the Biggest Source of DeFi Losses

**Source**: https://blockaid.io/blog/compromised-private-keys-remain-the-biggest-source-of-defi-losses
**Publisher**: Blockaid (on-chain security company)
**Period**: April–May 2026 incidents

---

## Three-step attack pattern

All major incidents follow this pattern:

```
1. ACCESS      → steal deployer / admin / governance key
                  OR blind-sign a malicious transaction (Bybit 2025)
2. ESCALATION  → upgrade contract to malicious version
                  OR grant self admin role
                  OR reconfigure bridge/cross-chain routing
3. DRAIN       → mint tokens, transfer balances, unlock funds
```

Key insight: legitimate signatures from a compromised key are **indistinguishable** from normal operations by standard on-chain analysis. The attack is invisible until step 3.

---

## 2026 incidents

| Protocol | Date | Loss | Method |
|---|---|---|---|
| Conduit | Apr 23 | $6.59M | Compromised account executed malicious USDC proxy upgrade on Arbitrum |
| Syndicate | Apr 29 | $629K (~33% supply) | Compromised governance key redirected Arbitrum Orbit token bridge to Base |
| Wasabi Protocol | Apr 30 | $5M (4 chains) | Deployer key granted admin role → upgraded perp vaults to malicious version |
| StakeDAO | May 27 | ~43.79 ETH | Deployer reconfigured LayerZero v2 token peer → minted 5.4 trillion tokens |
| StablR | — | $12.85M | 1-of-3 multisig signer compromised → funds routed via privacy network |
| Alephium | May 30 | $815K | Fake cross-chain validation messages |

---

## Blind signing as equivalent to key theft

Bybit 2025 example: the key was never stolen. The signer was manipulated into signing a malicious transaction without understanding what it did. From the contract's perspective — identical to key theft.

> "Дренаж занимает минуты. Окно для обнаружения и ответа — только секунды."

---

## Why code audits don't stop this

A code audit verifies that the contract behaves as specified when called with legitimate inputs. A compromised admin key IS a legitimate input — the contract executes exactly as written.

What an audit CAN do: document the **blast radius** — what becomes possible if the admin key is stolen.

---

## Implications for SR-agent

### What our existing BastetTags cover

- `centralization_risk` — single admin controls critical functions ✓
- `admin_privilege` — excessive admin powers ✓
- `upgradability` — proxy upgrade patterns ✓
- `delegatecall_injection` — malicious delegatecall via upgrade ✓

### What Stage 1 should explicitly check for key-compromise scenarios

Add to Stage 1 discovery checklist:

1. **Upgrade authority** — who can upgrade? timelock? multisig threshold?
2. **Mint authority** — who can mint tokens? any cap? any guard?
3. **Bridge configuration** — who can change peer addresses / token mappings?
4. **Role assignment** — who can grant admin roles? self-grant possible?
5. **Multisig quality** — 1-of-N vs M-of-N? hardware wallets required?

This maps to the "blast radius" question: if the admin key is compromised tomorrow, what is the maximum damage an attacker can do?

### Stage 3 synthesis note

When combining findings, a chain like:
```
admin_privilege (no timelock) + upgradability (no multisig) = CRITICAL blast radius
```
should produce a combined finding even if each finding individually is Medium.

### Connection to 2606.15465 (Audit Gap)

Confirms: private key compromise = 24.4% of total DeFi losses. Our audit scope declaration in final report must explicitly note:
- We assessed the code-layer blast radius of key compromise
- We did NOT assess key management practices, signer workflows, or operational security

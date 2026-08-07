"""Live on-chain integration (T060). Auto-skips without ALCHEMY_API_KEY / web3."""
import importlib.util
import os

import pytest

_HAS_WEB3 = importlib.util.find_spec("web3") is not None
_HAS_KEY = bool(os.environ.get("ALCHEMY_API_KEY"))

pytestmark = pytest.mark.skipif(
    not (_HAS_WEB3 and _HAS_KEY),
    reason="ALCHEMY_API_KEY / web3 not available",
)


def test_alchemy_fetcher_builds_and_fetches():
    from audit_agent.tools.onchain import analyze_transactions, make_alchemy_fetcher
    fetcher = make_alchemy_fetcher(os.environ["ALCHEMY_API_KEY"])
    # WETH on mainnet; a tiny 1-block window keeps the archive read cheap.
    weth = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
    res = analyze_transactions(weth, 19_000_000, 19_000_001, fetcher)
    assert res.tx_count >= 0  # smoke: the fetch path works end-to-end

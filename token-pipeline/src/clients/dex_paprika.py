import requests
from typing import Dict, Any, List, Optional
from src.utils.rate_limiter import RateLimiter
from loguru import logger


class DexPaprikaClient:
    """
    DexPaprika API client — fallback discovery source when GeckoTerminal is unavailable.
    Free tier, no API key required.
    Docs: https://api.dexpaprika.com
    """
    BASE_URL = "https://api.dexpaprika.com"

    # DexPaprika network IDs for supported chains
    CHAIN_MAP = {
        "ethereum": "ethereum",
        "solana": "solana",
        "base": "base",
        "arbitrum": "arbitrum",
        "bsc": "bsc",
    }

    def __init__(self):
        # Be conservative — public API, no documented rate limit
        self.rate_limiter = RateLimiter(rate_limit=20, period=60)
        self.headers = {
            "Accept": "application/json",
            "User-Agent": "TokenDiscoveryPipeline/1.0",
        }

    def _get(self, path: str, params: Dict = None) -> Optional[Dict]:
        self.rate_limiter.wait()
        url = f"{self.BASE_URL}{path}"
        try:
            resp = requests.get(url, headers=self.headers, params=params, timeout=10)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error(f"DexPaprika API error {path}: {e}")
            return None

    def get_new_pools(self, chain: str, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Fetch recently added pools for a given chain.
        Returns list of raw pool dicts (normalized to pipeline schema).
        """
        network = self.CHAIN_MAP.get(chain)
        if not network:
            logger.warning(f"DexPaprika: chain {chain} not supported")
            return []

        data = self._get(
            f"/networks/{network}/pools",
            params={"sort": "added_at", "order": "desc", "limit": limit}
        )
        if not data:
            return []

        pools = data.get("pools", [])
        result = []
        for pool in pools:
            mapped = self._map_pool(chain, pool)
            if mapped:
                result.append(mapped)
        return result

    def _map_pool(self, chain: str, pool: Dict) -> Optional[Dict]:
        """Map DexPaprika pool response to pipeline token dict."""
        try:
            tokens = pool.get("tokens", [])
            if len(tokens) < 2:
                return None

            # First token is typically the "new" token
            base_tok = tokens[0]
            quote_tok = tokens[1]

            from datetime import datetime, timezone
            created_str = pool.get("added_at") or pool.get("created_at")
            if created_str:
                try:
                    created_at = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                except Exception:
                    created_at = datetime.now(timezone.utc)
            else:
                created_at = datetime.now(timezone.utc)

            return {
                "chain": chain,
                "contract_address": base_tok.get("id", pool.get("id", "")),
                "pool_address": pool.get("id", ""),
                "name": f"{base_tok.get('symbol', '?')}/{quote_tok.get('symbol', '?')}",
                "symbol": base_tok.get("symbol", "UNKNOWN"),
                "dex": pool.get("dex_name", "Unknown"),
                "base_token": quote_tok.get("symbol", "UNKNOWN"),
                "liquidity_usd": float(pool.get("liquidity", 0) or 0),
                "volume_24h": float(pool.get("volume_24h", 0) or 0),
                "txns_24h": int(pool.get("txns_24h", 0) or 0),
                "pool_created_at": created_at,
                "source": "dexpaprika",
            }
        except Exception as e:
            logger.error(f"DexPaprika map error: {e}")
            return None

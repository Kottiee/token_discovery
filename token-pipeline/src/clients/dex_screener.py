import requests
from typing import List, Dict, Any
from src.utils.rate_limiter import RateLimiter
import logging
from loguru import logger

# logger = logging.getLogger(__name__)

class DexScreenerClient:
    BASE_URL = "https://api.dexscreener.com"

    def __init__(self):
        # 60 calls/min
        self.rate_limiter = RateLimiter(rate_limit=60, period=60)

    def get_token_boosts(self) -> List[Dict[str, Any]]:
        self.rate_limiter.wait()
        url = f"{self.BASE_URL}/token-boosts/latest"
        try:
            response = requests.get(url)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"DexScreener API error: {e}")
            return []

    def get_token_profiles(self) -> List[Dict[str, Any]]:
        self.rate_limiter.wait()
        url = f"{self.BASE_URL}/token-profiles/latest"
        try:
            response = requests.get(url)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"DexScreener API error: {e}")
            return []

    def get_pairs_by_chain_and_pair(self, chainId: str, pairId: str) -> List[Dict[str, Any]]:
        self.rate_limiter.wait()
        url = f"{self.BASE_URL}/latest/dex/pairs/{chainId}/{pairId}"
        try:
            response = requests.get(url)
            response.raise_for_status()
            return response.json().get("pairs", [])
        except requests.RequestException as e:
            logger.error(f"DexScreener API error: {e}")
            return []

    def get_pairs_by_token_addresses(self, tokenAddresses: str) -> List[Dict[str, Any]]:
        # tokenAddresses: comma separated list of token addresses (up to 30)
        self.rate_limiter.wait()
        url = f"{self.BASE_URL}/latest/dex/tokens/{tokenAddresses}"
        try:
            response = requests.get(url)
            response.raise_for_status()
            return response.json().get("pairs", [])
        except requests.RequestException as e:
            logger.error(f"DexScreener API error: {e}")
            return []

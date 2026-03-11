import logging
from typing import Any, Dict, List

import requests
from loguru import logger

from src.utils.rate_limiter import RateLimiter

# logger = logging.getLogger(__name__)


class GeckoTerminalClient:
    BASE_URL = "https://api.geckoterminal.com/api/v2"

    def __init__(self):
        # 30 calls/min -> 10 calls/min for safety
        self.rate_limiter = RateLimiter(rate_limit=10, period=60)

    def get_new_pools(self, network: str, page: int = 1) -> Dict[str, Any]:
        self.rate_limiter.wait()
        url = f"{self.BASE_URL}/networks/{network}/new_pools"
        params = {"page": page}
        headers = {
            "User-Agent": "TokenDiscoveryPipeline/1.0",
            "Accept": "application/json",
        }
        try:
            response = requests.get(url, params=params, headers=headers)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"GeckoTerminal API error: {e}")
            return {}

    def get_pool_info(self, network: str, pool_address: str) -> Dict[str, Any]:
        self.rate_limiter.wait()
        url = f"{self.BASE_URL}/networks/{network}/pools/{pool_address}"
        try:
            response = requests.get(url)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"GeckoTerminal API error: {e}")
            return {}

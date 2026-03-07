import requests
from typing import List, Dict, Any
from src.utils.rate_limiter import RateLimiter
from loguru import logger
import time

class GoPlusClient:
    BASE_URL = "https://api.gopluslabs.io/api/v1"

    def __init__(self):
        # 20 calls/min (Conservative initial setting)
        self.rate_limiter = RateLimiter(rate_limit=20, period=60)
        self.chain_map = {
            "ethereum": "1",
            "bsc": "56",
            "arbitrum": "42161",
            "base": "8453",
            "solana": "solana" # GoPlus uses 'solana' for Solana, IDs for EVM
        }

    def token_security(self, chain: str, contract_addresses: List[str]) -> Dict[str, Any]:
        """
        Get token security info. 
        Supports batch request for EVM, but GoPlus API structure varies.
        Solana endpoint is different from EVM.
        """
        self.rate_limiter.wait()
        
        chain_id = self.chain_map.get(chain)
        if not chain_id:
            logger.warning(f"Chain {chain} not supported by GoPlus Client")
            return {}

        try:
            if chain == "solana":
                 return self._token_security_solana(contract_addresses)
            else:
                 return self._token_security_evm(chain_id, contract_addresses)

        except requests.RequestException as e:
            logger.error(f"GoPlus API error: {e}")
            return {}

    def _token_security_evm(self, chain_id: str, addresses: List[str]) -> Dict[str, Any]:
        # GoPlus EVM endpoint supports checking one or multiple tokens?
        # GET /token_security/{chain_id}?contract_addresses=...
        url = f"{self.BASE_URL}/token_security/{chain_id}"
        params = {"contract_addresses": ",".join(addresses)}
        
        response = requests.get(url, params=params)
        response.raise_for_status()
        result = response.json()
        
        if result.get("code") != 1:
            logger.error(f"GoPlus API returned error code: {result}")
            return {}
            
        return result.get("result", {})

    def _token_security_solana(self, addresses: List[str]) -> Dict[str, Any]:
        # GoPlus Solana endpoint: GET /solana/token_security?contract_addresses=...
        url = f"{self.BASE_URL}/solana/token_security"
        params = {"contract_addresses": ",".join(addresses)}
        
        response = requests.get(url, params=params)
        response.raise_for_status()
        result = response.json()
        
        if result.get("code") != 1:
            logger.error(f"GoPlus API returned error code: {result}")
            return {}
            
        return result.get("result", {})

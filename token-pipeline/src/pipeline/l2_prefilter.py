from typing import List, Dict, Any
from .base import PipelineLayer
from src.db.repository import TokenRepository
import yaml
import logging
from loguru import logger
from datetime import datetime, timedelta

# logger = logging.getLogger(__name__)

class L2PreFilter(PipelineLayer):
    def __init__(self, repository: TokenRepository):
        self.repository = repository
        self.config = self._load_config()

    def _load_config(self):
        with open("config/settings.yaml", "r") as f:
            return yaml.safe_load(f)

    def run(self, input_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        # Input: List of token data dictionaries (from L1)
        filtered_tokens = []
        rules = self.config["prefilter"]
        
        for token_data in input_data:
            token_id = token_data["token_id"]
            
            # 1. Liquidity Check
            if token_data["liquidity_usd"] < rules["min_liquidity_usd"]:
                self.repository.update_token_status(token_id, "dropped", "low_liquidity")
                logger.info(f"Dropped {token_id}: Low liquidity ({token_data['liquidity_usd']})")
                continue
            
            # 2. Activity Check
            if token_data["txns_24h"] < rules["min_txns_24h"]:
                self.repository.update_token_status(token_id, "dropped", "low_activity")
                logger.info(f"Dropped {token_id}: Low activity ({token_data['txns_24h']} txns)")
                continue

            # 3. Cooldown Check (Waitlist)
            if token_data["pool_age_minutes"] < rules["cooldown_minutes"]:
                # Add to waitlist
                eligible_at = datetime.utcnow() + timedelta(minutes=rules["cooldown_minutes"] - token_data["pool_age_minutes"])
                self.repository.add_to_waitlist(token_id, "cooldown", eligible_at)
                self.repository.update_token_status(token_id, "watching", "cooldown")
                logger.info(f"Waitlisted {token_id}: Cooldown ({token_data['pool_age_minutes']} min)")
                continue

            # 4. Volume Sustain (Skipped for simple MVP)
            
            # 5. Whale Concentration (Skipped for simple MVP)

            filtered_tokens.append(token_data)

        logger.info(f"L2 Pre-filter passed {len(filtered_tokens)} tokens.")
        return filtered_tokens

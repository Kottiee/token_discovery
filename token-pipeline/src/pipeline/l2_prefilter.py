import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List

import yaml
from loguru import logger

from src.db.repository import TokenRepository

from .base import PipelineLayer

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

        logger.info(f"--- L2 Pre-filter Start (Input: {len(input_data)}) ---")

        for token_data in input_data:
            token_id = token_data["token_id"]
            symbol = token_data.get("symbol", "UNKNOWN")

            # 1. Liquidity Check
            liquidity = token_data["liquidity_usd"]
            if liquidity < rules["min_liquidity_usd"]:
                reason = f"Low liquidity (${liquidity:,.2f} < ${rules['min_liquidity_usd']:,.2f})"
                self.repository.update_token_status(
                    token_id, "dropped", "low_liquidity"
                )
                logger.info(f"❌ [DROP] {symbol} ({token_id}): {reason}")
                continue

            # 2. Activity Check
            txns = token_data["txns_24h"]
            if txns < rules["min_txns_24h"]:
                reason = f"Low activity ({txns} txns < {rules['min_txns_24h']} txns)"
                self.repository.update_token_status(token_id, "dropped", "low_activity")
                logger.info(f"❌ [DROP] {symbol} ({token_id}): {reason}")
                continue

            # 3. Cooldown Check (Waitlist)
            age = token_data["pool_age_minutes"]
            if age < rules["cooldown_minutes"]:
                # Add to waitlist
                reason = f"Cooldown ({age:.1f} min < {rules['cooldown_minutes']} min)"
                eligible_at = datetime.utcnow() + timedelta(
                    minutes=rules["cooldown_minutes"] - age
                )
                self.repository.add_to_waitlist(token_id, "cooldown", eligible_at)
                self.repository.update_token_status(token_id, "watching", "cooldown")
                logger.info(f"⏳ [WAIT] {symbol} ({token_id}): {reason}")
                continue

            # 4. Volume Sustain (Skipped for simple MVP)

            # 5. Whale Concentration (Skipped for simple MVP)

            logger.info(
                f"✅ [PASS] {symbol} ({token_id}): Liq=${liquidity:,.0f}, Txns={txns}, Age={age:.0f}m"
            )
            filtered_tokens.append(token_data)

        logger.info(f"--- L2 Pre-filter End (Passed: {len(filtered_tokens)}) ---")
        return filtered_tokens

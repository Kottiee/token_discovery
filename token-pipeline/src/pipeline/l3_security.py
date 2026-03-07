import yaml
from loguru import logger
import json
from datetime import datetime, timezone
from typing import List, Dict, Any
from .base import PipelineLayer
from src.db.repository import TokenRepository
from src.clients.goplus import GoPlusClient

class L3Security(PipelineLayer):
    def __init__(self, repository: TokenRepository):
        self.repository = repository
        self.client = GoPlusClient()
        self.config = self._load_config()

    def _load_config(self):
        with open("config/settings.yaml", "r") as f:
            return yaml.safe_load(f)

    def run(self, input_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        # Input: List of token data dictionaries (from L2)
        if not input_data:
            return []

        scanned_tokens = []
        rules = self.config["security"]
        
        logger.info(f"--- L3 Security Scan Start (Input: {len(input_data)}) ---")
        
        # Group by chain to batch requests
        tokens_by_chain = {}
        for t in input_data:
            chain = t["chain"]
            if chain not in tokens_by_chain:
                tokens_by_chain[chain] = []
            tokens_by_chain[chain].append(t)
        
        for chain, tokens in tokens_by_chain.items():
            logger.info(f"Running Security Scan for {len(tokens)} tokens on {chain}...")
            
            # Batch process (GoPlus might have limits on batch size, e.g. 30?)
            batch_size = 10
            for i in range(0, len(tokens), batch_size):
                batch = tokens[i:i+batch_size]
                addresses = [t["contract_address"] for t in batch]
                
                try:
                    # Note: GoPlus Client implementation for batch is assumed to return dict {address: info}
                    # Need to check GoPlusClient implementation if it handles batch correctly.
                    # The current dummy implementation in goplus.py supports list of addresses.
                    
                    # However, GoPlus API returns might use different keys (lower case address etc.)
                    # We need to be careful with matching.
                    
                    security_results = self.client.token_security(chain, addresses)
                    
                    # If GoPlus returns list (some endpoints do), convert to dict
                    # But for now assuming dict based on goplus.py impl intent.
                    
                    # Normalize security_results keys to lowercase
                    normalized_results = {}
                    if isinstance(security_results, dict):
                        normalized_results = {k.lower(): v for k, v in security_results.items()}
                    
                    for token_data in batch:
                        address = token_data["contract_address"]
                        symbol = token_data.get("symbol", "UNKNOWN")
                        sec_info = normalized_results.get(address.lower())

                        if not sec_info:
                            logger.warning(f"No security info found for {address}")
                            # Fallback: maybe skip or mark as warning? For now, pass with 0 score or skip?
                            # Let's skip to be safe, or retry later.
                            continue

                        score, flags = self._calculate_score(sec_info)
                        
                        token_id = token_data["token_id"]
                        
                        # Save result
                        self.repository.add_scan_result({
                            "token_id": token_id,
                            "layer": "L3",
                            "score": score,
                            "details": sec_info, # SQLAlchemy handles JSON
                            "flags": flags,
                            "scanned_at": datetime.now(timezone.utc)
                        })
                        
                        if score < rules["drop_threshold"]:
                             self.repository.update_token_status(token_id, "dropped", "security_fail")
                             logger.info(f"❌ [DROP] {symbol} ({token_id}): Score {score:.0f} < {rules['drop_threshold']} | Flags: {flags}")
                        else:
                             token_data["security_score"] = score
                             token_data["security_flags"] = flags
                             scanned_tokens.append(token_data)
                             logger.info(f"✅ [PASS] {symbol} ({token_id}): Score {score:.0f} | Flags: {flags}")

                except Exception as e:
                    logger.error(f"Error scanning batch on {chain}: {e}")
                    # Continue to next batch
        
        logger.info(f"--- L3 Security Scan End (Passed: {len(scanned_tokens)}) ---")
        return scanned_tokens

    def _calculate_score(self, sec_info: Dict[str, Any]) -> tuple[float, List[str]]:
        """
        Calculate security score based on GoPlus response.
        Start with 100, deduct points based on risks.
        """
        score = 100.0
        flags = []
        
        # Mapping from GoPlus field to deduction
        # Using the rules from system_design.md
        
        # Critical Risks (Immediate Drop effectively)
        if str(sec_info.get("is_honeypot", "0")) == "1":
            score -= 100
            flags.append("is_honeypot")
            
        # High Risks
        if str(sec_info.get("cannot_sell_all", "0")) == "1":
            score -= 80
            flags.append("cannot_sell_all")

        # Medium Risks
        if str(sec_info.get("can_take_back_ownership", "0")) == "1":
            score -= 40
            flags.append("can_take_back_ownership")
            
        if str(sec_info.get("owner_change_balance", "0")) == "1":
            score -= 40
            flags.append("owner_change_balance")

        # Other Risks
        if str(sec_info.get("is_blacklisted", "0")) == "1":
            score -= 30
            flags.append("is_blacklisted")
            
        if str(sec_info.get("is_proxy", "0")) == "1":
            score -= 20
            flags.append("is_proxy")
            
        if str(sec_info.get("is_mintable", "0")) == "1":
            score -= 15
            flags.append("is_mintable")
            
        if str(sec_info.get("hidden_owner", "0")) == "1":
            score -= 15
            flags.append("hidden_owner")
            
        if str(sec_info.get("external_call", "0")) == "1":
            score -= 10
            flags.append("external_call")

        # Positive Indicators (Penalty if missing)
        if str(sec_info.get("is_open_source", "1")) == "0":
            score -= 20
            flags.append("not_open_source")

        # Warnings (No score deduction in design, but flag)
        # Note: GoPlus fields vary. 'lp_holders_locked' logic might need adjustment based on real response.
        # Assuming we check LP lock separately or if GoPlus provides it.
        # For now, just follow basic deductions.

        return max(0.0, score), flags

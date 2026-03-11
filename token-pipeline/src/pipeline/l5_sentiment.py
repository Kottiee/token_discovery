from typing import List, Dict, Any
from datetime import datetime, timezone

import yaml
from loguru import logger

from .base import PipelineLayer
from src.clients.claude_agent import ClaudeAgent
from src.db.repository import TokenRepository


class L5Sentiment(PipelineLayer):
    """
    Layer 5: Sentiment & Narrative Scoring
    - Claude AI classifies narrative category (AI, RWA, DePIN, Meme, etc.)
    - Matches against hot_narratives config to compute narrative_score
    - Community score: Discord/Telegram presence + estimated engagement
    - Final: narrative_score and community_score are added to token_data
    """

    def __init__(self, repository: TokenRepository):
        self.repository = repository
        self.claude = ClaudeAgent()
        self.config = self._load_config()

    def _load_config(self) -> Dict:
        with open("config/settings.yaml", "r") as f:
            return yaml.safe_load(f)

    def run(self, input_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not input_data:
            return []

        results = []
        hot_narratives: List[Dict] = self.config.get("sentiment", {}).get(
            "hot_narratives",
            [
                {"name": "AI", "weight": 1.0},
                {"name": "RWA", "weight": 0.9},
                {"name": "DePIN", "weight": 0.85},
                {"name": "Meme", "weight": 0.7},
                {"name": "GameFi", "weight": 0.6},
            ],
        )

        logger.info(f"--- L5 Sentiment Start (Input: {len(input_data)}) ---")

        for token_data in input_data:
            token_id = token_data["token_id"]
            symbol = token_data.get("symbol", "UNKNOWN")
            name = token_data.get("name", symbol)

            try:
                # AI narrative classification
                ai_result = self.claude.analyze_narrative(
                    token_name=name,
                    token_symbol=symbol,
                    description=token_data.get("ai_summary") or token_data.get("description"),
                )
                narrative_category = ai_result.get("narrative_category", "Other")
                narrative_alignment = ai_result.get("narrative_alignment", 30)
                novelty_score = ai_result.get("novelty_score", 30)
                community_health_est = ai_result.get("community_health", 30)

                # Narrative score: blend AI alignment with hot-narrative weight boost
                hot_weight = self._get_narrative_weight(narrative_category, hot_narratives)
                # narrative_score = alignment * hot_weight, capped at 100
                narrative_score = round(min(100, narrative_alignment * hot_weight), 2)

                # Community score: check for social links + estimated health
                community_score = self._calculate_community_score(
                    token_data, community_health_est
                )

                flags = []
                if narrative_category == "Other":
                    flags.append("unclear_narrative")
                if community_health_est < 30:
                    flags.append("weak_community")

                details = {
                    "narrative_category": narrative_category,
                    "narrative_alignment": narrative_alignment,
                    "narrative_score": narrative_score,
                    "hot_weight": hot_weight,
                    "novelty_score": novelty_score,
                    "community_score": community_score,
                    "competitive_summary": ai_result.get("competitive_summary", ""),
                }

                self.repository.add_scan_result({
                    "token_id": token_id,
                    "layer": "L5",
                    "score": narrative_score,
                    "details": details,
                    "flags": flags,
                    "scanned_at": datetime.now(timezone.utc),
                })

                token_data["narrative_score"] = narrative_score
                token_data["community_score"] = community_score
                token_data["narrative_category"] = narrative_category
                token_data["sentiment_flags"] = flags
                results.append(token_data)

                logger.info(
                    f"✅ [L5] {symbol}: narrative={narrative_score:.0f} "
                    f"({narrative_category}), community={community_score:.0f} | Flags: {flags}"
                )

            except Exception as e:
                logger.error(f"L5 error for {symbol} ({token_id}): {e}")
                token_data["narrative_score"] = 0.0
                token_data["community_score"] = 0.0
                token_data["narrative_category"] = "Other"
                token_data["sentiment_flags"] = ["analysis_error"]
                results.append(token_data)

        logger.info(f"--- L5 Sentiment End (Processed: {len(results)}) ---")
        return results

    def _get_narrative_weight(self, category: str, hot_narratives: List[Dict]) -> float:
        """Return the hot-narrative multiplier for a given category name."""
        cat_lower = category.lower()
        for hn in hot_narratives:
            if hn["name"].lower() in cat_lower or cat_lower in hn["name"].lower():
                return hn["weight"]
        return 0.5  # Default weight for uncategorized narratives

    def _calculate_community_score(self, token_data: Dict, ai_health: float) -> float:
        """
        Community score (0–100):
          has_discord     0 or 20
          has_telegram    0 or 20
          ai_health_est   0–60 (scaled from AI estimate)
        """
        score = 0.0

        # Social presence checks from token_data (if enriched by L1/L4)
        if token_data.get("discord_url"):
            score += 20
        if token_data.get("telegram_url"):
            score += 20

        # AI health estimate fills remainder (0–60)
        score += min(60, ai_health * 0.6)

        return round(min(100, score), 2)

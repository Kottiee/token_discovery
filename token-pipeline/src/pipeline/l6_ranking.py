from datetime import date, datetime, timezone
from typing import Any, Dict, List

import yaml
from loguru import logger

from src.clients.claude_agent import ClaudeAgent
from src.db.models import DailyRanking
from src.db.repository import TokenRepository

from .base import PipelineLayer

RANK_MEDALS = ["🥇", "🥈", "🥉"] + ["🏅"] * 7


class L6Ranking(PipelineLayer):
    """
    Layer 6: Ranking & Output
    - Compute total_score from weighted layer scores
    - Select top N candidates
    - Generate AI summary for each
    - Persist to daily_rankings table
    - Dispatch to notifiers (Discord, Notion)
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
            logger.info("--- L6 Ranking: No candidates ---")
            return []

        ranking_cfg = self.config["ranking"]
        weights = ranking_cfg["weights"]
        top_n = ranking_cfg.get("top_n", 10)

        logger.info(f"--- L6 Ranking Start (Input: {len(input_data)}) ---")

        # 1. Score each token
        scored = []
        for token_data in input_data:
            total_score, breakdown = self._compute_total_score(token_data, weights)
            scored.append((total_score, breakdown, token_data))

        # 2. Sort descending and take top N
        scored.sort(key=lambda x: x[0], reverse=True)
        top_tokens = scored[:top_n]

        # 3. Persist & build report
        today = date.today()
        report_rows = []

        for rank_idx, (total_score, breakdown, token_data) in enumerate(
            top_tokens, start=1
        ):
            token_id = token_data["token_id"]
            symbol = token_data.get("symbol", "?")
            name = token_data.get("name", symbol)
            chain = token_data.get("chain", "?")

            all_flags = (
                token_data.get("security_flags", [])
                + token_data.get("fundamentals_flags", [])
                + token_data.get("sentiment_flags", [])
            )

            # Generate summary via Claude
            summary = self.claude.generate_token_summary(
                token_name=name,
                token_symbol=symbol,
                chain=chain,
                total_score=total_score,
                score_breakdown=breakdown,
                flags=all_flags,
            )

            # Persist ranking
            self.repository.upsert_daily_ranking(
                {
                    "date": today,
                    "rank": rank_idx,
                    "token_id": token_id,
                    "total_score": total_score,
                    "score_breakdown": breakdown,
                    "summary": summary,
                    "risk_flags": all_flags,
                }
            )

            report_rows.append(
                {
                    "rank": rank_idx,
                    "symbol": symbol,
                    "name": name,
                    "chain": chain,
                    "total_score": total_score,
                    "breakdown": breakdown,
                    "summary": summary,
                    "flags": all_flags,
                    "contract_address": token_data.get("contract_address", ""),
                    "pool_address": token_data.get("pool_address", ""),
                }
            )

            logger.info(
                f"{RANK_MEDALS[rank_idx-1]} #{rank_idx} {symbol} ({chain}): "
                f"Score={total_score:.1f} | {summary[:60]}"
            )

        # 4. Send notifications
        self._notify(today, report_rows)

        logger.info(f"--- L6 Ranking End (Top {len(report_rows)}) ---")
        return [row for row in report_rows]

    def _compute_total_score(
        self, token_data: Dict, weights: Dict
    ) -> tuple[float, Dict]:
        security = float(token_data.get("security_score", 0))
        fundamentals = float(token_data.get("fundamentals_score", 0))
        narrative = float(token_data.get("narrative_score", 0))
        community = float(token_data.get("community_score", 0))

        # Momentum: approximate from liquidity + volume growth
        momentum = self._compute_momentum_score(token_data)

        total = (
            security * weights.get("security", 0.30)
            + fundamentals * weights.get("fundamentals", 0.20)
            + narrative * weights.get("narrative", 0.25)
            + momentum * weights.get("momentum", 0.15)
            + community * weights.get("community", 0.10)
        )

        breakdown = {
            "security": round(security, 1),
            "fundamentals": round(fundamentals, 1),
            "narrative": round(narrative, 1),
            "momentum": round(momentum, 1),
            "community": round(community, 1),
        }
        return round(total, 2), breakdown

    def _compute_momentum_score(self, token_data: Dict) -> float:
        """
        Approximate momentum from available metrics.
        Higher volume/liquidity ratio and txn count → higher momentum.
        """
        liquidity = float(token_data.get("liquidity_usd", 0) or 0)
        volume = float(token_data.get("volume_24h", 0) or 0)
        txns = int(token_data.get("txns_24h", 0) or 0)

        if liquidity <= 0:
            return 20.0  # neutral

        # Volume / Liquidity ratio: >1 is very active
        vol_ratio = min(1.0, volume / max(liquidity, 1))
        vol_score = vol_ratio * 50  # up to 50 points

        # Transaction count: normalize (100 txns → 50 points)
        txn_score = min(50, txns / 2)

        return round(min(100, (vol_score + txn_score) / 2 * 2), 2)

    def _notify(self, report_date: date, rows: List[Dict]) -> None:
        """Send notifications to configured channels."""
        notif_cfg = self.config.get("notifications", {})

        discord_url = notif_cfg.get("discord_webhook_url", "")
        notion_key = notif_cfg.get("notion_api_key", "")
        notion_db = notif_cfg.get("notion_database_id", "")

        if discord_url:
            try:
                from src.notifiers.discord import DiscordNotifier

                notifier = DiscordNotifier(discord_url)
                notifier.send_daily_report(report_date, rows)
            except Exception as e:
                logger.error(f"Discord notification failed: {e}")

        if notion_key and notion_db:
            try:
                from src.notifiers.notion import NotionNotifier

                notifier = NotionNotifier(notion_key, notion_db)
                notifier.send_daily_report(report_date, rows)
            except Exception as e:
                logger.error(f"Notion notification failed: {e}")

        if not discord_url and not (notion_key and notion_db):
            logger.warning(
                "No notification channels configured. "
                "Set DISCORD_WEBHOOK_URL or NOTION_API_KEY + NOTION_DATABASE_ID."
            )

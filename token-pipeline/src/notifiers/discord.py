from datetime import date
from typing import Any, Dict, List

import requests
from loguru import logger

RANK_MEDALS = ["🥇", "🥈", "🥉"] + ["🏅"] * 7
CHAIN_ICONS = {
    "solana": "◎",
    "ethereum": "Ξ",
    "base": "🔵",
    "arbitrum": "🔷",
    "bsc": "🟡",
}
DEXSCREENER_BASE = "https://dexscreener.com"


class DiscordNotifier:
    """
    Sends daily token ranking reports to a Discord channel via Webhook.
    Uses Discord Embed format for rich formatting.
    """

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send_daily_report(self, report_date: date, rows: List[Dict[str, Any]]) -> bool:
        """
        Post a daily report embed to Discord.
        Splits into multiple messages if > 10 tokens (Discord embed field limit).
        """
        if not rows:
            return False

        date_str = report_date.strftime("%Y-%m-%d")
        embeds = [self._build_header_embed(date_str, len(rows))]

        for row in rows:
            embeds.append(self._build_token_embed(row))

        # Discord allows max 10 embeds per message
        for chunk_start in range(0, len(embeds), 10):
            chunk = embeds[chunk_start : chunk_start + 10]
            ok = self._post({"embeds": chunk})
            if not ok:
                return False

        logger.info(f"Discord: daily report for {date_str} sent ({len(rows)} tokens)")
        return True

    def send_alert(self, message: str) -> bool:
        """Send a plain-text alert message."""
        return self._post({"content": message})

    def _build_header_embed(self, date_str: str, count: int) -> Dict:
        return {
            "title": f"📊 Daily Token Report — {date_str}",
            "description": f"Top {count} candidates identified by the pipeline.",
            "color": 0x5865F2,  # Discord blurple
        }

    def _build_token_embed(self, row: Dict) -> Dict:
        rank = row["rank"]
        symbol = row["symbol"]
        chain = row["chain"]
        total_score = row["total_score"]
        breakdown = row.get("breakdown", {})
        summary = row.get("summary", "")
        flags = row.get("flags", [])
        chain_icon = CHAIN_ICONS.get(chain, "🔗")
        medal = RANK_MEDALS[rank - 1] if rank <= len(RANK_MEDALS) else "🏅"

        # DexScreener link
        pool_addr = row.get("pool_address", "")
        dex_url = f"{DEXSCREENER_BASE}/{chain}/{pool_addr}" if pool_addr else ""

        # Build score breakdown field
        bd_lines = [
            f"Security: {breakdown.get('security', 0):.0f}",
            f"Fundamentals: {breakdown.get('fundamentals', 0):.0f}",
            f"Narrative: {breakdown.get('narrative', 0):.0f}",
            f"Momentum: {breakdown.get('momentum', 0):.0f}",
            f"Community: {breakdown.get('community', 0):.0f}",
        ]

        fields = [
            {"name": "Score", "value": f"**{total_score:.1f}** / 100", "inline": True},
            {"name": "Chain", "value": f"{chain_icon} {chain}", "inline": True},
            {"name": "Breakdown", "value": "\n".join(bd_lines), "inline": False},
        ]

        if summary:
            fields.append({"name": "Summary", "value": summary, "inline": False})

        if flags:
            flag_text = " | ".join([f"⚠️ `{f}`" for f in flags[:5]])
            fields.append({"name": "Risk Flags", "value": flag_text, "inline": False})

        if dex_url:
            fields.append(
                {"name": "Chart", "value": f"[DEXScreener]({dex_url})", "inline": True}
            )

        # Color: green if score ≥ 70, yellow if ≥ 50, red otherwise
        color = (
            0x57F287
            if total_score >= 70
            else (0xFEE75C if total_score >= 50 else 0xED4245)
        )

        return {
            "title": f"{medal} #{rank}. ${symbol}",
            "color": color,
            "fields": fields,
        }

    def _post(self, payload: Dict) -> bool:
        try:
            resp = requests.post(
                self.webhook_url,
                json=payload,
                timeout=10,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            return True
        except requests.RequestException as e:
            logger.error(f"Discord webhook error: {e}")
            return False

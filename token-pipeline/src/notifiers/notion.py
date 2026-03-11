from datetime import date
from typing import Any, Dict, List

import requests
from loguru import logger


class NotionNotifier:
    """
    Appends daily token rankings to a Notion database.
    Each token becomes one database row (page).

    Required Notion DB properties:
      - Name (title)
      - Date (date)
      - Rank (number)
      - Chain (select)
      - TotalScore (number)
      - Security (number)
      - Fundamentals (number)
      - Narrative (number)
      - Momentum (number)
      - Community (number)
      - Summary (rich_text)
      - Flags (rich_text)
      - DexScreener (url)
    """

    API_VERSION = "2022-06-28"
    BASE_URL = "https://api.notion.com/v1"

    def __init__(self, api_key: str, database_id: str):
        self.database_id = database_id
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Notion-Version": self.API_VERSION,
        }

    def send_daily_report(self, report_date: date, rows: List[Dict[str, Any]]) -> bool:
        """Create one Notion page per token ranking row."""
        success_count = 0
        for row in rows:
            ok = self._create_page(report_date, row)
            if ok:
                success_count += 1

        logger.info(
            f"Notion: inserted {success_count}/{len(rows)} rows for {report_date}"
        )
        return success_count > 0

    def _create_page(self, report_date: date, row: Dict) -> bool:
        breakdown = row.get("breakdown", {})
        flags = row.get("flags", [])
        pool_addr = row.get("pool_address", "")
        chain = row.get("chain", "")
        dex_url = f"https://dexscreener.com/{chain}/{pool_addr}" if pool_addr else ""

        properties: Dict[str, Any] = {
            "Name": {
                "title": [{"text": {"content": f"${row['symbol']} #{row['rank']}"}}]
            },
            "Date": {"date": {"start": str(report_date)}},
            "Rank": {"number": row["rank"]},
            "Chain": {"select": {"name": row.get("chain", "unknown")}},
            "TotalScore": {"number": row["total_score"]},
            "Security": {"number": breakdown.get("security", 0)},
            "Fundamentals": {"number": breakdown.get("fundamentals", 0)},
            "Narrative": {"number": breakdown.get("narrative", 0)},
            "Momentum": {"number": breakdown.get("momentum", 0)},
            "Community": {"number": breakdown.get("community", 0)},
            "Summary": {
                "rich_text": [{"text": {"content": row.get("summary", "")[:2000]}}]
            },
            "Flags": {
                "rich_text": [
                    {"text": {"content": ", ".join(flags[:20]) if flags else "none"}}
                ]
            },
        }

        if dex_url:
            properties["DexScreener"] = {"url": dex_url}

        payload = {
            "parent": {"database_id": self.database_id},
            "properties": properties,
        }

        try:
            resp = requests.post(
                f"{self.BASE_URL}/pages",
                json=payload,
                headers=self.headers,
                timeout=15,
            )
            if resp.status_code in (400, 401, 403):
                logger.error(f"Notion API error {resp.status_code}: {resp.text[:300]}")
                return False
            resp.raise_for_status()
            return True
        except requests.RequestException as e:
            logger.error(f"Notion request error: {e}")
            return False

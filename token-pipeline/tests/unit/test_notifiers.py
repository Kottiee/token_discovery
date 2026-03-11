"""Unit tests for Discord and Notion notifiers."""
import pytest
from unittest.mock import MagicMock, patch
from datetime import date


def _sample_rows():
    return [
        {
            "rank": 1,
            "symbol": "TEST",
            "name": "Test Token",
            "chain": "ethereum",
            "total_score": 82.5,
            "breakdown": {
                "security": 90,
                "fundamentals": 75,
                "narrative": 80,
                "momentum": 60,
                "community": 55,
            },
            "summary": "Solid DeFi project with active GitHub.",
            "flags": ["is_mintable"],
            "contract_address": "0xABC",
            "pool_address": "0xPOOL",
        }
    ]


class TestDiscordNotifier:
    @patch("requests.post")
    def test_sends_embeds(self, mock_post):
        mock_post.return_value = MagicMock(status_code=204)
        mock_post.return_value.raise_for_status = MagicMock()

        from src.notifiers.discord import DiscordNotifier
        notifier = DiscordNotifier("https://discord.com/api/webhooks/test")
        ok = notifier.send_daily_report(date.today(), _sample_rows())

        assert ok is True
        assert mock_post.call_count >= 1
        payload = mock_post.call_args_list[0][1]["json"]
        assert "embeds" in payload

    @patch("requests.post")
    def test_returns_false_on_error(self, mock_post):
        import requests
        mock_post.side_effect = requests.RequestException("connection error")

        from src.notifiers.discord import DiscordNotifier
        notifier = DiscordNotifier("https://discord.com/api/webhooks/test")
        ok = notifier.send_daily_report(date.today(), _sample_rows())
        assert ok is False

    def test_empty_rows(self):
        from src.notifiers.discord import DiscordNotifier
        notifier = DiscordNotifier("https://discord.com/api/webhooks/test")
        ok = notifier.send_daily_report(date.today(), [])
        assert ok is False


class TestNotionNotifier:
    @patch("requests.post")
    def test_creates_page(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        mock_post.return_value.raise_for_status = MagicMock()

        from src.notifiers.notion import NotionNotifier
        notifier = NotionNotifier("secret_key", "database_id_123")
        ok = notifier.send_daily_report(date.today(), _sample_rows())

        assert ok is True
        mock_post.assert_called_once()
        payload = mock_post.call_args[1]["json"]
        assert payload["parent"]["database_id"] == "database_id_123"
        props = payload["properties"]
        assert "Name" in props
        assert "TotalScore" in props

    @patch("requests.post")
    def test_handles_403(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=403, text="Unauthorized"
        )
        mock_post.return_value.raise_for_status = MagicMock()

        from src.notifiers.notion import NotionNotifier
        notifier = NotionNotifier("bad_key", "db_id")
        ok = notifier.send_daily_report(date.today(), _sample_rows())
        assert ok is False

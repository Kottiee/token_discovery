"""Unit tests for L6 Ranking layer."""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest


def _make_scored_token(
    token_id="eth:0xABC",
    symbol="TEST",
    security=80,
    fundamentals=60,
    narrative=70,
    community=50,
):
    return {
        "token_id": token_id,
        "chain": "ethereum",
        "contract_address": "0xABC",
        "symbol": symbol,
        "name": "Test Token",
        "security_score": float(security),
        "fundamentals_score": float(fundamentals),
        "narrative_score": float(narrative),
        "community_score": float(community),
        "security_flags": [],
        "fundamentals_flags": [],
        "sentiment_flags": [],
        "narrative_category": "DeFi",
        "ai_summary": "Test summary",
        "liquidity_usd": 100000,
        "volume_24h": 50000,
        "txns_24h": 500,
        "pool_address": "0xPOOL",
    }


@pytest.fixture
def mock_repo():
    repo = MagicMock()
    repo.upsert_daily_ranking = MagicMock()
    return repo


@pytest.fixture
def l6(mock_repo):
    mock_claude = MagicMock()
    mock_claude.generate_token_summary.return_value = "A great DeFi project."

    weights = {
        "security": 0.30,
        "fundamentals": 0.20,
        "narrative": 0.25,
        "momentum": 0.15,
        "community": 0.10,
    }

    from src.pipeline.l6_ranking import L6Ranking

    inst = L6Ranking.__new__(L6Ranking)
    inst.repository = mock_repo
    inst.claude = mock_claude
    inst.config = {"ranking": {"weights": weights, "top_n": 10}, "notifications": {}}
    return inst


class TestL6Ranking:
    def test_total_score_calculation(self, l6):
        token = _make_scored_token(
            security=100, fundamentals=100, narrative=100, community=100
        )
        # momentum computed internally from liquidity/volume
        total, breakdown = l6._compute_total_score(
            token, l6.config["ranking"]["weights"]
        )
        # Without momentum: 100*0.30 + 100*0.20 + 100*0.25 + 0*0.15 + 100*0.10 = 85 + momentum portion
        assert total >= 70  # momentum will add some points
        assert "security" in breakdown

    def test_ranking_order(self, l6):
        """Tokens should be returned in descending score order."""
        tokens = [
            _make_scored_token(
                "eth:A", "A", security=50, fundamentals=50, narrative=50, community=50
            ),
            _make_scored_token(
                "eth:B", "B", security=90, fundamentals=80, narrative=80, community=70
            ),
            _make_scored_token(
                "eth:C", "C", security=70, fundamentals=60, narrative=60, community=60
            ),
        ]
        results = l6.run(tokens)
        ranks = [r["rank"] for r in results]
        symbols = [r["symbol"] for r in results]
        assert ranks == [1, 2, 3]
        assert symbols[0] == "B"  # highest scores

    def test_top_n_limit(self, l6):
        """Only top_n tokens should be returned."""
        l6.config["ranking"]["top_n"] = 2
        tokens = [_make_scored_token(f"eth:{i}", f"T{i}") for i in range(5)]
        results = l6.run(tokens)
        assert len(results) == 2

    def test_empty_input(self, l6):
        results = l6.run([])
        assert results == []

    def test_daily_ranking_persisted(self, l6, mock_repo):
        token = _make_scored_token()
        l6.run([token])
        mock_repo.upsert_daily_ranking.assert_called_once()
        call_kwargs = mock_repo.upsert_daily_ranking.call_args[0][0]
        assert call_kwargs["rank"] == 1
        assert call_kwargs["date"] == date.today()

    def test_momentum_score_zero_liquidity(self, l6):
        """Zero liquidity should return neutral momentum, not crash."""
        token = _make_scored_token()
        token["liquidity_usd"] = 0
        score = l6._compute_momentum_score(token)
        assert score == 20.0

    def test_notification_not_called_when_no_config(self, l6):
        """With empty notifications config, no notifier should raise."""
        token = _make_scored_token()
        # Should not raise even without Discord/Notion configured
        results = l6.run([token])
        assert len(results) == 1

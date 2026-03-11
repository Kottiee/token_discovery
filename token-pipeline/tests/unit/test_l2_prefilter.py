"""Unit tests for L2 Pre-filter layer."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


def _make_token(
    token_id="ethereum:0xABC",
    symbol="TEST",
    liquidity=10000,
    txns=50,
    age_minutes=120,
):
    return {
        "token_id": token_id,
        "symbol": symbol,
        "chain": "ethereum",
        "contract_address": "0xABC",
        "liquidity_usd": liquidity,
        "txns_24h": txns,
        "volume_24h": liquidity * 0.5,
        "pool_age_minutes": age_minutes,
    }


@pytest.fixture
def mock_repo():
    repo = MagicMock()
    repo.update_token_status = MagicMock()
    repo.add_to_waitlist = MagicMock()
    return repo


@pytest.fixture
def l2(mock_repo):
    with patch(
        "builtins.open",
        MagicMock(
            return_value=MagicMock(
                __enter__=lambda s: s,
                __exit__=MagicMock(return_value=False),
                read=MagicMock(return_value=""),
            )
        ),
    ):
        with patch(
            "yaml.safe_load",
            return_value={
                "prefilter": {
                    "min_liquidity_usd": 5000,
                    "min_txns_24h": 10,
                    "cooldown_minutes": 60,
                }
            },
        ):
            from src.pipeline.l2_prefilter import L2PreFilter

            return L2PreFilter(mock_repo)


class TestL2PreFilter:
    def test_passes_valid_token(self, l2, mock_repo):
        tokens = [_make_token()]
        result = l2.run(tokens)
        assert len(result) == 1
        mock_repo.update_token_status.assert_not_called()

    def test_drops_low_liquidity(self, l2, mock_repo):
        tokens = [_make_token(liquidity=100)]
        result = l2.run(tokens)
        assert len(result) == 0
        mock_repo.update_token_status.assert_called_once_with(
            "ethereum:0xABC", "dropped", "low_liquidity"
        )

    def test_drops_low_activity(self, l2, mock_repo):
        tokens = [_make_token(txns=2)]
        result = l2.run(tokens)
        assert len(result) == 0
        mock_repo.update_token_status.assert_called_once_with(
            "ethereum:0xABC", "dropped", "low_activity"
        )

    def test_sends_to_waitlist_if_too_new(self, l2, mock_repo):
        tokens = [_make_token(age_minutes=10)]
        result = l2.run(tokens)
        assert len(result) == 0
        mock_repo.add_to_waitlist.assert_called_once()
        mock_repo.update_token_status.assert_called_once_with(
            "ethereum:0xABC", "watching", "cooldown"
        )

    def test_empty_input(self, l2):
        result = l2.run([])
        assert result == []

    def test_multiple_tokens_mixed(self, l2, mock_repo):
        tokens = [
            _make_token(
                token_id="eth:A", symbol="A", liquidity=10000, txns=50, age_minutes=120
            ),
            _make_token(token_id="eth:B", symbol="B", liquidity=100),  # dropped
            _make_token(token_id="eth:C", symbol="C", txns=5),  # dropped
        ]
        result = l2.run(tokens)
        assert len(result) == 1
        assert result[0]["symbol"] == "A"

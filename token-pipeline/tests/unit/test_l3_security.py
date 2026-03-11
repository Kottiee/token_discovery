"""Unit tests for L3 Security layer scoring logic."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def l3(mock_repo):
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
        with patch("yaml.safe_load", return_value={"security": {"drop_threshold": 40}}):
            from src.pipeline.l3_security import L3Security

            inst = L3Security.__new__(L3Security)
            inst.repository = mock_repo
            inst.config = {"security": {"drop_threshold": 40}}
            return inst


@pytest.fixture
def mock_repo():
    repo = MagicMock()
    repo.update_token_status = MagicMock()
    repo.add_scan_result = MagicMock()
    return repo


class TestL3SecurityScoring:
    def _score(self, sec_info):
        from src.pipeline.l3_security import L3Security

        inst = L3Security.__new__(L3Security)
        return inst._calculate_score(sec_info)

    def test_clean_token_scores_100(self):
        score, flags = self._score({})
        assert score == 100.0
        assert flags == []

    def test_honeypot_scores_zero(self):
        score, flags = self._score({"is_honeypot": "1"})
        assert score == 0.0
        assert "is_honeypot" in flags

    def test_cannot_sell_all_deduction(self):
        score, flags = self._score({"cannot_sell_all": "1"})
        assert score == 20.0
        assert "cannot_sell_all" in flags

    def test_not_open_source_deduction(self):
        score, flags = self._score({"is_open_source": "0"})
        assert score == 80.0
        assert "not_open_source" in flags

    def test_multiple_flags_cumulative(self):
        sec_info = {
            "is_mintable": "1",  # -15
            "hidden_owner": "1",  # -15
            "is_proxy": "1",  # -20
        }
        score, flags = self._score(sec_info)
        assert score == 50.0
        assert len(flags) == 3

    def test_score_never_below_zero(self):
        sec_info = {
            "is_honeypot": "1",
            "cannot_sell_all": "1",
            "can_take_back_ownership": "1",
            "owner_change_balance": "1",
        }
        score, flags = self._score(sec_info)
        assert score == 0.0

    def test_string_zero_not_flagged(self):
        """GoPlus returns "0" for false — ensure no false positives."""
        sec_info = {
            "is_honeypot": "0",
            "cannot_sell_all": "0",
            "is_mintable": "0",
        }
        score, flags = self._score(sec_info)
        assert score == 100.0
        assert flags == []

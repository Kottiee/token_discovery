"""Unit tests for L4 Fundamentals layer."""

from unittest.mock import MagicMock, patch

import pytest


def _make_token(token_id="eth:0xABC", symbol="TEST"):
    return {
        "token_id": token_id,
        "chain": "ethereum",
        "contract_address": "0xABC",
        "symbol": symbol,
        "name": "Test Token",
        "security_score": 80.0,
        "security_flags": [],
        "liquidity_usd": 50000,
        "volume_24h": 25000,
        "txns_24h": 200,
    }


class TestExtractGithubOwnerRepo:
    def test_standard_url(self):
        from src.pipeline.l4_fundamentals import _extract_github_owner_repo

        assert _extract_github_owner_repo("https://github.com/owner/repo") == (
            "owner",
            "repo",
        )

    def test_url_with_git_suffix(self):
        from src.pipeline.l4_fundamentals import _extract_github_owner_repo

        assert _extract_github_owner_repo("https://github.com/owner/repo.git") == (
            "owner",
            "repo",
        )

    def test_url_with_trailing_slash(self):
        from src.pipeline.l4_fundamentals import _extract_github_owner_repo

        result = _extract_github_owner_repo("https://github.com/owner/repo/")
        assert result == ("owner", "repo")

    def test_non_github_url(self):
        from src.pipeline.l4_fundamentals import _extract_github_owner_repo

        assert _extract_github_owner_repo("https://example.com/owner/repo") is None

    def test_none_input(self):
        from src.pipeline.l4_fundamentals import _extract_github_owner_repo

        assert _extract_github_owner_repo(None) is None


class TestL4Fundamentals:
    @pytest.fixture
    def l4(self):
        mock_repo = MagicMock()
        mock_repo.add_scan_result = MagicMock()

        mock_github = MagicMock()
        mock_github.calculate_github_score.return_value = {
            "score": 60,
            "flags": [],
            "breakdown": {"commit_frequency": 20, "contributor_count": 15},
            "repo_url": "https://github.com/test/repo",
        }
        mock_github.search_repo.return_value = None  # no repo found

        mock_claude = MagicMock()
        mock_claude.analyze_fundamentals.return_value = {
            "summary": "Test project",
            "tokenomics_score": 50,
            "roadmap_score": 3,
            "has_audit": True,
            "audit_firms": ["CertiK"],
            "team_transparency": 4,
            "ai_analysis_score": 70,
        }

        with patch("yaml.safe_load", return_value={"fundamentals": {"enabled": True}}):
            with patch(
                "builtins.open",
                MagicMock(
                    return_value=MagicMock(
                        __enter__=lambda s: s,
                        __exit__=MagicMock(return_value=False),
                    )
                ),
            ):
                from src.pipeline.l4_fundamentals import L4Fundamentals

                inst = L4Fundamentals.__new__(L4Fundamentals)
                inst.repository = mock_repo
                inst.github = mock_github
                inst.claude = mock_claude
                inst.config = {"fundamentals": {"enabled": True}}
                return inst

    def test_scores_computed_correctly(self, l4):
        token = _make_token()
        token["github_url"] = "https://github.com/test/repo"

        results = l4.run([token])
        assert len(results) == 1

        # fundamentals_score = github(60) * 0.4 + ai(70) * 0.6 = 24 + 42 = 66
        assert results[0]["fundamentals_score"] == pytest.approx(66.0, abs=0.1)

    def test_no_github_scores_zero_github(self, l4):
        """Token without GitHub URL should still get an AI score."""
        token = _make_token()
        # no github_url set
        results = l4.run([token])
        assert len(results) == 1
        # github_score = 0, ai_score = 70 → 0*0.4 + 70*0.6 = 42
        assert results[0]["fundamentals_score"] == pytest.approx(42.0, abs=0.1)

    def test_error_is_handled_gracefully(self, l4):
        """If Claude raises an exception, token still passes with zero score."""
        l4.claude.analyze_fundamentals.side_effect = RuntimeError("API down")
        token = _make_token()
        results = l4.run([token])
        assert len(results) == 1
        assert results[0]["fundamentals_score"] == 0.0
        assert "analysis_error" in results[0]["fundamentals_flags"]

    def test_empty_input(self, l4):
        assert l4.run([]) == []

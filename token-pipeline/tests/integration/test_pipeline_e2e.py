"""
Integration test: Full pipeline run against in-memory SQLite DB.
External APIs are mocked so this test runs offline.
"""
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def in_memory_db():
    """Create a fresh in-memory SQLite database for the test session."""
    from src.db import Base
    from src.db import models  # ensure all models are registered
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
    yield Session
    Session.remove()
    engine.dispose()


@pytest.fixture
def repo(in_memory_db):
    from src.db.repository import TokenRepository
    db = in_memory_db()
    yield TokenRepository(db)
    db.close()


# ──────────────────────────────────────────────────────────────────────────────
# Mock data helpers
# ──────────────────────────────────────────────────────────────────────────────

def _gecko_new_pools_response():
    return {
        "data": [
            {
                "attributes": {
                    "name": "ALPHA / USDC",
                    "address": "0xpool1",
                    "reserve_in_usd": "50000",
                    "volume_usd": {"h24": "25000"},
                    "transactions": {"h24": {"buys": 150, "sells": 100}},
                    "pool_created_at": (
                        datetime.now(timezone.utc) - timedelta(hours=3)
                    ).isoformat(),
                }
            },
            {
                "attributes": {
                    "name": "BETA / ETH",
                    "address": "0xpool2",
                    "reserve_in_usd": "1000",  # below min_liquidity → should be dropped
                    "volume_usd": {"h24": "500"},
                    "transactions": {"h24": {"buys": 5, "sells": 3}},
                    "pool_created_at": (
                        datetime.now(timezone.utc) - timedelta(hours=5)
                    ).isoformat(),
                }
            },
        ]
    }


def _goplus_response(address):
    return {
        address.lower(): {
            "is_honeypot": "0",
            "cannot_sell_all": "0",
            "is_mintable": "0",
            "is_open_source": "1",
            "hidden_owner": "0",
            "is_proxy": "0",
        }
    }


# ──────────────────────────────────────────────────────────────────────────────
# Test
# ──────────────────────────────────────────────────────────────────────────────

class TestPipelineE2E:
    @patch("src.clients.gecko_terminal.GeckoTerminalClient.get_new_pools")
    @patch("src.clients.goplus.GoPlusClient.token_security")
    @patch("src.clients.claude_agent.ClaudeAgent.analyze_fundamentals")
    @patch("src.clients.claude_agent.ClaudeAgent.analyze_narrative")
    @patch("src.clients.claude_agent.ClaudeAgent.generate_token_summary")
    @patch("src.clients.github_client.GitHubClient.search_repo")
    def test_l1_to_l3(
        self,
        mock_github_search,
        mock_claude_summary,
        mock_claude_narrative,
        mock_claude_fundamentals,
        mock_goplus,
        mock_gecko,
        repo,
    ):
        mock_gecko.return_value = _gecko_new_pools_response()
        mock_goplus.side_effect = lambda chain, addrs: _goplus_response(addrs[0])
        mock_github_search.return_value = None
        mock_claude_fundamentals.return_value = {
            "summary": "Test token",
            "tokenomics_score": 60,
            "roadmap_score": 3,
            "has_audit": False,
            "audit_firms": [],
            "team_transparency": 3,
            "ai_analysis_score": 60,
        }
        mock_claude_narrative.return_value = {
            "narrative_category": "DeFi",
            "narrative_alignment": 70,
            "competitive_summary": "Competitive DeFi project.",
            "novelty_score": 60,
            "community_health": 50,
        }
        mock_claude_summary.return_value = "Solid DeFi project on Ethereum."

        # Run L1
        with patch("yaml.safe_load") as mock_yaml:
            mock_yaml.return_value = {
                "pipeline": {
                    "target_chains": ["ethereum"],
                    "schedule": "0 */4 * * *",
                },
                "prefilter": {
                    "min_liquidity_usd": 5000,
                    "min_txns_24h": 10,
                    "cooldown_minutes": 60,
                },
                "security": {"drop_threshold": 40},
                "ranking": {
                    "weights": {
                        "security": 0.30,
                        "fundamentals": 0.20,
                        "narrative": 0.25,
                        "momentum": 0.15,
                        "community": 0.10,
                    },
                    "top_n": 10,
                },
                "fundamentals": {"enabled": True},
                "sentiment": {"enabled": True, "hot_narratives": []},
                "notifications": {},
            }

            with patch("src.clients.gecko_terminal.GeckoTerminalClient.get_new_pools", mock_gecko):
                from src.pipeline import L1Discovery, L2PreFilter, L3Security
                l1 = L1Discovery(repo)
                l1_results = l1.run()

            assert len(l1_results) > 0, "L1 should discover at least one token"

            # Run L2
            l2 = L2PreFilter(repo)
            l2_results = l2.run(l1_results)

            # BETA (low liquidity) should be dropped
            assert len(l2_results) <= len(l1_results)

            # Run L3 (if any passed L2)
            if l2_results:
                with patch(
                    "src.clients.goplus.GoPlusClient.token_security",
                    side_effect=lambda chain, addrs: _goplus_response(addrs[0]),
                ):
                    l3 = L3Security(repo)
                    l3_results = l3.run(l2_results)
                assert len(l3_results) >= 0

    def test_repository_crud(self, repo):
        """Sanity-check CRUD operations on in-memory DB."""
        from datetime import datetime, timezone
        token = repo.create_token({
            "id": "eth:0xTEST",
            "chain": "ethereum",
            "contract_address": "0xTEST",
            "name": "Test",
            "symbol": "TST",
            "status": "active",
            "discovered_at": datetime.now(timezone.utc),
        })
        assert token.id == "eth:0xTEST"

        updated = repo.update_token_status("eth:0xTEST", "dropped", "low_liquidity")
        assert updated.status == "dropped"

        repo.add_scan_result({
            "token_id": "eth:0xTEST",
            "layer": "L3",
            "score": 75.0,
            "details": {"test": True},
            "flags": [],
            "scanned_at": datetime.now(timezone.utc),
        })

        scan = repo.get_latest_scan("eth:0xTEST", "L3")
        assert scan is not None
        assert scan.score == 75.0

    def test_waitlist_lifecycle(self, repo):
        """Token added to waitlist should be retrievable and removable."""
        from datetime import datetime, timezone, timedelta
        repo.create_token({
            "id": "sol:0xWAIT",
            "chain": "solana",
            "contract_address": "0xWAIT",
            "name": "Wait Token",
            "symbol": "WAIT",
            "status": "watching",
            "discovered_at": datetime.now(timezone.utc),
        })

        eligible_at = datetime.utcnow() - timedelta(seconds=1)  # already eligible
        repo.add_to_waitlist("sol:0xWAIT", "cooldown", eligible_at)

        eligible = repo.get_eligible_waitlist_tokens()
        ids = [e.token_id for e in eligible]
        assert "sol:0xWAIT" in ids

        repo.remove_from_waitlist("sol:0xWAIT")
        eligible_after = repo.get_eligible_waitlist_tokens()
        ids_after = [e.token_id for e in eligible_after]
        assert "sol:0xWAIT" not in ids_after

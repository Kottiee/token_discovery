import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import yaml
from loguru import logger

from src.clients.claude_agent import ClaudeAgent
from src.clients.github_client import GitHubClient
from src.db.repository import TokenRepository

from .base import PipelineLayer


def _extract_github_owner_repo(url: str) -> Optional[Tuple[str, str]]:
    """Extract (owner, repo) from a GitHub URL."""
    if not url:
        return None
    match = re.search(r"github\.com/([^/]+)/([^/?\s#]+)", url)
    if match:
        return match.group(1), match.group(2).rstrip(".git")
    return None


class L4Fundamentals(PipelineLayer):
    """
    Layer 4: Fundamentals Analysis
    - GitHub repository scoring (activity, contributors, recency, stars)
    - Claude AI analysis (tokenomics, roadmap, audit, team)
    - fundamentals_score = github_score * 0.4 + ai_score * 0.6
    """

    def __init__(self, repository: TokenRepository):
        self.repository = repository
        self.github = GitHubClient()
        self.claude = ClaudeAgent()
        self.config = self._load_config()

    def _load_config(self) -> Dict:
        with open("config/settings.yaml", "r") as f:
            return yaml.safe_load(f)

    def run(self, input_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not input_data:
            return []

        results = []
        logger.info(f"--- L4 Fundamentals Start (Input: {len(input_data)}) ---")

        for token_data in input_data:
            token_id = token_data["token_id"]
            symbol = token_data.get("symbol", "UNKNOWN")
            name = token_data.get("name", symbol)

            try:
                github_score, github_details = self._analyze_github(token_data)
                ai_result = self.claude.analyze_fundamentals(
                    token_name=name,
                    token_symbol=symbol,
                    website_url=token_data.get("website_url"),
                    extra_context=token_data.get("description"),
                )
                ai_score = ai_result.get("ai_analysis_score", 30)

                fundamentals_score = round(github_score * 0.4 + ai_score * 0.6, 2)

                flags = github_details.get("flags", [])
                if not ai_result.get("has_audit"):
                    flags.append("no_audit")
                if ai_result.get("team_transparency", 1) <= 2:
                    flags.append("anonymous_team")

                details = {
                    "github": github_details,
                    "ai_analysis": ai_result,
                    "github_score": github_score,
                    "ai_score": ai_score,
                }

                self.repository.add_scan_result(
                    {
                        "token_id": token_id,
                        "layer": "L4",
                        "score": fundamentals_score,
                        "details": details,
                        "flags": flags,
                        "scanned_at": datetime.now(timezone.utc),
                    }
                )

                token_data["fundamentals_score"] = fundamentals_score
                token_data["fundamentals_flags"] = flags
                token_data["ai_summary"] = ai_result.get("summary", "")
                results.append(token_data)

                logger.info(
                    f"✅ [L4] {symbol} ({token_id}): "
                    f"GitHub={github_score:.0f}, AI={ai_score:.0f}, "
                    f"Total={fundamentals_score:.0f} | Flags: {flags}"
                )

            except Exception as e:
                logger.error(f"L4 error for {symbol} ({token_id}): {e}")
                # Don't drop — pass with zero score and continue
                token_data["fundamentals_score"] = 0.0
                token_data["fundamentals_flags"] = ["analysis_error"]
                token_data["ai_summary"] = ""
                results.append(token_data)

        logger.info(f"--- L4 Fundamentals End (Processed: {len(results)}) ---")
        return results

    def _analyze_github(self, token_data: Dict) -> Tuple[float, Dict]:
        """
        Try to find and score the GitHub repo.
        1. Use github_url if available in token_data
        2. Search by project name
        3. Return score=0 with flag if not found
        """
        github_url = token_data.get("github_url")
        name = token_data.get("name", token_data.get("symbol", ""))

        owner_repo = _extract_github_owner_repo(github_url) if github_url else None

        if not owner_repo and name:
            # Try searching GitHub
            logger.debug(f"Searching GitHub for: {name}")
            repo = self.github.search_repo(f"{name} crypto token blockchain")
            if repo:
                full_name = repo.get("full_name", "")
                parts = full_name.split("/")
                if len(parts) == 2:
                    owner_repo = (parts[0], parts[1])

        if not owner_repo:
            logger.info(f"No GitHub repo found for {name}")
            return 0.0, {"score": 0, "flags": ["no_github"], "breakdown": {}}

        owner, repo = owner_repo
        result = self.github.calculate_github_score(owner, repo)
        return float(result["score"]), result

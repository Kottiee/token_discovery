import math
import os
from typing import Any, Dict, Optional

import requests
from loguru import logger

from src.utils.rate_limiter import RateLimiter


class GitHubClient:
    BASE_URL = "https://api.github.com"

    def __init__(self):
        # 5000 calls/h with auth, 60 without -> conservative 100/min with auth
        self.token = os.getenv("GITHUB_TOKEN")
        self.rate_limiter = RateLimiter(rate_limit=30, period=60)
        self.headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            self.headers["Authorization"] = f"Bearer {self.token}"
        else:
            logger.warning("GITHUB_TOKEN not set — GitHub API rate limit is 60/h")

    def _get(self, path: str, params: Dict = None) -> Optional[Dict]:
        self.rate_limiter.wait()
        url = f"{self.BASE_URL}{path}"
        try:
            resp = requests.get(url, headers=self.headers, params=params, timeout=10)
            if resp.status_code == 404:
                return None
            if resp.status_code == 403:
                logger.warning("GitHub rate limit hit or forbidden")
                return None
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error(f"GitHub API error {path}: {e}")
            return None

    def search_repo(self, query: str) -> Optional[Dict]:
        """Search for a repository by project name."""
        data = self._get(
            "/search/repositories", params={"q": query, "sort": "stars", "per_page": 1}
        )
        if data and data.get("total_count", 0) > 0:
            return data["items"][0]
        return None

    def get_repo(self, owner: str, repo: str) -> Optional[Dict]:
        return self._get(f"/repos/{owner}/{repo}")

    def get_commits(self, owner: str, repo: str, since_days: int = 30) -> int:
        """Return number of commits in last N days."""
        from datetime import datetime, timedelta, timezone

        since = (datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat()
        data = self._get(
            f"/repos/{owner}/{repo}/commits", params={"since": since, "per_page": 100}
        )
        if data is None:
            return 0
        return len(data) if isinstance(data, list) else 0

    def get_contributors_count(self, owner: str, repo: str) -> int:
        """Return number of unique contributors."""
        data = self._get(
            f"/repos/{owner}/{repo}/contributors",
            params={"per_page": 100, "anon": "true"},
        )
        if data is None:
            return 0
        return len(data) if isinstance(data, list) else 0

    def calculate_github_score(self, owner: str, repo: str) -> Dict[str, Any]:
        """
        Calculate GitHub score (0-100) based on:
        - commit_frequency (0-30): commits in last 30 days, normalized
        - contributor_count (0-30): unique contributors, normalized
        - recency (0-20): days since last commit (inverse)
        - stars (0-10): log-normalized star count
        - has_readme (0-10): README.md presence

        Returns dict with total score and breakdown.
        """
        repo_info = self.get_repo(owner, repo)
        if not repo_info:
            return {"score": 0, "flags": ["repo_not_found"], "breakdown": {}}

        import math
        from datetime import datetime, timezone

        # --- commit_frequency (0–30) ---
        commit_count = self.get_commits(owner, repo, since_days=30)
        commit_score = min(30, commit_count)  # cap at 30

        # --- contributor_count (0–30) ---
        contributors = self.get_contributors_count(owner, repo)
        contributor_score = min(30, contributors * 3)  # 10+ contributors → 30

        # --- recency (0–20) ---
        last_push = repo_info.get("pushed_at")
        recency_score = 0
        if last_push:
            try:
                last_dt = datetime.fromisoformat(last_push.replace("Z", "+00:00"))
                days_since = (datetime.now(timezone.utc) - last_dt).days
                # 0 days → 20, 30 days → 10, 90 days → 0
                recency_score = max(0, 20 - int(days_since / 4.5))
            except Exception:
                recency_score = 0

        # --- stars (0–10): log2(stars+1) normalized to 10 ---
        stars = repo_info.get("stargazers_count", 0)
        star_score = min(10, int(math.log2(stars + 1) * 1.5))

        # --- has_readme (0–10) ---
        # README presence is indicated by repo_info existing and not having empty description
        has_readme_data = self._get(f"/repos/{owner}/{repo}/contents/README.md")
        readme_score = 10 if has_readme_data else 0

        total = (
            commit_score + contributor_score + recency_score + star_score + readme_score
        )
        flags = []
        if commit_count == 0:
            flags.append("no_recent_commits")
        if contributors <= 1:
            flags.append("single_contributor")

        return {
            "score": min(100, total),
            "flags": flags,
            "breakdown": {
                "commit_frequency": commit_score,
                "contributor_count": contributor_score,
                "recency": recency_score,
                "stars": star_score,
                "has_readme": readme_score,
            },
            "repo_url": repo_info.get("html_url"),
            "stars": stars,
        }

import json
import os
from typing import Any, Dict, Optional

from loguru import logger

try:
    import anthropic

    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False
    logger.warning(
        "anthropic package not installed — Claude AI analysis will be skipped"
    )


FUNDAMENTALS_SYSTEM = """You are a DeFi project analyst. Analyze the provided token project information and return a JSON object with the following fields:

{
  "summary": "One sentence project description",
  "tokenomics_score": 0-100,  // Higher = better distribution/vesting/burn
  "roadmap_score": 1-5,       // 5 = very specific with milestones and dates
  "has_audit": true/false,
  "audit_firms": ["..."],      // Empty list if none
  "team_transparency": 1-5,   // 5 = fully doxxed team
  "ai_analysis_score": 0-100  // Overall project quality score
}

Be concise and objective. If information is missing, use conservative (low) scores.
Return ONLY the JSON object, no other text."""

NARRATIVE_SYSTEM = """You are a crypto market analyst. Classify the given token project and return a JSON object:

{
  "narrative_category": "AI|RWA|DePIN|Meme|GameFi|DeFi|L1/L2|Other",
  "narrative_alignment": 0-100,  // How well it fits current hot narratives
  "competitive_summary": "3-line competitive analysis",
  "novelty_score": 0-100,        // How novel/differentiated the project is
  "community_health": 0-100      // Estimated community health
}

Return ONLY the JSON object, no other text."""

SUMMARY_SYSTEM = """You are a crypto analyst writing a brief token summary for traders.
Write a single concise sentence (max 20 words) summarizing the key value proposition and any notable risks.
Return ONLY the summary sentence, no other text."""


class ClaudeAgent:
    def __init__(self):
        self.api_key = os.getenv("ANTHROPIC_API_KEY")
        # Use cheapest model by default to minimize costs
        self.model = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
        self.client = None
        if _ANTHROPIC_AVAILABLE and self.api_key:
            self.client = anthropic.Anthropic(api_key=self.api_key)
        elif not self.api_key:
            logger.warning(
                "ANTHROPIC_API_KEY not set — Claude AI analysis will use fallback scores"
            )

    def _chat(
        self, system: str, user_content: str, max_tokens: int = 500
    ) -> Optional[str]:
        """Send a message to Claude and return the text response."""
        if not self.client:
            return None
        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user_content}],
            )
            return message.content[0].text
        except Exception as e:
            logger.error(f"Claude API error: {e}")
            return None

    def _parse_json(self, text: Optional[str]) -> Optional[Dict]:
        if not text:
            return None
        # Strip markdown code fences if present
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1]) if len(lines) > 2 else text
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse Claude JSON response: {text[:200]}")
            return None

    def analyze_fundamentals(
        self,
        token_name: str,
        token_symbol: str,
        website_url: Optional[str] = None,
        whitepaper_url: Optional[str] = None,
        extra_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Analyze token fundamentals using Claude.
        Returns structured dict with scores.
        """
        context_parts = [f"Token: {token_name} ({token_symbol})"]
        if website_url:
            context_parts.append(f"Website: {website_url}")
        if whitepaper_url:
            context_parts.append(f"Whitepaper: {whitepaper_url}")
        if extra_context:
            context_parts.append(f"Additional info: {extra_context}")

        user_content = "\n".join(context_parts)
        response = self._chat(FUNDAMENTALS_SYSTEM, user_content, max_tokens=600)
        result = self._parse_json(response)

        if result:
            logger.debug(
                f"Claude fundamentals for {token_symbol}: score={result.get('ai_analysis_score')}"
            )
            return result

        # Fallback: conservative defaults when Claude unavailable
        return {
            "summary": f"{token_name} ({token_symbol})",
            "tokenomics_score": 30,
            "roadmap_score": 1,
            "has_audit": False,
            "audit_firms": [],
            "team_transparency": 1,
            "ai_analysis_score": 30,
        }

    def analyze_narrative(
        self,
        token_name: str,
        token_symbol: str,
        categories: Optional[list] = None,
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Classify token narrative and score alignment with hot narratives.
        """
        context_parts = [f"Token: {token_name} ({token_symbol})"]
        if categories:
            context_parts.append(f"Categories: {', '.join(categories)}")
        if description:
            context_parts.append(f"Description: {description[:500]}")

        user_content = "\n".join(context_parts)
        response = self._chat(NARRATIVE_SYSTEM, user_content, max_tokens=500)
        result = self._parse_json(response)

        if result:
            logger.debug(
                f"Claude narrative for {token_symbol}: category={result.get('narrative_category')}"
            )
            return result

        return {
            "narrative_category": "Other",
            "narrative_alignment": 30,
            "competitive_summary": "Insufficient data for analysis.",
            "novelty_score": 30,
            "community_health": 30,
        }

    def generate_token_summary(
        self,
        token_name: str,
        token_symbol: str,
        chain: str,
        total_score: float,
        score_breakdown: Dict,
        flags: list,
    ) -> str:
        """
        Generate a concise 30-second summary for the daily report.
        """
        context = (
            f"Token: {token_name} ({token_symbol}) on {chain}\n"
            f"Total Score: {total_score:.0f}/100\n"
            f"Score breakdown: {json.dumps(score_breakdown)}\n"
            f"Risk flags: {', '.join(flags) if flags else 'none'}"
        )
        response = self._chat(SUMMARY_SYSTEM, context, max_tokens=100)
        if response:
            return response.strip()
        # Fallback summary
        flag_str = f" ⚠️ {', '.join(flags[:2])}" if flags else ""
        return f"{token_name} ({chain}) — Score {total_score:.0f}/100.{flag_str}"

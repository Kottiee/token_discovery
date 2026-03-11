"""
Token Discovery Pipeline — Orchestrator
Schedules and runs all 6 pipeline layers.
"""

import os
import signal
import sys
import time
import uuid

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import yaml
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from src.db import get_db, init_db
from src.db.repository import TokenRepository
from src.pipeline import (
    L1Discovery,
    L2PreFilter,
    L3Security,
    L4Fundamentals,
    L5Sentiment,
    L6Ranking,
)
from src.utils.logger import setup_logger


def _load_config() -> dict:
    config_path = os.path.join(
        os.path.dirname(__file__), "..", "config", "settings.yaml"
    )
    with open(config_path, "r") as f:
        raw = f.read()

    # Expand ${ENV_VAR} placeholders
    import re

    def _expand(m):
        return os.getenv(m.group(1), "")

    raw = re.sub(r"\$\{(\w+)\}", _expand, raw)
    return yaml.safe_load(raw)


def _get_repo() -> TokenRepository:
    db = next(get_db())
    return TokenRepository(db)


# ──────────────────────────────────────────────────────────────────────────────
# Job: Discovery (L1 + L2) — runs every 4 hours
# ──────────────────────────────────────────────────────────────────────────────


def job_discovery():
    logger.info("=== JOB: discovery_run (L1 + L2) ===")
    run_id = str(uuid.uuid4())
    repo = _get_repo()
    repo.create_pipeline_run(run_id)
    stats = {}

    try:
        l1 = L1Discovery(repo)
        l1_results = l1.run()
        stats["l1_discovered"] = len(l1_results)

        l2 = L2PreFilter(repo)
        l2_results = l2.run(l1_results)
        stats["l2_passed"] = len(l2_results)

        repo.finish_pipeline_run(run_id, "completed", stats)
        logger.info(
            f"discovery_run done: L1={stats['l1_discovered']} L2={stats['l2_passed']}"
        )
    except Exception as e:
        logger.error(f"discovery_run failed: {e}")
        repo.finish_pipeline_run(run_id, "failed", {"error": str(e)})


# ──────────────────────────────────────────────────────────────────────────────
# Job: Security (L3) — runs every 6 hours
# ──────────────────────────────────────────────────────────────────────────────


def job_security_scan():
    logger.info("=== JOB: security_scan (L3) ===")
    repo = _get_repo()
    stats = {}

    try:
        # Get active tokens not yet scanned by L3
        pending_tokens = repo.get_tokens_pending_layer("L3")
        if not pending_tokens:
            logger.info("security_scan: no pending tokens")
            return

        # Convert ORM objects to dicts that L3 expects
        token_list = []
        for t in pending_tokens:
            pool = repo.get_latest_pool(t.id)
            token_list.append(
                {
                    "token_id": t.id,
                    "chain": t.chain,
                    "contract_address": t.contract_address,
                    "symbol": t.symbol,
                    "name": t.name,
                    "liquidity_usd": pool.liquidity_usd if pool else 0,
                    "volume_24h": pool.volume_24h if pool else 0,
                    "txns_24h": pool.txns_24h if pool else 0,
                    "pool_address": pool.id if pool else "",
                }
            )

        l3 = L3Security(repo)
        l3_results = l3.run(token_list)
        stats["l3_passed"] = len(l3_results)

        logger.info(
            f"security_scan done: {stats['l3_passed']}/{len(pending_tokens)} passed"
        )
    except Exception as e:
        logger.error(f"security_scan failed: {e}")


# ──────────────────────────────────────────────────────────────────────────────
# Job: Deep Analysis (L4 + L5) — runs every 12 hours
# ──────────────────────────────────────────────────────────────────────────────


def job_deep_analysis():
    logger.info("=== JOB: deep_analysis (L4 + L5) ===")
    repo = _get_repo()
    stats = {}

    try:
        # Tokens that passed L3 but not yet L4
        pending_l3 = repo.get_tokens_pending_layer("L4")
        # Only tokens with a passing L3 score
        token_list = []
        for t in pending_l3:
            l3_scan = repo.get_latest_scan(t.id, "L3")
            if l3_scan is None:
                continue  # hasn't been through L3 yet
            pool = repo.get_latest_pool(t.id)
            token_list.append(
                {
                    "token_id": t.id,
                    "chain": t.chain,
                    "contract_address": t.contract_address,
                    "symbol": t.symbol,
                    "name": t.name,
                    "security_score": l3_scan.score,
                    "security_flags": l3_scan.flags or [],
                    "liquidity_usd": pool.liquidity_usd if pool else 0,
                    "volume_24h": pool.volume_24h if pool else 0,
                    "txns_24h": pool.txns_24h if pool else 0,
                    "pool_address": pool.id if pool else "",
                }
            )

        if not token_list:
            logger.info("deep_analysis: no pending tokens")
            return

        l4 = L4Fundamentals(repo)
        l4_results = l4.run(token_list)
        stats["l4_processed"] = len(l4_results)

        l5 = L5Sentiment(repo)
        l5_results = l5.run(l4_results)
        stats["l5_processed"] = len(l5_results)

        logger.info(
            f"deep_analysis done: L4={stats['l4_processed']} L5={stats['l5_processed']}"
        )
    except Exception as e:
        logger.error(f"deep_analysis failed: {e}")


# ──────────────────────────────────────────────────────────────────────────────
# Job: Daily Report (L6) — runs once per day at 08:00 UTC
# ──────────────────────────────────────────────────────────────────────────────


def job_daily_report():
    logger.info("=== JOB: daily_report (L6) ===")
    repo = _get_repo()

    try:
        # Gather active tokens that have been through L5
        active_tokens = repo.get_active_tokens()
        token_list = []

        for t in active_tokens:
            scores = repo.get_all_layer_scores(t.id)
            if "L5" not in scores:
                continue  # not fully analyzed yet

            l3_scan = repo.get_latest_scan(t.id, "L3")
            l4_scan = repo.get_latest_scan(t.id, "L4")
            l5_scan = repo.get_latest_scan(t.id, "L5")
            pool = repo.get_latest_pool(t.id)

            l5_details = (l5_scan.details or {}) if l5_scan else {}

            token_list.append(
                {
                    "token_id": t.id,
                    "chain": t.chain,
                    "contract_address": t.contract_address,
                    "symbol": t.symbol,
                    "name": t.name,
                    "security_score": scores.get("L3", 0),
                    "fundamentals_score": scores.get("L4", 0),
                    "narrative_score": l5_details.get(
                        "narrative_score", scores.get("L5", 0)
                    ),
                    "community_score": l5_details.get("community_score", 0),
                    "security_flags": (l3_scan.flags or []) if l3_scan else [],
                    "fundamentals_flags": (l4_scan.flags or []) if l4_scan else [],
                    "sentiment_flags": (l5_scan.flags or []) if l5_scan else [],
                    "narrative_category": l5_details.get("narrative_category", "Other"),
                    "ai_summary": (
                        (l4_scan.details or {})
                        .get("ai_analysis", {})
                        .get("summary", "")
                        if l4_scan
                        else ""
                    ),
                    "liquidity_usd": pool.liquidity_usd if pool else 0,
                    "volume_24h": pool.volume_24h if pool else 0,
                    "txns_24h": pool.txns_24h if pool else 0,
                    "pool_address": pool.id if pool else "",
                }
            )

        if not token_list:
            logger.info("daily_report: no fully-analyzed tokens yet")
            return

        l6 = L6Ranking(repo)
        rankings = l6.run(token_list)
        logger.info(f"daily_report done: {len(rankings)} tokens ranked")
    except Exception as e:
        logger.error(f"daily_report failed: {e}")


# ──────────────────────────────────────────────────────────────────────────────
# Job: Waitlist Check — runs every hour
# ──────────────────────────────────────────────────────────────────────────────


def job_waitlist_check():
    logger.info("=== JOB: waitlist_check ===")
    repo = _get_repo()

    try:
        eligible = repo.get_eligible_waitlist_tokens()
        if not eligible:
            return

        logger.info(f"waitlist_check: re-activating {len(eligible)} tokens")
        for entry in eligible:
            repo.update_token_status(entry.token_id, "active", None)
            repo.remove_from_waitlist(entry.token_id)
            logger.info(f"  Re-activated: {entry.token_id}")
    except Exception as e:
        logger.error(f"waitlist_check failed: {e}")


# ──────────────────────────────────────────────────────────────────────────────
# Job: Weekly Cleanup
# ──────────────────────────────────────────────────────────────────────────────


def job_cleanup():
    logger.info("=== JOB: cleanup ===")
    repo = _get_repo()
    try:
        deleted = repo.cleanup_old_dropped(days=30)
        logger.info(f"cleanup: removed {deleted} old dropped tokens")
    except Exception as e:
        logger.error(f"cleanup failed: {e}")


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────


def run_once():
    """Run all layers once (for manual / CI testing)."""
    logger.info("Running pipeline once (all layers)...")
    job_discovery()
    job_security_scan()
    job_deep_analysis()
    job_daily_report()
    job_waitlist_check()
    logger.info("Single run complete.")


def run_scheduler():
    """Start the APScheduler-based scheduler."""
    config = _load_config()
    scheduler = BlockingScheduler(timezone="UTC")

    # Discovery: every 4 hours
    scheduler.add_job(
        job_discovery, CronTrigger.from_crontab("0 */4 * * *"), id="discovery_run"
    )

    # Security scan: every 6 hours
    scheduler.add_job(
        job_security_scan, CronTrigger.from_crontab("30 */6 * * *"), id="security_scan"
    )

    # Deep analysis: every 12 hours
    scheduler.add_job(
        job_deep_analysis, CronTrigger.from_crontab("0 */12 * * *"), id="deep_analysis"
    )

    # Daily report: 08:00 UTC
    scheduler.add_job(
        job_daily_report, CronTrigger.from_crontab("0 8 * * *"), id="daily_report"
    )

    # Waitlist check: every hour
    scheduler.add_job(
        job_waitlist_check, CronTrigger.from_crontab("0 * * * *"), id="waitlist_check"
    )

    # Weekly cleanup: Sunday 03:00 UTC
    scheduler.add_job(job_cleanup, CronTrigger.from_crontab("0 3 * * 0"), id="cleanup")

    def _shutdown(signum, frame):
        logger.info("Shutting down scheduler...")
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    logger.info("Scheduler started. Jobs:")
    for job in scheduler.get_jobs():
        logger.info(f"  {job.id}: next run at {job.next_run_time}")

    scheduler.start()


def main():
    setup_logger()
    init_db()
    logger.info("Database initialized.")

    mode = os.getenv("PIPELINE_MODE", "scheduler")
    if mode == "once":
        run_once()
    else:
        run_scheduler()


if __name__ == "__main__":
    main()

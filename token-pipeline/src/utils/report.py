import json

from loguru import logger

from src.db.repository import TokenRepository


def generate_report(repository: TokenRepository):
    """
    Generate a simple console report of the current pipeline state.
    """
    logger.info("=" * 50)
    logger.info("       TOKEN DISCOVERY PIPELINE REPORT       ")
    logger.info("=" * 50)

    # 1. Overall Stats
    # Import models here to avoid circular imports if any, or just standard import
    from src.db.models import ScanResult, Token

    # repository.db is a Session instance
    total_tokens = repository.db.query(Token).count()
    dropped_tokens = (
        repository.db.query(Token).filter(Token.status == "dropped").count()
    )
    active_count = repository.db.query(Token).filter(Token.status == "active").count()
    watching_count = (
        repository.db.query(Token).filter(Token.status == "watching").count()
    )

    logger.info(f"Total Tokens: {total_tokens}")
    logger.info(f"  - Active:   {active_count}")
    logger.info(f"  - Watching: {watching_count}")
    logger.info(f"  - Dropped:  {dropped_tokens}")

    logger.info("-" * 50)

    # 2. Recent L3 Results (Passed)
    # Get tokens with L3 scan results and high score
    # Assuming L3 is the last step for now

    # Join Token and ScanResult
    # results = repository.db.query(Token, ScanResult).join(ScanResult).filter(ScanResult.layer == "L3").order_by(ScanResult.scanned_at.desc()).limit(10).all()

    # Let's just show the active ones with high scores
    pass_l3_tokens = (
        repository.db.query(Token)
        .join(ScanResult)
        .filter(
            Token.status == "active",
            ScanResult.layer == "L3",
            ScanResult.score >= 60,  # Arbitrary threshold for "Good"
        )
        .all()
    )

    if pass_l3_tokens:
        logger.info(f"Top Candidates (Active & L3 Score >= 60):")
        for token in pass_l3_tokens:
            # Get latest L3 score
            l3_res = (
                repository.db.query(ScanResult)
                .filter(ScanResult.token_id == token.id, ScanResult.layer == "L3")
                .order_by(ScanResult.scanned_at.desc())
                .first()
            )

            score = l3_res.score if l3_res else 0
            logger.info(f"  Rank: {token.symbol} ({token.chain}) - Score: {score}")
            logger.info(f"        Addr: {token.contract_address}")
    else:
        logger.info("No high-scoring candidates yet.")

    logger.info("=" * 50)

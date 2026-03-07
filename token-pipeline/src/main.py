import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.db import init_db, get_db
from src.db.repository import TokenRepository
from src.pipeline import L1Discovery, L2PreFilter
from src.utils.logger import setup_logger

logger = setup_logger()

def main():
    logger.info("Starting Token Discovery Pipeline (Phase 1)...")

    # 1. Initialize Database
    init_db()
    logger.info("Database initialized.")

    # 2. Setup Repository
    db_gen = get_db()
    db = next(db_gen)
    repository = TokenRepository(db)

    try:
        # 3. Layer 1: Discovery
        logger.info("Running Layer 1: Discovery...")
        l1 = L1Discovery(repository)
        l1_results = l1.run()
        
        if not l1_results:
            logger.info("No new tokens discovered.")
            return

        # 4. Layer 2: Pre-filter
        logger.info("Running Layer 2: Pre-filter...")
        l2 = L2PreFilter(repository)
        l2_results = l2.run(l1_results)

        # 5. Output Results
        logger.info("Phase 1 Complete.")
        logger.info(f"Discovered: {len(l1_results)}")
        logger.info(f"Passed Pre-filter: {len(l2_results)}")
        
        for token in l2_results:
            logger.info(f"Candidate: {token['symbol']} ({token['chain']}) - {token['contract_address']}")

    except Exception as e:
        logger.error(f"Pipeline failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    main()

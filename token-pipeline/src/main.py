import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.db import init_db, get_db
from src.db.repository import TokenRepository
from src.pipeline import L1Discovery, L2PreFilter, L3Security
from src.utils.logger import setup_logger

logger = setup_logger()

def main():
    logger.info("Starting Token Discovery Pipeline (Phase 2)...")

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
        
        # For testing Phase 2 even if no NEW tokens, we can fetch 'active' tokens from DB that haven't been scanned
        # But for now, let's stick to the flow.
        
        if not l1_results:
            logger.info("No new tokens discovered in L1.")
            # Optional: Load existing active tokens for testing L3?
            # active_tokens = repository.get_active_tokens()
            # l1_results = [t.to_dict() for t in active_tokens] # Need to implement to_dict on model
            pass

        # 4. Layer 2: Pre-filter
        logger.info("Running Layer 2: Pre-filter...")
        l2 = L2PreFilter(repository)
        l2_results = l2.run(l1_results)

        if not l2_results:
             logger.info("No tokens passed L2 Pre-filter.")
             # For Phase 2 verification, if we want to test L3, we might need to mock L2 results or relax constraints.
             # Let's proceed only if we have results.
             pass

        # 5. Layer 3: Security Scan
        if l2_results:
            logger.info("Running Layer 3: Security Scan...")
            l3 = L3Security(repository)
            l3_results = l3.run(l2_results)

            # 6. Output Results
            logger.info("Phase 2 Complete.")
            logger.info(f"Discovered: {len(l1_results)}")
            logger.info(f"Passed Pre-filter: {len(l2_results)}")
            logger.info(f"Passed Security Scan: {len(l3_results)}")
            
            for token in l3_results:
                logger.info(f"Candidate: {token['symbol']} ({token['chain']}) - {token['contract_address']} (Score: {token.get('security_score')})")
        else:
            logger.info("Skipping L3 (No candidates).")

    except Exception as e:
        logger.error(f"Pipeline failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    main()

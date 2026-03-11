from datetime import date, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from .models import DailyRanking, PipelineRun, Pool, ScanResult, Token, WaitList


class TokenRepository:
    def __init__(self, db: Session):
        self.db = db

    # ── Token ──────────────────────────────────────────────────────────────

    def get_token(self, chain: str, address: str) -> Optional[Token]:
        return self.db.query(Token).filter(Token.id == f"{chain}:{address}").first()

    def get_token_by_id(self, token_id: str) -> Optional[Token]:
        return self.db.query(Token).filter(Token.id == token_id).first()

    def create_token(self, token_data: dict) -> Token:
        token = Token(**token_data)
        self.db.add(token)
        self.db.commit()
        self.db.refresh(token)
        return token

    def update_token_status(
        self, token_id: str, status: str, drop_reason: str = None
    ) -> Optional[Token]:
        token = self.db.query(Token).filter(Token.id == token_id).first()
        if token:
            token.status = status
            token.drop_reason = drop_reason
            token.updated_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(token)
        return token

    def get_active_tokens(self) -> List[Token]:
        return self.db.query(Token).filter(Token.status == "active").all()

    def get_tokens_by_status(self, status: str) -> List[Token]:
        return self.db.query(Token).filter(Token.status == status).all()

    def get_tokens_pending_layer(self, layer: str) -> List[Token]:
        """Return active tokens that do NOT yet have a scan_result for the given layer."""
        scanned_ids = (
            self.db.query(ScanResult.token_id)
            .filter(ScanResult.layer == layer)
            .subquery()
        )
        return (
            self.db.query(Token)
            .filter(Token.status == "active")
            .filter(~Token.id.in_(scanned_ids))
            .all()
        )

    # ── Pool ───────────────────────────────────────────────────────────────

    def add_pool(self, pool_data: dict) -> Pool:
        pool = Pool(**pool_data)
        self.db.add(pool)
        self.db.commit()
        self.db.refresh(pool)
        return pool

    def get_latest_pool(self, token_id: str) -> Optional[Pool]:
        return (
            self.db.query(Pool)
            .filter(Pool.token_id == token_id)
            .order_by(Pool.snapshot_at.desc())
            .first()
        )

    # ── ScanResult ─────────────────────────────────────────────────────────

    def add_scan_result(self, result_data: dict) -> ScanResult:
        result = ScanResult(**result_data)
        self.db.add(result)
        self.db.commit()
        return result

    def get_latest_scan(self, token_id: str, layer: str) -> Optional[ScanResult]:
        return (
            self.db.query(ScanResult)
            .filter(
                ScanResult.token_id == token_id,
                ScanResult.layer == layer,
            )
            .order_by(ScanResult.scanned_at.desc())
            .first()
        )

    def get_all_layer_scores(self, token_id: str) -> Dict[str, float]:
        """Return {layer: score} dict for the most recent scan of each layer."""
        rows = (
            self.db.query(ScanResult.layer, ScanResult.score)
            .filter(ScanResult.token_id == token_id)
            .order_by(ScanResult.scanned_at.desc())
            .all()
        )
        seen: Dict[str, float] = {}
        for layer, score in rows:
            if layer not in seen:
                seen[layer] = score
        return seen

    # ── WaitList ───────────────────────────────────────────────────────────

    def add_to_waitlist(
        self, token_id: str, reason: str, eligible_at: datetime
    ) -> None:
        wait_item = WaitList(token_id=token_id, reason=reason, eligible_at=eligible_at)
        self.db.merge(wait_item)
        self.db.commit()

    def get_eligible_waitlist_tokens(self) -> List[WaitList]:
        """Return waitlist entries whose cooldown has expired."""
        now = datetime.utcnow()
        return self.db.query(WaitList).filter(WaitList.eligible_at <= now).all()

    def remove_from_waitlist(self, token_id: str) -> None:
        self.db.query(WaitList).filter(WaitList.token_id == token_id).delete()
        self.db.commit()

    # ── PipelineRun ────────────────────────────────────────────────────────

    def create_pipeline_run(self, run_id: str) -> PipelineRun:
        run = PipelineRun(id=run_id, status="running", started_at=datetime.utcnow())
        self.db.add(run)
        self.db.commit()
        return run

    def finish_pipeline_run(
        self, run_id: str, status: str, stats: Dict
    ) -> Optional[PipelineRun]:
        run = self.db.query(PipelineRun).filter(PipelineRun.id == run_id).first()
        if run:
            run.finished_at = datetime.utcnow()
            run.status = status
            run.stats = stats
            self.db.commit()
        return run

    # ── DailyRanking ───────────────────────────────────────────────────────

    def upsert_daily_ranking(self, ranking_data: Dict) -> DailyRanking:
        """Insert or replace ranking row for (date, rank)."""
        existing = (
            self.db.query(DailyRanking)
            .filter(
                DailyRanking.date == ranking_data["date"],
                DailyRanking.rank == ranking_data["rank"],
            )
            .first()
        )
        if existing:
            for k, v in ranking_data.items():
                setattr(existing, k, v)
            self.db.commit()
            return existing

        ranking = DailyRanking(**ranking_data)
        self.db.add(ranking)
        self.db.commit()
        return ranking

    def get_daily_rankings(self, for_date: date) -> List[DailyRanking]:
        return (
            self.db.query(DailyRanking)
            .filter(DailyRanking.date == for_date)
            .order_by(DailyRanking.rank)
            .all()
        )

    # ── Cleanup ────────────────────────────────────────────────────────────

    def cleanup_old_dropped(self, days: int = 30) -> int:
        """Delete dropped tokens older than N days. Returns deleted count."""
        from datetime import timedelta

        cutoff = datetime.utcnow() - timedelta(days=days)
        result = (
            self.db.query(Token)
            .filter(
                Token.status == "dropped",
                Token.updated_at <= cutoff,
            )
            .delete(synchronize_session=False)
        )
        self.db.commit()
        return result

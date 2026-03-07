from sqlalchemy.orm import Session
from .models import Token, Pool, PipelineRun, ScanResult, DailyRanking, WaitList
from typing import List, Optional
from datetime import datetime

class TokenRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_token(self, chain: str, address: str) -> Optional[Token]:
        return self.db.query(Token).filter(
            Token.id == f"{chain}:{address}"
        ).first()

    def create_token(self, token_data: dict) -> Token:
        token = Token(**token_data)
        self.db.add(token)
        self.db.commit()
        self.db.refresh(token)
        return token
    
    def update_token_status(self, token_id: str, status: str, drop_reason: str = None):
        token = self.db.query(Token).filter(Token.id == token_id).first()
        if token:
            token.status = status
            token.drop_reason = drop_reason
            self.db.commit()
            self.db.refresh(token)
        return token

    def add_pool(self, pool_data: dict) -> Pool:
        pool = Pool(**pool_data)
        self.db.add(pool)
        self.db.commit()
        self.db.refresh(pool)
        return pool
    
    def get_active_tokens(self) -> List[Token]:
        return self.db.query(Token).filter(Token.status == "active").all()

    def add_to_waitlist(self, token_id: str, reason: str, eligible_at: datetime):
        wait_item = WaitList(token_id=token_id, reason=reason, eligible_at=eligible_at)
        self.db.merge(wait_item) # Use merge to handle potential existing entry
        self.db.commit()
    
    def add_scan_result(self, result_data: dict) -> ScanResult:
        result = ScanResult(**result_data)
        self.db.add(result)
        self.db.commit()
        return result

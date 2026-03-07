from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey, Text, JSON, Date
from sqlalchemy.orm import relationship
from datetime import datetime
from . import Base

class Token(Base):
    __tablename__ = "tokens"

    id = Column(String, primary_key=True) # {chain}:{contract_address}
    chain = Column(String, nullable=False)
    contract_address = Column(String, nullable=False)
    name = Column(String)
    symbol = Column(String)
    discovered_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String) # active / dropped / watching
    drop_reason = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    pools = relationship("Pool", back_populates="token")
    scan_results = relationship("ScanResult", back_populates="token")
    daily_rankings = relationship("DailyRanking", back_populates="token")
    wait_list = relationship("WaitList", back_populates="token", uselist=False)

class Pool(Base):
    __tablename__ = "pools"

    id = Column(String, primary_key=True) # Pool address
    token_id = Column(String, ForeignKey("tokens.id"))
    dex = Column(String)
    base_token = Column(String)
    liquidity_usd = Column(Float)
    volume_24h = Column(Float)
    txns_24h = Column(Integer)
    created_at = Column(DateTime) # Pool creation time
    snapshot_at = Column(DateTime, default=datetime.utcnow)

    token = relationship("Token", back_populates="pools")

class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id = Column(String, primary_key=True) # UUID
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    status = Column(String) # running / completed / failed
    stats = Column(JSON)

    scan_results = relationship("ScanResult", back_populates="run")

class ScanResult(Base):
    __tablename__ = "scan_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    token_id = Column(String, ForeignKey("tokens.id"))
    layer = Column(String) # L1 ~ L6
    score = Column(Float)
    details = Column(JSON)
    flags = Column(JSON)
    run_id = Column(String, ForeignKey("pipeline_runs.id"))
    scanned_at = Column(DateTime, default=datetime.utcnow)

    token = relationship("Token", back_populates="scan_results")
    run = relationship("PipelineRun", back_populates="scan_results")

class DailyRanking(Base):
    __tablename__ = "daily_rankings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, default=datetime.utcnow().date)
    rank = Column(Integer)
    token_id = Column(String, ForeignKey("tokens.id"))
    total_score = Column(Float)
    score_breakdown = Column(JSON)
    summary = Column(Text)
    risk_flags = Column(JSON)

    token = relationship("Token", back_populates="daily_rankings")

class WaitList(Base):
    __tablename__ = "wait_list"

    token_id = Column(String, ForeignKey("tokens.id"), primary_key=True)
    reason = Column(String)
    eligible_at = Column(DateTime)

    token = relationship("Token", back_populates="wait_list")

"""
SQLAlchemy database configuration and session management.

Feature 011: Document Ingestion & Batch Processing
Provides database engine, SessionLocal factory, and get_db dependency.
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool

# Get database URL from environment
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/gov_ai_db")

# Create SQLAlchemy engine with connection pooling
# Feature 011 requires connection pooling for parallel workers (T031)
engine = create_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=10,  # Support up to 10 parallel workers (FR-029)
    max_overflow=20,  # Additional connections for burst load
    pool_pre_ping=True,  # Verify connections before using
    pool_recycle=3600,  # Recycle connections after 1 hour
    echo=False,  # Set to True for SQL query logging (debugging)
)

# Create SessionLocal factory
# Each request gets its own database session via get_db() dependency
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Session:
    """
    Database session dependency for FastAPI.

    Yields a SQLAlchemy session that is automatically closed after request.
    Used in all ingestion and processing API endpoints.

    Usage:
        @app.get("/endpoint")
        def endpoint(db: Session = Depends(get_db)):
            # Use db for queries
            pass

    Yields:
        Session: SQLAlchemy database session
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """
    Initialize database by creating all tables.

    This should be called once during application startup or via migration script.
    In production, use Alembic migrations instead of direct table creation.
    """
    from models.base import Base

    Base.metadata.create_all(bind=engine)

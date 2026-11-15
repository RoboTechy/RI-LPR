from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import DATABASE_URL

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def apply_column_migrations():
    """create_all() adds missing tables but never a missing column on a
    table that already exists. Called by both the api and the worker at
    startup - the worker starts first (the api depends on it) and
    writes these columns, so it can't wait for the api to add them."""
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as connection:
        connection.execute(text(
            "ALTER TABLE detected_plates ADD COLUMN IF NOT EXISTS char_boxes JSON"
        ))

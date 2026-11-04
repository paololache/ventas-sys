import os

from sqlalchemy import create_engine, event
from sqlalchemy.pool import NullPool
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


def normalize_url(url: str) -> str:
    """Neon/Supabase/Heroku entregan postgres:// o postgresql://; SQLAlchemy necesita el driver explícito."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg2://" + url[len(prefix):]
    return url


def make_engine(url: str | None = None):
    url = normalize_url(url or get_settings().database_url)
    kwargs = {}
    if os.environ.get("VERCEL"):  # serverless: sin pool persistente (usa el pooler de Neon/Supabase)
        kwargs["poolclass"] = NullPool
    elif not url.startswith("sqlite"):
        kwargs["pool_pre_ping"] = True
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_engine(url, future=True, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _fk(dbapi_conn, _):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

    return engine


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

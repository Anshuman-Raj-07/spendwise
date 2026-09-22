import os
from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from database.models import Base

# Database path defaults to spendwise.db in the project root directory
DB_PATH = os.getenv("SPENDWISE_DB_PATH", os.path.join(os.path.dirname(os.path.dirname(__file__)), "spendwise.db"))
DATABASE_URL = f"sqlite:///{DB_PATH}"

# For SQLite, check_same_thread=False allows Streamlit's multi-threaded model to access the engine safely
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """
    Initializes database tables if they do not already exist.
    """
    Base.metadata.create_all(bind=engine)


@contextmanager
def get_db():
    """
    Context manager for database sessions.
    Ensures safe commit and rollback on errors, and closes the session upon exit.
    """
    db: Session = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


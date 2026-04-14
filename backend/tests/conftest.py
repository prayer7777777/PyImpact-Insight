from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Base
from app.db.session import build_engine, get_session
from app.main import app


@pytest.fixture()
def test_session_factory(tmp_path: Path) -> Generator[sessionmaker[Session], None, None]:
    db_path = tmp_path / "test.sqlite3"
    engine = build_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )

    def override_session() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        yield session_factory
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


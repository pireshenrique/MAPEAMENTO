from datetime import datetime, timezone

import pytest

from radar.db.engine import make_engine, make_session_factory
from radar.db.tables import Base
from radar.settings import EnvSettings, load_config


@pytest.fixture(scope="session")
def config():
    return load_config("config", env=EnvSettings(_env_file=None))


@pytest.fixture
def session_factory():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return make_session_factory(engine)


@pytest.fixture
def session(session_factory):
    s = session_factory()
    yield s
    s.close()


NOW = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)

"""Shared backend test fixtures."""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.runtime import RuntimeContext
from app.main import create_app
from tests.fakes import FakeHealthDependency


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        log_level="CRITICAL",
        log_json=True,
    )


@pytest.fixture
def database_dependency() -> FakeHealthDependency:
    return FakeHealthDependency(name="database")


@pytest.fixture
def redis_dependency() -> FakeHealthDependency:
    return FakeHealthDependency(name="redis")


@pytest.fixture
def runtime(
    database_dependency: FakeHealthDependency,
    redis_dependency: FakeHealthDependency,
) -> RuntimeContext:
    return RuntimeContext(dependencies=(database_dependency, redis_dependency))


@pytest.fixture
def application(test_settings: Settings, runtime: RuntimeContext) -> FastAPI:
    return create_app(test_settings, runtime)


@pytest.fixture
def client(application: FastAPI) -> Iterator[TestClient]:
    with TestClient(application) as test_client:
        yield test_client

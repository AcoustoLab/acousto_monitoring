"""Configuration file for pytest."""

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    """Pytest parser options."""
    parser.addoption(
        "--run-ni",
        action="store_true",
        default=False,
        help="run NI hardware tests",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]):
    """Skip integration tests without special flag."""
    if config.getoption("--run-ni"):
        return

    skip_ni = pytest.mark.skip(
        reason="need --run-ni option to run",
    )

    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_ni)

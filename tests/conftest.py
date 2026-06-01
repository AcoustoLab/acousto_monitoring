import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--run-ni",
        action="store_true",
        default=False,
        help="run NI hardware tests",
    )


def pytest_collection_modifyitems(config, items):

    if config.getoption("--run-ni"):
        return

    skip_ni = pytest.mark.skip(
        reason="need --run-ni option to run",
    )

    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_ni)

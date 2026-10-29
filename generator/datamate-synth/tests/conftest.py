from pathlib import Path
import pytest


@pytest.fixture(scope='session')
def output(pytestconfig):
    return Path(pytestconfig.getoption('--out')).resolve()


def pytest_addoption(parser):
    parser.addoption('--out', action='store', default=str(Path(__file__).resolve().parent.parent / 'out'),
                     help='Generated output root to test')

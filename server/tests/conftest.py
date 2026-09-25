import pytest
from helpers import AccessFixture


@pytest.fixture
def access(tmp_path):
    return AccessFixture(tmp_path)

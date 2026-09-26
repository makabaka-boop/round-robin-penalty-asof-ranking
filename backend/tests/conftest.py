import os
import pytest


@pytest.fixture
def base_url():
    return os.environ.get("BOARD_URL", "http://localhost:8080")

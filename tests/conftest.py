import pytest
from memory_server.server import MemoryManager


@pytest.fixture
def manager():
    # Provide a clean, in-memory database for each test
    return MemoryManager(":memory:")

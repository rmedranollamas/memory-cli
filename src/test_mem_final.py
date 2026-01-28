from memory_server.server import MemoryManager


def test():
    manager = MemoryManager(":memory:")
    db = manager.get_db()
    id1 = manager.remember("A")
    id2 = manager.remember("B", relation_to=id1, relation_type="updates")
    assert db["memories"].get(id1)["is_latest"] == 0
    print("Test Passed")


if __name__ == "__main__":
    test()

from memory_server.server import MemoryManager


def test_memory_relationships():
    # Use in-memory DB for isolated testing as suggested in PR review
    manager = MemoryManager(":memory:")
    db = manager.get_db()

    print("--- Testing Relationships (Updates) ---")
    id1 = manager.remember(
        "Ramón works at Supermemory as a content engineer.", citation="chat_1"
    )
    id2 = manager.remember(
        "Ramón now works at Supermemory as the CMO.",
        citation="chat_2",
        relation_to=id1,
        relation_type="updates",
    )

    # Verify is_latest
    m1 = db["memories"].get(id1)
    m2 = db["memories"].get(id2)
    assert m1["is_latest"] == 0
    assert m2["is_latest"] == 1

    print("\n--- Testing Relationships (Extends) ---")
    id3 = manager.remember(
        "Ramón's CMO role includes marketing and SEO.",
        citation="chat_3",
        relation_to=id2,
        relation_type="extends",
    )

    print("\n--- Testing Recall (Filtering Latest) ---")
    results = manager.recall("CMO")
    print(f"Recall results for 'CMO': {len(results)}")

    contents = [r["content"] for r in results]
    assert "Ramón now works at Supermemory as the CMO." in contents

    results_old = manager.recall("content engineer")
    assert any(r["is_latest"] == 0 for r in results_old)
    print("Old memory correctly marked as not latest in recall results")

    print("\nAll relationship tests passed!")


if __name__ == "__main__":
    test_memory_relationships()

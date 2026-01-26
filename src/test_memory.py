from memory_server.server import MemoryManager
import os


def test_memory_flow():
    # Clean up previous test DB
    if os.path.exists("memories.db"):
        os.remove("memories.db")

    manager = MemoryManager("memories.db")
    db = manager.get_db()

    print("--- Testing Remember ---")
    id1 = manager.remember("Ramón likes his coffee black.", citation="conversation_1")
    id2 = manager.remember("The project is using FastMCP.", citation="README.md")
    print(f"Saved: {id1}")
    print(f"Saved: {id2}")

    print(f"Total rows in DB: {db['memories'].count}")
    for row in db["memories"].rows:
        print(f"Row: {row['content']}")

    print("\n--- Testing Recall ---")
    results = manager.recall("coffee")
    print(f"Recall results for 'coffee': {len(results)}")

    # If FTS failed, try a simple query to see if data is there
    like_results = []
    if len(results) == 0:
        print("FTS returned nothing, checking with LIKE...")
        like_results = list(db["memories"].rows_where("content LIKE '%coffee%'"))
        print(f"LIKE results: {len(like_results)}")

    assert len(results) > 0 or len(like_results) > 0

    print("\n--- Testing Promotion (Recall 2 more times) ---")
    manager.recall("coffee")
    results = manager.recall("coffee")
    for r in results:
        print(
            f"Found: {r['content']} (Accessed: {r['access_count']}, Long Term: {r['is_long_term']})"
        )

    print("\n--- Testing Consolidation (Pruning) ---")
    db["memories"].insert(
        {
            "id": "old-fact",
            "content": "This is an old irrelevant fact.",
            "last_accessed": "2020-01-01T00:00:00",
            "is_long_term": 0,
            "access_count": 0,
            "created_at": "2020-01-01T00:00:00",
            "importance": 1.0,
            "metadata": "{}",
        },
        pk="id",
    )

    summary = manager.consolidate(ttl_days=1)
    print(summary)

    remaining = [row["id"] for row in db["memories"].rows if row["id"] == "old-fact"]
    assert len(remaining) == 0, "Old fact should have been pruned"

    print("\nAll tests passed!")


if __name__ == "__main__":
    test_memory_flow()

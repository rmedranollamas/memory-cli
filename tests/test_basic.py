def test_remember_recall(manager):
    mid = manager.remember("Coffee is good", citation="kitchen")
    results = manager.recall("Coffee")
    assert len(results) == 1
    assert results[0]["content"] == "Coffee is good"

def test_promotion(manager):
    manager.remember("Important fact")
    manager.recall("Important")
    manager.recall("Important")
    results = manager.recall("Important")
    assert results[0]["access_count"] == 3
    assert results[0]["is_long_term"] == 1

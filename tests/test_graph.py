def test_updates_relation(manager):
    id1 = manager.remember("Role: Dev")
    id2 = manager.remember("Role: CMO", relation_to=id1, relation_type="updates")
    r1 = manager.recall("Dev")
    assert r1[0]["is_latest"] == 0
    r2 = manager.recall("CMO")
    assert r2[0]["is_latest"] == 1

def test_extends_relation(manager):
    id1 = manager.remember("Role: CMO")
    id2 = manager.remember("CMO handles SEO", relation_to=id1, relation_type="extends")
    results = manager.recall("CMO")
    contents = [r["content"] for r in results]
    assert "Role: CMO" in contents
    assert "CMO handles SEO" in contents

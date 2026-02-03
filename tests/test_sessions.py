def test_sessions(manager):
    s1, s2 = "s1", "s2"
    manager.remember("Task A: Install deps", session_id=s1)
    manager.remember("Task B: Configure server", session_id=s2)
    results = manager.recall("Task", session_id=s1)
    assert results[0]["content"] == "Task A: Install deps"
    results2 = manager.recall("Task", session_id=s2)
    assert results2[0]["content"] == "Task B: Configure server"


def test_summarization(manager):
    s = "session-sum"
    manager.remember("Fact 1", session_id=s)
    manager.remember("Fact 2", session_id=s)
    summary_id = manager.summarize_session(s, "Integrated summary")
    results = manager.recall("Integrated", session_id=s)
    assert results[0]["id"] == summary_id
    assert results[0]["type"] == "summary"
    links = list(
        manager.get_db().query("SELECT * FROM links WHERE source_id = ?", [summary_id])
    )
    assert len(links) == 2

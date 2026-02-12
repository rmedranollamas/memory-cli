import datetime
import json
import uuid
import re
import sqlite3
from typing import Optional, List, Dict, Any

try:
    import diskcache
    from diskcache import JSONDisk
    diskcache.Cache.disk = JSONDisk
except ImportError: pass

    import diskcache
    from diskcache import JSONDisk
    diskcache.Cache.disk = JSONDisk
except ImportError: pass

import datetime
import json
import uuid
import re
import sqlite3
from typing import Optional, List, Dict, Any

# Mitigation for DiskCache unsafe pickle deserialization (CVE-2023-45803)
try:
    import diskcache
    from diskcache import JSONDisk

    # Force diskcache to use JSON instead of Pickle for its internal caching if it happens to be used
    diskcache.Cache.disk = JSONDisk
except ImportError:
    pass

from fastmcp import FastMCP
import sqlite_utils

DB_PATH = "memories.db"


class MemoryManager:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        # Use a persistent connection for the instance to support :memory: properly
        self.db = sqlite_utils.Database(self.db_path)
        self._init_db()

    def _init_db(self):
        if "memories" not in self.db.table_names():
            self.db["memories"].create(
                {
                    "id": str,
                    "content": str,
                    "citation": str,
                    "metadata": str,  # JSON string
                    "type": str,  # fact, reasoning, summary
                    "session_id": str,
                    "access_count": int,
                    "last_accessed": str,
                    "importance": float,
                    "is_long_term": int,  # 0 or 1
                    "is_latest": int,  # 0 or 1
                    "created_at": str,
                },
                pk="id",
            )
            self.db["memories"].enable_fts(["content", "citation"], tokenize="porter")
        else:
            # Migration for existing DBs
            cols = self.db["memories"].columns_dict
            if "session_id" not in cols:
                self.db["memories"].add_column("session_id", str)
            if "type" not in cols:
                self.db["memories"].add_column("type", str)

        if "links" not in self.db.table_names():
            self.db["links"].create(
                {
                    "source_id": str,
                    "target_id": str,
                    "relation_type": str,  # updates, extends, derives, reasons
                    "created_at": str,
                },
                foreign_keys=[
                    ("source_id", "memories", "id"),
                    ("target_id", "memories", "id"),
                ],
            )
        return self.db

    def get_db(self):
        return self.db

    def remember(
        self,
        fact: str,
        citation: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        importance: float = 1.0,
        relation_to: Optional[str] = None,
        relation_type: Optional[str] = None,  # updates, extends, derives, reasons
        session_id: Optional[str] = None,
        memory_type: str = "fact",
    ) -> str:
        db = self.get_db()
        memory_id = str(uuid.uuid4())
        now = datetime.datetime.now().isoformat()

        # Auto-promote if importance is high
        is_long_term = 1 if importance >= 5.0 else 0

        db["memories"].insert(
            {
                "id": memory_id,
                "content": fact,
                "citation": citation,
                "metadata": json.dumps(metadata or {}),
                "type": memory_type,
                "session_id": session_id,
                "access_count": 0,
                "last_accessed": now,
                "importance": importance,
                "is_long_term": is_long_term,
                "is_latest": 1,
                "created_at": now,
            }
        )

        if relation_to and relation_type:
            db["links"].insert(
                {
                    "source_id": memory_id,
                    "target_id": relation_to,
                    "relation_type": relation_type,
                    "created_at": now,
                }
            )

            # If it's an update, the old one is no longer latest
            if relation_type == "updates":
                db["memories"].update(relation_to, {"is_latest": 0})

        return memory_id

    def recall(
        self, query: str, session_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        db = self.get_db()
        now = datetime.datetime.now().isoformat()

        # Clean query: remove non-alphanumeric for FTS/LIKE
        clean_query = re.sub(r"[^\w\s]", " ", query).strip()

        results = []
        # 1. Try FTS search
        try:
            results = list(db["memories"].search(clean_query, limit=20))
        except (sqlite3.OperationalError, AssertionError):
            results = []

        # 2. Fallback to LIKE
        if not results:
            like_query = f"%{clean_query.replace(' ', '%')}%"
            # Try latest first
            results = list(
                db["memories"].rows_where(
                    "(content LIKE ? OR citation LIKE ?) AND is_latest = 1",
                    [like_query, like_query],
                    limit=20,
                )
            )
            if not results:
                # Try all
                results = list(
                    db["memories"].rows_where(
                        "content LIKE ? OR citation LIKE ?",
                        [like_query, like_query],
                        limit=20,
                    )
                )

        # De-duplicate
        unique_results = []
        seen_ids = set()
        for row in results:
            mid = row.get("id")
            if mid and mid not in seen_ids:
                seen_ids.add(mid)
                unique_results.append(row)

        # Sort: session_id match > latest > importance
        def sort_key(x):
            score = 0
            if session_id and x.get("session_id") == session_id:
                score += 10
            if x.get("is_latest"):
                score += 5
            # Importance can range 1-10, so it now has comparable weight to is_latest
            score += x.get("importance", 1.0)
            return score

        sorted_results = sorted(unique_results, key=sort_key, reverse=True)

        final_results = []
        for row in sorted_results[:5]:
            mid = row["id"]
            new_count = row.get("access_count", 0) + 1
            is_long_term = 1 if new_count >= 3 else row.get("is_long_term", 0)

            db["memories"].update(
                mid,
                {
                    "access_count": new_count,
                    "last_accessed": now,
                    "is_long_term": is_long_term,
                },
            )

            row["access_count"] = new_count
            row["is_long_term"] = is_long_term
            row["last_accessed"] = now

            if row.get("metadata") and isinstance(row["metadata"], str):
                try:
                    row["metadata"] = json.loads(row["metadata"])
                except Exception:
                    pass

            row["links"] = list(
                db.query(
                    "SELECT target_id, relation_type FROM links WHERE source_id = ?",
                    [mid],
                )
            )

            final_results.append(row)
        return final_results

    def summarize_session(self, session_id: str, summary_content: str) -> str:
        now = datetime.datetime.now().isoformat()
        mid = self.remember(
            summary_content,
            session_id=session_id,
            memory_type="summary",
            importance=5.0,
        )
        mems = list(
            self.db["memories"].rows_where(
                "session_id = ? AND type != 'summary'", [session_id]
            )
        )
        for m in mems:
            self.db["links"].insert(
                {
                    "source_id": mid,
                    "target_id": m["id"],
                    "relation_type": "derives",
                    "created_at": now,
                }
            )
        return mid

    def consolidate(self, ttl_days: int = 7) -> str:
        db = self.get_db()
        now = datetime.datetime.now()
        cutoff = (now - datetime.timedelta(days=ttl_days)).isoformat()

        stale_ids = [
            row["id"]
            for row in db.query(
                "SELECT id FROM memories WHERE is_long_term = 0 AND (last_accessed < ? OR is_latest = 0) AND created_at < ?",
                [cutoff, cutoff],
            )
        ]

        if stale_ids:
            placeholders = ",".join(["?" for _ in stale_ids])
            db.execute(
                f"DELETE FROM links WHERE source_id IN ({placeholders}) OR target_id IN ({placeholders})",
                stale_ids + stale_ids,
            )
            db.execute(f"DELETE FROM memories WHERE id IN ({placeholders})", stale_ids)

        return f"Consolidation complete. Pruned {len(stale_ids)} stale memories."


mcp = FastMCP("MemorySystem")
manager = MemoryManager()


@mcp.tool()
def remember(
    fact: str,
    citation: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    importance: float = 1.0,
    relation_to: Optional[str] = None,
    relation_type: Optional[str] = None,
    session_id: Optional[str] = None,
    memory_type: str = "fact",
) -> str:
    """Saves a new fact to memory."""
    mid = manager.remember(
        fact,
        citation,
        metadata,
        importance,
        relation_to,
        relation_type,
        session_id,
        memory_type,
    )
    return f"Memory saved with ID: {mid}"


@mcp.tool()
def recall(query: str, session_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Recalls relevant memories, optionally biasing by session_id."""
    return manager.recall(query, session_id)


@mcp.tool()
def summarize_session(session_id: str, summary_content: str) -> str:
    """Summarizes all facts in a session into a single 'summary' memory."""
    mid = manager.summarize_session(session_id, summary_content)
    return f"Summary saved with ID: {mid}"


@mcp.tool()
def consolidate_memories(ttl_days: int = 7) -> str:
    """Performs maintenance: prunes old short-term memories."""
    return manager.consolidate(ttl_days)


@mcp.tool()
def list_relationships(memory_id: str) -> List[Dict[str, Any]]:
    """Lists all relationships for a given memory."""
    return list(
        manager.get_db().query(
            "SELECT * FROM links WHERE source_id = ? OR target_id = ?",
            [memory_id, memory_id],
        )
    )


if __name__ == "__main__":
    mcp.run()

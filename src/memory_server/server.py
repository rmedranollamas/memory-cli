import datetime
import json
import uuid
from typing import Optional, List, Dict, Any
from fastmcp import FastMCP
import sqlite_utils

DB_PATH = "memories.db"


class MemoryManager:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        db = sqlite_utils.Database(self.db_path)
        if "memories" not in db.table_names():
            db["memories"].create(
                {
                    "id": str,
                    "content": str,
                    "citation": str,
                    "metadata": str,  # JSON string
                    "access_count": int,
                    "last_accessed": str,
                    "importance": float,
                    "is_long_term": int,  # 0 or 1
                    "created_at": str,
                },
                pk="id",
            )
            db["memories"].enable_fts(["content", "citation"], tokenize="porter")
        return db

    def get_db(self):
        return sqlite_utils.Database(self.db_path)

    def remember(
        self,
        fact: str,
        citation: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        importance: float = 1.0,
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
                "access_count": 0,
                "last_accessed": now,
                "importance": importance,
                "is_long_term": is_long_term,
                "created_at": now,
            }
        )
        return memory_id

    def recall(self, query: str) -> List[Dict[str, Any]]:
        db = self.get_db()
        now = datetime.datetime.now().isoformat()

        # 1. Try FTS search
        try:
            results = list(db["memories"].search(query, limit=5))
        except Exception:
            results = []

        # 2. Fallback to LIKE if FTS is empty or fails
        if not results:
            like_query = f"%{query}%"
            results = list(
                db["memories"].rows_where(
                    "content LIKE ? OR citation LIKE ?",
                    [like_query, like_query],
                    limit=5,
                )
            )

        updated_results = []
        for row in results:
            mid = row.get("id")
            if not mid:
                continue

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
            updated_results.append(row)
        return updated_results

    def consolidate(self, ttl_days: int = 7) -> str:
        db = self.get_db()
        now = datetime.datetime.now()
        cutoff = (now - datetime.timedelta(days=ttl_days)).isoformat()

        stale_ids = [
            row["id"]
            for row in db.query(
                "SELECT id FROM memories WHERE is_long_term = 0 AND last_accessed < ?",
                [cutoff],
            )
        ]

        for mid in stale_ids:
            db["memories"].delete(mid)

        return f"Consolidation complete. Pruned {len(stale_ids)} stale memories."


# Initialize MCP
mcp = FastMCP("MemorySystem")
manager = MemoryManager()


@mcp.tool()
def remember(
    fact: str,
    citation: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    importance: float = 1.0,
) -> str:
    """Saves a new fact or observation to memory."""
    memory_id = manager.remember(fact, citation, metadata, importance)
    return f"Memory saved with ID: {memory_id}"


@mcp.tool()
def recall(query: str) -> List[Dict[str, Any]]:
    """Recalls relevant memories based on a search query."""
    return manager.recall(query)


@mcp.tool()
def consolidate_memories(ttl_days: int = 7) -> str:
    """Performs maintenance on the memory system."""
    return manager.consolidate(ttl_days)


if __name__ == "__main__":
    mcp.run()

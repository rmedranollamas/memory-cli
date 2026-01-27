import datetime
import json
import uuid
import re
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
                    "is_latest": int,  # 0 or 1
                    "created_at": str,
                },
                pk="id",
            )
            db["memories"].enable_fts(["content", "citation"], tokenize="porter")

        if "links" not in db.table_names():
            db["links"].create(
                {
                    "source_id": str,
                    "target_id": str,
                    "relation_type": str,  # updates, extends, derives
                    "created_at": str,
                },
                foreign_keys=[
                    ("source_id", "memories", "id"),
                    ("target_id", "memories", "id"),
                ],
            )
        return db

    def get_db(self):
        return sqlite_utils.Database(self.db_path)

    def remember(
        self,
        fact: str,
        citation: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        importance: float = 1.0,
        relation_to: Optional[str] = None,
        relation_type: Optional[str] = None,  # updates, extends, derives
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

    def recall(self, query: str) -> List[Dict[str, Any]]:
        db = self.get_db()
        now = datetime.datetime.now().isoformat()

        # Clean query: remove non-alphanumeric for FTS/LIKE
        clean_query = re.sub(r"[^\w\s]", " ", query).strip()

        results = []
        # 1. Try FTS search
        try:
            results = list(db["memories"].search(clean_query, limit=10))
        except Exception:
            results = []

        # 2. Fallback to LIKE if FTS is empty
        if not results:
            like_query = f"%{clean_query.replace(' ', '%')}%"
            results = list(
                db["memories"].rows_where(
                    "content LIKE ? OR citation LIKE ?",
                    [like_query, like_query],
                    limit=10,
                )
            )

        # 3. Final fallback: search by individual words
        if not results and " " in clean_query:
            words = [w for w in clean_query.split() if len(w) > 2]
            if words:
                where_clause = " OR ".join(["content LIKE ?" for _ in words])
                params = [f"%{w}%" for w in words]
                results = list(
                    db["memories"].rows_where(where_clause, params, limit=10)
                )

        # Filter and Update
        updated_results = []
        # Sort by latest and importance
        results = sorted(
            results,
            key=lambda x: (x.get("is_latest", 1), x.get("importance", 1)),
            reverse=True,
        )

        seen_ids = set()
        for row in results[:5]:
            mid = row.get("id")
            if not mid or mid in seen_ids:
                continue
            seen_ids.add(mid)

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

            # Fetch related memories
            row["links"] = list(
                db.query(
                    "SELECT target_id, relation_type FROM links WHERE source_id = ?",
                    [mid],
                )
            )

            updated_results.append(row)
        return updated_results

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

        for mid in stale_ids:
            db.execute(
                "DELETE FROM links WHERE source_id = ? OR target_id = ?", [mid, mid]
            )
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
    relation_to: Optional[str] = None,
    relation_type: Optional[str] = None,
) -> str:
    """
    Saves a new fact or observation to memory.
    - relation_to: ID of an existing memory this relates to.
    - relation_type: 'updates', 'extends', or 'derives'.
    """
    memory_id = manager.remember(
        fact, citation, metadata, importance, relation_to, relation_type
    )
    return f"Memory saved with ID: {memory_id}"


@mcp.tool()
def recall(query: str) -> List[Dict[str, Any]]:
    """Recalls relevant memories based on a search query."""
    return manager.recall(query)


@mcp.tool()
def consolidate_memories(ttl_days: int = 7) -> str:
    """Performs maintenance on the memory system."""
    return manager.consolidate(ttl_days)


@mcp.tool()
def list_relationships(memory_id: str) -> List[Dict[str, Any]]:
    """
    Lists all relationships (links) for a given memory ID.
    """
    db = manager.get_db()
    # Find links where this memory is either source or target
    links = list(
        db.query(
            "SELECT * FROM links WHERE source_id = ? OR target_id = ?",
            [memory_id, memory_id],
        )
    )
    return links


if __name__ == "__main__":
    mcp.run()

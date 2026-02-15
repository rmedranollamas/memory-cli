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
    # Force diskcache to use JSON instead of Pickle if it's used by dependencies
    diskcache.Cache.disk = JSONDisk
except (ImportError, AttributeError):
    pass

from fastmcp import FastMCP
import sqlite_utils

DB_PATH = "memories.db"

class MemoryManager:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.db = sqlite_utils.Database(self.db_path)
        self._init_db()

    def _init_db(self):
        if "memories" not in self.db.table_names():
            self.db["memories"].create({
                "id": str, "content": str, "citation": str, "metadata": str,
                "type": str, "session_id": str, "access_count": int,
                "last_accessed": str, "importance": float, "is_long_term": int,
                "is_latest": int, "created_at": str
            }, pk="id")
            self.db["memories"].enable_fts(["content", "citation"], tokenize="porter")
        else:
            cols = self.db["memories"].columns_dict
            if "session_id" not in cols: self.db["memories"].add_column("session_id", str)
            if "type" not in cols: self.db["memories"].add_column("type", str)

        if "links" not in self.db.table_names():
            self.db["links"].create({
                "source_id": str, "target_id": str, "relation_type": str, "created_at": str
            }, foreign_keys=[("source_id", "memories", "id"), ("target_id", "memories", "id")])
        return self.db

    def get_db(self): return self.db

    def remember(self, fact, citation=None, metadata=None, importance=1.0, relation_to=None, relation_type=None, session_id=None, memory_type="fact"):
        mid = str(uuid.uuid4())
        now = datetime.datetime.now().isoformat()
        self.db["memories"].insert({
            "id": mid, "content": fact, "citation": citation, "metadata": json.dumps(metadata or {}),
            "type": memory_type, "session_id": session_id, "access_count": 0, "last_accessed": now,
            "importance": importance, "is_long_term": (1 if importance >= 5.0 else 0), "is_latest": 1, "created_at": now
        })
        if relation_to and relation_type:
            self.db["links"].insert({"source_id": mid, "target_id": relation_to, "relation_type": relation_type, "created_at": now})
            if relation_type == "updates": self.db["memories"].update(relation_to, {"is_latest": 0})
        return mid

    def recall(self, query, session_id=None):
        now = datetime.datetime.now().isoformat()
        clean = re.sub(r"[^\w\s]", " ", query).strip()
        try: res = list(self.db["memories"].search(clean, limit=20))
        except: res = []
        if not res:
            lq = f"%{clean.replace(' ', '%')}%"
            res = list(self.db["memories"].rows_where("(content LIKE ? OR citation LIKE ?) AND is_latest = 1", [lq, lq], limit=20))
            if not res: res = list(self.db["memories"].rows_where("content LIKE ? OR citation LIKE ?", [lq, lq], limit=20))
        
        def sort_key(x):
            s = 0
            if session_id and x.get("session_id") == session_id: s += 10
            if x.get("is_latest"): s += 5
            return s + (x.get("importance", 1) / 1.0)

        final = []
        for r in sorted(res, key=sort_key, reverse=True)[:5]:
            mid = r["id"]
            cnt = r.get("access_count", 0) + 1
            self.db["memories"].update(mid, {"access_count": cnt, "last_accessed": now, "is_long_term": (1 if cnt >= 3 else r.get("is_long_term", 0))})
            r.update({"access_count": cnt, "last_accessed": now, "is_long_term": (1 if cnt >= 3 else r.get("is_long_term", 0)), "links": list(self.db.query("SELECT target_id, relation_type FROM links WHERE source_id = ?", [mid]))})
            if isinstance(r.get("metadata"), str): r["metadata"] = json.loads(r["metadata"])
            final.append(r)
        return final

    def summarize_session(self, session_id, summary_content):
        now = datetime.datetime.now().isoformat()
        mid = self.remember(summary_content, session_id=session_id, memory_type="summary", importance=5.0)
        mems = list(self.db["memories"].rows_where("session_id = ? AND type != 'summary'", [session_id]))
        for m in mems:
            self.db["links"].insert({"source_id": mid, "target_id": m["id"], "relation_type": "derives", "created_at": now})
        return mid

    def consolidate(self, ttl=7):
        cutoff = (datetime.datetime.now() - datetime.timedelta(days=ttl)).isoformat()
        stale = [r["id"] for r in self.db.query("SELECT id FROM memories WHERE is_long_term = 0 AND (last_accessed < ? OR is_latest = 0) AND created_at < ?", [cutoff, cutoff])]
        if stale:
            ph = ",".join(["?" for _ in stale])
            self.db.execute(f"DELETE FROM links WHERE source_id IN ({ph}) OR target_id IN ({ph})", stale + stale)
            self.db.execute(f"DELETE FROM memories WHERE id IN ({ph})", stale)
        return f"Pruned {len(stale)}"

mcp = FastMCP("MemorySystem")
man = MemoryManager()

@mcp.tool()
def remember(fact, citation=None, metadata=None, importance=1.0, relation_to=None, relation_type=None, session_id=None, memory_type="fact"): 
    mid = man.remember(fact, citation, metadata, importance, relation_to, relation_type, session_id, memory_type)
    return f"Memory saved with ID: {mid}"

@mcp.tool()
def recall(query, session_id=None): return man.recall(query, session_id)

@mcp.tool()
def summarize_session(session_id, summary_content): return f"Summary saved with ID: {man.summarize_session(session_id, summary_content)}"

@mcp.tool()
def consolidate_memories(ttl_days=7): return man.consolidate(ttl_days)

@mcp.tool()
def list_relationships(memory_id): return list(man.get_db().query("SELECT * FROM links WHERE source_id = ? OR target_id = ?", [memory_id, memory_id]))

if __name__ == "__main__": mcp.run()

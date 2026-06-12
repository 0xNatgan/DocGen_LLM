import json
import sqlite3
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any
from src.logging.logging import get_logger

logger = get_logger(__name__)

_SQL_DIR = Path(__file__).parent


class DatabaseCall:
    """SQLite database interface for DocGen_LLM.

    Supports use as a context manager::

        with DatabaseCall(db_path="project.db") as db:
            db.init_db()
            ...
    """

    db_path: str
    conn: sqlite3.Connection
    cur: sqlite3.Cursor

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row  # allows dict-like access
        self.cur = self.conn.cursor()
        logger.debug(f"Connected to database at {db_path}")

    # ── Context manager ───────────────────────────────────────────────────────

    def __enter__(self) -> "DatabaseCall":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
        return False  # do not suppress exceptions

    # ── Schema initialisation ─────────────────────────────────────────────────

    def init_db(self):
        """Create tables and views by running the bundled SQL scripts."""
        for script_name in ("db_creation.sql", "functions.sql"):
            script_path = _SQL_DIR / script_name
            with open(script_path, "r", encoding="utf-8") as f:
                sql_script = f.read()
            self.cur.executescript(sql_script)
            self.conn.commit()
        logger.info("Database initialized.")

    # ── Symbol queries ────────────────────────────────────────────────────────

    def get_number_of_symbols_with_no_documentation(self) -> int:
        query = "SELECT COUNT(*) FROM SymbolModel WHERE COALESCE(documented, 0) = 0"
        self.cur.execute(query)
        result = self.cur.fetchone()
        return result[0] if result else 0

    def get_next_symbol_to_document(self) -> Optional[Dict[str, Any]]:
        """Return the next symbol to document as ``{'symbol_id': int, 'calls': int}`` or None.

        Symbols with fewer outgoing calls are documented first so that their
        summaries are available as context when their callers are documented.
        """
        # Try the pre-built view first (fast path)
        try:
            self.cur.execute("SELECT symbol_id FROM view_next_symbol_to_document LIMIT 1")
            row = self.cur.fetchone()
            if row:
                symbol_id = row[0]
                # Fetch the call count separately
                self.cur.execute(
                    "SELECT COUNT(sr.caller_id) FROM SymbolRelationship sr WHERE sr.caller_id = ?",
                    (symbol_id,),
                )
                call_row = self.cur.fetchone()
                calls = call_row[0] if call_row else 0
                return {"symbol_id": symbol_id, "calls": calls}
        except Exception:
            pass  # view may not exist yet; fall through to inline query

        # Fallback inline query
        query = """
        SELECT s.id AS symbol_id, COUNT(sr.caller_id) AS calls
        FROM SymbolModel s
        LEFT JOIN SymbolRelationship sr ON sr.caller_id = s.id
        WHERE COALESCE(s.documented, 0) = 0
        GROUP BY s.id
        ORDER BY calls ASC, s.id ASC
        LIMIT 1
        """
        self.cur.execute(query)
        row = self.cur.fetchone()
        if not row:
            return None
        return {"symbol_id": row[0], "calls": row[1]}

    def get_all_info_on_symbol(self, symbol_id: int) -> Optional[Dict[str, Any]]:
        """Return all fields from the ``all_info_on_symbol`` view for the given symbol id.

        JSON columns (documentation, selection_range, range, called_symbols_json) are
        automatically parsed into Python objects.
        """
        query = "SELECT * FROM all_info_on_symbol WHERE id = ?"
        self.cur.execute(query, (symbol_id,))
        row = self.cur.fetchone()
        if not row:
            return None
        data = dict(row)

        # Parse JSON columns
        for field in ("documentation", "selection_range", "range", "called_symbols_json"):
            if field in data and data[field]:
                try:
                    data[field] = json.loads(data[field])
                except Exception:
                    pass  # leave raw string if parsing fails

        return data

    def add_summary_to_symbol(self, symbol_id: int, summary: str) -> None:
        query = "UPDATE SymbolModel SET summary = ? WHERE id = ?"
        self.cur.execute(query, (summary, symbol_id))
        self.conn.commit()

    def add_documentation_to_symbol(self, symbol_id: int, documentation: dict) -> None:
        documentation_str = json.dumps(documentation)
        tags_str = json.dumps(documentation.get("tags", []))
        query = "UPDATE SymbolModel SET documentation = ?, documented = TRUE, tags = ? WHERE id = ?"
        self.cur.execute(query, (documentation_str, tags_str, symbol_id))
        self.conn.commit()

    def get_documentation_for_symbol(self, symbol_id: int) -> Optional[dict]:
        """Return the stored JSON documentation for a symbol, or None."""
        query = "SELECT documentation FROM SymbolModel WHERE id = ?"
        res = self.cur.execute(query, (symbol_id,)).fetchone()
        if res and res[0]:
            return json.loads(res[0])
        return None

    def get_documented_symbols(self) -> List[dict]:
        """Return all symbols that have been documented."""
        query = "SELECT id, name, documentation FROM SymbolModel WHERE documented = TRUE AND documentation IS NOT NULL"
        results = self.cur.execute(query).fetchall()
        return [{"id": r[0], "name": r[1], "documentation": json.loads(r[2])} for r in results]

    def get_symbol_summary(self, symbol_id: int) -> Dict[str, Any]:
        """Return a dict with ``name``, ``kind``, and ``summary`` for a symbol."""
        query = "SELECT name, kind, summary FROM SymbolModel WHERE id = ?"
        self.cur.execute(query, (symbol_id,))
        row = self.cur.fetchone()
        if not row:
            return {"name": "", "kind": "", "summary": ""}
        return {"name": row[0], "kind": row[1], "summary": row[2] or ""}

    def get_symbols_infos(self) -> List[Tuple[int, str, str, str]]:
        query = "SELECT id, name, kind, summary FROM SymbolModel"
        self.cur.execute(query)
        return self.cur.fetchall()

    # ── File queries ──────────────────────────────────────────────────────────

    def add_file_documentation(self, file_id: int, documentation: str) -> None:
        query = "UPDATE FileModel SET documentation = ?, documented = TRUE WHERE id = ?"
        self.cur.execute(query, (documentation, file_id))
        self.conn.commit()

    def get_undocumented_files(self) -> List[sqlite3.Row]:
        """Return files where every symbol has been documented.

        These are ready for file-level summary generation.
        """
        query = """
        SELECT DISTINCT f.id, f.path
        FROM FileModel f
        WHERE COALESCE(f.documented, 0) = 0
          AND EXISTS (
              SELECT 1 FROM SymbolModel s WHERE s.file_id = f.id
          )
          AND NOT EXISTS (
              SELECT 1 FROM SymbolModel s
              WHERE s.file_id = f.id AND COALESCE(s.documented, 0) = 0
          )
        """
        self.cur.execute(query)
        return self.cur.fetchall()

    def get_symbols_in_file(self, file_id: int) -> List[int]:
        query = "SELECT id FROM SymbolModel WHERE file_id = ?"
        self.cur.execute(query, (file_id,))
        return [row[0] for row in self.cur.fetchall()]

    # ── Relationship queries ──────────────────────────────────────────────────

    def get_called_symbols(self, symbol_id: int) -> List[sqlite3.Row]:
        query = """
        SELECT sm.* FROM SymbolModel sm
        JOIN SymbolRelationship sr ON sm.id = sr.called_id
        WHERE sr.caller_id = ?
        """
        self.cur.execute(query, (symbol_id,))
        return self.cur.fetchall()

    def get_calling_symbols(self, symbol_id: int) -> List[sqlite3.Row]:
        query = """
        SELECT sm.* FROM SymbolModel sm
        JOIN SymbolRelationship sr ON sm.id = sr.caller_id
        WHERE sr.called_id = ?
        """
        self.cur.execute(query, (symbol_id,))
        return self.cur.fetchall()

    # ── Project / folder queries ──────────────────────────────────────────────

    def project_exists(self, project_name: str, project_path: str) -> Optional[int]:
        """Return the ProjectData id if a project with the same name and path already exists."""
        query = "SELECT id FROM ProjectData WHERE project_name = ? AND project_path = ?"
        self.cur.execute(query, (project_name, project_path))
        row = self.cur.fetchone()
        return row[0] if row else None

    def get_folders_from_root(self, root_folder_id: int) -> Optional[sqlite3.Row]:
        query = "SELECT * FROM FolderModel WHERE id = ?"
        self.cur.execute(query, (root_folder_id,))
        return self.cur.fetchone()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def close(self) -> None:
        """Close the database connection."""
        if self.conn:
            self.conn.close()
            logger.debug(f"Closed database connection to {self.db_path}")

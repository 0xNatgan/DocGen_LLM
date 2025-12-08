import json
import sqlite3
from typing import List, Tuple, Optional, Dict, Any
from src.extraction import models
from src.extraction.models import SymbolModel
import logging
from src.logging.logging import get_logger

# Configure logging
logging.basicConfig(level=logging.INFO) 
logger = get_logger(__name__)

class DatabaseCall:
    db_path: str
    conn: sqlite3.Connection
    cur: sqlite3.Cursor

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path)
        self.cur = self.conn.cursor()
        logger.debug(f"Connected to database at {db_path}")

    def init_db(self):
        #execute db_creation.sql script to create tables
        with open('src/storage/db_creation.sql', 'r') as f:
            sql_script = f.read()
            self.cur.executescript(sql_script)
            self.conn.commit()
        with open('src/storage/functions.sql', 'r') as f:
            sql_script = f.read()
            self.cur.executescript(sql_script)
            self.conn.commit()
        logger.info("Database initialized.")


    def make_model_from_db(self, id: int) -> List[Tuple]:
        query = "SELECT * FROM SymbolModel WHERE id = ?"
        self.cur.execute(query, (id,))
        results = self.cur.fetchall()
        return [models.SymbolModel(*row) for row in results]

    def get_number_of_symbols_with_no_documentation(self) -> int:
        query = "SELECT COUNT(*) FROM SymbolModel WHERE documented = 0"
        self.cur.execute(query)
        results = self.cur.fetchall()
        return results[0][0] if results else 0
    
    def get_next_symbol_to_document(self) -> Optional[dict]:
        """
        Return the next symbol to document as a dict {'symbol_id': int, 'calls': int} or None.
        Tries view_next_symbol_to_document first, otherwise falls back to inline SQL.
        """
        # Try the view first
        try:
            self.cur.execute("SELECT symbol_id, calls FROM view_next_symbol_to_document LIMIT 1")
            row = self.cur.fetchone()
            if row:
                return row[0]
        except Exception:
            # view may not exist or SQL error; fallback
            pass

        # Fallback inline query (same logic as view_undocumented_symbol_call_counts, then pick lowest)
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
        return row[0]
    
    def add_summary_to_symbol(self, symbol_id: int, summary: str) -> None:
        query = "UPDATE SymbolModel SET summary = ? WHERE id = ?"
        self.cur.execute(query, (summary, symbol_id))
        self.conn.commit()

    def add_documentation_to_symbol(self, symbol_id: int, documentation: dict) -> None:
        query = "UPDATE SymbolModel SET documentation = ?, documented = 1 WHERE id = ?"
        self.cur.execute(query, (json.dumps(documentation), symbol_id))
        self.conn.commit()

    def get_symbols_infos(self) -> List[Tuple[int, str, str, str]]:
        query = "SELECT id, name, kind, summary FROM SymbolModel"
        self.cur.execute(query)
        results = self.cur.fetchall()
        return results

    def get_called_symbols(self, symbol_id: int) -> List[SymbolModel]:
        query = """
        SELECT sm.* FROM SymbolModel sm
        JOIN SymbolCall sc ON sm.id = sc.called_symbol_id
        WHERE sc.caller_symbol_id = ?
        """
        self.cur.execute(query, (symbol_id,))
        results = self.cur.fetchall()
        return [SymbolModel(*row) for row in results]

    def get_calling_symbols(self, symbol_id: int) -> List[SymbolModel]:
        query = """
        SELECT sm.* FROM SymbolModel sm
        JOIN SymbolCall sc ON sm.id = sc.caller_symbol_id
        WHERE sc.called_symbol_id = ?
        """
        self.cur.execute(query, (symbol_id,))
        results = self.cur.fetchall()
        return [SymbolModel(*row) for row in results]
    
        
    def get_documentation_for_symbol(self, symbol_id: int) -> dict:
        """
        Return the stored JSON documentation for a symbol, parsed as dict, or None.
        """
        query = "SELECT documentation FROM SymbolModel WHERE id = ?"
        self.cur.execute(query, (symbol_id,))
        row = self.cur.fetchone()
        if not row:
            return None
        try:
            return json.loads(row[0]) if row[0] else None
        except Exception:
            return None

    def get_all_info_on_symbol(self, symbol_id: int) -> Optional[Dict[str, Any]]:
        """
        Return a dict with all fields from the all_info_on_symbol view for the given symbol id.
        JSON/text columns (documentation, selection_range, range, called_symbols_json) are parsed.
        """
        query = "SELECT * FROM all_info_on_symbol WHERE id = ?"
        self.cur.execute(query, (symbol_id,))
        row = self.cur.fetchone()
        if not row:
            return None
        columns = [d[0] for d in self.cur.description]
        data = dict(zip(columns, row))

        # Fields that are JSON/text we want parsed
        json_fields = ("documentation", "selection_range", "range", "called_symbols_json")
        for f in json_fields:
            if f in data and data[f]:
                try:
                    data[f] = json.loads(data[f])
                except Exception:
                    # leave raw value if parsing fails
                    pass

        return data

    def close(self):
        self.conn.close()



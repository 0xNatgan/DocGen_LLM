import json
import sqlite3
from typing import Optional
from src.extraction.models import FolderModel, FileModel, SymbolModel
from pathlib import Path
from ..logging.logging import get_logger

logger = get_logger(__name__)


def from_obj_to_sql(project: FolderModel, db: Optional[str] = None) -> str:
    """
    Persist a FolderModel project into an SQLite database file.
    Returns the path to the created/used database file.
    """
    if not project or not getattr(project, "name", None):
        logger.error(f"Project empty or no name associated with {project}")
        raise ValueError("Project must have a name")

    db_path = db if db else f"{project.name}.db"
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    cur = conn.cursor()

    # caches to avoid duplicate inserts
    language_to_dbid = {}
    folder_to_dbid = {}
    file_to_dbid = {}
    symbol_to_dbid = {}

    def insert_language(lang_name: Optional[str]) -> Optional[int]:
        if not lang_name:
            return None
        if lang_name in language_to_dbid:
            return language_to_dbid[lang_name]
        cur.execute("SELECT id FROM Language WHERE name = ?", (lang_name,))
        row = cur.fetchone()
        if row:
            language_to_dbid[lang_name] = row[0]
            return row[0]
        cur.execute("INSERT INTO Language (name) VALUES (?)", (lang_name,))
        language_to_dbid[lang_name] = cur.lastrowid
        return cur.lastrowid

    def insert_folder(folder: FolderModel, parent_id: Optional[int] = None) -> int:
        key = id(folder)
        if key in folder_to_dbid:
            return folder_to_dbid[key]
        cur.execute("INSERT INTO FolderModel (name, path, parent_id) VALUES (?, ?, ?)",
                    (getattr(folder, "name", None), str(getattr(folder, "path", "")), parent_id))
        fid = cur.lastrowid
        folder_to_dbid[key] = fid
        # recurse subfolders
        for sub in getattr(folder, "subfolders", []) or []:
            insert_folder(sub, fid)
        # insert files
        for f in getattr(folder, "files", []) or []:
            insert_file(f, fid)
        return fid

    def insert_file(f: FileModel, folder_id: int) -> int:
        key = id(f)
        if key in file_to_dbid:
            return file_to_dbid[key]
        # language handling: could be object or string
        lang_obj = getattr(f, "language", None)
        lang_name = None
        if isinstance(lang_obj, str):
            lang_name = lang_obj
        elif getattr(lang_obj, "name", None):
            lang_name = lang_obj.name
        language_id = insert_language(lang_name)
        documented = int(bool(getattr(f, "documented", False)))
        documentation = getattr(f, "documentation", None)
        cur.execute(
            "INSERT INTO FileModel (path, documented, documentation, folder_id, language_id) VALUES (?, ?, ?, ?, ?)",
            (str(getattr(f, "path", "")), documented, documentation, folder_id, language_id)
        )
        fid = cur.lastrowid
        file_to_dbid[key] = fid
        for sym in getattr(f, "symbols", []) or []:
            insert_symbol(sym, fid, parent_id=None)
        return fid

    def insert_symbol(symbol: SymbolModel, file_id: int, parent_id: Optional[int] = None) -> int:
        key = id(symbol)
        if key in symbol_to_dbid:
            return symbol_to_dbid[key]
        documented = int(bool(getattr(symbol, "documented", False)))
        documentation = getattr(symbol, "documentation", None)
        docstring = getattr(symbol, "docstring", None)
        summary = getattr(symbol, "summary", None)
        sel_range = getattr(symbol, "selection_range", None)
        range = getattr(symbol, "range", None)
        sel_range = sel_range.to_json() if sel_range else None
        range = range.to_json() if range else None
        sel_range = json.dumps(sel_range) if sel_range else None
        range = json.dumps(range) if range else None
        cur.execute(
            "INSERT INTO SymbolModel (name, kind, detail, documentation, docstring, selection_range, range, documented, summary, file_id, parent_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                getattr(symbol, "name", None),
                getattr(symbol, "kind", None) or getattr(symbol, "symbol_kind", None),
                getattr(symbol, "detail", None),
                documentation,
                docstring,
                sel_range,
                range,
                documented,
                summary,
                file_id,
                parent_id
            )
        )
        sid = cur.lastrowid
        symbol_to_dbid[key] = sid
        # recurse children (support different attribute names)
        children = getattr(symbol, "children", None) or getattr(symbol, "childrens", None) or getattr(symbol, "nested_symbols", None) or []
        for c in children or []:
            insert_symbol(c, file_id, sid)
        return sid

    def insert_symbol_relationships():
        # After all symbols inserted, add relationships
        for f_obj in list(file_to_dbid.keys()):
            # get the file object by identity; we stored id keys so recover objects via mapping
            pass
        # Simpler approach: iterate over all inserted symbols in memory via symbol_to_dbid keys
        for sym_obj_id, sym_dbid in list(symbol_to_dbid.items()):
            # need original object; we stored key as id(obj) so can't retrieve object from id
            # Instead re-traverse project to find relationships
            break
        # We'll traverse folders/files/symbols again to find relationships using object identity mapping
        def traverse_and_insert(folder: FolderModel):
            for f in getattr(folder, "files", []) or []:
                for sym in getattr(f, "symbols", []) or []:
                    insert_relationships_for_symbol(sym)
            for sf in getattr(folder, "subfolders", []) or []:
                traverse_and_insert(sf)

        def insert_relationships_for_symbol(symbol: SymbolModel):
            caller_key = id(symbol)
            caller_id = symbol_to_dbid.get(caller_key)
            if not caller_id:
                return
            # called_symbols attribute names may vary
            called_list = getattr(symbol, "called_symbols", None) or getattr(symbol, "calls", None) or []
            for called in called_list or []:
                called_id = symbol_to_dbid.get(id(called))
                if called_id:
                    cur.execute("INSERT OR IGNORE INTO SymbolRelationship (caller_id, called_id) VALUES (?, ?)",
                                (caller_id, called_id))
            # also insert reverse calling_symbols if present
            calling_list = getattr(symbol, "calling_symbols", None) or getattr(symbol, "callers", None) or []
            for caller in calling_list or []:
                caller_of_id = symbol_to_dbid.get(id(caller))
                if caller_of_id:
                    cur.execute("INSERT OR IGNORE INTO SymbolRelationship (caller_id, called_id) VALUES (?, ?)",
                                (caller_of_id, caller_id))
            # recurse children
            for c in getattr(symbol, "children", []) or getattr(symbol, "childrens", []) or []:
                insert_relationships_for_symbol(c)

        traverse_and_insert(project)

    def insert_project_metadata(main_folder_id: int):
        cur.execute(
            "INSERT INTO ProjectData (scan_complete, scan_date, scan_hash, project_name, project_path, entry_point) VALUES (?, ?, ?, ?, ?, ?)",
            (0, None, None, getattr(project, "name", None), str(getattr(project, "path", "")), main_folder_id)
        )

    # Begin insertion
    # Insert languages from project if helper exists, else rely on insert_file to add languages
    try:
        main_folder_id = insert_folder(project, None)
        # ensure we inserted files/symbols; now insert relationships
        insert_symbol_relationships()
        insert_project_metadata(main_folder_id)
        conn.commit()
        logger.info(f"Project persisted to {db_path}")
    except Exception as e:
        conn.rollback()
        logger.error(f"Failed to persist project: {e}")
        raise
    finally:
        conn.close()

    return db_path




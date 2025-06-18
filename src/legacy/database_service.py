"""Database service for storing and retrieving project symbols."""

import sqlite3
import json
import logging
from pathlib import Path
from typing import List, Dict, Optional, Any
from contextlib import contextmanager

from ..extraction.models import ProjectModel, FileModel, SymbolModel

logger = logging.getLogger(__name__)


class DatabaseService:
    """Service for interacting with the SQLite database."""
    
    def __init__(self, db_path: str = None):
        """Initialize database service."""
        self.db_path = db_path or "genDoc_ai.db"
        self.init_schema()
    
    def init_schema(self):
        """Initialize database schema from SQL file."""
        schema_path = Path(__file__).parent / "init_db.sql"
        
        try:
            with open(schema_path, 'r', encoding='utf-8') as f:
                schema_sql = f.read()
            
            with self.get_connection() as conn:
                cursor = conn.cursor()
                # Execute each statement separately
                for statement in schema_sql.split(';'):
                    statement = statement.strip()
                    if statement:
                        cursor.execute(statement)
                conn.commit()
                
            logger.info(f"Database initialized: {self.db_path}")
            
        except Exception as e:
            logger.error(f"Error initializing database: {e}")
            raise
    
    @contextmanager
    def get_connection(self):
        """Get database connection with proper cleanup."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Enable dict-like access
        try:
            yield conn
        finally:
            conn.close()
    
    def save_project(self, project: ProjectModel) -> int:
        """Save project to database and return project ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Insert or update project
            cursor.execute("""
                INSERT OR REPLACE INTO projects (name, root_path, languages)
                VALUES (?, ?, ?)
            """, (
                project.name,
                project.root,
                json.dumps(project.langs)
            ))
            
            project_id = cursor.lastrowid
            conn.commit()
            
            logger.info(f"Saved project '{project.name}' with ID {project_id}")
            return project_id
    
    def save_files(self, project_id: int, files: List[FileModel], project_root: str) -> Dict[str, int]:
        """Save files to database and return mapping of file_path -> file_id."""
        file_id_map = {}
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            for file_model in files:
                try:
                    # Calculate relative path
                    relative_path = str(Path(file_model.path).relative_to(project_root))
                    
                    cursor.execute("""
                        INSERT OR REPLACE INTO files (project_id, relative_path, language)
                        VALUES (?, ?, ?)
                    """, (project_id, relative_path, file_model.language))
                    
                    file_id = cursor.lastrowid
                    file_id_map[file_model.path] = file_id
                    
                except Exception as e:
                    logger.warning(f"Error saving file {file_model.path}: {e}")
                    continue
            
            conn.commit()
            
        logger.info(f"Saved {len(file_id_map)} files to database")
        return file_id_map
    
    def save_symbols(self, symbols: List[SymbolModel], file_id_map: Dict[str, int]) -> Dict[tuple, int]:
        """Save symbols to database."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # First pass: save symbols without parent references
            symbol_id_map = {}  # (file_path, symbol_name, line_start) -> symbol_id
            
            for symbol in symbols:
                file_id = file_id_map.get(symbol.file_path)
                if not file_id:
                    logger.warning(f"No file ID found for {symbol.file_path}")
                    continue
                
                try:
                    cursor.execute("""
                        INSERT OR REPLACE INTO symbols 
                        (file_id, name, symbol_kind, line_start, line_end, source_code, existing_doc, lsp_signature)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        file_id,
                        symbol.name,
                        symbol.symbol_kind,
                        symbol.line_start,
                        symbol.line_end,
                        symbol.source_code,
                        symbol.existing_symbol_doc,
                        getattr(symbol, 'lsp_signature', None)
                    ))
                    
                    symbol_id = cursor.lastrowid
                    symbol_key = (symbol.file_path, symbol.name, symbol.line_start)
                    symbol_id_map[symbol_key] = symbol_id
                    
                except Exception as e:
                    logger.warning(f"Error saving symbol {symbol.name}: {e}")
                    continue
            
            # Second pass: update parent relationships
            for symbol in symbols:
                if symbol.parent_symbol:
                    symbol_key = (symbol.file_path, symbol.name, symbol.line_start)
                    parent_key = (symbol.parent_symbol.file_path, symbol.parent_symbol.name, symbol.parent_symbol.line_start)
                    
                    symbol_id = symbol_id_map.get(symbol_key)
                    parent_id = symbol_id_map.get(parent_key)
                    
                    if symbol_id and parent_id:
                        try:
                            cursor.execute("""
                                UPDATE symbols SET parent_symbol_id = ? WHERE id = ?
                            """, (parent_id, symbol_id))
                        except Exception as e:
                            logger.warning(f"Error updating parent relationship for {symbol.name}: {e}")
            
            conn.commit()
            
        logger.info(f"Saved {len(symbol_id_map)} symbols to database")
        return symbol_id_map
    
    def save_project_complete(self, project: ProjectModel) -> int:
        """Save complete project with all files and symbols."""
        try:
            # Save project
            project_id = self.save_project(project)
            
            # Save files
            file_id_map = self.save_files(project_id, project.files, project.root)
            
            # Collect all symbols
            all_symbols = []
            for file_model in project.files:
                all_symbols.extend(file_model.symbols)
            
            # Save symbols
            if all_symbols:
                self.save_symbols(all_symbols, file_id_map)
            
            logger.info(f"Complete project saved: {len(project.files)} files, {len(all_symbols)} symbols")
            return project_id
            
        except Exception as e:
            logger.error(f"Error saving complete project: {e}")
            raise
    
    def update_symbol_documentation(self, symbol_id: int, documentation_data: Dict[str, Any]):
        """Update generated documentation for a symbol."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            try:
                cursor.execute("""
                    UPDATE symbols SET 
                        generated_summary = ?,
                        generated_parameters = ?,
                        generated_returns = ?,
                        generated_examples = ?
                    WHERE id = ?
                """, (
                    documentation_data.get('summary'),
                    json.dumps(documentation_data.get('parameters', [])),
                    json.dumps(documentation_data.get('returns', {})),
                    json.dumps(documentation_data.get('examples', [])),
                    symbol_id
                ))
                
                conn.commit()
                logger.debug(f"Updated documentation for symbol ID {symbol_id}")
                
            except Exception as e:
                logger.error(f"Error updating documentation for symbol {symbol_id}: {e}")
                raise
    
    def get_symbols_without_documentation(self, project_id: int) -> List[Dict]:
        """Get symbols that don't have generated documentation yet."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT s.id, s.name, s.symbol_kind, s.source_code, s.existing_doc,
                       f.relative_path, f.language
                FROM symbols s
                JOIN files f ON s.file_id = f.id
                WHERE f.project_id = ? 
                  AND (s.generated_summary IS NULL OR s.generated_summary = '')
                  AND s.symbol_kind IN ('function', 'method', 'class', 'constructor')
                ORDER BY f.relative_path, s.line_start
            """, (project_id,))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_project_stats(self, project_id: int) -> Dict[str, Any]:
        """Get statistics for a project."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # File count
            cursor.execute("SELECT COUNT(*) FROM files WHERE project_id = ?", (project_id,))
            file_count = cursor.fetchone()[0]
            
            # Symbol counts by type
            cursor.execute("""
                SELECT s.symbol_kind, COUNT(*) as count
                FROM symbols s
                JOIN files f ON s.file_id = f.id
                WHERE f.project_id = ?
                GROUP BY s.symbol_kind
            """, (project_id,))
            
            symbol_counts = dict(cursor.fetchall())
            
            # Documentation status
            cursor.execute("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN generated_summary IS NOT NULL AND generated_summary != '' THEN 1 ELSE 0 END) as documented
                FROM symbols s
                JOIN files f ON s.file_id = f.id
                WHERE f.project_id = ? AND s.symbol_kind IN ('function', 'method', 'class', 'constructor')
            """, (project_id,))
            
            doc_stats = cursor.fetchone()
            
            return {
                'files': file_count,
                'symbol_counts': symbol_counts,
                'total_documentable': doc_stats[0] if doc_stats else 0,
                'documented': doc_stats[1] if doc_stats else 0,
                'documentation_progress': (doc_stats[1] / doc_stats[0] * 100) if doc_stats and doc_stats[0] > 0 else 0
            }
    
    def get_project_by_name(self, name: str) -> Optional[Dict]:
        """Get project by name."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT id, name, root_path, languages 
                FROM projects 
                WHERE name = ?
            """, (name,))
            
            result = cursor.fetchone()
            if result:
                return {
                    'id': result[0],
                    'name': result[1],
                    'root_path': result[2],
                    'languages': json.loads(result[3] or '[]')
                }
            return None
    
    def delete_project(self, project_id: int):
        """Delete a project and all its associated data."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            conn.commit()
            
            logger.info(f"Deleted project with ID {project_id}")
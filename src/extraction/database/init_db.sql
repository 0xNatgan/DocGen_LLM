-- Projects
CREATE TABLE projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(255) NOT NULL,
    root_path TEXT NOT NULL,
    languages TEXT,  -- JSON array: ["python", "javascript"]
    UNIQUE(name, root_path)
);

-- Files
CREATE TABLE files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    relative_path TEXT NOT NULL,  -- Chemin relatif au projet
    language VARCHAR(50) NOT NULL,
    
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    UNIQUE(project_id, relative_path)
);

-- Symbols (simplifié)
CREATE TABLE symbols (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    name VARCHAR(255) NOT NULL,
    symbol_kind VARCHAR(50) NOT NULL,  -- function, class, method, constructor, interface
    line_start INTEGER NOT NULL,
    line_end INTEGER,
    
    -- Hiérarchie des symboles
    parent_symbol_id INTEGER,
    
    -- Code source et documentation
    source_code TEXT,
    existing_doc TEXT,  -- Documentation existante extraite
    
    -- Documentation générée par LLM
    generated_summary TEXT,
    generated_parameters TEXT,  -- JSON: [{"name": "param1", "type": "str", "description": "..."}]
    generated_returns TEXT,     -- JSON: {"type": "int", "description": "..."}
    generated_examples TEXT,    -- JSON: ["example1", "example2"]
    
    -- Signature LSP (optionnel)
    lsp_signature TEXT,
    
    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE,
    FOREIGN KEY (parent_symbol_id) REFERENCES symbols(id) ON DELETE SET NULL,
    UNIQUE(file_id, name, symbol_kind, line_start, COALESCE(parent_symbol_id, 0))
);

-- Relations entre symboles (simplifié)
CREATE TABLE symbol_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_symbol_id INTEGER NOT NULL,
    target_symbol_id INTEGER NOT NULL,
    relationship_type VARCHAR(50) NOT NULL,  -- 'calls', 'inherits', 'implements', 'uses'
    
    FOREIGN KEY (source_symbol_id) REFERENCES symbols(id) ON DELETE CASCADE,
    FOREIGN KEY (target_symbol_id) REFERENCES symbols(id) ON DELETE CASCADE,
    UNIQUE(source_symbol_id, target_symbol_id, relationship_type),
    CHECK(source_symbol_id != target_symbol_id)
);
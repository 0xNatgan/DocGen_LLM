PRAGMA foreign_keys = ON;

CREATE TABLE Language (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE
);

CREATE TABLE FolderModel (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    path TEXT,
    parent_id INTEGER,  
    FOREIGN KEY(parent_id) REFERENCES FolderModel(id)
);

CREATE TABLE FileModel (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT, -- Relative Path to the project root
    documented BOOLEAN,
    documentation TEXT,
    folder_id INTEGER NOT NULL,
    language_id INTEGER NOT NULL,
    FOREIGN KEY(folder_id) REFERENCES FolderModel(id),
    FOREIGN KEY(language_id) REFERENCES Language(id)
);

CREATE TABLE SymbolModel (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    detail TEXT,
    documentation JSON,
    docstring TEXT,
    selection_range JSON,
    range JSON,
    documented BOOLEAN,
    summary TEXT,
    file_id INTEGER NOT NULL,
    parent_id INTEGER,
    FOREIGN KEY(file_id) REFERENCES FileModel(id),
    FOREIGN KEY(parent_id) REFERENCES SymbolModel(id)
);


CREATE TABLE SymbolRelationship (
    caller_id INTEGER NOT NULL,  
    called_id INTEGER NOT NULL,
    PRIMARY KEY (caller_id, called_id),
    FOREIGN KEY(caller_id) REFERENCES SymbolModel(id),
    FOREIGN KEY(called_id) REFERENCES SymbolModel(id)
);

CREATE TABLE ProjectData (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_complete BOOLEAN,
    scan_date DATE,
    scan_hash TEXT ,
    project_name TEXT NOT NULL,
    project_path TEXT NOT NULL,
    entry_point INTEGER,
    FOREIGN KEY(entry_point) REFERENCES FolderModel(id)
);

CREATE UNIQUE INDEX idx_unique_project ON ProjectData(project_name, project_path);


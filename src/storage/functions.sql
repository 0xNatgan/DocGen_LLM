-- Ensure indexes for fast aggregation

-- Index to get every relationship of the called_id symbol (by its id)
CREATE INDEX IF NOT EXISTS idx_rel_called ON SymbolRelationship(called_id);

-- Index to get every symbols a symbol uses (every symbols called by caller_id)
CREATE INDEX IF NOT EXISTS idx_rel_caller ON SymbolRelationship(caller_id);

-- Index to retrieve every symbols in a File
CREATE INDEX IF NOT EXISTS idx_symbol_file ON SymbolModel(file_id);

-- View: undocumented symbols with their external-call counts
DROP VIEW IF EXISTS view_undocumented_symbol_call_counts;
CREATE VIEW IF NOT EXISTS view_undocumented_symbol_call_counts AS
SELECT
    s.id AS symbol_id,
    COUNT(sr.caller_id) AS calls
FROM SymbolModel s
LEFT JOIN SymbolRelationship sr ON sr.caller_id = s.id
WHERE COALESCE(s.documented, 0) = 0
GROUP BY s.id;

-- Convenience view for caller -> callee pairs
DROP VIEW IF EXISTS view_caller_to_callees;
CREATE VIEW IF NOT EXISTS view_caller_to_callees AS
SELECT caller_id, called_id
FROM SymbolRelationship
WHERE caller_id IS NOT NULL AND called_id IS NOT NULL;

-- View to aggregate full info on a symbol (file, parent and called symbols json)
DROP VIEW IF EXISTS all_info_on_symbol;
CREATE VIEW IF NOT EXISTS all_info_on_symbol AS
SELECT
    s.id,
    s.name,
    s.kind,
    s.detail,
    s.documentation,
    s.docstring,
    s.selection_range,
    s.range,
    s.documented,
    s.summary,
    f.path       AS file_path,
    l.name       AS language_name,
    parent.name      AS parent_name,
    parent.kind      AS parent_kind,
    parent.docstring AS parent_docstring,
    parent.summary   AS parent_summary,
    COALESCE(
      (
        SELECT json_group_array(
          json_object(
            'id',    cs.id,
            'name',  cs.name,
            'docstring', cs.docstring,
            'summary',   cs.summary,
            'documentation', cs.documentation
          )
        )
        FROM SymbolRelationship sr2
        JOIN SymbolModel cs ON cs.id = sr2.called_id
        WHERE sr2.caller_id = s.id
      ),
      '[]'
    ) AS called_symbols_json
FROM SymbolModel s
LEFT JOIN FileModel f ON f.id = s.file_id
LEFT JOIN Language l ON l.id = f.language_id
LEFT JOIN SymbolModel parent ON parent.id = s.parent_id;

-- View: candidate(s) for next symbol to document (lowest external calls)
DROP VIEW IF EXISTS view_next_symbol_to_document;
CREATE VIEW IF NOT EXISTS view_next_symbol_to_document AS
SELECT u.symbol_id
FROM view_undocumented_symbol_call_counts u
WHERE u.calls = (
    SELECT MIN(calls) FROM view_undocumented_symbol_call_counts
);






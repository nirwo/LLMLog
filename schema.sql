CREATE TABLE IF NOT EXISTS log_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,  -- 'file' or 'url'
    name TEXT NOT NULL,    -- filename or url
    error_count INTEGER NOT NULL,
    warning_count INTEGER NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    summary TEXT          -- JSON string of analysis summary
);

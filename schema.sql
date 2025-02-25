CREATE TABLE IF NOT EXISTS log_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,  -- 'file' or 'url'
    name TEXT NOT NULL,    -- filename or url
    error_count INTEGER NOT NULL,
    warning_count INTEGER NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    summary TEXT          -- JSON string of analysis summary
);

-- Table to store log files with analysis results
CREATE TABLE IF NOT EXISTS log_files (
    log_id TEXT PRIMARY KEY,
    file_name TEXT NOT NULL,
    source_type TEXT NOT NULL,  -- 'file' or 'url'
    upload_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    error_count INTEGER NOT NULL,
    warning_count INTEGER NOT NULL,
    content TEXT NOT NULL      -- JSON string of log lines
);

-- Table to store error lines for each log file
CREATE TABLE IF NOT EXISTS log_errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    log_id TEXT NOT NULL,
    line_number INTEGER NOT NULL,
    level TEXT NOT NULL,  -- 'Error', 'Warning', 'Info'
    FOREIGN KEY (log_id) REFERENCES log_files (log_id)
);

-- Table to store the full log files for training purposes
CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id TEXT UNIQUE NOT NULL,  -- UUID of the log file
    log_content TEXT NOT NULL,     -- Full log content
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Table to store chat messages between user and the LLM
CREATE TABLE IF NOT EXISTS chat_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id TEXT,  -- UUID of the related log file (can be null for general chats)
    user_message TEXT,
    llm_message TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Table to store successful error solutions for training
CREATE TABLE IF NOT EXISTS error_solutions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id TEXT NOT NULL,
    line_number INTEGER NOT NULL,
    error_text TEXT NOT NULL,
    solution TEXT NOT NULL,
    was_helpful BOOLEAN DEFAULT FALSE,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Invoice & Receipt Intelligence System (IRIS) - database schema (SQLite; PostgreSQL-compatible design)
PRAGMA foreign_keys = ON;

CREATE TABLE users (
  user_id       INTEGER PRIMARY KEY AUTOINCREMENT,
  name          TEXT NOT NULL,
  email         TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,              -- salted hash (werkzeug scrypt/pbkdf2), never plain text
  api_key       TEXT UNIQUE NOT NULL,       -- token for the REST API (Authorization: Bearer <key>)
  created_at    TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE categories (
  category_id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id     INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  name        TEXT NOT NULL,
  keywords    TEXT DEFAULT '',              -- space-separated words used by the categorizer
  UNIQUE (user_id, name)
);

CREATE TABLE documents (
  doc_id         INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id        INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  file_path      TEXT NOT NULL,             -- stored under a random UUID name
  preview_path   TEXT,                      -- PNG preview for PDFs
  original_name  TEXT,
  vendor         TEXT,
  gstin          TEXT,
  invoice_no     TEXT,
  doc_date       TEXT,                      -- ISO 8601 (YYYY-MM-DD)
  subtotal       REAL,
  tax            REAL,
  total          REAL,
  category_id    INTEGER REFERENCES categories(category_id) ON DELETE SET NULL,
  status         TEXT NOT NULL DEFAULT 'processed',   -- processed | needs_review | verified
  flags          TEXT DEFAULT '[]',         -- JSON list of validation flags
  ocr_text       TEXT,
  ocr_confidence REAL,
  processing_ms  INTEGER,
  uploaded_at    TEXT DEFAULT CURRENT_TIMESTAMP,
  verified_at    TEXT
);

CREATE TABLE line_items (
  item_id INTEGER PRIMARY KEY AUTOINCREMENT,
  doc_id  INTEGER NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
  name    TEXT NOT NULL,
  qty     INTEGER DEFAULT 1,
  amount  REAL NOT NULL
);

CREATE INDEX idx_documents_user_date ON documents(user_id, doc_date);
CREATE INDEX idx_documents_user_status ON documents(user_id, status);
CREATE INDEX idx_line_items_doc ON line_items(doc_id);

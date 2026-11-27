CREATE TABLE sessions (
    id         TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    ended_at   TEXT,
    note       TEXT
);

CREATE TABLE moves (
    id          INTEGER PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    move_number INTEGER NOT NULL,
    side        TEXT NOT NULL CHECK (side IN ('w', 'b')),
    uci         TEXT NOT NULL,
    fen_before  TEXT NOT NULL,
    fen_after   TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    UNIQUE (session_id, move_number)
);

CREATE TABLE move_reviews (
    id                     INTEGER PRIMARY KEY,
    session_id             TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    move_number            INTEGER NOT NULL,
    review_json            TEXT NOT NULL,
    move_quality_score     REAL,
    thinking_quality_score REAL,
    created_at             TEXT NOT NULL
);
CREATE INDEX idx_move_reviews_session ON move_reviews (session_id, move_number);

CREATE TABLE thinking_mistakes (
    id          INTEGER PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    move_number INTEGER NOT NULL,
    component   TEXT NOT NULL,
    description TEXT NOT NULL,
    fen         TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX idx_thinking_mistakes_component ON thinking_mistakes (component, created_at);

CREATE TABLE engine_cache (
    fen         TEXT NOT NULL,
    depth       INTEGER NOT NULL,
    multipv     INTEGER NOT NULL,
    result_json TEXT NOT NULL,
    PRIMARY KEY (fen, depth, multipv)
);

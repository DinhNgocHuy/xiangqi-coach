-- GĐ6: one review per move (upsert key), Training Center exercises + attempts.
CREATE UNIQUE INDEX ux_move_reviews_session_move ON move_reviews (session_id, move_number);

CREATE TABLE exercises (
    id            INTEGER PRIMARY KEY,
    session_id    TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    move_number   INTEGER NOT NULL,
    component     TEXT NOT NULL,
    type          TEXT NOT NULL,
    fen           TEXT NOT NULL,
    side_to_move  TEXT NOT NULL CHECK (side_to_move IN ('w', 'b')),
    played_move   TEXT NOT NULL,
    answer_kind   TEXT NOT NULL CHECK (answer_kind IN ('move', 'eval')),
    prompt        TEXT NOT NULL,
    solution_json TEXT NOT NULL,
    engine_depth  INTEGER NOT NULL,
    created_at    TEXT NOT NULL,
    UNIQUE (session_id, move_number, type)
);

CREATE TABLE exercise_attempts (
    id          INTEGER PRIMARY KEY,
    exercise_id INTEGER NOT NULL REFERENCES exercises(id) ON DELETE CASCADE,
    answer      TEXT NOT NULL,
    correct     INTEGER NOT NULL CHECK (correct IN (0, 1)),
    created_at  TEXT NOT NULL
);
CREATE INDEX idx_exercise_attempts_exercise ON exercise_attempts (exercise_id);

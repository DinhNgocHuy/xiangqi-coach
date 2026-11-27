-- Starting position of a session (full FEN incl. side to move); Move Tracker rebuilds state from it + moves.
ALTER TABLE sessions ADD COLUMN start_fen TEXT NOT NULL
    DEFAULT 'rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1';

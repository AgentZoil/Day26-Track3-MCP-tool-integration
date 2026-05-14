from __future__ import annotations

import sqlite3
from pathlib import Path


DB_PATH = Path(__file__).with_name("sqlite_lab.db")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    cohort TEXT NOT NULL,
    score REAL NOT NULL CHECK(score >= 0 AND score <= 100),
    email TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    credit_hours INTEGER NOT NULL CHECK(credit_hours > 0)
);

CREATE TABLE IF NOT EXISTS enrollments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    course_id INTEGER NOT NULL,
    grade TEXT,
    enrolled_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE,
    FOREIGN KEY(course_id) REFERENCES courses(id) ON DELETE CASCADE,
    UNIQUE(student_id, course_id)
);
"""

SEED_SQL = """
INSERT INTO students (name, cohort, score, email) VALUES
    ('An', 'A1', 95.5, 'an@example.com'),
    ('Binh', 'A1', 88.0, 'binh@example.com'),
    ('Chi', 'B2', 91.25, 'chi@example.com'),
    ('Dung', 'B2', 76.0, 'dung@example.com'),
    ('Em', 'C3', 83.5, 'em@example.com');

INSERT INTO courses (code, title, credit_hours) VALUES
    ('MCP101', 'MCP Fundamentals', 3),
    ('SQL201', 'Applied SQL', 4),
    ('DS301', 'Data Systems', 3);

INSERT INTO enrollments (student_id, course_id, grade) VALUES
    (1, 1, 'A'),
    (1, 2, 'A-'),
    (2, 1, 'B+'),
    (3, 2, 'A'),
    (4, 3, 'B'),
    (5, 1, 'B+');
"""


def create_database(db_path: Path = DB_PATH) -> Path:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
        conn.executescript(SEED_SQL)
        conn.commit()

    return db_path


if __name__ == "__main__":
    path = create_database()
    print(path)

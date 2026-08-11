from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


class JournalStore:
    def __init__(self, path: str | Path = "data/ficc_terminal.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self._initialise()

    def _initialise(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS morning_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                call_date TEXT NOT NULL,
                summary TEXT NOT NULL,
                interpretation TEXT,
                sources_checked TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS pitches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pitch_date TEXT NOT NULL,
                client TEXT NOT NULL,
                client_problem TEXT,
                trade TEXT NOT NULL,
                product TEXT,
                market_view TEXT,
                instrument TEXT,
                entry_level TEXT,
                target TEXT,
                invalidation TEXT,
                time_horizon TEXT,
                catalyst TEXT,
                main_risk TEXT,
                client_relevance TEXT,
                closing_question TEXT,
                status TEXT NOT NULL DEFAULT 'Open',
                performance TEXT,
                maximum_adverse_move TEXT,
                catalyst_outcome TEXT,
                thesis_review TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS pitch_updates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pitch_id INTEGER NOT NULL,
                update_date TEXT NOT NULL,
                current_level TEXT,
                performance TEXT,
                status TEXT NOT NULL DEFAULT 'Open',
                comment TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (pitch_id) REFERENCES pitches(id)
            );
            """
        )
        self.connection.commit()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def save_morning_call(
        self,
        call_date: str,
        summary: str,
        interpretation: str,
        sources_checked: str,
    ) -> int:
        cursor = self.connection.execute(
            """
            INSERT INTO morning_calls (call_date, summary, interpretation, sources_checked, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (call_date, summary, interpretation, sources_checked, self._now()),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def save_pitch(self, pitch: dict[str, str], pitch_date: str) -> int:
        columns = [
            "client",
            "client_problem",
            "trade",
            "product",
            "market_view",
            "instrument",
            "entry_level",
            "target",
            "invalidation",
            "time_horizon",
            "catalyst",
            "main_risk",
            "client_relevance",
            "closing_question",
        ]
        values = [pitch.get(column, "") for column in columns]
        placeholders = ", ".join("?" for _ in range(len(columns) + 2))
        cursor = self.connection.execute(
            f"INSERT INTO pitches (pitch_date, {', '.join(columns)}, created_at) VALUES ({placeholders})",
            [pitch_date, *values, self._now()],
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def list_pitches(self) -> pd.DataFrame:
        return pd.read_sql_query("SELECT * FROM pitches ORDER BY pitch_date DESC, id DESC", self.connection)

    def list_morning_calls(self) -> pd.DataFrame:
        return pd.read_sql_query(
            "SELECT * FROM morning_calls ORDER BY call_date DESC, id DESC", self.connection
        )

    def add_pitch_update(
        self,
        pitch_id: int,
        *,
        update_date: str,
        current_level: str,
        performance: str,
        status: str,
        comment: str,
    ) -> int:
        cursor = self.connection.execute(
            """
            INSERT INTO pitch_updates (
                pitch_id, update_date, current_level, performance, status,
                comment, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pitch_id,
                update_date,
                current_level,
                performance,
                status,
                comment,
                self._now(),
            ),
        )
        self.connection.execute(
            "UPDATE pitches SET status = ?, performance = ? WHERE id = ?",
            (status, performance, pitch_id),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def list_pitch_updates(self, pitch_id: int | None = None) -> pd.DataFrame:
        if pitch_id is None:
            return pd.read_sql_query(
                "SELECT * FROM pitch_updates ORDER BY update_date DESC, id DESC",
                self.connection,
            )
        return pd.read_sql_query(
            """
            SELECT * FROM pitch_updates
            WHERE pitch_id = ?
            ORDER BY update_date DESC, id DESC
            """,
            self.connection,
            params=(pitch_id,),
        )

    def review_pitch(
        self,
        pitch_id: int,
        *,
        status: str,
        performance: str,
        maximum_adverse_move: str,
        catalyst_outcome: str,
        thesis_review: str,
    ) -> None:
        self.connection.execute(
            """
            UPDATE pitches
            SET status = ?, performance = ?, maximum_adverse_move = ?,
                catalyst_outcome = ?, thesis_review = ?
            WHERE id = ?
            """,
            (status, performance, maximum_adverse_move, catalyst_outcome, thesis_review, pitch_id),
        )
        self.connection.commit()

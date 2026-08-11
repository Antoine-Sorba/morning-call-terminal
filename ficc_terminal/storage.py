from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


class JournalStore:
    persistent = False
    backend_label = "Local SQLite"

    def __init__(self, path: str | Path = "data/ficc_terminal.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(
            self.path,
            check_same_thread=False,
            timeout=30.0,
        )
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA busy_timeout = 30000")
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self._initialise()

    def close(self) -> None:
        self.connection.close()

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
                closed_date TEXT,
                realized_return_pct REAL,
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
        pitch_columns = {
            row["name"]
            for row in self.connection.execute("PRAGMA table_info(pitches)").fetchall()
        }
        migrations = {
            "closed_date": "ALTER TABLE pitches ADD COLUMN closed_date TEXT",
            "realized_return_pct": (
                "ALTER TABLE pitches ADD COLUMN realized_return_pct REAL"
            ),
        }
        for column, statement in migrations.items():
            if column not in pitch_columns:
                self.connection.execute(statement)
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
        existing = self.connection.execute(
            """
            SELECT id FROM morning_calls
            WHERE call_date = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (call_date,),
        ).fetchone()
        if existing is not None:
            call_id = int(existing["id"])
            self.connection.execute(
                """
                UPDATE morning_calls
                SET summary = ?, interpretation = ?, sources_checked = ?, created_at = ?
                WHERE id = ?
                """,
                (summary, interpretation, sources_checked, self._now(), call_id),
            )
            self.connection.commit()
            return call_id

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

    def update_pitch(
        self,
        pitch_id: int,
        pitch: dict[str, str],
        pitch_date: str,
    ) -> bool:
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
        assignments = ", ".join(f"{column} = ?" for column in columns)
        values = [pitch.get(column, "") for column in columns]
        cursor = self.connection.execute(
            f"UPDATE pitches SET pitch_date = ?, {assignments} WHERE id = ?",
            [pitch_date, *values, pitch_id],
        )
        self.connection.commit()
        return cursor.rowcount == 1

    def delete_pitch(self, pitch_id: int) -> bool:
        self.connection.execute(
            "DELETE FROM pitch_updates WHERE pitch_id = ?",
            (pitch_id,),
        )
        cursor = self.connection.execute(
            "DELETE FROM pitches WHERE id = ?",
            (pitch_id,),
        )
        self.connection.commit()
        return cursor.rowcount == 1

    def list_morning_calls(self) -> pd.DataFrame:
        return pd.read_sql_query(
            """
            SELECT * FROM morning_calls AS current_call
            WHERE current_call.id = (
                SELECT MAX(latest.id)
                FROM morning_calls AS latest
                WHERE latest.call_date = current_call.call_date
            )
            ORDER BY call_date DESC, id DESC
            """,
            self.connection,
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
        closed_date: str | None = None,
        realized_return_pct: float | None = None,
    ) -> None:
        self.connection.execute(
            """
            UPDATE pitches
            SET status = ?, performance = ?, maximum_adverse_move = ?,
                catalyst_outcome = ?, thesis_review = ?, closed_date = ?,
                realized_return_pct = ?
            WHERE id = ?
            """,
            (
                status,
                performance,
                maximum_adverse_move,
                catalyst_outcome,
                thesis_review,
                closed_date,
                realized_return_pct,
                pitch_id,
            ),
        )
        self.connection.commit()


class PostgresJournalStore:
    """Persistent journal backend for hosted deployments.

    A fresh connection is used for each operation so the cached Streamlit
    resource remains safe across concurrent sessions.
    """

    persistent = True
    backend_label = "Persistent PostgreSQL"

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._initialise()

    def _connect(self):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as error:  # pragma: no cover - deployment dependency guard
            raise RuntimeError(
                "Persistent journal storage requires the psycopg package."
            ) from error
        return psycopg.connect(self.database_url, row_factory=dict_row, connect_timeout=15)

    def close(self) -> None:
        return None

    def _initialise(self) -> None:
        statements = (
            """
            CREATE TABLE IF NOT EXISTS morning_calls (
                id BIGSERIAL PRIMARY KEY,
                call_date TEXT NOT NULL,
                summary TEXT NOT NULL,
                interpretation TEXT,
                sources_checked TEXT,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS pitches (
                id BIGSERIAL PRIMARY KEY,
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
                closed_date TEXT,
                realized_return_pct DOUBLE PRECISION,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS pitch_updates (
                id BIGSERIAL PRIMARY KEY,
                pitch_id BIGINT NOT NULL REFERENCES pitches(id) ON DELETE CASCADE,
                update_date TEXT NOT NULL,
                current_level TEXT,
                performance TEXT,
                status TEXT NOT NULL DEFAULT 'Open',
                comment TEXT,
                created_at TEXT NOT NULL
            )
            """,
            "ALTER TABLE pitches ADD COLUMN IF NOT EXISTS closed_date TEXT",
            (
                "ALTER TABLE pitches ADD COLUMN IF NOT EXISTS "
                "realized_return_pct DOUBLE PRECISION"
            ),
        )
        with self._connect() as connection:
            with connection.cursor() as cursor:
                for statement in statements:
                    cursor.execute(statement)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _frame(self, query: str, params: tuple[object, ...] = ()) -> pd.DataFrame:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, params)
                return pd.DataFrame(cursor.fetchall())

    def save_morning_call(
        self,
        call_date: str,
        summary: str,
        interpretation: str,
        sources_checked: str,
    ) -> int:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id FROM morning_calls
                    WHERE call_date = %s
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (call_date,),
                )
                existing = cursor.fetchone()
                if existing is not None:
                    call_id = int(existing["id"])
                    cursor.execute(
                        """
                        UPDATE morning_calls
                        SET summary = %s, interpretation = %s, sources_checked = %s,
                            created_at = %s
                        WHERE id = %s
                        """,
                        (
                            summary,
                            interpretation,
                            sources_checked,
                            self._now(),
                            call_id,
                        ),
                    )
                    return call_id

                cursor.execute(
                    """
                    INSERT INTO morning_calls (
                        call_date, summary, interpretation, sources_checked, created_at
                    ) VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (call_date, summary, interpretation, sources_checked, self._now()),
                )
                return int(cursor.fetchone()["id"])

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
        placeholders = ", ".join("%s" for _ in range(len(columns) + 2))
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    INSERT INTO pitches (pitch_date, {', '.join(columns)}, created_at)
                    VALUES ({placeholders})
                    RETURNING id
                    """,
                    [pitch_date, *values, self._now()],
                )
                return int(cursor.fetchone()["id"])

    def list_pitches(self) -> pd.DataFrame:
        return self._frame("SELECT * FROM pitches ORDER BY pitch_date DESC, id DESC")

    def update_pitch(
        self,
        pitch_id: int,
        pitch: dict[str, str],
        pitch_date: str,
    ) -> bool:
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
        assignments = ", ".join(f"{column} = %s" for column in columns)
        values = [pitch.get(column, "") for column in columns]
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"UPDATE pitches SET pitch_date = %s, {assignments} WHERE id = %s",
                    [pitch_date, *values, pitch_id],
                )
                return cursor.rowcount == 1

    def delete_pitch(self, pitch_id: int) -> bool:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM pitch_updates WHERE pitch_id = %s",
                    (pitch_id,),
                )
                cursor.execute(
                    "DELETE FROM pitches WHERE id = %s",
                    (pitch_id,),
                )
                return cursor.rowcount == 1

    def list_morning_calls(self) -> pd.DataFrame:
        return self._frame(
            """
            SELECT * FROM morning_calls AS current_call
            WHERE current_call.id = (
                SELECT MAX(latest.id)
                FROM morning_calls AS latest
                WHERE latest.call_date = current_call.call_date
            )
            ORDER BY call_date DESC, id DESC
            """
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
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO pitch_updates (
                        pitch_id, update_date, current_level, performance, status,
                        comment, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
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
                update_id = int(cursor.fetchone()["id"])
                cursor.execute(
                    "UPDATE pitches SET status = %s, performance = %s WHERE id = %s",
                    (status, performance, pitch_id),
                )
                return update_id

    def list_pitch_updates(self, pitch_id: int | None = None) -> pd.DataFrame:
        if pitch_id is None:
            return self._frame(
                "SELECT * FROM pitch_updates ORDER BY update_date DESC, id DESC"
            )
        return self._frame(
            """
            SELECT * FROM pitch_updates
            WHERE pitch_id = %s
            ORDER BY update_date DESC, id DESC
            """,
            (pitch_id,),
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
        closed_date: str | None = None,
        realized_return_pct: float | None = None,
    ) -> None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE pitches
                    SET status = %s, performance = %s, maximum_adverse_move = %s,
                        catalyst_outcome = %s, thesis_review = %s, closed_date = %s,
                        realized_return_pct = %s
                    WHERE id = %s
                    """,
                    (
                        status,
                        performance,
                        maximum_adverse_move,
                        catalyst_outcome,
                        thesis_review,
                        closed_date,
                        realized_return_pct,
                        pitch_id,
                    ),
                )


def create_journal_store(
    *,
    database_url: str = "",
    sqlite_path: str | Path = "data/ficc_terminal.db",
) -> JournalStore | PostgresJournalStore:
    if database_url.strip():
        return PostgresJournalStore(database_url.strip())
    return JournalStore(sqlite_path)

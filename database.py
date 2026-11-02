from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Generator

if TYPE_CHECKING:
    from codeforces import CodeforcesContest


@dataclass(frozen=True)
class UserPreference:
    telegram_user_id: int
    selected_division: str | None
    notifications_enabled: bool
    created_at: float
    updated_at: float


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    @contextmanager
    def _connection(self) -> Generator[sqlite3.Connection, None, None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    telegram_user_id INTEGER PRIMARY KEY,
                    selected_division TEXT,
                    notifications_enabled INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS contests (
                    contest_id INTEGER PRIMARY KEY,
                    contest_name TEXT NOT NULL,
                    contest_phase TEXT NOT NULL,
                    contest_start_time INTEGER NOT NULL,
                    contest_type TEXT NOT NULL,
                    classified_divisions TEXT NOT NULL,
                    first_seen_at REAL NOT NULL,
                    is_baseline INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS notification_history (
                    telegram_user_id INTEGER NOT NULL,
                    contest_id INTEGER NOT NULL,
                    notified_at REAL NOT NULL,
                    PRIMARY KEY (telegram_user_id, contest_id),
                    FOREIGN KEY (telegram_user_id) REFERENCES users (telegram_user_id),
                    FOREIGN KEY (contest_id) REFERENCES contests (contest_id)
                );

                CREATE TABLE IF NOT EXISTS app_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_users_notifications
                    ON users (notifications_enabled);
                """
            )
            contest_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(contests)").fetchall()
            }
            if "is_baseline" not in contest_columns:
                connection.execute(
                    "ALTER TABLE contests ADD COLUMN is_baseline INTEGER NOT NULL DEFAULT 1"
                )

    def get_user(self, telegram_user_id: int) -> UserPreference | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT telegram_user_id, selected_division, notifications_enabled,
                       created_at, updated_at
                FROM users
                WHERE telegram_user_id = ?
                """,
                (telegram_user_id,),
            ).fetchone()
        if row is None:
            return None
        return UserPreference(
            telegram_user_id=row["telegram_user_id"],
            selected_division=row["selected_division"],
            notifications_enabled=bool(row["notifications_enabled"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def save_preference(self, telegram_user_id: int, division: str) -> None:
        now = time.time()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO users (
                    telegram_user_id, selected_division, notifications_enabled,
                    created_at, updated_at
                )
                VALUES (?, ?, 1, ?, ?)
                ON CONFLICT (telegram_user_id) DO UPDATE SET
                    selected_division = excluded.selected_division,
                    notifications_enabled = 1,
                    updated_at = excluded.updated_at
                """,
                (telegram_user_id, division, now, now),
            )

    def set_notifications_enabled(
        self, telegram_user_id: int, enabled: bool
    ) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE users
                SET notifications_enabled = ?, updated_at = ?
                WHERE telegram_user_id = ? AND selected_division IS NOT NULL
                """,
                (int(enabled), time.time(), telegram_user_id),
            )
            return cursor.rowcount > 0

    def get_enabled_users(self) -> list[UserPreference]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT telegram_user_id, selected_division, notifications_enabled,
                       created_at, updated_at
                FROM users
                WHERE notifications_enabled = 1 AND selected_division IS NOT NULL
                """
            ).fetchall()
        return [
            UserPreference(
                telegram_user_id=row["telegram_user_id"],
                selected_division=row["selected_division"],
                notifications_enabled=bool(row["notifications_enabled"]),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    def record_contests(self, contests: list[CodeforcesContest]) -> None:
        now = time.time()

        with self._connection() as connection:
            row = connection.execute(
                "SELECT value FROM app_state WHERE key = 'contest_baseline_complete'"
            ).fetchone()
            baseline_complete = row is not None and row["value"] == "1"
            is_baseline = int(not baseline_complete)

            for contest in contests:
                divisions_json = json.dumps(contest.divisions)
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO contests (
                        contest_id, contest_name, contest_phase, contest_start_time,
                        contest_type, classified_divisions, first_seen_at, is_baseline
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        contest.contest_id,
                        contest.name,
                        contest.phase,
                        contest.start_time_seconds,
                        contest.contest_type,
                        divisions_json,
                        now,
                        is_baseline,
                    ),
                )
                if cursor.rowcount != 1:
                    connection.execute(
                        """
                        UPDATE contests
                        SET contest_name = ?, contest_phase = ?,
                            contest_start_time = ?, contest_type = ?,
                            classified_divisions = ?
                        WHERE contest_id = ?
                        """,
                        (
                            contest.name,
                            contest.phase,
                            contest.start_time_seconds,
                            contest.contest_type,
                            divisions_json,
                            contest.contest_id,
                        ),
                    )

            if not baseline_complete:
                connection.execute(
                    """
                    INSERT INTO app_state (key, value)
                    VALUES ('contest_baseline_complete', '1')
                    ON CONFLICT (key) DO UPDATE SET value = '1'
                    """
                )

    def get_pending_contests(
        self, now: float
    ) -> list[tuple[CodeforcesContest, float]]:
        from codeforces import CodeforcesContest

        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT contest_id, contest_name, contest_phase, contest_start_time,
                       contest_type, classified_divisions, first_seen_at
                FROM contests
                WHERE contest_phase = 'BEFORE' AND contest_start_time > ?
                  AND is_baseline = 0
                """,
                (now,),
            ).fetchall()
        return [
            (
                CodeforcesContest(
                    contest_id=row["contest_id"],
                    name=row["contest_name"],
                    phase=row["contest_phase"],
                    start_time_seconds=row["contest_start_time"],
                    contest_type=row["contest_type"],
                    divisions=tuple(json.loads(row["classified_divisions"])),
                ),
                row["first_seen_at"],
            )
            for row in rows
        ]

    def claim_notification(
        self,
        telegram_user_id: int,
        contest_id: int,
        first_seen_at: float,
        divisions: tuple[int, ...],
    ) -> str | None:
        with self._connection() as connection:
            user = connection.execute(
                """
                SELECT selected_division, notifications_enabled, updated_at
                FROM users
                WHERE telegram_user_id = ?
                """,
                (telegram_user_id,),
            ).fetchone()
            if (
                user is None
                or not user["notifications_enabled"]
                or user["selected_division"] is None
                or first_seen_at <= user["updated_at"]
            ):
                return None

            selected_division = user["selected_division"]
            if selected_division != "All Divisions":
                division_number = {
                    "Div. 1": 1,
                    "Div. 2": 2,
                    "Div. 3": 3,
                    "Div. 4": 4,
                }.get(selected_division)
                if division_number not in divisions:
                    return None

            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO notification_history (
                    telegram_user_id, contest_id, notified_at
                )
                VALUES (?, ?, ?)
                """,
                (telegram_user_id, contest_id, time.time()),
            )
            if cursor.rowcount != 1:
                return None
            return selected_division

    def release_notification_claim(
        self, telegram_user_id: int, contest_id: int
    ) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                DELETE FROM notification_history
                WHERE telegram_user_id = ? AND contest_id = ?
                """,
                (telegram_user_id, contest_id),
            )

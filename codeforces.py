from __future__ import annotations

import asyncio
import html
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

import httpx
from telegram import Bot
from telegram.error import TelegramError

if TYPE_CHECKING:
    from database import Database

logger = logging.getLogger(__name__)

API_URL = "https://codeforces.com/api/contest.list"
IST = ZoneInfo("Asia/Kolkata")
DIVISION_PATTERN = re.compile(r"\bdiv(?:ision)?\s*\.?\s*([1-4])\b", re.IGNORECASE)


class CodeforcesAPIError(Exception):
    """Raised when Codeforces cannot provide a valid contest list."""


@dataclass(frozen=True)
class CodeforcesContest:
    contest_id: int
    name: str
    phase: str
    start_time_seconds: int
    contest_type: str
    divisions: tuple[int, ...]


def classify_divisions(contest_name: str) -> tuple[int, ...]:
    """Return only divisions explicitly named in the contest title."""
    return tuple(
        sorted({int(match.group(1)) for match in DIVISION_PATTERN.finditer(contest_name)})
    )


class CodeforcesClient:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(20.0),
            headers={"User-Agent": "CodeforcesContestAlertBot/1.0"},
        )

    async def fetch_contests(self) -> list[CodeforcesContest]:
        try:
            response = await self._client.get(API_URL, params={"gym": "false"})
        except httpx.TimeoutException as error:
            raise CodeforcesAPIError("The Codeforces API request timed out.") from error
        except httpx.HTTPError as error:
            raise CodeforcesAPIError(
                f"Could not connect to the Codeforces API: {error}"
            ) from error

        if response.status_code == 429:
            raise CodeforcesAPIError("The Codeforces API rate limit was reached.")
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise CodeforcesAPIError(
                f"The Codeforces API returned HTTP {response.status_code}."
            ) from error

        try:
            payload: Any = response.json()
        except ValueError as error:
            raise CodeforcesAPIError("The Codeforces API returned invalid JSON.") from error
        if not isinstance(payload, dict) or payload.get("status") != "OK":
            raise CodeforcesAPIError("The Codeforces API response was not successful.")

        result = payload.get("result")
        if not isinstance(result, list):
            raise CodeforcesAPIError("The Codeforces API response has no contest list.")

        contests: list[CodeforcesContest] = []
        for item in result:
            if not isinstance(item, dict):
                raise CodeforcesAPIError("The API returned a malformed contest entry.")
            contest_id = item.get("id")
            name = item.get("name")
            phase = item.get("phase")
            start_time = item.get("startTimeSeconds")
            contest_type = item.get("type")
            if (
                not isinstance(contest_id, int)
                or isinstance(contest_id, bool)
                or not isinstance(name, str)
                or not isinstance(phase, str)
                or not isinstance(start_time, int)
                or isinstance(start_time, bool)
                or not isinstance(contest_type, str)
            ):
                raise CodeforcesAPIError("The API returned a contest with invalid fields.")

            contests.append(
                CodeforcesContest(
                    contest_id=contest_id,
                    name=name,
                    phase=phase,
                    start_time_seconds=start_time,
                    contest_type=contest_type,
                    divisions=classify_divisions(name),
                )
            )
        return contests

    async def close(self) -> None:
        await self._client.aclose()


def format_contest_message(
    contest: CodeforcesContest, selected_division: str
) -> str:
    if contest.divisions:
        division_label = " + ".join(f"Div. {division}" for division in contest.divisions)
    else:
        division_label = "Not specified"

    start_time = datetime.fromtimestamp(contest.start_time_seconds, tz=IST)
    safe_name = html.escape(contest.name)
    contest_url = f"https://codeforces.com/contest/{contest.contest_id}"
    return (
        "🚨 <b>NEW CODEFORCES CONTEST</b>\n\n"
        f"📌 <b>Contest:</b> {safe_name}\n\n"
        f"🏆 <b>Division:</b> {division_label}\n\n"
        f"📅 <b>Date:</b> {start_time.strftime('%d %b %Y')}\n\n"
        f"⏰ <b>Start Time:</b> {start_time.strftime('%I:%M %p %Z')}\n\n"
        f'🔗 <b>Contest Link:</b> <a href="{contest_url}">Open contest</a>\n\n'
        f"<b>Your selected division:</b> {html.escape(selected_division)}\n\n"
        "Use /change to change your division."
    )


class ContestMonitor:
    def __init__(self, database: Database, bot: Bot) -> None:
        self._database = database
        self._bot = bot
        self._client = CodeforcesClient()
        self._interval_seconds = 5 * 60

    async def poll_once(self) -> None:
        try:
            contests = await self._client.fetch_contests()
            await asyncio.to_thread(
                self._database.record_contests, contests
            )
            pending = await asyncio.to_thread(
                self._database.get_pending_contests, time.time()
            )
            for contest, first_seen_at in pending:
                await self._notify_matching_users(contest, first_seen_at)
        except CodeforcesAPIError as error:
            logger.warning("Codeforces contest check failed: %s", error)
        except Exception:
            logger.exception("Unexpected error while checking Codeforces contests.")

    async def _notify_matching_users(
        self, contest: CodeforcesContest, first_seen_at: float
    ) -> None:
        users = await asyncio.to_thread(self._database.get_enabled_users)
        for user in users:
            selected_division = await asyncio.to_thread(
                self._database.claim_notification,
                user.telegram_user_id,
                contest.contest_id,
                first_seen_at,
                contest.divisions,
            )
            if selected_division is None:
                continue

            if contest.start_time_seconds <= time.time():
                await asyncio.to_thread(
                    self._database.release_notification_claim,
                    user.telegram_user_id,
                    contest.contest_id,
                )
                continue

            message = format_contest_message(contest, selected_division)
            try:
                await self._bot.send_message(
                    chat_id=user.telegram_user_id,
                    text=message,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
            except TelegramError:
                logger.exception(
                    "Could not deliver contest %s notification to user %s.",
                    contest.contest_id,
                    user.telegram_user_id,
                )
                await asyncio.to_thread(
                    self._database.release_notification_claim,
                    user.telegram_user_id,
                    contest.contest_id,
                )

    async def run(self) -> None:
        while True:
            await asyncio.sleep(self._interval_seconds)
            await self.poll_once()

    async def close(self) -> None:
        await self._client.close()

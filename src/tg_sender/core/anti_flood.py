import asyncio
import random
from datetime import UTC, datetime, timedelta

from telethon import errors


class FloodHandler:
    @staticmethod
    def get_random_delay(min_seconds: int, max_seconds: int) -> float:
        if min_seconds >= max_seconds:
            return float(min_seconds)
        return random.uniform(float(min_seconds), float(max_seconds))

    @staticmethod
    async def simulate_typing(client, entity, duration_seconds: int = 3) -> None:
        try:
            async with client.action(entity, "typing"):
                await asyncio.sleep(duration_seconds)
        except Exception:
            await asyncio.sleep(duration_seconds)

    @staticmethod
    def classify_error(err: Exception) -> tuple[str, str | None, int | None]:
        if isinstance(err, errors.FloodWaitError):
            seconds = int(err.seconds)
            cooldown_dt = datetime.now(UTC) + timedelta(seconds=seconds)
            return "FLOOD_WAIT", cooldown_dt.isoformat(), seconds

        if isinstance(err, errors.PeerFloodError):
            cooldown_dt = datetime.now(UTC) + timedelta(hours=24)
            return "PEER_FLOOD", cooldown_dt.isoformat(), 86400

        if isinstance(
            err,
            (
                errors.UserDeactivatedError,
                errors.UserDeactivatedBanError,
                errors.AuthKeyUnregisteredError,
            ),
        ):
            return "ACCOUNT_BANNED", None, None

        if isinstance(err, errors.UserPrivacyRestrictedError):
            return "PRIVACY_RESTRICTED", None, None

        if isinstance(err, (errors.ChatWriteForbiddenError, errors.UserBannedInChannelError)):
            return "WRITE_FORBIDDEN", None, None

        if isinstance(err, ValueError):
            err_str = str(err)
            if "Cannot find any entity" in err_str or "No user has" in err_str:
                return "USER_NOT_FOUND", None, None

        return "UNKNOWN_ERROR", None, None

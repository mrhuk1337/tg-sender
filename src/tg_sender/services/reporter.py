from pathlib import Path
from typing import Any

import pandas as pd
from loguru import logger

from tg_sender.db.database import Database


class Reporter:
    def __init__(self, db: Database):
        self.db = db

    async def export_to_csv(self, file_path: Path | str, status: str | None = None) -> int:
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        contacts = await self.db.get_all_contacts(status=status)
        cols = [
            "id",
            "recipient",
            "first_name",
            "status",
            "account_phone",
            "sent_at",
            "error_message",
        ]
        df = pd.DataFrame(contacts)
        if df.empty:
            df = pd.DataFrame(columns=cols)
        else:
            existing = [c for c in cols if c in df.columns]
            df = df[existing]
        df.to_csv(path, index=False, encoding="utf-8-sig")
        logger.info(f"Exported {len(contacts)} contacts to CSV: {path}")
        return len(contacts)

    async def export_to_excel(self, file_path: Path | str, status: str | None = None) -> int:
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        contacts = await self.db.get_all_contacts(status=status)
        cols = [
            "id",
            "recipient",
            "first_name",
            "status",
            "account_phone",
            "sent_at",
            "error_message",
        ]
        df = pd.DataFrame(contacts)
        if df.empty:
            df = pd.DataFrame(columns=cols)
        else:
            existing = [c for c in cols if c in df.columns]
            df = df[existing]
        df.to_excel(path, index=False)
        logger.info(f"Exported {len(contacts)} contacts to Excel: {path}")
        return len(contacts)

    async def get_summary(self) -> dict[str, Any]:
        return await self.db.get_stats()

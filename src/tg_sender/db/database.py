import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite


class Database:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def connect(self):
        return aiosqlite.connect(self.db_path, timeout=30.0)

    async def init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        async with self.connect() as db:
            await db.execute("PRAGMA journal_mode = WAL")
            await db.execute("PRAGMA busy_timeout = 30000")
            await db.execute(
                "CREATE TABLE IF NOT EXISTS contacts ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "recipient TEXT UNIQUE NOT NULL, "
                "first_name TEXT, "
                "extra_data TEXT, "
                "status TEXT NOT NULL DEFAULT 'PENDING', "
                "account_phone TEXT, "
                "sent_at TEXT, "
                "error_message TEXT, "
                "created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
            )
            await db.execute(
                "CREATE TABLE IF NOT EXISTS accounts ("
                "phone TEXT PRIMARY KEY, "
                "api_id INTEGER NOT NULL, "
                "api_hash TEXT NOT NULL, "
                "proxy_type TEXT, "
                "proxy_host TEXT, "
                "proxy_port INTEGER, "
                "proxy_user TEXT, "
                "proxy_password TEXT, "
                "daily_limit INTEGER DEFAULT 20, "
                "sent_today INTEGER DEFAULT 0, "
                "last_sent_at TEXT, "
                "status TEXT DEFAULT 'ACTIVE', "
                "cooldown_until TEXT)"
            )
            await db.execute(
                "CREATE TABLE IF NOT EXISTS send_logs ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "contact_recipient TEXT NOT NULL, "
                "account_phone TEXT NOT NULL, "
                "message_text TEXT, "
                "status TEXT NOT NULL, "
                "error_message TEXT, "
                "created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
            )
            await db.commit()

    async def add_contact(
        self,
        recipient: str,
        first_name: str | None = None,
        extra_data: dict[str, Any] | None = None,
    ) -> bool:
        extra_json = json.dumps(extra_data or {}, ensure_ascii=False)
        async with self.connect() as db:
            try:
                await db.execute(
                    "INSERT INTO contacts (recipient, first_name, extra_data) VALUES (?, ?, ?)",
                    (recipient, first_name, extra_json),
                )
                await db.commit()
                return True
            except aiosqlite.IntegrityError:
                return False

    async def bulk_add_contacts(self, contacts: list[dict[str, Any]]) -> tuple[int, int]:
        inserted = 0
        skipped = 0
        async with self.connect() as db:
            for item in contacts:
                recipient = item.get("recipient")
                if not recipient:
                    skipped += 1
                    continue
                first_name = item.get("first_name")
                extra = json.dumps(item.get("extra_data") or {}, ensure_ascii=False)
                try:
                    await db.execute(
                        "INSERT INTO contacts (recipient, first_name, extra_data) VALUES (?, ?, ?)",
                        (recipient, first_name, extra),
                    )
                    inserted += 1
                except aiosqlite.IntegrityError:
                    skipped += 1
            await db.commit()
        return inserted, skipped

    async def get_pending_contacts(self, limit: int | None = None) -> list[dict[str, Any]]:
        query = "SELECT id, recipient, first_name, extra_data, status FROM contacts WHERE status = 'PENDING' ORDER BY id ASC"
        if limit:
            query += f" LIMIT {int(limit)}"
        async with self.connect() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query) as cursor:
                rows = await cursor.fetchall()
                results = []
                for row in rows:
                    data = dict(row)
                    data["extra_data"] = (
                        json.loads(data["extra_data"]) if data.get("extra_data") else {}
                    )
                    results.append(data)
                return results

    async def update_contact_status(
        self,
        recipient: str,
        status: str,
        account_phone: str | None = None,
        error_message: str | None = None,
    ) -> None:
        now_iso = datetime.now(UTC).isoformat()
        async with self.connect() as db:
            await db.execute(
                (
                    "UPDATE contacts "
                    "SET status = ?, account_phone = ?, error_message = ?, sent_at = ? "
                    "WHERE recipient = ?"
                ),
                (
                    status,
                    account_phone,
                    error_message,
                    now_iso if status == "SENT" else None,
                    recipient,
                ),
            )
            await db.commit()

    async def save_account(
        self,
        phone: str,
        api_id: int,
        api_hash: str,
        proxy_type: str | None = None,
        proxy_host: str | None = None,
        proxy_port: int | None = None,
        proxy_user: str | None = None,
        proxy_password: str | None = None,
        daily_limit: int = 20,
    ) -> None:
        async with self.connect() as db:
            await db.execute(
                (
                    "INSERT INTO accounts ("
                    "phone, api_id, api_hash, proxy_type, proxy_host, proxy_port, "
                    "proxy_user, proxy_password, daily_limit"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(phone) DO UPDATE SET "
                    "api_id = excluded.api_id, "
                    "api_hash = excluded.api_hash, "
                    "proxy_type = COALESCE(excluded.proxy_type, accounts.proxy_type), "
                    "proxy_host = COALESCE(excluded.proxy_host, accounts.proxy_host), "
                    "proxy_port = COALESCE(excluded.proxy_port, accounts.proxy_port), "
                    "proxy_user = COALESCE(excluded.proxy_user, accounts.proxy_user), "
                    "proxy_password = COALESCE(excluded.proxy_password, accounts.proxy_password), "
                    "daily_limit = excluded.daily_limit"
                ),
                (
                    phone,
                    api_id,
                    api_hash,
                    proxy_type,
                    proxy_host,
                    proxy_port,
                    proxy_user,
                    proxy_password,
                    daily_limit,
                ),
            )
            await db.commit()

    async def update_account_proxy(
        self,
        phone: str,
        proxy_type: str | None = None,
        proxy_host: str | None = None,
        proxy_port: int | None = None,
        proxy_user: str | None = None,
        proxy_password: str | None = None,
    ) -> None:
        async with self.connect() as db:
            await db.execute(
                (
                    "UPDATE accounts SET "
                    "proxy_type = ?, proxy_host = ?, proxy_port = ?, proxy_user = ?, proxy_password = ? "
                    "WHERE phone = ?"
                ),
                (proxy_type, proxy_host, proxy_port, proxy_user, proxy_password, phone),
            )
            await db.commit()

    async def get_accounts_without_proxy(self) -> list[dict[str, Any]]:
        async with self.connect() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM accounts WHERE proxy_host IS NULL OR proxy_host = '' ORDER BY phone ASC"
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def get_accounts(self) -> list[dict[str, Any]]:
        async with self.connect() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM accounts ORDER BY phone ASC") as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def get_account(self, phone: str) -> dict[str, Any] | None:
        async with self.connect() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM accounts WHERE phone = ?", (phone,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def update_account_state(
        self,
        phone: str,
        increment_sent: bool = False,
        cooldown_until: str | None = None,
        status: str | None = None,
    ) -> None:
        now_iso = datetime.now(UTC).isoformat()
        async with self.connect() as db:
            if increment_sent:
                await db.execute(
                    "UPDATE accounts SET sent_today = sent_today + 1, last_sent_at = ? WHERE phone = ?",
                    (now_iso, phone),
                )
            if cooldown_until is not None:
                await db.execute(
                    "UPDATE accounts SET cooldown_until = ? WHERE phone = ?",
                    (cooldown_until, phone),
                )
            if status is not None:
                await db.execute(
                    "UPDATE accounts SET status = ? WHERE phone = ?",
                    (status, phone),
                )
            await db.commit()

    async def reset_daily_limits_if_needed(self) -> None:
        now = datetime.now(UTC)
        async with self.connect() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT phone, last_sent_at FROM accounts WHERE sent_today > 0"
            ) as cursor:
                rows = await cursor.fetchall()
                for row in rows:
                    last_sent = row["last_sent_at"]
                    if last_sent:
                        dt = datetime.fromisoformat(last_sent)
                        if dt.date() < now.date():
                            await db.execute(
                                "UPDATE accounts SET sent_today = 0 WHERE phone = ?",
                                (row["phone"],),
                            )
            await db.commit()

    async def save_send_log(
        self,
        recipient: str,
        account_phone: str,
        message_text: str,
        status: str,
        error_message: str | None = None,
    ) -> None:
        async with self.connect() as db:
            await db.execute(
                (
                    "INSERT INTO send_logs (contact_recipient, account_phone, message_text, status, error_message) "
                    "VALUES (?, ?, ?, ?, ?)"
                ),
                (recipient, account_phone, message_text, status, error_message),
            )
            await db.commit()

    async def get_stats(self) -> dict[str, Any]:
        async with self.connect() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT status, COUNT(*) as count FROM contacts GROUP BY status"
            ) as cursor:
                rows = await cursor.fetchall()
                contact_counts = {row["status"]: row["count"] for row in rows}

            async with db.execute("SELECT COUNT(*) as total FROM accounts") as cursor:
                total_row = await cursor.fetchone()
                total_accounts = total_row["total"] if total_row else 0

            async with db.execute(
                "SELECT COUNT(*) as active FROM accounts WHERE status = 'ACTIVE'"
            ) as cursor:
                active_row = await cursor.fetchone()
                active_accounts = active_row["active"] if active_row else 0

            return {
                "contacts": contact_counts,
                "total_contacts": sum(contact_counts.values()),
                "total_accounts": total_accounts,
                "active_accounts": active_accounts,
            }

    async def get_all_contacts(self, status: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM contacts"
        params = ()
        if status:
            query += " WHERE status = ?"
            params = (status,)
        query += " ORDER BY id ASC"
        async with self.connect() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                results = []
                for row in rows:
                    d = dict(row)
                    if d.get("extra_data"):
                        d["extra_data"] = json.loads(d["extra_data"])
                    results.append(d)
                return results

    async def clear_contacts(self, status: str | None = None) -> int:
        async with self.connect() as db:
            if status:
                cursor = await db.execute("DELETE FROM contacts WHERE status = ?", (status,))
            else:
                cursor = await db.execute("DELETE FROM contacts")
            await db.commit()
            return cursor.rowcount

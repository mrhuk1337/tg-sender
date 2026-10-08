from pathlib import Path
from typing import Any

import socks
from better_proxy import Proxy
from loguru import logger
from telethon import TelegramClient

from tg_sender.config.settings import settings
from tg_sender.db.database import Database


class ClientManager:
    def __init__(self, db: Database):
        self.db = db
        self.sessions_dir = settings.sessions_dir

    @staticmethod
    def _to_better_proxy(raw: str) -> Proxy:
        line = raw.strip()
        if "://" not in line:
            try:
                return Proxy.from_str(f"socks5://{line}")
            except Exception:
                return Proxy.from_str(line)
        return Proxy.from_str(line)

    @classmethod
    def parse_proxy_string(cls, raw: str | None) -> dict[str, Any] | None:
        if not raw:
            return None
        try:
            p = cls._to_better_proxy(raw)
            return {
                "type": p.protocol.lower(),
                "host": p.host,
                "port": int(p.port),
                "username": p.login,
                "password": p.password,
            }
        except Exception:
            return None

    def parse_proxy(self, proxy_data: dict[str, Any] | str | None) -> tuple[Any, ...] | None:
        if not proxy_data:
            return None
        try:
            if isinstance(proxy_data, str):
                p = self._to_better_proxy(proxy_data)
            elif isinstance(proxy_data, dict):
                p_host = proxy_data.get("host")
                if not p_host:
                    return None
                p_type = proxy_data.get("type", "socks5")
                p_port = proxy_data.get("port", 1080)
                p_user = proxy_data.get("username")
                p_pwd = proxy_data.get("password")
                if p_user and p_pwd:
                    p = Proxy.from_str(f"{p_type}://{p_user}:{p_pwd}@{p_host}:{p_port}")
                else:
                    p = Proxy.from_str(f"{p_type}://{p_host}:{p_port}")
            else:
                return None

            type_map = {
                "socks5": socks.SOCKS5,
                "socks4": socks.SOCKS4,
                "http": socks.HTTP,
            }
            proxy_type = type_map.get(p.protocol.lower(), socks.SOCKS5)
            if p.login and p.password:
                return (proxy_type, p.host, p.port, True, p.login, p.password)
            return (proxy_type, p.host, p.port)
        except Exception:
            return None

    def get_session_path(self, phone: str) -> Path:
        safe_phone = phone.replace("+", "").strip()
        return self.sessions_dir / f"{safe_phone}.session"

    def create_client(
        self,
        account: dict[str, Any],
        force_no_proxy: bool = False,
        override_proxy: dict[str, Any] | str | None = None,
    ) -> TelegramClient:
        phone = account["phone"]
        api_id = int(account["api_id"])
        api_hash = str(account["api_hash"])
        session_file = str(self.get_session_path(phone))

        if force_no_proxy:
            proxy_tuple = None
        elif override_proxy:
            proxy_tuple = self.parse_proxy(override_proxy)
        else:
            proxy_data = None
            if account.get("proxy_host"):
                proxy_data = {
                    "type": account.get("proxy_type", "socks5"),
                    "host": account.get("proxy_host"),
                    "port": account.get("proxy_port"),
                    "username": account.get("proxy_user"),
                    "password": account.get("proxy_password"),
                }
            elif account.get("proxy"):
                proxy_data = account.get("proxy")
            proxy_tuple = self.parse_proxy(proxy_data)

        proxy_arg: Any = proxy_tuple
        return TelegramClient(session_file, api_id, api_hash, proxy=proxy_arg)

    def load_proxies_file(self, file_path: Path | None = None) -> list[dict[str, Any]]:
        path = file_path or settings.proxies_file_path
        if not path.exists():
            return []
        proxies = []
        text = path.read_text(encoding="utf-8", errors="ignore")
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            parsed = self.parse_proxy_string(line)
            if parsed:
                proxies.append(parsed)
        return proxies

    async def get_next_available_proxy(
        self, file_path: Path | None = None
    ) -> dict[str, Any] | None:
        proxies = self.load_proxies_file(file_path)
        if not proxies:
            return None
        accounts = await self.db.get_accounts()
        used_keys = set()
        for acc in accounts:
            if acc.get("proxy_host"):
                used_keys.add((acc.get("proxy_host"), acc.get("proxy_port"), acc.get("proxy_user")))
        for p in proxies:
            key = (p["host"], p["port"], p.get("username"))
            if key not in used_keys:
                return p
        return proxies[len(accounts) % len(proxies)]

    async def assign_proxies_from_file(self, file_path: Path | None = None) -> int:
        proxies = self.load_proxies_file(file_path)
        if not proxies:
            return 0
        unassigned = await self.db.get_accounts_without_proxy()
        if not unassigned:
            return 0
        all_accounts = await self.db.get_accounts()
        used_keys = set()
        for acc in all_accounts:
            if acc.get("proxy_host"):
                used_keys.add((acc.get("proxy_host"), acc.get("proxy_port"), acc.get("proxy_user")))
        available = [
            p for p in proxies if (p["host"], p["port"], p.get("username")) not in used_keys
        ]
        assigned_count = 0
        for idx, acc in enumerate(unassigned):
            phone = acc["phone"]
            if available:
                proxy_data = available.pop(0)
            else:
                proxy_data = proxies[idx % len(proxies)]
            used_keys.add((proxy_data["host"], proxy_data["port"], proxy_data.get("username")))
            await self.db.update_account_proxy(
                phone=phone,
                proxy_type=proxy_data.get("type", "socks5"),
                proxy_host=proxy_data["host"],
                proxy_port=proxy_data["port"],
                proxy_user=proxy_data.get("username"),
                proxy_password=proxy_data.get("password"),
            )
            assigned_count += 1
        if assigned_count > 0:
            logger.info(f"Assigned {assigned_count} new proxies to accounts")
        return assigned_count

    async def sync_accounts_to_db(self) -> int:
        await self.assign_proxies_from_file()
        accounts = await self.db.get_accounts()
        return len(accounts)

    async def add_or_update_account_entry(self, account_data: dict[str, Any]) -> None:
        phone = account_data["phone"]
        api_id = int(account_data["api_id"])
        api_hash = str(account_data["api_hash"])
        proxy = account_data.get("proxy") or {}
        port_val = proxy.get("port")
        proxy_port = int(port_val) if port_val is not None else None
        limit_val = account_data.get("daily_limit")
        daily_limit = int(limit_val) if limit_val is not None else settings.daily_limit_per_account
        await self.db.save_account(
            phone=phone,
            api_id=api_id,
            api_hash=api_hash,
            proxy_type=proxy.get("type"),
            proxy_host=proxy.get("host"),
            proxy_port=proxy_port,
            proxy_user=proxy.get("username"),
            proxy_password=proxy.get("password"),
            daily_limit=daily_limit,
        )
        await self.assign_proxies_from_file()

    async def check_account_health(
        self,
        account_data: dict[str, Any],
        force_no_proxy: bool = False,
        override_proxy: dict[str, Any] | str | None = None,
    ) -> dict[str, Any]:
        client: Any = self.create_client(
            account_data, force_no_proxy=force_no_proxy, override_proxy=override_proxy
        )
        phone = account_data["phone"]
        try:
            await client.connect()
            if not await client.is_user_authorized():
                await client.disconnect()
                await self.db.update_account_state(phone, status="UNAUTHORIZED")
                return {"phone": phone, "status": "UNAUTHORIZED", "authorized": False}

            me = await client.get_me()
            await client.disconnect()
            await self.db.update_account_state(phone, status="ACTIVE")
            return {
                "phone": phone,
                "status": "ACTIVE",
                "authorized": True,
                "id": me.id,
                "first_name": me.first_name,
                "username": me.username,
            }
        except Exception as e:
            try:
                await client.disconnect()
            except Exception:
                pass
            err_msg = str(e)
            await self.db.update_account_state(phone, status="ERROR")
            return {
                "phone": phone,
                "status": "ERROR",
                "authorized": False,
                "error": err_msg,
            }

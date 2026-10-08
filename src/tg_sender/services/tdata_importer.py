import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any, cast

from telethon import TelegramClient
from TGConvertor import SessionManager

from tg_sender.config.settings import settings
from tg_sender.core.client_manager import ClientManager
from tg_sender.db.database import Database


class TDataImporter:
    PHONE_REGEX = re.compile(r"\+?([0-9]{10,15})")

    def __init__(self, db: Database, client_manager: ClientManager):
        self.db = db
        self.client_manager = client_manager
        self.sessions_dir = settings.sessions_dir

    def extract_all_zips(self, source_dir: Path, target_dir: Path) -> int:
        archives_count = 0
        target_dir.mkdir(parents=True, exist_ok=True)

        for zip_path in list(source_dir.rglob("*.zip")):
            try:
                dest_subfolder = target_dir / f"extracted_{archives_count}_{zip_path.stem}"
                dest_subfolder.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(zip_path, "r") as zf:
                    zf.extractall(dest_subfolder)
                archives_count += 1
            except Exception:
                pass

        while True:
            nested_zips = list(target_dir.rglob("*.zip"))
            if not nested_zips:
                break
            for n_zip in nested_zips:
                try:
                    nested_dest = n_zip.parent / f"nested_{archives_count}_{n_zip.stem}"
                    nested_dest.mkdir(parents=True, exist_ok=True)
                    with zipfile.ZipFile(n_zip, "r") as zf:
                        zf.extractall(nested_dest)
                    archives_count += 1
                except Exception:
                    pass
                finally:
                    try:
                        n_zip.unlink(missing_ok=True)
                    except Exception:
                        pass

        return archives_count

    def is_tdata_folder(self, path: Path) -> bool:
        if not path.is_dir():
            return False
        if (path / "key_datas").exists():
            return True
        for item in path.iterdir():
            if item.is_file() and len(item.name) == 16 and (path / "settingss").exists():
                return True
        return False

    def find_tdata_directories(self, search_paths: list[Path]) -> list[Path]:
        found: set[Path] = set()
        for root in search_paths:
            if not root.exists():
                continue
            if self.is_tdata_folder(root):
                found.add(root.resolve())
            for sub in root.rglob("*"):
                if sub.is_dir() and self.is_tdata_folder(sub):
                    found.add(sub.resolve())
        return sorted(found)

    def detect_proxy(self, tdata_dir: Path) -> dict[str, Any] | None:
        check_dirs = [tdata_dir, tdata_dir.parent]
        if tdata_dir.parent.parent != tdata_dir.parent:
            check_dirs.append(tdata_dir.parent.parent)

        for d in check_dirs:
            for txt_name in ["proxy.txt", "proxies.txt"]:
                pf = d / txt_name
                if pf.exists():
                    text = pf.read_text(encoding="utf-8", errors="ignore").strip()
                    for line in text.splitlines():
                        parsed = self.parse_proxy_string(line)
                        if parsed:
                            return parsed

            for json_name in ["proxy.json", "config.json"]:
                jf = d / json_name
                if jf.exists():
                    try:
                        data = json.loads(jf.read_text(encoding="utf-8", errors="ignore"))
                        if isinstance(data, dict):
                            if "proxy" in data and isinstance(data["proxy"], str):
                                return self.parse_proxy_string(data["proxy"])
                            if "host" in data and "port" in data:
                                return {
                                    "type": data.get("type", "socks5"),
                                    "host": data["host"],
                                    "port": int(data["port"]),
                                    "username": data.get("username") or data.get("user"),
                                    "password": data.get("password") or data.get("pass"),
                                }
                    except Exception:
                        pass
        return None

    def parse_proxy_string(self, raw: str) -> dict[str, Any] | None:
        return ClientManager.parse_proxy_string(raw)

    def detect_phone_from_path(self, path: Path) -> str | None:
        for segment in [path.name, path.parent.name, path.parent.parent.name]:
            match = self.PHONE_REGEX.search(segment)
            if match:
                digits = match.group(1)
                return f"+{digits}"
        return None

    async def import_single_tdata(
        self,
        tdata_dir: Path,
        temp_dir: Path,
        default_api_id: int = 2040,
        default_api_hash: str = "b18441a1ff607e10a989891a5462e627",
        force_no_proxy: bool = False,
        override_proxy: dict[str, Any] | str | None = None,
    ) -> dict[str, Any]:
        session_mgr = SessionManager.from_tdata_folder(tdata_dir)
        user_id = session_mgr.user_id

        if force_no_proxy:
            proxy_data = None
        elif override_proxy:
            proxy_data = (
                self.parse_proxy_string(override_proxy)
                if isinstance(override_proxy, str)
                else override_proxy
            )
        else:
            proxy_data = self.detect_proxy(tdata_dir)
            if not proxy_data:
                proxy_data = await self.client_manager.get_next_available_proxy()

        detected_phone = self.detect_phone_from_path(tdata_dir)
        temp_session_file = temp_dir / f"td_{user_id}.session"
        await session_mgr.to_telethon_file(temp_session_file)

        phone = detected_phone or f"+{user_id}"
        first_name = None
        username = None

        try:
            proxy_tuple = None if force_no_proxy else self.client_manager.parse_proxy(proxy_data)
            client: Any = TelegramClient(
                str(temp_session_file),
                default_api_id,
                default_api_hash,
                proxy=cast(Any, proxy_tuple),
            )
            await client.connect()
            if await client.is_user_authorized():
                me = await client.get_me()
                if me:
                    if me.phone:
                        phone = f"+{me.phone}"
                    first_name = me.first_name
                    username = me.username
            disconnect_res = client.disconnect()
            if disconnect_res is not None:
                await disconnect_res
        except Exception:
            pass

        safe_phone = phone.replace("+", "").strip()
        final_session_file = self.sessions_dir / f"{safe_phone}.session"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(temp_session_file, final_session_file)

        account_entry = {
            "phone": phone,
            "api_id": default_api_id,
            "api_hash": default_api_hash,
            "proxy": proxy_data,
            "daily_limit": settings.daily_limit_per_account,
        }

        await self.client_manager.add_or_update_account_entry(account_entry)

        return {
            "phone": phone,
            "user_id": user_id,
            "first_name": first_name,
            "username": username,
            "proxy": proxy_data,
            "status": "IMPORTED",
            "session_file": str(final_session_file),
        }

    async def process_inbox(
        self,
        inbox_dir: Path | None = None,
        clean_inbox: bool = False,
        force_no_proxy: bool = False,
        override_proxy: dict[str, Any] | str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        target_inbox = (inbox_dir or settings.tdata_inbox_dir).resolve()
        target_inbox.mkdir(parents=True, exist_ok=True)

        temp_dir = Path(tempfile.mkdtemp(prefix="tdata_work_"))
        results = []
        archives_unpacked = 0

        try:
            archives_unpacked = self.extract_all_zips(target_inbox, temp_dir)
            tdata_folders = self.find_tdata_directories([target_inbox, temp_dir])

            for tdata_path in tdata_folders:
                try:
                    res = await self.import_single_tdata(
                        tdata_path,
                        temp_dir,
                        force_no_proxy=force_no_proxy,
                        override_proxy=override_proxy,
                    )
                    results.append(res)
                except Exception as ex:
                    results.append(
                        {
                            "path": str(tdata_path),
                            "status": "ERROR",
                            "error": str(ex),
                        }
                    )

            if clean_inbox:
                for item in target_inbox.iterdir():
                    try:
                        if item.is_file():
                            item.unlink()
                        elif item.is_dir():
                            shutil.rmtree(item)
                    except Exception:
                        pass

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        await self.client_manager.assign_proxies_from_file()
        return results, archives_unpacked

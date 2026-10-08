import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger
from telethon import TelegramClient
from telethon.tl.functions.contacts import ImportContactsRequest
from telethon.tl.types import InputPhoneContact

from tg_sender.config.settings import settings
from tg_sender.core.anti_flood import FloodHandler
from tg_sender.core.client_manager import ClientManager
from tg_sender.core.spintax import SpintaxParser
from tg_sender.db.database import Database


class SenderEngine:
    def __init__(
        self,
        db: Database,
        client_manager: ClientManager,
        min_delay: int | None = None,
        max_delay: int | None = None,
        typing_duration: int | None = None,
        force_no_proxy: bool = False,
        override_proxy: dict[str, Any] | str | None = None,
        concurrency: int | None = None,
    ):
        self.db = db
        self.client_manager = client_manager
        self.min_delay = min_delay or settings.min_delay_seconds
        self.max_delay = max_delay or settings.max_delay_seconds
        self.typing_duration = typing_duration or settings.typing_duration_seconds
        self.force_no_proxy = force_no_proxy
        self.override_proxy = override_proxy
        self.concurrency = concurrency
        self.active_clients: dict[str, TelegramClient] = {}
        self.last_sent_timestamps: dict[str, float] = {}
        self._is_running = False

    def stop(self) -> None:
        self._is_running = False

    async def _get_or_create_client(self, account: dict[str, Any]) -> TelegramClient:
        phone = account["phone"]
        if phone not in self.active_clients:
            client = self.client_manager.create_client(
                account,
                force_no_proxy=self.force_no_proxy,
                override_proxy=self.override_proxy,
            )
            await client.connect()
            self.active_clients[phone] = client
        return self.active_clients[phone]

    async def close_clients(self) -> None:
        for client in self.active_clients.values():
            try:
                res = client.disconnect()
                if res is not None:
                    await res
            except Exception:
                pass
        self.active_clients.clear()

    async def _resolve_entity(
        self, client: TelegramClient, recipient: str, first_name: str | None = None
    ):
        if recipient.startswith("+"):
            phone_digits = recipient.replace("+", "").strip()
            contact_obj = InputPhoneContact(
                client_id=0,
                phone=phone_digits,
                first_name=first_name or "Contact",
                last_name="",
            )
            res = await client(ImportContactsRequest([contact_obj]))
            if res.users:
                return res.users[0]
            raise ValueError(f"Cannot find any entity corresponding to phone {recipient}")
        return await client.get_input_entity(recipient)

    async def _filter_eligible_accounts(
        self, accounts: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        now_dt = datetime.now(UTC)
        eligible = []
        for acc in accounts:
            phone = acc["phone"]
            db_acc = await self.db.get_account(phone)
            if not db_acc:
                continue
            if db_acc["status"] not in ("ACTIVE", "OK"):
                continue
            if db_acc["sent_today"] >= db_acc["daily_limit"]:
                continue
            cooldown_iso = db_acc["cooldown_until"]
            if cooldown_iso:
                cooldown_dt = datetime.fromisoformat(cooldown_iso)
                if cooldown_dt > now_dt:
                    continue
            eligible.append(db_acc)
        return eligible

    async def run(
        self,
        template: str,
        media_path: Path | None = None,
        dry_run: bool = False,
        limit: int | None = None,
        event_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, int]:
        self._is_running = True
        stats = {
            "processed": 0,
            "success": 0,
            "failed": 0,
            "skipped": 0,
        }

        await self.db.reset_daily_limits_if_needed()
        all_accounts = await self.db.get_accounts()
        if not all_accounts and not dry_run:
            if event_callback:
                event_callback({"type": "error", "message": "No accounts found in database"})
            return stats

        pending_contacts = await self.db.get_pending_contacts(limit=limit)
        if not pending_contacts:
            if event_callback:
                event_callback({"type": "info", "message": "No pending contacts to process"})
            return stats

        queue: asyncio.Queue = asyncio.Queue()
        for c in pending_contacts:
            await queue.put(c)

        if dry_run:
            worker_count = self.concurrency or min(len(all_accounts) if all_accounts else 1, 3)
            worker_count = max(1, worker_count)
            sim_accounts = (
                all_accounts
                if all_accounts
                else [{"phone": f"SIM_{i + 1}"} for i in range(worker_count)]
            )

            async def _dry_worker(sim_acc: dict[str, Any]):
                phone = sim_acc["phone"]
                while not queue.empty() and self._is_running:
                    try:
                        contact = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    recipient = contact["recipient"]
                    extra_data = contact.get("extra_data") or {}
                    rendered = SpintaxParser.render(template, extra_data)
                    stats["processed"] += 1
                    stats["success"] += 1
                    if event_callback:
                        event_callback(
                            {
                                "type": "item_processed",
                                "status": "DRY_RUN",
                                "recipient": recipient,
                                "account": phone,
                                "message_preview": rendered,
                            }
                        )
                    await asyncio.sleep(0.15)
                    queue.task_done()

            workers = [
                asyncio.create_task(_dry_worker(sim_accounts[i % len(sim_accounts)]))
                for i in range(worker_count)
            ]
            await asyncio.gather(*workers, return_exceptions=True)
            self._is_running = False
            return stats

        eligible_accounts = await self._filter_eligible_accounts(all_accounts)
        if not eligible_accounts:
            if event_callback:
                event_callback(
                    {
                        "type": "warning",
                        "message": "No eligible active accounts available (all in cooldown or reached daily limit).",
                    }
                )
            return stats

        if self.concurrency and self.concurrency > 0:
            active_worker_accounts = eligible_accounts[: self.concurrency]
        else:
            active_worker_accounts = eligible_accounts

        if event_callback:
            event_callback(
                {
                    "type": "info",
                    "message": f"Starting {len(active_worker_accounts)} parallel account workers for {queue.qsize()} contacts.",
                }
            )

        async def _account_worker(account: dict[str, Any]):
            phone = account["phone"]
            try:
                client = await self._get_or_create_client(account)
            except Exception as err:
                if event_callback:
                    event_callback(
                        {"type": "error", "message": f"Worker connection failed for {phone}: {err}"}
                    )
                return

            while not queue.empty() and self._is_running:
                db_acc = await self.db.get_account(phone)
                if not db_acc or db_acc["sent_today"] >= db_acc["daily_limit"]:
                    if event_callback:
                        event_callback(
                            {
                                "type": "info",
                                "message": f"Account {phone} reached daily limit ({db_acc.get('daily_limit') if db_acc else 0}). Worker stopping.",
                            }
                        )
                    break

                try:
                    contact = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

                recipient = contact["recipient"]
                first_name = contact["first_name"]
                extra_data = contact.get("extra_data") or {}
                rendered_text = SpintaxParser.render(template, extra_data)

                last_sent = self.last_sent_timestamps.get(phone, 0.0)
                target_delay = FloodHandler.get_random_delay(self.min_delay, self.max_delay)
                elapsed = asyncio.get_event_loop().time() - last_sent
                if elapsed < target_delay and last_sent > 0:
                    wait_for = target_delay - elapsed
                    if event_callback:
                        event_callback({"type": "delay", "account": phone, "seconds": wait_for})
                    await asyncio.sleep(wait_for)

                if not self._is_running:
                    await queue.put(contact)
                    queue.task_done()
                    break

                stats["processed"] += 1

                try:
                    entity = await self._resolve_entity(client, recipient, first_name)
                    await FloodHandler.simulate_typing(client, entity, self.typing_duration)
                    if media_path and media_path.exists():
                        await client.send_file(entity, file=str(media_path), caption=rendered_text)
                    else:
                        await client.send_message(entity, rendered_text)

                    self.last_sent_timestamps[phone] = asyncio.get_event_loop().time()
                    await self.db.update_contact_status(recipient, "SENT", account_phone=phone)
                    await self.db.update_account_state(phone, increment_sent=True)
                    await self.db.save_send_log(recipient, phone, rendered_text, "SENT")
                    stats["success"] += 1
                    logger.info(f"[{phone}] Message delivered to {recipient}")

                    if event_callback:
                        event_callback(
                            {
                                "type": "item_processed",
                                "status": "SENT",
                                "recipient": recipient,
                                "account": phone,
                                "message_preview": rendered_text,
                            }
                        )

                except Exception as exc:
                    err_type, cooldown_iso, _ = FloodHandler.classify_error(exc)
                    err_msg = str(exc)
                    logger.warning(
                        f"[{phone}] Sending failed for {recipient}: {err_type} - {err_msg}"
                    )

                    if err_type in ("FLOOD_WAIT", "PEER_FLOOD"):
                        await self.db.update_account_state(
                            phone, cooldown_until=cooldown_iso, status="COOLDOWN"
                        )
                        await queue.put(contact)
                        stats["skipped"] += 1
                        if event_callback:
                            event_callback(
                                {
                                    "type": "account_cooldown",
                                    "account": phone,
                                    "reason": err_type,
                                    "cooldown_until": cooldown_iso,
                                }
                            )
                        queue.task_done()
                        break
                    elif err_type == "ACCOUNT_BANNED":
                        await self.db.update_account_state(phone, status="BANNED")
                        await queue.put(contact)
                        stats["skipped"] += 1
                        if event_callback:
                            event_callback(
                                {
                                    "type": "account_banned",
                                    "account": phone,
                                    "error": err_msg,
                                }
                            )
                        queue.task_done()
                        break
                    elif err_type == "PRIVACY_RESTRICTED":
                        await self.db.update_contact_status(
                            recipient,
                            "PRIVACY_RESTRICTED",
                            account_phone=phone,
                            error_message=err_msg,
                        )
                        await self.db.save_send_log(
                            recipient, phone, rendered_text, "PRIVACY_RESTRICTED", err_msg
                        )
                        stats["failed"] += 1
                        if event_callback:
                            event_callback(
                                {
                                    "type": "item_processed",
                                    "status": "PRIVACY_RESTRICTED",
                                    "recipient": recipient,
                                    "account": phone,
                                    "error": err_msg,
                                }
                            )
                    elif err_type == "USER_NOT_FOUND":
                        await self.db.update_contact_status(
                            recipient, "USER_NOT_FOUND", account_phone=phone, error_message=err_msg
                        )
                        await self.db.save_send_log(
                            recipient, phone, rendered_text, "USER_NOT_FOUND", err_msg
                        )
                        stats["failed"] += 1
                        if event_callback:
                            event_callback(
                                {
                                    "type": "item_processed",
                                    "status": "USER_NOT_FOUND",
                                    "recipient": recipient,
                                    "account": phone,
                                    "error": err_msg,
                                }
                            )
                    else:
                        await self.db.update_contact_status(
                            recipient, "FAILED", account_phone=phone, error_message=err_msg
                        )
                        await self.db.save_send_log(
                            recipient, phone, rendered_text, "FAILED", err_msg
                        )
                        stats["failed"] += 1
                        if event_callback:
                            event_callback(
                                {
                                    "type": "item_processed",
                                    "status": "FAILED",
                                    "recipient": recipient,
                                    "account": phone,
                                    "error": err_msg,
                                }
                            )
                finally:
                    queue.task_done()

        try:
            tasks = [asyncio.create_task(_account_worker(acc)) for acc in active_worker_accounts]
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            await self.close_clients()
            self._is_running = False

        return stats

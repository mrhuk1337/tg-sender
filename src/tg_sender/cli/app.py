import asyncio
from pathlib import Path

import typer

from tg_sender.cli.ui import (
    console,
    print_accounts_table,
    print_banner,
    print_contacts_stats_table,
    print_event,
    print_tdata_import_results,
)
from tg_sender.config.logger import init_logger
from tg_sender.config.settings import settings
from tg_sender.core.client_manager import ClientManager
from tg_sender.core.engine import SenderEngine
from tg_sender.core.spintax import SpintaxParser
from tg_sender.db.database import Database
from tg_sender.services.importer import ContactImporter
from tg_sender.services.reporter import Reporter
from tg_sender.services.tdata_importer import TDataImporter

app = typer.Typer(help="TG-Sender mass messaging management CLI")
accounts_app = typer.Typer(help="Manage Telegram accounts and proxies")
contacts_app = typer.Typer(help="Manage recipient contacts")

app.add_typer(accounts_app, name="accounts")
app.add_typer(contacts_app, name="contacts")


def get_db() -> Database:
    settings.setup_directories()
    init_logger()
    return Database(settings.db_path)


@accounts_app.command("list")
def list_accounts():
    async def _runner():
        db = get_db()
        await db.init_db()
        cm = ClientManager(db)
        await cm.sync_accounts_to_db()
        accounts = await db.get_accounts()
        print_banner()
        print_accounts_table(accounts)

    asyncio.run(_runner())


@accounts_app.command("assign-proxies")
def assign_proxies_command(
    file: Path | None = typer.Option(
        None, "--file", "-f", help="Path to text file with proxies list"
    ),
):
    async def _runner():
        print_banner()
        db = get_db()
        await db.init_db()
        cm = ClientManager(db)
        await cm.sync_accounts_to_db()
        assigned = await cm.assign_proxies_from_file(file_path=file)
        if assigned > 0:
            console.print(f"[bold green]Assigned {assigned} new proxies to accounts![/bold green]")
        else:
            console.print(
                "[yellow]No accounts pending proxy assignment or no new proxies available.[/yellow]"
            )
        accounts = await db.get_accounts()
        print_accounts_table(accounts)

    asyncio.run(_runner())


@accounts_app.command("check")
def check_accounts(
    no_proxy: bool = typer.Option(False, "--no-proxy", help="Test accounts directly without proxy"),
    proxy: str | None = typer.Option(
        None, "--proxy", "-p", help="Test accounts using specified proxy override"
    ),
):
    async def _runner():
        print_banner()
        db = get_db()
        await db.init_db()
        cm = ClientManager(db)
        await cm.sync_accounts_to_db()
        accounts = await db.get_accounts()
        if not accounts:
            console.print(
                "[yellow]No accounts registered yet. Use 'accounts import-tdata' to import accounts.[/yellow]"
            )
            return

        if no_proxy:
            console.print("[yellow]Connection Mode: DIRECT (all proxies disabled)[/yellow]")
        elif proxy:
            console.print(f"[cyan]Connection Mode: OVERRIDE PROXY ({proxy})[/cyan]")
        else:
            console.print("[dim]Connection Mode: ACCOUNT DEFAULT (per-account proxy)[/dim]")

        for acc in accounts:
            console.print(f"Checking account [cyan]{acc['phone']}[/cyan]...")
            res = await cm.check_account_health(acc, force_no_proxy=no_proxy, override_proxy=proxy)
            if res.get("authorized"):
                console.print(
                    f"  [green]OK[/green]: {res.get('first_name')} (@{res.get('username')})"
                )
            else:
                console.print(f"  [red]FAILED[/red]: {res.get('status')} - {res.get('error')}")

        accounts_refreshed = await db.get_accounts()
        print_accounts_table(accounts_refreshed)

    asyncio.run(_runner())


@accounts_app.command("import-tdata")
def import_tdata_accounts(
    path: Path | None = typer.Option(
        None, "--path", "-p", help="Directory where zip archives and tdata folders are located"
    ),
    clean: bool = typer.Option(False, "--clean", help="Clean up inbox directory after processing"),
    no_proxy: bool = typer.Option(False, "--no-proxy", help="Import all accounts without proxies"),
    proxy: str | None = typer.Option(
        None, "--proxy", help="Assign specified proxy to all imported accounts"
    ),
):
    async def _runner():
        print_banner()
        db = get_db()
        await db.init_db()
        cm = ClientManager(db)
        importer = TDataImporter(db, cm)
        target_path = path or settings.tdata_inbox_dir
        console.print(
            f"[cyan]Scanning folder: [bold]{target_path}[/bold] for zip archives and tdata folders...[/cyan]"
        )
        results, archives_count = await importer.process_inbox(
            inbox_dir=target_path,
            clean_inbox=clean,
            force_no_proxy=no_proxy,
            override_proxy=proxy,
        )
        print_tdata_import_results(results, archives_count)
        accounts_refreshed = await db.get_accounts()
        console.print(
            f"[bold green]Current total accounts in pool: {len(accounts_refreshed)}[/bold green]"
        )

    asyncio.run(_runner())


@contacts_app.command("import")
def import_contacts(file_path: Path = typer.Argument(..., help="Path to CSV, XLSX, or TXT file")):
    async def _runner():
        print_banner()
        db = get_db()
        await db.init_db()

        try:
            records = ContactImporter.import_from_file(file_path)
            console.print(f"[cyan]Parsed {len(records)} candidate contacts from file.[/cyan]")
            inserted, skipped = await db.bulk_add_contacts(records)
            console.print(
                f"[bold green]Import finished:[/bold green] {inserted} added to queue, {skipped} duplicates or invalid skipped."
            )
        except Exception as e:
            console.print(f"[bold red]Import error: {e}[/bold red]")

    asyncio.run(_runner())


@contacts_app.command("clear")
def clear_contacts(
    status: str | None = typer.Option(
        None,
        "--status",
        "-s",
        help="Status to clear (PENDING, SENT, FAILED, etc.) or omit to clear all",
    ),
):
    async def _runner():
        db = get_db()
        await db.init_db()
        count = await db.clear_contacts(status=status)
        console.print(f"[yellow]Cleared {count} contacts with status {status or 'ALL'}.[/yellow]")

    asyncio.run(_runner())


@contacts_app.command("list")
def list_contacts(
    status: str | None = typer.Option("PENDING", "--status", "-s", help="Status filter"),
    limit: int = typer.Option(50, "--limit", "-l", help="Number of contacts to display"),
):
    async def _runner():
        print_banner()
        db = get_db()
        await db.init_db()
        contacts = await db.get_all_contacts(status=status)
        console.print(f"[bold]Total contacts matching status '{status}': {len(contacts)}[/bold]")
        for c in contacts[:limit]:
            console.print(
                f"- [cyan]{c['recipient']}[/cyan] ({c.get('first_name') or 'No name'}) | extra: [dim]{c.get('extra_data')}[/dim]"
            )

    asyncio.run(_runner())


@app.command("stats")
def show_stats():
    async def _runner():
        print_banner()
        db = get_db()
        await db.init_db()
        reporter = Reporter(db)
        summary = await reporter.get_summary()
        print_contacts_stats_table(summary)

    asyncio.run(_runner())


@app.command("export")
def export_report(
    output_path: Path = typer.Argument(..., help="Destination path (.csv or .xlsx)"),
    status: str | None = typer.Option(None, "--status", "-s", help="Optional status filter"),
):
    async def _runner():
        print_banner()
        db = get_db()
        await db.init_db()
        reporter = Reporter(db)
        suffix = output_path.suffix.lower()
        if suffix == ".xlsx":
            count = await reporter.export_to_excel(output_path, status=status)
        else:
            count = await reporter.export_to_csv(output_path, status=status)
        console.print(
            f"[bold green]Report exported successfully:[/bold green] {count} rows saved to [cyan]{output_path}[/cyan]"
        )

    asyncio.run(_runner())


@app.command("preview")
def preview_template(
    template: str = typer.Option(
        ..., "--template", "-t", help="Template string or path to template file"
    ),
    sample_name: str = typer.Option(
        "Алексей", "--name", help="Sample name for variable substitution"
    ),
    count: int = typer.Option(
        3, "--count", "-c", help="Number of Spintax variation samples to generate"
    ),
):
    print_banner()
    text = template
    path = Path(template)
    if path.exists() and path.is_file():
        text = path.read_text(encoding="utf-8")

    console.print("[bold cyan]Template preview with Spintax:[/bold cyan]")
    sample_vars = {"name": sample_name, "first_name": sample_name, "recipient": "@sample_user"}
    for i in range(1, count + 1):
        rendered = SpintaxParser.render(text, sample_vars)
        console.print(f"[bold yellow]Sample [{i}]:[/bold yellow]\n{rendered}\n{'-' * 40}")


@app.command("send")
def run_sender(
    template: str = typer.Option(
        ..., "--template", "-t", help="Template text or path to file (.txt / .md)"
    ),
    media: Path | None = typer.Option(None, "--media", "-m", help="Path to media file attachment"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Simulate execution without sending actual messages"
    ),
    limit: int | None = typer.Option(
        None, "--limit", "-l", help="Max contacts to send in this batch"
    ),
    min_delay: int | None = typer.Option(
        None, "--min-delay", help="Minimum jitter delay in seconds"
    ),
    max_delay: int | None = typer.Option(
        None, "--max-delay", help="Maximum jitter delay in seconds"
    ),
    no_proxy: bool = typer.Option(
        False, "--no-proxy", help="Run without proxies (direct connection for all accounts)"
    ),
    proxy: str | None = typer.Option(
        None,
        "--proxy",
        "-p",
        help="Override with single proxy (e.g. socks5://host:port or host:port:user:pass)",
    ),
    concurrency: int | None = typer.Option(
        None,
        "--concurrency",
        "-c",
        help="Max parallel account workers (defaults to all eligible accounts)",
    ),
):
    async def _runner():
        print_banner()
        db = get_db()
        await db.init_db()
        cm = ClientManager(db)
        await cm.sync_accounts_to_db()

        tmpl_text = template
        tmpl_path = Path(template)
        if tmpl_path.exists() and tmpl_path.is_file():
            tmpl_text = tmpl_path.read_text(encoding="utf-8")

        if dry_run:
            console.print(
                "[bold yellow]*** RUNNING IN DRY-RUN MODE (NO ACTUAL MESSAGES SENT) ***[/bold yellow]"
            )

        if no_proxy:
            console.print("[yellow]Proxy Mode: DIRECT (all proxies disabled)[/yellow]")
        elif proxy:
            console.print(f"[cyan]Proxy Mode: OVERRIDE ({proxy})[/cyan]")
        else:
            console.print("[dim]Proxy Mode: DEFAULT (using per-account proxy configurations)[/dim]")

        engine = SenderEngine(
            db=db,
            client_manager=cm,
            min_delay=min_delay,
            max_delay=max_delay,
            force_no_proxy=no_proxy,
            override_proxy=proxy,
            concurrency=concurrency,
        )

        stats = await engine.run(
            template=tmpl_text,
            media_path=media,
            dry_run=dry_run,
            limit=limit,
            event_callback=print_event,
        )

        console.print("\n[bold green]Execution completed![/bold green]")
        console.print(
            f"Processed: {stats['processed']} | Success: {stats['success']} | Failed: {stats['failed']} | Skipped: {stats['skipped']}"
        )

    asyncio.run(_runner())

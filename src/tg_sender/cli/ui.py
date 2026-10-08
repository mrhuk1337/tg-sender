from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def print_banner() -> None:
    banner = "[bold cyan]TG-SENDER[/bold cyan] - [dim]Personal Contact Bulk Messaging System[/dim]"
    console.print(Panel(banner, border_style="cyan"))


def print_accounts_table(accounts: list[dict[str, Any]]) -> None:
    table = Table(title="Telegram Accounts Pool", border_style="blue")
    table.add_column("Phone", style="cyan", no_wrap=True)
    table.add_column("API ID", style="dim")
    table.add_column("Proxy", style="magenta")
    table.add_column("Sent Today", justify="right")
    table.add_column("Daily Limit", justify="right")
    table.add_column("Status", style="bold")
    table.add_column("Cooldown", style="yellow")

    for acc in accounts:
        proxy_info = "Direct"
        if acc.get("proxy_host"):
            proxy_info = f"{acc.get('proxy_type', 'socks5')}://{acc.get('proxy_host')}:{acc.get('proxy_port')}"

        status = acc.get("status", "ACTIVE")
        status_color = "green" if status == "ACTIVE" else "red" if status == "BANNED" else "yellow"

        table.add_row(
            acc.get("phone", ""),
            str(acc.get("api_id", "")),
            proxy_info,
            str(acc.get("sent_today", 0)),
            str(acc.get("daily_limit", 20)),
            f"[{status_color}]{status}[/{status_color}]",
            str(acc.get("cooldown_until") or "-"),
        )
    console.print(table)


def print_tdata_import_results(results: list[dict[str, Any]], archives_count: int) -> None:
    console.print(
        f"[bold cyan]TData Inbox Ingestion Summary[/bold cyan] (Unpacked archives: {archives_count})"
    )
    if not results:
        console.print("[yellow]No TData folders or accounts were detected.[/yellow]")
        return

    table = Table(title="Imported Accounts from TData", border_style="green")
    table.add_column("Account Phone", style="cyan")
    table.add_column("User ID", style="dim")
    table.add_column("Name / User", style="bold")
    table.add_column("Proxy", style="magenta")
    table.add_column("Status", style="bold")

    for item in results:
        status = item.get("status", "ERROR")
        color = "green" if status == "IMPORTED" else "red"
        proxy_data = item.get("proxy")
        proxy_str = "Direct"
        if proxy_data and proxy_data.get("host"):
            proxy_str = f"{proxy_data.get('type', 'socks5')}://{proxy_data.get('host')}:{proxy_data.get('port')}"

        name_str = item.get("first_name") or ""
        if item.get("username"):
            name_str = (
                f"{name_str} (@{item.get('username')})" if name_str else f"@{item.get('username')}"
            )

        table.add_row(
            str(item.get("phone") or item.get("path") or "Unknown"),
            str(item.get("user_id") or "-"),
            name_str or "-",
            proxy_str,
            f"[{color}]{status}[/{color}]",
        )
    console.print(table)


def print_contacts_stats_table(stats: dict[str, Any]) -> None:
    table = Table(title="Campaign Contacts Status", border_style="green")
    table.add_column("Status", style="bold")
    table.add_column("Count", justify="right")

    contacts_by_status = stats.get("contacts", {})
    status_colors = {
        "PENDING": "cyan",
        "SENT": "green",
        "FAILED": "red",
        "PRIVACY_RESTRICTED": "magenta",
        "USER_NOT_FOUND": "dim",
        "COOLDOWN": "yellow",
    }

    for status_key, count in sorted(contacts_by_status.items()):
        color = status_colors.get(status_key, "white")
        table.add_row(f"[{color}]{status_key}[/{color}]", str(count))

    table.add_section()
    table.add_row("[bold]Total Contacts[/bold]", str(stats.get("total_contacts", 0)))
    table.add_row("[bold]Total Accounts[/bold]", str(stats.get("total_accounts", 0)))
    table.add_row("[bold]Active Accounts[/bold]", str(stats.get("active_accounts", 0)))
    console.print(table)


def print_event(event: dict[str, Any]) -> None:
    ev_type = event.get("type")
    if ev_type == "item_processed":
        st = event.get("status")
        rec = event.get("recipient")
        acc = event.get("account")
        if st in ("SENT", "DRY_RUN"):
            msg_prev = event.get("message_preview", "").replace("\n", " ")
            if len(msg_prev) > 40:
                msg_prev = msg_prev[:37] + "..."
            console.print(
                f'[{"green" if st == "SENT" else "blue"}][{st}][/{"green" if st == "SENT" else "blue"}] [bold]{rec}[/bold] via [dim]{acc}[/dim] -> "{msg_prev}"'
            )
        else:
            err = event.get("error", "")
            console.print(f"[red][{st}][/red] [bold]{rec}[/bold] via [dim]{acc}[/dim]: {err}")
    elif ev_type == "delay":
        acc = event.get("account")
        sec = event.get("seconds", 0)
        console.print(f"[dim]⏳ Account {acc} sleeping for {sec:.1f}s (anti-flood jitter)...[/dim]")
    elif ev_type == "account_cooldown":
        acc = event.get("account")
        reason = event.get("reason")
        until = event.get("cooldown_until")
        console.print(
            f"[yellow]⚠️ Account {acc} placed in cooldown ({reason}) until {until}[/yellow]"
        )
    elif ev_type == "account_banned":
        acc = event.get("account")
        err = event.get("error")
        console.print(f"[bold red]❌ Account {acc} is restricted or banned: {err}[/bold red]")
    elif ev_type == "warning":
        console.print(f"[yellow]⚠️ {event.get('message')}[/yellow]")
    elif ev_type == "error":
        console.print(f"[bold red]❌ {event.get('message')}[/bold red]")
    elif ev_type == "info":
        console.print(f"[cyan]ℹ️ {event.get('message')}[/cyan]")

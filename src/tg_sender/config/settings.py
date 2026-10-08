from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    data_dir: Path = Path("data")
    sessions_dir: Path = Path("data/sessions")
    templates_dir: Path = Path("data/templates")
    tdata_inbox_dir: Path = Path("data/tdata_inbox")
    proxies_file_path: Path = Path("data/proxies.txt")
    logs_dir: Path = Path("data/logs")
    db_path: Path = Path("data/app.db")
    min_delay_seconds: int = 40
    max_delay_seconds: int = 90
    typing_duration_seconds: int = 3
    daily_limit_per_account: int = 20

    def setup_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        self.tdata_inbox_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()

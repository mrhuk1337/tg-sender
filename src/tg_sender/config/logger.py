import sys

from loguru import logger

from tg_sender.config.settings import settings


def init_logger(level: str = "INFO", log_file: bool = True) -> None:
    logger.remove()
    logger.add(
        sys.stderr,
        level=level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    )
    if log_file:
        settings.logs_dir.mkdir(parents=True, exist_ok=True)
        file_path = settings.logs_dir / "app.log"
        logger.add(
            str(file_path),
            level="DEBUG",
            rotation="10 MB",
            retention="10 days",
            compression="zip",
            encoding="utf-8",
            enqueue=True,
        )


init_logger()

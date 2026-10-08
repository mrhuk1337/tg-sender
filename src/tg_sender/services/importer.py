import re
from pathlib import Path
from typing import Any

import pandas as pd
import phonenumbers
from loguru import logger
from phonenumbers import PhoneNumberFormat


class ContactImporter:
    USERNAME_PATTERN = re.compile(r"^@?([a-zA-Z0-9_]{4,32})$")
    PHONE_PATTERN = re.compile(r"^\+?([0-9]{10,15})$")

    @classmethod
    def normalize_recipient(cls, raw: str) -> str | None:
        val = raw.strip()
        if not val:
            return None
        if val.startswith("https://t.me/"):
            val = val.replace("https://t.me/", "")
        if val.startswith("t.me/"):
            val = val.replace("t.me/", "")
        val = val.strip("/")

        clean_phone = re.sub(r"[\s\-\(\)\.]+", "", val)
        if clean_phone.isdigit() or (clean_phone.startswith("+") and clean_phone[1:].isdigit()):
            candidate = clean_phone if clean_phone.startswith("+") else "+" + clean_phone
            try:
                parsed = phonenumbers.parse(candidate, None)
                if phonenumbers.is_possible_number(parsed):
                    return phonenumbers.format_number(parsed, PhoneNumberFormat.E164)
            except Exception:
                pass

            if clean_phone.startswith("8") and len(clean_phone) == 11:
                try:
                    parsed = phonenumbers.parse("+7" + clean_phone[1:], None)
                    if phonenumbers.is_possible_number(parsed):
                        return phonenumbers.format_number(parsed, PhoneNumberFormat.E164)
                except Exception:
                    pass

            if cls.PHONE_PATTERN.match(clean_phone):
                return f"+{clean_phone.replace('+', '')}"

        user_match = cls.USERNAME_PATTERN.match(val)
        if user_match:
            return f"@{user_match.group(1)}"

        return val

    @classmethod
    def import_from_file(cls, file_path: Path | str) -> list[dict[str, Any]]:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        suffix = path.suffix.lower()
        if suffix in [".xlsx", ".xls"]:
            records = cls._import_dataframe(pd.read_excel(path, dtype=str))
        elif suffix == ".csv":
            records = cls._import_csv(path)
        elif suffix in [".txt"]:
            records = cls._import_txt(path)
        else:
            raise ValueError(f"Unsupported file format: {suffix}")

        logger.info(f"Imported {len(records)} contacts from {path.name}")
        return records

    @classmethod
    def _import_csv(cls, path: Path) -> list[dict[str, Any]]:
        try:
            df = pd.read_csv(path, sep=None, engine="python", dtype=str, encoding_errors="ignore")
            if df.empty or (
                len(df.columns) <= 1 and "\n" in str(df.iloc[0, 0] if not df.empty else "")
            ):
                df = pd.read_csv(path, dtype=str, encoding_errors="ignore")
            return cls._import_dataframe(df)
        except Exception:
            return cls._import_txt(path)

    @classmethod
    def _import_dataframe(cls, df: pd.DataFrame) -> list[dict[str, Any]]:
        if df.empty:
            return []
        df = df.fillna("")
        df.columns = [str(c).strip() for c in df.columns]
        headers = list(df.columns)
        recipient_col = cls._find_recipient_col(headers)
        name_col = cls._find_name_col(headers)
        records = []
        for row in df.to_dict(orient="records"):
            rec = cls._process_row(row, recipient_col, name_col)
            if rec:
                records.append(rec)
        return records

    @classmethod
    def _import_txt(cls, path: Path) -> list[dict[str, Any]]:
        records = []
        with open(path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                val = cls.normalize_recipient(line)
                if val:
                    records.append({"recipient": val, "first_name": None, "extra_data": {}})
        return records

    @classmethod
    def _find_recipient_col(cls, headers: list[str]) -> str | None:
        target_keys = [
            "recipient",
            "username",
            "phone",
            "contact",
            "tg",
            "telegram",
            "user",
            "юзернейм",
            "телефон",
            "контакт",
        ]
        for h in headers:
            h_clean = h.lower().strip()
            if h_clean in target_keys:
                return h
        for h in headers:
            h_clean = h.lower().strip()
            if any(k in h_clean for k in target_keys):
                return h
        return headers[0] if headers else None

    @classmethod
    def _find_name_col(cls, headers: list[str]) -> str | None:
        target_keys = ["first_name", "firstname", "name", "имя", "фio", "фио"]
        for h in headers:
            h_clean = h.lower().strip()
            if h_clean in target_keys:
                return h
        for h in headers:
            h_clean = h.lower().strip()
            if any(k in h_clean for k in target_keys):
                return h
        return None

    @classmethod
    def _process_row(
        cls, row: dict[str, Any], recipient_col: str | None, name_col: str | None
    ) -> dict[str, Any] | None:
        if not recipient_col or recipient_col not in row:
            return None
        raw_recipient = str(row[recipient_col]) if row[recipient_col] is not None else ""
        recipient = cls.normalize_recipient(raw_recipient)
        if not recipient:
            return None

        first_name = None
        if name_col and name_col in row and row[name_col]:
            first_name = str(row[name_col]).strip()

        extra_data = {}
        for k, v in row.items():
            if k not in (recipient_col, name_col) and v is not None:
                extra_data[k] = str(v).strip()

        if first_name:
            extra_data["name"] = first_name
            extra_data["first_name"] = first_name
        extra_data["recipient"] = recipient

        return {
            "recipient": recipient,
            "first_name": first_name,
            "extra_data": extra_data,
        }

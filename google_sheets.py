"""
CRUD-клиент для Google Таблиц через Sheets API v4 (сервисный аккаунт).

Пример подключения в другом приложении:

    from google_sheets import GoogleSheetsClient

    sheets = GoogleSheetsClient(
        credentials_path="excel-factory-512714-341d64a29ff2.json",
        spreadsheet_id="YOUR_SPREADSHEET_ID",
    )
    rows = sheets.read_all()
    sheets.update("A1", [["Hello", "World"]])
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Sequence

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ("https://www.googleapis.com/auth/spreadsheets",)

DEFAULT_CREDENTIALS_PATH = Path(__file__).resolve().parent / (
    "excel-factory-512714-341d64a29ff2.json"
)


class GoogleSheetsClient:
    """Обёртка над Google Sheets API с CRUD-операциями над ячейками."""

    def __init__(
        self,
        spreadsheet_id: str,
        credentials_path: str | Path | None = None,
        *,
        default_sheet: str = "Sheet1",
    ) -> None:
        if not spreadsheet_id:
            raise ValueError("spreadsheet_id обязателен")

        self.spreadsheet_id = spreadsheet_id
        self.default_sheet = default_sheet
        self.credentials_path = Path(
            credentials_path or os.getenv("GOOGLE_CREDENTIALS_PATH") or DEFAULT_CREDENTIALS_PATH
        )

        if not self.credentials_path.is_file():
            raise FileNotFoundError(f"JSON-ключ не найден: {self.credentials_path}")

        credentials = service_account.Credentials.from_service_account_file(
            str(self.credentials_path),
            scopes=SCOPES,
        )
        self._service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
        self._values = self._service.spreadsheets().values()

    # --- helpers ---

    def _range(self, a1_range: str) -> str:
        """Нормализует A1-диапазон: добавляет имя листа к ячейкам, если его нет."""
        a1_range = a1_range.strip()
        if "!" in a1_range or not self.default_sheet:
            return a1_range
        # "A1", "B2:C5" → "Sheet!A1"; голое имя листа ("Invoices") не трогаем
        if any(ch.isdigit() for ch in a1_range):
            return f"{self.default_sheet}!{a1_range}"
        return a1_range

    # --- CREATE ---

    def append(
        self,
        values: Sequence[Sequence[Any]],
        a1_range: str | None = None,
        *,
        value_input_option: str = "USER_ENTERED",
        insert_data_option: str = "INSERT_ROWS",
    ) -> dict[str, Any]:
        """Добавляет строки в конец таблицы (или указанного диапазона)."""
        target = self._range(a1_range or self.default_sheet)
        try:
            return (
                self._values.append(
                    spreadsheetId=self.spreadsheet_id,
                    range=target,
                    valueInputOption=value_input_option,
                    insertDataOption=insert_data_option,
                    body={"values": [list(row) for row in values]},
                )
                .execute()
            )
        except HttpError as exc:
            raise RuntimeError(f"append failed for {target}: {exc}") from exc

    def create_sheet(self, title: str) -> dict[str, Any]:
        """Создаёт новый лист внутри текущей таблицы."""
        body = {
            "requests": [
                {
                    "addSheet": {
                        "properties": {"title": title},
                    }
                }
            ]
        }
        try:
            return (
                self._service.spreadsheets()
                .batchUpdate(spreadsheetId=self.spreadsheet_id, body=body)
                .execute()
            )
        except HttpError as exc:
            raise RuntimeError(f"create_sheet failed for '{title}': {exc}") from exc

    def batch_requests(self, requests: Sequence[dict[str, Any]]) -> dict[str, Any]:
        """Пакет spreadsheets.batchUpdate: объединение, ширины, границы, шрифты."""
        if not requests:
            return {}
        try:
            return (
                self._service.spreadsheets()
                .batchUpdate(
                    spreadsheetId=self.spreadsheet_id,
                    body={"requests": list(requests)},
                )
                .execute()
            )
        except HttpError as exc:
            raise RuntimeError(f"batch_requests failed: {exc}") from exc

    # --- READ ---

    def read(self, a1_range: str) -> list[list[Any]]:
        """Читает значения из указанного A1-диапазона."""
        target = self._range(a1_range)
        try:
            result = (
                self._values.get(
                    spreadsheetId=self.spreadsheet_id,
                    range=target,
                )
                .execute()
            )
        except HttpError as exc:
            raise RuntimeError(f"read failed for {target}: {exc}") from exc
        return result.get("values", [])

    def read_all(self, sheet_name: str | None = None) -> list[list[Any]]:
        """Читает все заполненные ячейки листа."""
        sheet = sheet_name or self.default_sheet
        return self.read(sheet)

    def get_cell(self, cell: str) -> Any | None:
        """Читает одну ячейку (например, 'B2'). Пустая → None."""
        rows = self.read(cell)
        if not rows or not rows[0]:
            return None
        return rows[0][0]

    def list_sheets(self) -> list[str]:
        """Возвращает названия всех листов в таблице."""
        try:
            meta = (
                self._service.spreadsheets()
                .get(spreadsheetId=self.spreadsheet_id)
                .execute()
            )
        except HttpError as exc:
            raise RuntimeError(f"list_sheets failed: {exc}") from exc
        return [s["properties"]["title"] for s in meta.get("sheets", [])]

    # --- UPDATE ---

    def update(
        self,
        a1_range: str,
        values: Sequence[Sequence[Any]],
        *,
        value_input_option: str = "USER_ENTERED",
    ) -> dict[str, Any]:
        """Перезаписывает значения в указанном диапазоне."""
        target = self._range(a1_range)
        try:
            return (
                self._values.update(
                    spreadsheetId=self.spreadsheet_id,
                    range=target,
                    valueInputOption=value_input_option,
                    body={"values": [list(row) for row in values]},
                )
                .execute()
            )
        except HttpError as exc:
            raise RuntimeError(f"update failed for {target}: {exc}") from exc

    def set_cell(
        self,
        cell: str,
        value: Any,
        *,
        value_input_option: str = "USER_ENTERED",
    ) -> dict[str, Any]:
        """Записывает значение в одну ячейку."""
        return self.update(cell, [[value]], value_input_option=value_input_option)

    def batch_update(
        self,
        data: Sequence[dict[str, Any]],
        *,
        value_input_option: str = "USER_ENTERED",
    ) -> dict[str, Any]:
        """
        Пакетное обновление нескольких диапазонов.

        data: [{"range": "A1:B2", "values": [[1, 2], [3, 4]]}, ...]
        """
        body = {
            "valueInputOption": value_input_option,
            "data": [
                {
                    "range": self._range(item["range"]),
                    "values": [list(row) for row in item["values"]],
                }
                for item in data
            ],
        }
        try:
            return (
                self._values.batchUpdate(
                    spreadsheetId=self.spreadsheet_id,
                    body=body,
                )
                .execute()
            )
        except HttpError as exc:
            raise RuntimeError(f"batch_update failed: {exc}") from exc

    # --- DELETE ---

    def clear(self, a1_range: str) -> dict[str, Any]:
        """Очищает значения в диапазоне (форматирование сохраняется)."""
        target = self._range(a1_range)
        try:
            return (
                self._values.clear(
                    spreadsheetId=self.spreadsheet_id,
                    range=target,
                    body={},
                )
                .execute()
            )
        except HttpError as exc:
            raise RuntimeError(f"clear failed for {target}: {exc}") from exc

    def delete_rows(
        self,
        start_index: int,
        end_index: int,
        *,
        sheet_id: int | None = None,
        sheet_name: str | None = None,
    ) -> dict[str, Any]:
        """
        Удаляет строки [start_index, end_index) (0-based, как в Sheets API).

        Нужен sheet_id или sheet_name.
        """
        resolved_sheet_id = sheet_id
        if resolved_sheet_id is None:
            name = sheet_name or self.default_sheet
            resolved_sheet_id = self._sheet_id_by_name(name)

        body = {
            "requests": [
                {
                    "deleteDimension": {
                        "range": {
                            "sheetId": resolved_sheet_id,
                            "dimension": "ROWS",
                            "startIndex": start_index,
                            "endIndex": end_index,
                        }
                    }
                }
            ]
        }
        try:
            return (
                self._service.spreadsheets()
                .batchUpdate(spreadsheetId=self.spreadsheet_id, body=body)
                .execute()
            )
        except HttpError as exc:
            raise RuntimeError(f"delete_rows failed: {exc}") from exc

    def _sheet_id_by_name(self, sheet_name: str) -> int:
        try:
            meta = (
                self._service.spreadsheets()
                .get(spreadsheetId=self.spreadsheet_id)
                .execute()
            )
        except HttpError as exc:
            raise RuntimeError(f"не удалось получить метаданные таблицы: {exc}") from exc

        for sheet in meta.get("sheets", []):
            props = sheet.get("properties", {})
            if props.get("title") == sheet_name:
                return int(props["sheetId"])

        raise ValueError(f"Лист '{sheet_name}' не найден")


def _load_dotenv(path: Path | None = None) -> None:
    """Простой парсер .env без внешних зависимостей."""
    env_path = path or Path(__file__).resolve().parent / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        os.environ.setdefault(key, value)


def main() -> None:
    """Точка входа: читает все ячейки и печатает их в консоль."""
    _load_dotenv()

    spreadsheet_id = os.getenv("SPREADSHEET_ID", "").strip()
    if not spreadsheet_id:
        raise SystemExit(
            "Укажите SPREADSHEET_ID в .env или переменной окружения.\n"
            "ID берётся из URL таблицы: "
            "https://docs.google.com/spreadsheets/d/<SPREADSHEET_ID>/edit"
        )

    credentials_path = os.getenv("GOOGLE_CREDENTIALS_PATH") or str(DEFAULT_CREDENTIALS_PATH)
    sheet_name = os.getenv("SHEET_NAME", "Sheet1")

    client = GoogleSheetsClient(
        spreadsheet_id=spreadsheet_id,
        credentials_path=credentials_path,
        default_sheet=sheet_name,
    )

    print(f"Таблица: {client.spreadsheet_id}")
    print(f"Листы: {', '.join(client.list_sheets())}")
    print(f"Чтение листа: {sheet_name}\n")

    rows = client.read_all(sheet_name)
    if not rows:
        print("(таблица пуста)")
        return

    for i, row in enumerate(rows, start=1):
        print(f"{i:>4}: {row}")


if __name__ == "__main__":
    main()

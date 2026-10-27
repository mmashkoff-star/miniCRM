"""
CRUD-клиент для Google Drive API v3.

По умолчанию подключается через OAuth2 личного аккаунта (client_secret JSON).
Файлы тогда создаются от имени пользователя, а не сервисного аккаунта.

    from google_drive import GoogleDriveClient

    drive = GoogleDriveClient(auth="oauth", folder_id="FOLDER_ID")
    doc = drive.create_document("Договор")
    sheet = drive.create_spreadsheet("Отчёт")

Сервисный аккаунт по-прежнему доступен: auth="service_account".
"""

from __future__ import annotations

import json
import mimetypes
import os
import sys
from pathlib import Path
from typing import Any, Iterable, Literal

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

SCOPES = (
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
)
AuthMode = Literal["oauth", "service_account"]

_PROJECT_DIR = Path(__file__).resolve().parent.parent
_CREDENTIALS_DIR = _PROJECT_DIR / "credentials"
DEFAULT_SERVICE_ACCOUNT_PATH = _CREDENTIALS_DIR / "excel-factory-512714-341d64a29ff2.json"
DEFAULT_OAUTH_CLIENT_SECRET = _CREDENTIALS_DIR / (
    "client_secret_602945622742-1187qejn865hpg8bqg0o65gh1gke6ic5.apps.googleusercontent.com.json"
)
DEFAULT_TOKEN_PATH = _CREDENTIALS_DIR / "token.json"

FILE_FIELDS = (
    "id, name, mimeType, parents, size, modifiedTime, createdTime, "
    "webViewLink, iconLink, owners, shared, trashed"
)
LIST_FIELDS = f"nextPageToken, incompleteSearch, files({FILE_FIELDS})"

MIME_FOLDER = "application/vnd.google-apps.folder"
MIME_SPREADSHEET = "application/vnd.google-apps.spreadsheet"
MIME_DOCUMENT = "application/vnd.google-apps.document"


class GoogleDriveClient:
    """Обёртка над Google Drive API с CRUD-операциями над файлами."""

    def __init__(
        self,
        credentials_path: str | Path | None = None,
        *,
        folder_id: str | None = None,
        auth: AuthMode | None = None,
        token_path: str | Path | None = None,
    ) -> None:
        self.folder_id = (folder_id or "").strip() or None
        self.auth_mode: AuthMode = _resolve_auth_mode(auth, credentials_path)
        self.credentials_path = _resolve_credentials_path(credentials_path, self.auth_mode)
        self.token_path = Path(
            token_path or os.getenv("GOOGLE_OAUTH_TOKEN_PATH") or DEFAULT_TOKEN_PATH
        )

        if not self.credentials_path.is_file():
            raise FileNotFoundError(f"JSON-ключ не найден: {self.credentials_path}")

        if self.auth_mode == "oauth":
            credentials = _credentials_from_oauth(self.credentials_path, self.token_path)
            self.user_email = ""
            self.user_name = ""
        else:
            credentials = _credentials_from_service_account(self.credentials_path)
            self.user_email = getattr(credentials, "service_account_email", "")
            self.user_name = "service account"

        self.client_email = self.user_email
        self._service = build("drive", "v3", credentials=credentials, cache_discovery=False)
        self._files = self._service.files()
        self._load_user_profile()

    def _load_user_profile(self) -> None:
        if self.auth_mode != "oauth":
            return
        try:
            about = self._service.about().get(fields="user(displayName,emailAddress)").execute()
        except HttpError:
            return
        user = about.get("user") or {}
        self.user_email = user.get("emailAddress") or ""
        self.user_name = user.get("displayName") or ""
        self.client_email = self.user_email

    def _parent(self, folder_id: str | None = None) -> str | None:
        return (folder_id or self.folder_id or "").strip() or None

    def _body(self, name: str, mime_type: str | None = None, parent_id: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"name": name}
        if mime_type:
            body["mimeType"] = mime_type
        parent = self._parent(parent_id)
        if parent:
            body["parents"] = [parent]
        return body

    # --- CREATE ---

    def create_file(
        self,
        name: str,
        *,
        mime_type: str = "text/plain",
        parent_id: str | None = None,
        local_path: str | Path | None = None,
    ) -> dict[str, Any]:
        """Создаёт файл. Без local_path — пустой Google-файл указанного MIME-типа."""
        body = self._body(name, mime_type, parent_id)
        media = None
        if local_path is not None:
            path = Path(local_path)
            if not path.is_file():
                raise FileNotFoundError(f"Локальный файл не найден: {path}")
            guessed, _ = mimetypes.guess_type(path.name)
            body["mimeType"] = mime_type or guessed or "application/octet-stream"
            media = MediaFileUpload(str(path), mimetype=body["mimeType"], resumable=True)

        try:
            request = self._files.create(
                body=body,
                media_body=media,
                fields=FILE_FIELDS,
                supportsAllDrives=True,
            )
            return request.execute()
        except HttpError as exc:
            raise RuntimeError(f"create_file failed for '{name}': {exc}") from exc

    def create_folder(self, name: str, parent_id: str | None = None) -> dict[str, Any]:
        """Создаёт папку на Диске."""
        return self.create_file(name, mime_type=MIME_FOLDER, parent_id=parent_id)

    def create_document(self, name: str, parent_id: str | None = None) -> dict[str, Any]:
        """Создаёт пустой Google Документ в указанной папке."""
        return self.create_file(name, mime_type=MIME_DOCUMENT, parent_id=parent_id)

    def create_spreadsheet(self, name: str, parent_id: str | None = None) -> dict[str, Any]:
        """Создаёт пустую Google Таблицу в указанной папке."""
        return self.create_file(name, mime_type=MIME_SPREADSHEET, parent_id=parent_id)

    def upload_file(
        self,
        local_path: str | Path,
        *,
        name: str | None = None,
        parent_id: str | None = None,
        mime_type: str | None = None,
    ) -> dict[str, Any]:
        """Загружает локальный файл на Диск."""
        path = Path(local_path)
        guessed, _ = mimetypes.guess_type(path.name)
        return self.create_file(
            name or path.name,
            mime_type=mime_type or guessed or "application/octet-stream",
            parent_id=parent_id,
            local_path=path,
        )

    # --- READ ---

    def list_files(
        self,
        folder_id: str | None = None,
        *,
        query: str | None = None,
        include_trashed: bool = False,
        page_size: int = 100,
    ) -> list[dict[str, Any]]:
        """Возвращает список файлов. Без folder_id — все доступные текущему аккаунту."""
        parent = self._parent(folder_id)
        clauses: list[str] = []
        if not include_trashed:
            clauses.append("trashed = false")
        if parent:
            clauses.append(f"'{_escape_query_value(parent)}' in parents")
        if query:
            clauses.append(f"({query})")

        params: dict[str, Any] = {
            "q": " and ".join(clauses) if clauses else None,
            "pageSize": page_size,
            "fields": LIST_FIELDS,
            "supportsAllDrives": True,
            "includeItemsFromAllDrives": True,
            "orderBy": "folder,name",
        }

        files: list[dict[str, Any]] = []
        token: str | None = None
        try:
            while True:
                result = self._files.list(pageToken=token, **params).execute()
                files.extend(result.get("files", []))
                token = result.get("nextPageToken")
                if not token:
                    break
        except HttpError as exc:
            raise RuntimeError(f"list_files failed: {exc}") from exc
        return files

    def list_all(self, folder_id: str | None = None) -> list[dict[str, Any]]:
        """Читает все файлы рабочей папки (или всего доступного Диска)."""
        return self.list_files(folder_id)

    def get_file(self, file_id: str) -> dict[str, Any]:
        """Читает метаданные одного файла."""
        try:
            return (
                self._files.get(
                    fileId=file_id,
                    fields=FILE_FIELDS,
                    supportsAllDrives=True,
                )
                .execute()
            )
        except HttpError as exc:
            raise RuntimeError(f"get_file failed for {file_id}: {exc}") from exc

    def list_children(self, folder_id: str | None = None) -> list[dict[str, Any]]:
        """Синоним list_all для содержимого конкретной папки."""
        parent = self._parent(folder_id)
        if not parent:
            raise ValueError("folder_id не задан (ни аргументом, ни в конструкторе)")
        return self.list_all(parent)

    # --- UPDATE ---

    def rename(self, file_id: str, name: str) -> dict[str, Any]:
        """Переименовывает файл или папку."""
        try:
            return (
                self._files.update(
                    fileId=file_id,
                    body={"name": name},
                    fields=FILE_FIELDS,
                    supportsAllDrives=True,
                )
                .execute()
            )
        except HttpError as exc:
            raise RuntimeError(f"rename failed for {file_id}: {exc}") from exc

    def move(self, file_id: str, new_parent_id: str) -> dict[str, Any]:
        """Перемещает файл в другую папку."""
        current = self.get_file(file_id)
        previous_parents = ",".join(current.get("parents", []))
        try:
            return (
                self._files.update(
                    fileId=file_id,
                    addParents=new_parent_id,
                    removeParents=previous_parents or None,
                    fields=FILE_FIELDS,
                    supportsAllDrives=True,
                )
                .execute()
            )
        except HttpError as exc:
            raise RuntimeError(f"move failed for {file_id}: {exc}") from exc

    # --- DELETE ---

    def trash(self, file_id: str) -> dict[str, Any]:
        """Перемещает файл в корзину."""
        try:
            return (
                self._files.update(
                    fileId=file_id,
                    body={"trashed": True},
                    fields=FILE_FIELDS,
                    supportsAllDrives=True,
                )
                .execute()
            )
        except HttpError as exc:
            raise RuntimeError(f"trash failed for {file_id}: {exc}") from exc

    def delete(self, file_id: str) -> None:
        """Удаляет файл безвозвратно (не в корзину)."""
        try:
            self._files.delete(fileId=file_id, supportsAllDrives=True).execute()
        except HttpError as exc:
            raise RuntimeError(f"delete failed for {file_id}: {exc}") from exc


def _escape_query_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _find_oauth_client_secret() -> Path | None:
    env_path = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
    if env_path:
        return Path(env_path)
    if DEFAULT_OAUTH_CLIENT_SECRET.is_file():
        return DEFAULT_OAUTH_CLIENT_SECRET
    matches = sorted(_CREDENTIALS_DIR.glob("client_secret_*.json"))
    return matches[0] if matches else None


def _detect_auth_from_file(path: Path) -> AuthMode:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("type") == "service_account":
        return "service_account"
    if "installed" in payload or "web" in payload:
        return "oauth"
    raise ValueError(f"Не удалось определить тип ключа: {path}")


def _resolve_auth_mode(auth: AuthMode | None, credentials_path: str | Path | None) -> AuthMode:
    if auth in ("oauth", "service_account"):
        return auth
    env_auth = (os.getenv("GOOGLE_AUTH") or "").strip().lower()
    if env_auth in ("oauth", "service_account"):
        return env_auth  # type: ignore[return-value]
    if credentials_path:
        return _detect_auth_from_file(Path(credentials_path))
    if _find_oauth_client_secret():
        return "oauth"
    return "service_account"


def _resolve_credentials_path(credentials_path: str | Path | None, auth: AuthMode) -> Path:
    if credentials_path:
        return Path(credentials_path)
    if auth == "oauth":
        found = _find_oauth_client_secret()
        if found:
            return found
        raise FileNotFoundError(
            "OAuth client_secret JSON не найден. "
            "Положите client_secret_*.json в папку credentials или задайте GOOGLE_OAUTH_CLIENT_SECRET."
        )
    return Path(os.getenv("GOOGLE_CREDENTIALS_PATH") or DEFAULT_SERVICE_ACCOUNT_PATH)


def _credentials_from_oauth(client_secret_path: Path, token_path: Path):
    payload = json.loads(client_secret_path.read_text(encoding="utf-8"))
    if "installed" not in payload and "web" not in payload:
        raise ValueError(
            f"{client_secret_path.name} — это не OAuth client secret "
            "(ожидаются ключи installed или web)."
        )

    creds = None
    if token_path.is_file():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        if creds and hasattr(creds, "has_scopes") and not creds.has_scopes(SCOPES):
            creds = None

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError:
            creds = None

    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_path), SCOPES)
        creds = flow.run_local_server(port=0)

    token_path.write_text(creds.to_json(), encoding="utf-8")
    return creds


def _credentials_from_service_account(path: Path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("type") != "service_account":
        raise ValueError(
            f"{path.name} — это не ключ сервисного аккаунта "
            "(ожидается поле type=service_account)."
        )
    return service_account.Credentials.from_service_account_file(str(path), scopes=SCOPES)


def _load_dotenv(path: Path | None = None) -> None:
    """Простой парсер .env без внешних зависимостей."""
    env_path = path or _PROJECT_DIR / ".env"
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


def _kind(mime_type: str) -> str:
    mapping = {
        MIME_FOLDER: "папка",
        MIME_SPREADSHEET: "таблица",
        MIME_DOCUMENT: "документ",
        "application/pdf": "pdf",
    }
    return mapping.get(mime_type, mime_type.split("/")[-1] if mime_type else "?")


def _print_files(files: Iterable[dict[str, Any]]) -> None:
    rows = list(files)
    if not rows:
        print("(файлов нет — папка пуста или нет доступа)")
        return

    print(f"Найдено файлов: {len(rows)}\n")
    print(f"{'#':>4}  {'тип':<10}  {'имя':<40}  id")
    print("-" * 90)
    for i, item in enumerate(rows, start=1):
        name = (item.get("name") or "")[:40]
        kind = _kind(item.get("mimeType") or "")
        print(f"{i:>4}  {kind:<10}  {name:<40}  {item.get('id')}")


def main() -> None:
    """Точка входа: OAuth2-вход и список файлов рабочей папки."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    _load_dotenv()

    folder_id = os.getenv("DRIVE_FOLDER_ID", "").strip() or None
    client = GoogleDriveClient(folder_id=folder_id)

    owner = client.user_email or client.client_email or "(неизвестно)"
    print(f"Режим: {client.auth_mode}")
    print(f"Аккаунт: {owner}")
    print(f"Ключ: {client.credentials_path.name}")
    print(f"Рабочая папка: {folder_id or '(весь доступный Диск)'}\n")

    _print_files(client.list_all())


if __name__ == "__main__":
    main()

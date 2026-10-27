"""Окно мини-CRM: таблицы и формы, все данные через локальный FastAPI.

Запуск (бэкенд должен быть уже поднят):
    docker compose up --build -d
    python ui/crm_app.py
"""

from __future__ import annotations

import json
import os
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

_PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_DIR / "integrations"))

from google_drive import (
    DEFAULT_OAUTH_CLIENT_SECRET,
    DEFAULT_TOKEN_PATH,
    GoogleDriveClient,
)
from google_sheets import GoogleSheetsClient

API_BASE = os.getenv("CRM_API_URL", "http://127.0.0.1:8020").rstrip("/")
GOOGLE_SETTINGS_PATH = _PROJECT_DIR / "google_gui.txt"
LIST_LIMIT = 200

NAVY = "#1B3A4B"
GOLD = "#C4A574"
INK = "#2C2C2C"
MUTED = "#5E6A71"
LINE = "#D9D3C7"
PAPER = "#F7F4EE"
WHITE = "#FFFFFF"
ZEBRA = "#F4F0E8"

CLIENT_STATUSES = [("lead", "Лид"), ("active", "Активный"), ("archived", "Архив")]
DEAL_STATUSES = [
    ("new", "Новая"),
    ("in_progress", "В работе"),
    ("won", "Успешна"),
    ("lost", "Проиграна"),
    ("cancelled", "Отменена"),
]
ORDER_STATUSES = [
    ("new", "Новый"),
    ("confirmed", "Подтверждён"),
    ("in_progress", "В работе"),
    ("paid", "Оплачен"),
    ("done", "Выполнен"),
    ("cancelled", "Отменён"),
]
TASK_DONE_FILTERS = [
    ("", "Все"),
    ("false", "Открытые"),
    ("true", "Выполненные"),
]

REPORT_KINDS = {
    "clients": "Клиенты",
    "deals": "Сделки",
    "orders": "Заказы",
    "tasks": "Задачи",
}


@dataclass
class GoogleGuiSettings:
    client_secret: str = ""
    token_path: str = ""
    folder_id: str = ""
    last_spreadsheet_id: str = ""


def load_google_settings() -> GoogleGuiSettings:
    settings = GoogleGuiSettings(
        client_secret=str(DEFAULT_OAUTH_CLIENT_SECRET) if DEFAULT_OAUTH_CLIENT_SECRET.is_file() else "",
        token_path=str(DEFAULT_TOKEN_PATH),
    )
    if not GOOGLE_SETTINGS_PATH.is_file():
        return settings
    for line in GOOGLE_SETTINGS_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key == "client_secret":
            settings.client_secret = value
        elif key == "token_path":
            settings.token_path = value
        elif key == "folder_id":
            settings.folder_id = value
        elif key == "last_spreadsheet_id":
            settings.last_spreadsheet_id = value
    return settings


def save_google_settings(settings: GoogleGuiSettings) -> None:
    GOOGLE_SETTINGS_PATH.write_text(
        "\n".join(
            [
                f"client_secret={settings.client_secret}",
                f"token_path={settings.token_path}",
                f"folder_id={settings.folder_id}",
                f"last_spreadsheet_id={settings.last_spreadsheet_id}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def extract_folder_id(raw: str) -> str:
    text = (raw or "").strip().strip('"').strip("'")
    if "/folders/" in text:
        text = text.split("/folders/", 1)[1]
    text = text.split("?", 1)[0].split("&", 1)[0].strip("/")
    return text


def _hex(color: str) -> dict[str, float]:
    raw = color.lstrip("#")
    return {
        "red": int(raw[0:2], 16) / 255,
        "green": int(raw[2:4], 16) / 255,
        "blue": int(raw[4:6], 16) / 255,
    }


class ApiError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        self.status = status
        self.detail = detail
        super().__init__(detail)


class CrmApi:
    """HTTP-клиент к локальному CRM API."""

    def __init__(self, base_url: str = API_BASE) -> None:
        self.base_url = base_url.rstrip("/")

    def get(self, path: str, query: dict[str, Any] | None = None) -> Any:
        return self._request("GET", path, query=query)

    def post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        return self._request("POST", path, body=body)

    def patch(self, path: str, body: dict[str, Any]) -> Any:
        return self._request("PATCH", path, body=body)

    def delete(self, path: str) -> Any:
        return self._request("DELETE", path)

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        url = self.base_url + path
        if query:
            params = []
            for key, value in query.items():
                if value is None or value == "":
                    continue
                if isinstance(value, bool):
                    value = "true" if value else "false"
                params.append((key, str(value)))
            if params:
                url += "?" + urllib.parse.urlencode(params)
        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=12) as response:
                raw = response.read()
                if not raw:
                    return None
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            payload = exc.read().decode("utf-8", errors="replace")
            detail = payload
            try:
                parsed = json.loads(payload)
                detail = parsed.get("detail", payload)
            except json.JSONDecodeError:
                pass
            raise ApiError(exc.code, str(detail)) from exc
        except urllib.error.URLError as exc:
            raise ApiError(
                0,
                "Нет связи с сервером CRM. Сначала запустите python backend/crm.py",
            ) from exc


@dataclass
class Field:
    key: str
    label: str
    kind: str = "entry"
    required: bool = False
    options: list[tuple[Any, str]] | None = None
    width: int = 42


class FormDialog(tk.Toplevel):
    """Модальное окно создания и редактирования записи."""

    def __init__(
        self,
        parent: tk.Tk,
        title: str,
        fields: list[Field],
        initial: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(parent)
        self.title(title)
        self.result: dict[str, Any] | None = None
        self.fields = fields
        self.initial = initial or {}
        self.widgets: dict[str, Any] = {}
        self.configure(bg=PAPER)
        self.transient(parent)
        self.resizable(False, False)

        body = tk.Frame(self, bg=WHITE, padx=18, pady=16)
        body.pack(fill="both", expand=True, padx=16, pady=16)

        tk.Label(
            body,
            text=title,
            bg=WHITE,
            fg=NAVY,
            font=("Segoe UI", 14, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))

        for row, field in enumerate(fields, start=1):
            tk.Label(
                body,
                text=field.label + (" *" if field.required else ""),
                bg=WHITE,
                fg=MUTED,
                font=("Segoe UI", 9),
            ).grid(row=row, column=0, sticky="nw", pady=6, padx=(0, 12))
            value = self.initial.get(field.key)
            widget: Any
            if field.kind == "text":
                widget = tk.Text(
                    body,
                    width=field.width,
                    height=4,
                    font=("Segoe UI", 10),
                    relief="flat",
                    bg=PAPER,
                    fg=INK,
                    wrap="word",
                )
                if value:
                    widget.insert("1.0", str(value))
            elif field.kind == "combo":
                labels = [label for _stored, label in field.options or []]
                widget = ttk.Combobox(body, values=labels, state="readonly", width=field.width - 2)
                stored = value
                chosen = 0
                for index, (item, _label) in enumerate(field.options or []):
                    if item == stored:
                        chosen = index
                        break
                if labels:
                    widget.current(chosen)
            elif field.kind == "check":
                var = tk.BooleanVar(value=bool(value))
                widget = ttk.Checkbutton(body, text="да", variable=var)
                widget.var = var  # type: ignore[attr-defined]
            else:
                widget = tk.Entry(
                    body,
                    width=field.width,
                    font=("Segoe UI", 10),
                    relief="flat",
                    bg=PAPER,
                    fg=INK,
                    insertbackground=NAVY,
                )
                if value is not None and value != "":
                    widget.insert(0, str(value))
            widget.grid(row=row, column=1, sticky="ew", pady=6)
            self.widgets[field.key] = widget

        buttons = tk.Frame(body, bg=WHITE)
        buttons.grid(row=len(fields) + 1, column=0, columnspan=2, sticky="e", pady=(16, 0))
        ttk.Button(buttons, text="Отмена", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(buttons, text="Сохранить", command=self._submit).pack(side="right")

        self.bind("<Escape>", lambda _event: self.destroy())
        self.grab_set()
        self._center(parent)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _center(self, parent: tk.Tk) -> None:
        self.update_idletasks()
        width = self.winfo_reqwidth()
        height = self.winfo_reqheight()
        x = parent.winfo_rootx() + (parent.winfo_width() - width) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - height) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    def _submit(self) -> None:
        data: dict[str, Any] = {}
        for field in self.fields:
            widget = self.widgets[field.key]
            if field.kind == "text":
                value: Any = widget.get("1.0", "end").strip() or None
            elif field.kind == "combo":
                labels = [label for _stored, label in field.options or []]
                try:
                    index = labels.index(widget.get())
                    value = (field.options or [])[index][0]
                except ValueError:
                    value = None
            elif field.kind == "check":
                value = bool(widget.var.get())
            elif field.kind == "number":
                raw = widget.get().strip().replace(",", ".")
                if not raw:
                    value = None
                else:
                    try:
                        value = float(raw)
                    except ValueError:
                        messagebox.showerror("Проверьте поля", f"«{field.label}» должно быть числом", parent=self)
                        return
            else:
                value = widget.get().strip() or None
            if field.required and (value is None or value == ""):
                messagebox.showerror("Проверьте поля", f"Заполните поле «{field.label}»", parent=self)
                return
            data[field.key] = value
        self.result = data
        self.destroy()


class GoogleSettingsDialog(tk.Toplevel):
    """OAuth JSON и папка Drive. Пути пишутся в google_gui.txt."""

    def __init__(self, parent: tk.Tk, settings: GoogleGuiSettings) -> None:
        super().__init__(parent)
        self.title("Google")
        self.saved = False
        self.settings = settings
        self.configure(bg=PAPER)
        self.transient(parent)
        self.resizable(False, False)

        body = tk.Frame(self, bg=WHITE, padx=18, pady=16)
        body.pack(fill="both", expand=True, padx=16, pady=16)
        tk.Label(
            body,
            text="Подключение Google",
            bg=WHITE,
            fg=NAVY,
            font=("Segoe UI", 14, "bold"),
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))

        self.secret_var = tk.StringVar(value=settings.client_secret)
        self.token_var = tk.StringVar(value=settings.token_path)
        self.folder_var = tk.StringVar(value=settings.folder_id)

        self._path_row(body, 1, "OAuth JSON", self.secret_var, self._browse_secret)
        self._path_row(body, 2, "Файл token", self.token_var, self._browse_token)

        tk.Label(body, text="ID папки Drive", bg=WHITE, fg=MUTED, font=("Segoe UI", 9)).grid(
            row=3, column=0, sticky="w", pady=6, padx=(0, 12)
        )
        folder_entry = tk.Entry(
            body,
            textvariable=self.folder_var,
            width=46,
            font=("Segoe UI", 10),
            relief="flat",
            bg=PAPER,
            fg=INK,
            insertbackground=NAVY,
        )
        folder_entry.grid(row=3, column=1, sticky="ew", pady=6)
        ttk.Button(body, text="Вставить", command=self._paste_folder).grid(
            row=3, column=2, padx=(8, 0), pady=6
        )

        tk.Label(
            body,
            text="Ctrl+V в поле папки часто не срабатывает — используйте «Вставить».",
            bg=WHITE,
            fg=MUTED,
            font=("Segoe UI", 8),
        ).grid(row=4, column=0, columnspan=3, sticky="w", pady=(0, 8))

        buttons = tk.Frame(body, bg=WHITE)
        buttons.grid(row=5, column=0, columnspan=3, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="Отмена", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(buttons, text="Сохранить", command=self._save).pack(side="right")

        self.bind("<Escape>", lambda _event: self.destroy())
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.update_idletasks()
        x = parent.winfo_rootx() + 80
        y = parent.winfo_rooty() + 80
        self.geometry(f"+{x}+{y}")

    def _path_row(
        self,
        parent: tk.Misc,
        row: int,
        label: str,
        variable: tk.StringVar,
        browse: Callable[[], None],
    ) -> None:
        tk.Label(parent, text=label, bg=WHITE, fg=MUTED, font=("Segoe UI", 9)).grid(
            row=row, column=0, sticky="w", pady=6, padx=(0, 12)
        )
        tk.Entry(
            parent,
            textvariable=variable,
            width=46,
            font=("Segoe UI", 10),
            relief="flat",
            bg=PAPER,
            fg=INK,
            insertbackground=NAVY,
        ).grid(row=row, column=1, sticky="ew", pady=6)
        ttk.Button(parent, text="Обзор", command=browse).grid(row=row, column=2, padx=(8, 0), pady=6)

    def _browse_secret(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="OAuth client_secret JSON",
            filetypes=[("JSON", "*.json"), ("Все файлы", "*.*")],
        )
        if path:
            self.secret_var.set(path)

    def _browse_token(self) -> None:
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Файл token.json",
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("Все файлы", "*.*")],
            initialfile="token.json",
        )
        if path:
            self.token_var.set(path)

    def _paste_folder(self) -> None:
        try:
            raw = self.clipboard_get()
        except tk.TclError:
            return
        self.folder_var.set(extract_folder_id(raw))

    def _save(self) -> None:
        secret = self.secret_var.get().strip()
        if secret and not Path(secret).is_file():
            messagebox.showerror("Google", "JSON клиентского секрета не найден.", parent=self)
            return
        self.settings.client_secret = secret
        self.settings.token_path = self.token_var.get().strip() or str(DEFAULT_TOKEN_PATH)
        self.settings.folder_id = extract_folder_id(self.folder_var.get())
        save_google_settings(self.settings)
        self.saved = True
        self.destroy()


class DataTable(ttk.Frame):
    def __init__(self, parent: tk.Misc, columns: list[tuple[str, str, int]]) -> None:
        super().__init__(parent)
        self.column_keys = [key for key, _title, _width in columns]
        self.tree = ttk.Treeview(
            self,
            columns=self.column_keys,
            show="headings",
            selectmode="browse",
        )
        for key, title, width in columns:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, stretch=True, anchor="w")
        scroll = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.tag_configure("odd", background=WHITE)
        self.tree.tag_configure("even", background=ZEBRA)

    def fill(self, rows: list[dict[str, Any]]) -> None:
        self.tree.delete(*self.tree.get_children())
        for index, row in enumerate(rows):
            values = [row.get(key, "") for key in self.column_keys]
            tag = "even" if index % 2 else "odd"
            self.tree.insert("", "end", iid=str(row["id"]), values=values, tags=(tag,))

    def selected_id(self) -> int | None:
        selection = self.tree.selection()
        if not selection:
            return None
        return int(selection[0])

    def snapshot(self) -> tuple[list[str], list[list[Any]], list[int]]:
        headers = [str(self.tree.heading(key)["text"]) for key in self.column_keys]
        rows: list[list[Any]] = []
        ids: list[int] = []
        for iid in self.tree.get_children():
            ids.append(int(iid))
            rows.append(list(self.tree.item(iid, "values")))
        return headers, rows, ids


def _label(code: str, pairs: list[tuple[str, str]]) -> str:
    for item, title in pairs:
        if item == code:
            return title
    return code or "—"


def _money(value: Any) -> str:
    if value is None or value == "":
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number.is_integer():
        return f"{int(number):,}".replace(",", " ")
    return f"{number:,.2f}".replace(",", " ")


def _dash(value: Any) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "да" if value else "нет"
    return str(value)


def _lookup(mapping: dict[int, str], entity_id: Any) -> str:
    if not entity_id:
        return "—"
    return mapping.get(int(entity_id), "—")


def _related_name(item: dict[str, Any], name_key: str, fallback_map: dict[int, str], id_key: str) -> str:
    name = (item.get(name_key) or "").strip()
    if name:
        return name
    return _lookup(fallback_map, item.get(id_key))


class CrmApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Excel Factory CRM")
        self.configure(bg=PAPER)
        self.geometry("1280x760")
        self.minsize(980, 620)
        self.api = CrmApi()
        self.clients_cache: list[dict[str, Any]] = []
        self.deals_cache: list[dict[str, Any]] = []
        self.orders_cache: list[dict[str, Any]] = []
        self.tasks_cache: list[dict[str, Any]] = []

        self._style()
        self._build()
        self.after(200, self.refresh_all)

    def _style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=PAPER)
        style.configure("TNotebook", background=PAPER)
        style.configure("TNotebook.Tab", padding=(14, 8), font=("Segoe UI", 10))
        style.configure(
            "Treeview",
            font=("Segoe UI", 10),
            rowheight=28,
            background=WHITE,
            fieldbackground=WHITE,
            foreground=INK,
        )
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"), foreground=NAVY)
        style.map("Treeview", background=[("selected", NAVY)], foreground=[("selected", WHITE)])
        style.configure("TButton", font=("Segoe UI", 9), padding=(10, 5))
        style.configure("TLabel", background=PAPER, foreground=INK, font=("Segoe UI", 10))
        style.configure("TCheckbutton", background=PAPER, font=("Segoe UI", 9))

    def _build(self) -> None:
        header = tk.Frame(self, bg=NAVY, padx=20, pady=14)
        header.pack(fill="x")
        tk.Label(
            header,
            text="Excel Factory CRM",
            bg=NAVY,
            fg=WHITE,
            font=("Segoe UI", 18, "bold"),
        ).pack(side="left")
        tk.Label(
            header,
            text="личный кабинет",
            bg=NAVY,
            fg=GOLD,
            font=("Segoe UI", 11),
        ).pack(side="left", padx=(12, 0))
        self.server_var = tk.StringVar(value=f"сервер {API_BASE}")
        tk.Label(
            header,
            textvariable=self.server_var,
            bg=NAVY,
            fg=GOLD,
            font=("Segoe UI", 9),
        ).pack(side="right")
        tk.Button(
            header,
            text="Google",
            command=self.open_google_settings,
            bg=GOLD,
            fg=NAVY,
            font=("Segoe UI", 9, "bold"),
            relief="flat",
            padx=12,
            pady=4,
            cursor="hand2",
        ).pack(side="right", padx=(0, 16))

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=12, pady=12)

        self.clients_tab = self._clients_tab()
        self.deals_tab = self._deals_tab()
        self.orders_tab = self._orders_tab()
        self.tasks_tab = self._tasks_tab()
        self.stats_tab = self._stats_tab()
        self.notebook.add(self.clients_tab, text="Клиенты")
        self.notebook.add(self.deals_tab, text="Сделки")
        self.notebook.add(self.orders_tab, text="Заказы")
        self.notebook.add(self.tasks_tab, text="Задачи")
        self.notebook.add(self.stats_tab, text="Сводка")

        self.status_var = tk.StringVar(value="Готово")
        tk.Label(
            self,
            textvariable=self.status_var,
            bg=WHITE,
            fg=MUTED,
            font=("Segoe UI", 9),
            anchor="w",
            padx=16,
            pady=8,
        ).pack(fill="x", side="bottom")

    def _toolbar(self, parent: tk.Misc) -> tk.Frame:
        bar = tk.Frame(parent, bg=PAPER)
        bar.pack(fill="x", pady=(8, 8))
        return bar

    def _entry(self, parent: tk.Misc, variable: tk.StringVar, width: int = 28) -> tk.Entry:
        return tk.Entry(
            parent,
            textvariable=variable,
            width=width,
            font=("Segoe UI", 10),
            relief="flat",
            bg=WHITE,
            fg=INK,
            insertbackground=NAVY,
            highlightthickness=1,
            highlightbackground=LINE,
            highlightcolor=NAVY,
        )

    def _clients_tab(self) -> ttk.Frame:
        tab = ttk.Frame(self.notebook)
        bar = self._toolbar(tab)
        self.client_q = tk.StringVar()
        self.client_status = tk.StringVar(value="")
        self.client_archived = tk.BooleanVar(value=False)
        tk.Label(bar, text="Поиск", bg=PAPER, fg=MUTED).pack(side="left")
        search = self._entry(bar, self.client_q, 24)
        search.pack(side="left", padx=6)
        search.bind("<Return>", lambda _e: self.load_clients())
        ttk.Combobox(
            bar,
            textvariable=self.client_status,
            values=["Все статусы", *[title for _code, title in CLIENT_STATUSES]],
            state="readonly",
            width=16,
        ).pack(side="left", padx=6)
        self.client_status.set("Все статусы")
        ttk.Checkbutton(
            bar,
            text="показывать архив",
            variable=self.client_archived,
            command=self.load_clients,
        ).pack(side="left", padx=6)
        ttk.Button(bar, text="Найти", command=self.load_clients).pack(side="left", padx=4)
        ttk.Button(bar, text="Обновить", command=self.load_clients).pack(side="left")
        ttk.Button(
            bar,
            text="Выгрузить отчёт",
            command=lambda: self.export_report("clients"),
        ).pack(side="left", padx=(12, 0))
        ttk.Button(bar, text="Создать", command=self.create_client).pack(side="right")
        ttk.Button(bar, text="Изменить", command=self.edit_client).pack(side="right", padx=4)
        ttk.Button(bar, text="Архив", command=self.archive_client).pack(side="right")
        ttk.Button(bar, text="Вернуть", command=self.restore_client).pack(side="right", padx=4)
        ttk.Button(bar, text="Удалить", command=self.delete_client).pack(side="right")

        self.clients_table = DataTable(
            tab,
            [
                ("id", "ID", 50),
                ("name", "Имя", 180),
                ("company", "Компания", 160),
                ("phone", "Телефон", 130),
                ("email", "Email", 170),
                ("telegram", "Telegram", 120),
                ("status", "Статус", 100),
                ("updated_at", "Обновлён", 160),
            ],
        )
        self.clients_table.pack(fill="both", expand=True)
        self.clients_table.tree.bind("<Double-1>", lambda _e: self.edit_client())
        return tab

    def _deals_tab(self) -> ttk.Frame:
        tab = ttk.Frame(self.notebook)
        bar = self._toolbar(tab)
        self.deal_q = tk.StringVar()
        self.deal_status = tk.StringVar(value="Все статусы")
        self.deal_unassigned = tk.BooleanVar(value=False)
        search = self._entry(bar, self.deal_q, 24)
        search.pack(side="left")
        search.bind("<Return>", lambda _e: self.load_deals())
        ttk.Combobox(
            bar,
            textvariable=self.deal_status,
            values=["Все статусы", *[title for _code, title in DEAL_STATUSES]],
            state="readonly",
            width=16,
        ).pack(side="left", padx=6)
        ttk.Checkbutton(
            bar,
            text="без клиента",
            variable=self.deal_unassigned,
            command=self.load_deals,
        ).pack(side="left", padx=6)
        ttk.Button(bar, text="Найти", command=self.load_deals).pack(side="left", padx=4)
        ttk.Button(bar, text="Обновить", command=self.load_deals).pack(side="left")
        ttk.Button(
            bar,
            text="Выгрузить отчёт",
            command=lambda: self.export_report("deals"),
        ).pack(side="left", padx=(12, 0))
        ttk.Button(bar, text="Создать", command=self.create_deal).pack(side="right")
        ttk.Button(bar, text="Изменить", command=self.edit_deal).pack(side="right", padx=4)
        ttk.Button(bar, text="Удалить", command=self.delete_deal).pack(side="right")

        self.deals_table = DataTable(
            tab,
            [
                ("id", "ID", 50),
                ("title", "Название", 240),
                ("client", "Клиент", 180),
                ("amount", "Сумма", 110),
                ("status", "Статус", 120),
                ("expected_close_at", "Закрыть до", 120),
                ("updated_at", "Обновлена", 160),
            ],
        )
        self.deals_table.pack(fill="both", expand=True)
        self.deals_table.tree.bind("<Double-1>", lambda _e: self.edit_deal())
        return tab

    def _orders_tab(self) -> ttk.Frame:
        tab = ttk.Frame(self.notebook)
        bar = self._toolbar(tab)
        self.order_q = tk.StringVar()
        self.order_status = tk.StringVar(value="Все статусы")
        search = self._entry(bar, self.order_q, 24)
        search.pack(side="left")
        search.bind("<Return>", lambda _e: self.load_orders())
        ttk.Combobox(
            bar,
            textvariable=self.order_status,
            values=["Все статусы", *[title for _code, title in ORDER_STATUSES]],
            state="readonly",
            width=16,
        ).pack(side="left", padx=6)
        ttk.Button(bar, text="Найти", command=self.load_orders).pack(side="left", padx=4)
        ttk.Button(bar, text="Обновить", command=self.load_orders).pack(side="left")
        ttk.Button(
            bar,
            text="Выгрузить отчёт",
            command=lambda: self.export_report("orders"),
        ).pack(side="left", padx=(12, 0))
        ttk.Button(bar, text="Создать", command=self.create_order).pack(side="right")
        ttk.Button(bar, text="Изменить", command=self.edit_order).pack(side="right", padx=4)
        ttk.Button(bar, text="Удалить", command=self.delete_order).pack(side="right")

        self.orders_table = DataTable(
            tab,
            [
                ("id", "ID", 50),
                ("title", "Название", 220),
                ("client", "Клиент", 160),
                ("deal", "Сделка", 160),
                ("amount", "Сумма", 110),
                ("status", "Статус", 120),
                ("due_at", "Срок", 120),
                ("updated_at", "Обновлён", 160),
            ],
        )
        self.orders_table.pack(fill="both", expand=True)
        self.orders_table.tree.bind("<Double-1>", lambda _e: self.edit_order())
        return tab

    def _tasks_tab(self) -> ttk.Frame:
        tab = ttk.Frame(self.notebook)
        bar = self._toolbar(tab)
        self.task_filter = tk.StringVar(value="Все")
        self.task_overdue = tk.BooleanVar(value=False)
        ttk.Combobox(
            bar,
            textvariable=self.task_filter,
            values=[title for _code, title in TASK_DONE_FILTERS],
            state="readonly",
            width=16,
        ).pack(side="left")
        ttk.Checkbutton(
            bar,
            text="только просроченные",
            variable=self.task_overdue,
            command=self.load_tasks,
        ).pack(side="left", padx=8)
        ttk.Button(bar, text="Обновить", command=self.load_tasks).pack(side="left")
        ttk.Button(
            bar,
            text="Выгрузить отчёт",
            command=lambda: self.export_report("tasks"),
        ).pack(side="left", padx=(12, 0))
        ttk.Button(bar, text="Создать", command=self.create_task).pack(side="right")
        ttk.Button(bar, text="Изменить", command=self.edit_task).pack(side="right", padx=4)
        ttk.Button(bar, text="Выполнена", command=self.complete_task).pack(side="right")
        ttk.Button(bar, text="Открыть снова", command=self.reopen_task).pack(side="right", padx=4)
        ttk.Button(bar, text="Удалить", command=self.delete_task).pack(side="right")

        self.tasks_table = DataTable(
            tab,
            [
                ("id", "ID", 50),
                ("title", "Задача", 260),
                ("client", "Клиент", 160),
                ("deal", "Сделка", 160),
                ("due_at", "Напомнить", 150),
                ("is_done", "Готово", 80),
                ("updated_at", "Обновлена", 160),
            ],
        )
        self.tasks_table.pack(fill="both", expand=True)
        self.tasks_table.tree.bind("<Double-1>", lambda _e: self.edit_task())
        return tab

    def _stats_tab(self) -> ttk.Frame:
        tab = ttk.Frame(self.notebook)
        wrap = tk.Frame(tab, bg=PAPER)
        wrap.pack(fill="both", expand=True, padx=20, pady=20)
        tk.Label(
            wrap,
            text="Сводка по базе",
            bg=PAPER,
            fg=NAVY,
            font=("Segoe UI", 16, "bold"),
        ).pack(anchor="w")
        ttk.Button(wrap, text="Обновить сводку", command=self.load_stats).pack(anchor="w", pady=10)
        self.stats_var = tk.StringVar(value="Загрузка…")
        tk.Label(
            wrap,
            textvariable=self.stats_var,
            bg=PAPER,
            fg=INK,
            font=("Segoe UI", 11),
            justify="left",
            anchor="nw",
        ).pack(anchor="w", pady=8)
        return tab

    # --- загрузка таблиц ---

    def refresh_all(self) -> None:
        self.load_clients()
        self.load_deals()
        self.load_orders()
        self.load_tasks()
        self.load_stats()

    def load_clients(self) -> None:
        status = _code_from_label(self.client_status.get(), CLIENT_STATUSES)

        def job() -> list[dict[str, Any]]:
            payload = self.api.get(
                "/clients",
                {
                    "q": self.client_q.get().strip() or None,
                    "status": status,
                    "include_archived": self.client_archived.get() or status == "archived",
                    "limit": LIST_LIMIT,
                },
            )
            return payload["items"]

        def ok(items: list[dict[str, Any]]) -> None:
            self.clients_cache = items
            self.clients_table.fill(
                [
                    {
                        **item,
                        "company": _dash(item.get("company")),
                        "phone": _dash(item.get("phone")),
                        "email": _dash(item.get("email")),
                        "telegram": _dash(item.get("telegram")),
                        "status": _label(item.get("status") or "", CLIENT_STATUSES),
                    }
                    for item in items
                ]
            )
            self._ok(f"Клиенты: {len(items)}")

        self._run(job, ok)

    def load_deals(self) -> None:
        status = _code_from_label(self.deal_status.get(), DEAL_STATUSES)

        def job() -> list[dict[str, Any]]:
            payload = self.api.get(
                "/deals",
                {
                    "q": self.deal_q.get().strip() or None,
                    "status": status,
                    "unassigned": self.deal_unassigned.get(),
                    "limit": LIST_LIMIT,
                },
            )
            return payload["items"]

        def ok(items: list[dict[str, Any]]) -> None:
            self.deals_cache = items
            names = {item["id"]: item["name"] for item in self.clients_cache}
            self.deals_table.fill(
                [
                    {
                        **item,
                        "client": _related_name(item, "client_name", names, "client_id"),
                        "amount": _money(item.get("amount")),
                        "status": _label(item.get("status") or "", DEAL_STATUSES),
                        "expected_close_at": _dash(item.get("expected_close_at")),
                    }
                    for item in items
                ]
            )
            self._ok(f"Сделки: {len(items)}")

        self._run(job, ok)

    def load_orders(self) -> None:
        status = _code_from_label(self.order_status.get(), ORDER_STATUSES)

        def job() -> list[dict[str, Any]]:
            payload = self.api.get(
                "/orders",
                {
                    "q": self.order_q.get().strip() or None,
                    "status": status,
                    "limit": LIST_LIMIT,
                },
            )
            return payload["items"]

        def ok(items: list[dict[str, Any]]) -> None:
            clients = {item["id"]: item["name"] for item in self.clients_cache}
            deals = {item["id"]: item["title"] for item in self.deals_cache}
            self.orders_table.fill(
                [
                    {
                        **item,
                        "client": _related_name(item, "client_name", clients, "client_id"),
                        "deal": _related_name(item, "deal_title", deals, "deal_id"),
                        "amount": _money(item.get("amount")),
                        "status": _label(item.get("status") or "", ORDER_STATUSES),
                        "due_at": _dash(item.get("due_at")),
                    }
                    for item in items
                ]
            )
            self.orders_cache = items
            self._ok(f"Заказы: {len(items)}")

        self._run(job, ok)

    def load_tasks(self) -> None:
        done_code = ""
        for code, title in TASK_DONE_FILTERS:
            if title == self.task_filter.get():
                done_code = code
                break
        is_done: bool | None
        if done_code == "true":
            is_done = True
        elif done_code == "false":
            is_done = False
        else:
            is_done = None

        def job() -> list[dict[str, Any]]:
            payload = self.api.get(
                "/tasks",
                {
                    "is_done": is_done,
                    "overdue": self.task_overdue.get(),
                    "limit": LIST_LIMIT,
                },
            )
            return payload["items"]

        def ok(items: list[dict[str, Any]]) -> None:
            clients = {item["id"]: item["name"] for item in self.clients_cache}
            deals = {item["id"]: item["title"] for item in self.deals_cache}
            self.tasks_table.fill(
                [
                    {
                        **item,
                        "client": _related_name(item, "client_name", clients, "client_id"),
                        "deal": _related_name(item, "deal_title", deals, "deal_id"),
                        "due_at": _dash(item.get("due_at")),
                        "is_done": "да" if item.get("is_done") else "нет",
                    }
                    for item in items
                ]
            )
            self.tasks_cache = items
            self._ok(f"Задачи: {len(items)}")

        self._run(job, ok)

    def load_stats(self) -> None:
        def job() -> dict[str, Any]:
            health = self.api.get("/health")
            stats = self.api.get("/stats")
            return {"health": health, "stats": stats}

        def ok(payload: dict[str, Any]) -> None:
            health = payload["health"]
            stats = payload["stats"]
            self.server_var.set(f"сервер {API_BASE}  ·  {health.get('status', 'ok')}")
            clients = stats["clients"]["by_status"]
            deals = stats["deals"]["by_status"]
            orders = stats["orders"]["by_status"]
            tasks = stats["tasks"]
            self.stats_var.set(
                "\n".join(
                    [
                        f"Клиенты: {stats['clients']['total']}  (лиды {clients.get('lead', 0)}, "
                        f"активные {clients.get('active', 0)}, архив {clients.get('archived', 0)})",
                        f"Сделки: {stats['deals']['total']}  (новые {deals.get('new', 0)}, "
                        f"в работе {deals.get('in_progress', 0)}, успешные {deals.get('won', 0)})",
                        f"Открытая сумма сделок: {_money(stats['deals'].get('open_amount'))} ₽",
                        f"Заказы: {stats['orders']['total']}  (оплачены {orders.get('paid', 0)}, "
                        f"выполнены {orders.get('done', 0)})",
                        f"Задачи: открытые {tasks.get('open', 0)}, выполненные {tasks.get('done', 0)}, "
                        f"просроченные {tasks.get('overdue', 0)}",
                    ]
                )
            )
            self._ok("Сводка обновлена")

        self._run(job, ok)

    # --- клиенты ---

    def create_client(self) -> None:
        data = self._form("Новый клиент", self._client_fields(), {"status": "active"})
        if data:
            self._mutate(lambda: self.api.post("/clients", data), "Клиент создан", self.load_clients)

    def edit_client(self) -> None:
        item = self._selected(self.clients_table, self.clients_cache, "клиент")
        if not item:
            return
        data = self._form("Клиент", self._client_fields(), item)
        if data:
            self._mutate(
                lambda: self.api.patch(f"/clients/{item['id']}", data),
                "Клиент сохранён",
                self.load_clients,
            )

    def archive_client(self) -> None:
        item = self._selected(self.clients_table, self.clients_cache, "клиент")
        if not item:
            return
        self._mutate(
            lambda: self.api.post(f"/clients/{item['id']}/archive"),
            "Клиент в архиве",
            self.load_clients,
        )

    def restore_client(self) -> None:
        item = self._selected(self.clients_table, self.clients_cache, "клиент")
        if not item:
            return
        self._mutate(
            lambda: self.api.post(f"/clients/{item['id']}/restore"),
            "Клиент восстановлен",
            self.load_clients,
        )

    def delete_client(self) -> None:
        item = self._selected(self.clients_table, self.clients_cache, "клиент")
        if not item:
            return
        if not messagebox.askyesno("Удалить клиента", f"Удалить «{item['name']}»?", parent=self):
            return
        self._mutate(
            lambda: self.api.delete(f"/clients/{item['id']}"),
            "Клиент удалён",
            lambda: (self.load_clients(), self.load_deals(), self.load_orders(), self.load_tasks()),
        )

    # --- сделки ---

    def create_deal(self) -> None:
        self._ensure_lookups()
        data = self._form("Новая сделка", self._deal_fields(), {"status": "new", "currency": "RUB"})
        if data:
            self._mutate(lambda: self.api.post("/deals", data), "Сделка создана", self.load_deals)

    def edit_deal(self) -> None:
        item = self._selected(self.deals_table, self.deals_cache, "сделка")
        if not item:
            return
        self._ensure_lookups()
        data = self._form("Сделка", self._deal_fields(), item)
        if data:
            self._mutate(
                lambda: self.api.patch(f"/deals/{item['id']}", data),
                "Сделка сохранена",
                self.load_deals,
            )

    def delete_deal(self) -> None:
        item = self._selected(self.deals_table, self.deals_cache, "сделка")
        if not item:
            return
        if not messagebox.askyesno("Удалить сделку", f"Удалить «{item['title']}»?", parent=self):
            return
        self._mutate(lambda: self.api.delete(f"/deals/{item['id']}"), "Сделка удалена", self.load_deals)

    # --- заказы ---

    def create_order(self) -> None:
        self._ensure_lookups()
        data = self._form("Новый заказ", self._order_fields(), {"status": "new", "currency": "RUB"})
        if data:
            self._mutate(lambda: self.api.post("/orders", data), "Заказ создан", self.load_orders)

    def edit_order(self) -> None:
        item = self._selected(self.orders_table, self.orders_cache, "заказ")
        if not item:
            return
        self._ensure_lookups()
        data = self._form("Заказ", self._order_fields(), item)
        if data:
            self._mutate(
                lambda: self.api.patch(f"/orders/{item['id']}", data),
                "Заказ сохранён",
                self.load_orders,
            )

    def delete_order(self) -> None:
        item = self._selected(self.orders_table, self.orders_cache, "заказ")
        if not item:
            return
        if not messagebox.askyesno("Удалить заказ", f"Удалить «{item['title']}»?", parent=self):
            return
        self._mutate(lambda: self.api.delete(f"/orders/{item['id']}"), "Заказ удалён", self.load_orders)

    # --- задачи ---

    def create_task(self) -> None:
        self._ensure_lookups()
        data = self._form("Новая задача", self._task_fields(), {"is_done": False})
        if data:
            self._mutate(lambda: self.api.post("/tasks", data), "Задача создана", self.load_tasks)

    def edit_task(self) -> None:
        item = self._selected(self.tasks_table, self.tasks_cache, "задача")
        if not item:
            return
        self._ensure_lookups()
        data = self._form("Задача", self._task_fields(), item)
        if data:
            self._mutate(
                lambda: self.api.patch(f"/tasks/{item['id']}", data),
                "Задача сохранена",
                self.load_tasks,
            )

    def complete_task(self) -> None:
        item = self._selected(self.tasks_table, self.tasks_cache, "задача")
        if not item:
            return
        self._mutate(
            lambda: self.api.post(f"/tasks/{item['id']}/complete"),
            "Задача отмечена выполненной",
            self.load_tasks,
        )

    def reopen_task(self) -> None:
        item = self._selected(self.tasks_table, self.tasks_cache, "задача")
        if not item:
            return
        self._mutate(
            lambda: self.api.post(f"/tasks/{item['id']}/reopen"),
            "Задача снова открыта",
            self.load_tasks,
        )

    def delete_task(self) -> None:
        item = self._selected(self.tasks_table, self.tasks_cache, "задача")
        if not item:
            return
        if not messagebox.askyesno("Удалить задачу", f"Удалить «{item['title']}»?", parent=self):
            return
        self._mutate(lambda: self.api.delete(f"/tasks/{item['id']}"), "Задача удалена", self.load_tasks)

    # --- поля форм ---

    def _client_fields(self) -> list[Field]:
        return [
            Field("name", "Имя", required=True),
            Field("company", "Компания"),
            Field("phone", "Телефон"),
            Field("email", "Email"),
            Field("telegram", "Telegram"),
            Field("notes", "Заметки", kind="text"),
            Field("status", "Статус", kind="combo", options=CLIENT_STATUSES),
        ]

    def _deal_fields(self) -> list[Field]:
        return [
            Field("title", "Название", required=True),
            Field("client_id", "Клиент", kind="combo", options=self._client_options()),
            Field("amount", "Сумма", kind="number"),
            Field("currency", "Валюта"),
            Field("status", "Статус", kind="combo", options=DEAL_STATUSES),
            Field("expected_close_at", "Закрыть до"),
            Field("description", "Описание", kind="text"),
        ]

    def _order_fields(self) -> list[Field]:
        return [
            Field("title", "Название", required=True),
            Field("client_id", "Клиент", kind="combo", options=self._client_options()),
            Field("deal_id", "Сделка", kind="combo", options=self._deal_options()),
            Field("amount", "Сумма", kind="number"),
            Field("currency", "Валюта"),
            Field("status", "Статус", kind="combo", options=ORDER_STATUSES),
            Field("due_at", "Срок"),
            Field("description", "Описание", kind="text"),
        ]

    def _task_fields(self) -> list[Field]:
        return [
            Field("title", "Название", required=True),
            Field("client_id", "Клиент", kind="combo", options=self._client_options()),
            Field("deal_id", "Сделка", kind="combo", options=self._deal_options()),
            Field("due_at", "Напомнить"),
            Field("is_done", "Выполнена", kind="check"),
            Field("description", "Описание", kind="text"),
        ]

    def _client_options(self) -> list[tuple[Any, str]]:
        options: list[tuple[Any, str]] = [(None, "— нет —")]
        options.extend((item["id"], item["name"]) for item in self.clients_cache)
        return options

    def _deal_options(self) -> list[tuple[Any, str]]:
        options: list[tuple[Any, str]] = [(None, "— нет —")]
        options.extend((item["id"], item["title"]) for item in self.deals_cache)
        return options

    def _ensure_lookups(self) -> None:
        try:
            self.clients_cache = self.api.get(
                "/clients",
                {"include_archived": True, "limit": LIST_LIMIT},
            )["items"]
            self.deals_cache = self.api.get("/deals", {"limit": LIST_LIMIT})["items"]
        except ApiError as exc:
            messagebox.showerror("Сервер CRM", exc.detail, parent=self)

    def _form(
        self,
        title: str,
        fields: list[Field],
        initial: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        dialog = FormDialog(self, title, fields, initial)
        self.wait_window(dialog)
        return dialog.result

    def _selected(
        self,
        table: DataTable,
        cache: list[dict[str, Any]],
        noun: str,
    ) -> dict[str, Any] | None:
        entity_id = table.selected_id()
        if entity_id is None:
            messagebox.showinfo("Выбор", f"Сначала выберите {noun} в таблице.", parent=self)
            return None
        for item in cache:
            if item["id"] == entity_id:
                return item
        messagebox.showinfo("Выбор", f"Не удалось найти {noun} #{entity_id}. Обновите таблицу.", parent=self)
        return None

    def _mutate(self, job: Callable[[], Any], success: str, then: Callable[[], None]) -> None:
        def ok(_result: Any) -> None:
            self._ok(success)
            then()

        self._run(job, ok)

    def _run(self, job: Callable[[], Any], on_ok: Callable[[Any], None]) -> None:
        def worker() -> None:
            try:
                result = job()
            except Exception as exc:
                message = str(exc)
                self.after(0, lambda: self._error(message))
                return
            self.after(0, lambda: on_ok(result))

        threading.Thread(target=worker, daemon=True).start()

    def _ok(self, text: str) -> None:
        self.status_var.set(text)

    def _error(self, message: str) -> None:
        self.status_var.set("Ошибка запроса")
        if "Нет связи с сервером CRM" in message:
            self.server_var.set(f"сервер {API_BASE}  ·  нет связи")
        messagebox.showerror("Ошибка", message[:900], parent=self)

    def open_google_settings(self) -> bool:
        dialog = GoogleSettingsDialog(self, load_google_settings())
        self.wait_window(dialog)
        return bool(dialog.saved)

    def export_report(self, kind: str) -> None:
        settings = load_google_settings()
        if not settings.client_secret or not Path(settings.client_secret).is_file():
            if not self.open_google_settings():
                return
            settings = load_google_settings()
        if not settings.client_secret or not Path(settings.client_secret).is_file():
            messagebox.showerror(
                "Google",
                "Укажите JSON клиентского секрета OAuth в настройках Google.",
                parent=self,
            )
            return

        table, cache = {
            "clients": (self.clients_table, self.clients_cache),
            "deals": (self.deals_table, self.deals_cache),
            "orders": (self.orders_table, self.orders_cache),
            "tasks": (self.tasks_table, self.tasks_cache),
        }[kind]
        headers, rows, ids = table.snapshot()
        items = [item for item in cache if item.get("id") in set(ids)]
        title = REPORT_KINDS[kind]
        self.status_var.set(f"Выгружаю отчёт «{title}» в Google…")

        def job() -> dict[str, str]:
            return _upload_google_report(kind, title, headers, rows, items, settings)

        def ok(result: dict[str, str]) -> None:
            self._ok(f"Отчёт «{result['title']}» выгружен")
            open_sheet = messagebox.askyesno(
                "Отчёт в Google",
                f"Таблица «{result['title']}» создана.\nID: {result['id']}\n\nОткрыть?",
                parent=self,
            )
            if open_sheet and result.get("url"):
                webbrowser.open(result["url"])

        self._run(job, ok)


def _upload_google_report(
    kind: str,
    title: str,
    headers: list[str],
    rows: list[list[Any]],
    items: list[dict[str, Any]],
    settings: GoogleGuiSettings,
) -> dict[str, str]:
    now = datetime.now()
    sheet_title = f"CRM · {title} · {now.strftime('%d.%m.%Y %H-%M')}"
    analysis = _analyze_export(kind, items)
    values = _build_export_values(title, now, analysis, headers, rows)

    drive = GoogleDriveClient(
        settings.client_secret,
        folder_id=settings.folder_id or None,
        auth="oauth",
        token_path=settings.token_path or None,
    )
    created = drive.create_spreadsheet(sheet_title)
    spreadsheet_id = created["id"]
    settings.last_spreadsheet_id = spreadsheet_id
    save_google_settings(settings)

    sheets = GoogleSheetsClient(
        spreadsheet_id,
        settings.client_secret,
        auth="oauth",
        token_path=settings.token_path or None,
    )
    sheet_names = sheets.list_sheets()
    if not sheet_names:
        raise RuntimeError("Новая таблица создана без листов")
    sheets.default_sheet = sheet_names[0]
    sheets.update("A1", values)
    header_row = 5 + len(analysis)
    sheets.batch_requests(
        _export_format_requests(
            sheet_id=0,
            columns=max(len(headers), 2),
            analysis_rows=len(analysis),
            header_row=header_row,
            data_rows=len(rows),
            title=title,
        )
    )
    return {
        "id": spreadsheet_id,
        "title": sheet_title,
        "url": created.get("webViewLink") or f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}",
    }


def _analyze_export(kind: str, items: list[dict[str, Any]]) -> list[tuple[str, str]]:
    total = len(items)
    lines: list[tuple[str, str]] = [("Всего в выборке", str(total))]
    if kind == "clients":
        counts = Counter(item.get("status") or "" for item in items)
        lines.extend(
            [
                ("Лиды", str(counts.get("lead", 0))),
                ("Активные", str(counts.get("active", 0))),
                ("Архив", str(counts.get("archived", 0))),
            ]
        )
    elif kind in {"deals", "orders"}:
        counts = Counter(item.get("status") or "" for item in items)
        amount = sum(float(item["amount"]) for item in items if item.get("amount") is not None)
        without_client = sum(1 for item in items if not item.get("client_id"))
        labels = DEAL_STATUSES if kind == "deals" else ORDER_STATUSES
        lines.append(("Сумма по видимым строкам", f"{_money(amount)} ₽"))
        lines.append(("Без клиента", str(without_client)))
        lines.extend((label, str(counts.get(code, 0))) for code, label in labels)
    elif kind == "tasks":
        done = sum(1 for item in items if item.get("is_done"))
        open_count = total - done
        now = datetime.now().isoformat()
        overdue = sum(
            1
            for item in items
            if not item.get("is_done") and item.get("due_at") and str(item["due_at"]) < now
        )
        lines.extend(
            [
                ("Открытые", str(open_count)),
                ("Выполненные", str(done)),
                ("Просроченные среди видимых", str(overdue)),
            ]
        )
    if total == 0:
        lines.append(("Комментарий", "В таблице нет строк — выгружен только заголовок отчёта"))
    return lines


def _build_export_values(
    title: str,
    now: datetime,
    analysis: list[tuple[str, str]],
    headers: list[str],
    rows: list[list[Any]],
) -> list[list[Any]]:
    width = max(len(headers), 2)
    values: list[list[Any]] = []

    def row_of(*cells: Any) -> list[Any]:
        data = list(cells)
        data.extend([""] * (width - len(data)))
        return data[:width]

    values.append(row_of(f"Excel Factory CRM — {title}"))
    values.append(row_of(f"Сформировано {now.strftime('%d.%m.%Y %H:%M')}"))
    values.append(row_of(""))
    values.append(row_of("Анализ выборки"))
    for label, value in analysis:
        values.append(row_of(label, value))
    values.append(row_of(""))
    values.append(row_of(*headers))
    if rows:
        for item in rows:
            padded = list(item) + [""] * (width - len(item))
            values.append(padded[:width])
    else:
        values.append(row_of("Нет данных"))
    return values


def _export_format_requests(
    *,
    sheet_id: int,
    columns: int,
    analysis_rows: int,
    header_row: int,
    data_rows: int,
    title: str,
) -> list[dict[str, Any]]:
    last_row = header_row + max(data_rows, 1) + 1
    analysis_start = 4
    analysis_end = 4 + analysis_rows

    def grid(r1: int, c1: int, r2: int, c2: int) -> dict[str, int]:
        return {
            "sheetId": sheet_id,
            "startRowIndex": r1,
            "endRowIndex": r2,
            "startColumnIndex": c1,
            "endColumnIndex": c2,
        }

    def paint(r1: int, c1: int, r2: int, c2: int, fmt: dict[str, Any]) -> dict[str, Any]:
        return {
            "repeatCell": {
                "range": grid(r1, c1, r2, c2),
                "cell": {"userEnteredFormat": fmt},
                "fields": ",".join(f"userEnteredFormat.{key}" for key in fmt),
            }
        }

    requests: list[dict[str, Any]] = [
        {
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sheet_id,
                    "title": title[:90],
                    "gridProperties": {"frozenRowCount": header_row + 1},
                },
                "fields": "title,gridProperties.frozenRowCount",
            }
        },
        {
            "mergeCells": {
                "range": grid(0, 0, 1, columns),
                "mergeType": "MERGE_ALL",
            }
        },
        {
            "mergeCells": {
                "range": grid(1, 0, 2, columns),
                "mergeType": "MERGE_ALL",
            }
        },
        paint(
            0,
            0,
            1,
            columns,
            {
                "backgroundColor": _hex(NAVY),
                "horizontalAlignment": "LEFT",
                "verticalAlignment": "MIDDLE",
                "textFormat": {"fontFamily": "Segoe UI", "fontSize": 16, "bold": True, "foregroundColor": _hex(WHITE)},
            },
        ),
        paint(
            1,
            0,
            2,
            columns,
            {
                "backgroundColor": _hex(GOLD),
                "textFormat": {"fontFamily": "Segoe UI", "fontSize": 10, "foregroundColor": _hex(NAVY)},
            },
        ),
        paint(
            3,
            0,
            4,
            columns,
            {
                "textFormat": {"fontFamily": "Segoe UI", "fontSize": 11, "bold": True, "foregroundColor": _hex(NAVY)},
            },
        ),
        paint(
            analysis_start,
            0,
            analysis_end,
            1,
            {"textFormat": {"fontFamily": "Segoe UI", "fontSize": 10, "foregroundColor": _hex(MUTED)}},
        ),
        paint(
            header_row,
            0,
            header_row + 1,
            columns,
            {
                "backgroundColor": _hex(NAVY),
                "horizontalAlignment": "CENTER",
                "textFormat": {"fontFamily": "Segoe UI", "fontSize": 10, "bold": True, "foregroundColor": _hex(WHITE)},
            },
        ),
        {
            "updateBorders": {
                "range": grid(header_row, 0, last_row, columns),
                "top": {"style": "SOLID", "color": _hex(NAVY)},
                "bottom": {"style": "SOLID", "color": _hex(LINE)},
                "left": {"style": "SOLID", "color": _hex(LINE)},
                "right": {"style": "SOLID", "color": _hex(LINE)},
                "innerHorizontal": {"style": "SOLID", "color": _hex(LINE)},
                "innerVertical": {"style": "SOLID", "color": _hex(LINE)},
            }
        },
        {
            "updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": 0, "endIndex": 1},
                "properties": {"pixelSize": 42},
                "fields": "pixelSize",
            }
        },
    ]
    for index in range(columns):
        width = 160 if index else 220
        requests.append(
            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "COLUMNS",
                        "startIndex": index,
                        "endIndex": index + 1,
                    },
                    "properties": {"pixelSize": width},
                    "fields": "pixelSize",
                }
            }
        )
    for offset in range(max(data_rows, 1)):
        if offset % 2:
            requests.append(
                paint(
                    header_row + 1 + offset,
                    0,
                    header_row + 2 + offset,
                    columns,
                    {"backgroundColor": _hex(ZEBRA)},
                )
            )
    return requests


def _code_from_label(label: str, pairs: list[tuple[str, str]]) -> str | None:
    if not label or label.startswith("Все"):
        return None
    for code, title in pairs:
        if title == label:
            return code
    return None


def main() -> None:
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    app = CrmApp()
    app.mainloop()


if __name__ == "__main__":
    main()

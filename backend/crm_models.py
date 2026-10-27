"""Модели таблиц мини-CRM под типы SQLite 3: INTEGER, REAL, TEXT, BLOB.

Схема живёт отдельно от CRUD: CrmDB при старте создаёт каждую таблицу
из TABLES, если файла базы ещё нет или таблица отсутствует.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# --- типы колонок SQLite 3 ---
INTEGER = "INTEGER"
REAL = "REAL"
TEXT = "TEXT"
BLOB = "BLOB"

CLIENT_STATUSES = ("lead", "active", "archived")
DEAL_STATUSES = ("new", "in_progress", "won", "lost", "cancelled")
ORDER_STATUSES = ("new", "confirmed", "in_progress", "paid", "done", "cancelled")

CLIENT_STATUS_DEFAULT = "active"
DEAL_STATUS_DEFAULT = "new"
ORDER_STATUS_DEFAULT = "new"
CURRENCY_DEFAULT = "RUB"

CLIENT_SEARCH_COLUMNS = ("name", "company", "phone", "email", "telegram", "notes")
DEAL_SEARCH_COLUMNS = ("title", "description")
ORDER_SEARCH_COLUMNS = ("title", "description")


@dataclass(frozen=True)
class Column:
    """Описание колонки SQLite: имя, тип и ограничения."""

    name: str
    sqlite_type: str
    primary_key: bool = False
    autoincrement: bool = False
    not_null: bool = False
    unique: bool = False
    default: str | None = None
    references: str | None = None

    def ddl(self) -> str:
        parts = [self.name, self.sqlite_type]
        if self.primary_key:
            parts.append("PRIMARY KEY")
            if self.autoincrement:
                parts.append("AUTOINCREMENT")
        if self.not_null:
            parts.append("NOT NULL")
        if self.unique:
            parts.append("UNIQUE")
        if self.default is not None:
            parts.append(f"DEFAULT {self.default}")
        if self.references:
            parts.append(f"REFERENCES {self.references}")
        return " ".join(parts)


@dataclass(frozen=True)
class Table:
    """Таблица SQLite: колонки, внешние ключи и индексы."""

    name: str
    columns: tuple[Column, ...]
    indexes: tuple[tuple[str, ...], ...] = ()

    def create_sql(self) -> str:
        body = ",\n    ".join(column.ddl() for column in self.columns)
        return f"CREATE TABLE IF NOT EXISTS {self.name} (\n    {body}\n)"

    def index_sqls(self) -> tuple[str, ...]:
        statements: list[str] = []
        for cols in self.indexes:
            index_name = f"idx_{self.name}_{'_'.join(cols)}"
            joined = ", ".join(cols)
            statements.append(
                f"CREATE INDEX IF NOT EXISTS {index_name} ON {self.name} ({joined})"
            )
        return tuple(statements)


# --- схемы таблиц ---

CLIENTS_TABLE = Table(
    name="clients",
    columns=(
        Column("id", INTEGER, primary_key=True, autoincrement=True),
        Column("name", TEXT, not_null=True),
        Column("company", TEXT),
        Column("phone", TEXT),
        Column("email", TEXT),
        Column("telegram", TEXT),
        Column("notes", TEXT),
        Column("status", TEXT, not_null=True, default="'active'"),
        Column("archived_at", TEXT),
        Column("created_at", TEXT, not_null=True),
        Column("updated_at", TEXT, not_null=True),
    ),
    indexes=(("status",), ("phone",), ("email",)),
)

DEALS_TABLE = Table(
    name="deals",
    columns=(
        Column("id", INTEGER, primary_key=True, autoincrement=True),
        Column("title", TEXT, not_null=True),
        Column("client_id", INTEGER, references="clients(id) ON DELETE SET NULL"),
        Column("amount", REAL),
        Column("currency", TEXT, not_null=True, default="'RUB'"),
        Column("status", TEXT, not_null=True, default="'new'"),
        Column("description", TEXT),
        Column("expected_close_at", TEXT),
        Column("created_at", TEXT, not_null=True),
        Column("updated_at", TEXT, not_null=True),
    ),
    indexes=(("client_id",), ("status",)),
)

ORDERS_TABLE = Table(
    name="orders",
    columns=(
        Column("id", INTEGER, primary_key=True, autoincrement=True),
        Column("title", TEXT, not_null=True),
        Column("client_id", INTEGER, references="clients(id) ON DELETE SET NULL"),
        Column("deal_id", INTEGER, references="deals(id) ON DELETE SET NULL"),
        Column("amount", REAL),
        Column("currency", TEXT, not_null=True, default="'RUB'"),
        Column("status", TEXT, not_null=True, default="'new'"),
        Column("description", TEXT),
        Column("due_at", TEXT),
        Column("created_at", TEXT, not_null=True),
        Column("updated_at", TEXT, not_null=True),
    ),
    indexes=(("client_id",), ("deal_id",), ("status",)),
)

TASKS_TABLE = Table(
    name="tasks",
    columns=(
        Column("id", INTEGER, primary_key=True, autoincrement=True),
        Column("title", TEXT, not_null=True),
        Column("description", TEXT),
        Column("client_id", INTEGER, references="clients(id) ON DELETE SET NULL"),
        Column("deal_id", INTEGER, references="deals(id) ON DELETE SET NULL"),
        Column("due_at", TEXT),
        Column("is_done", INTEGER, not_null=True, default="0"),
        Column("created_at", TEXT, not_null=True),
        Column("updated_at", TEXT, not_null=True),
    ),
    indexes=(("client_id",), ("deal_id",), ("is_done",), ("due_at",)),
)

TABLES: tuple[Table, ...] = (
    CLIENTS_TABLE,
    DEALS_TABLE,
    ORDERS_TABLE,
    TASKS_TABLE,
)


# --- строки таблиц ---

@dataclass
class Client:
    id: int
    name: str
    company: str | None
    phone: str | None
    email: str | None
    telegram: str | None
    notes: str | None
    status: str
    archived_at: str | None
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: Any) -> Client:
        return cls(**dict(row))


@dataclass
class Deal:
    id: int
    title: str
    client_id: int | None
    amount: float | None
    currency: str
    status: str
    description: str | None
    expected_close_at: str | None
    created_at: str
    updated_at: str
    client_name: str | None = None

    @classmethod
    def from_row(cls, row: Any) -> Deal:
        data = dict(row)
        data["amount"] = _as_float(data.get("amount"))
        return _row_to(cls, data)


@dataclass
class Order:
    id: int
    title: str
    client_id: int | None
    deal_id: int | None
    amount: float | None
    currency: str
    status: str
    description: str | None
    due_at: str | None
    created_at: str
    updated_at: str
    client_name: str | None = None
    deal_title: str | None = None

    @classmethod
    def from_row(cls, row: Any) -> Order:
        data = dict(row)
        data["amount"] = _as_float(data.get("amount"))
        return _row_to(cls, data)


@dataclass
class Task:
    id: int
    title: str
    description: str | None
    client_id: int | None
    deal_id: int | None
    due_at: str | None
    is_done: bool
    created_at: str
    updated_at: str
    client_name: str | None = None
    deal_title: str | None = None

    @classmethod
    def from_row(cls, row: Any) -> Task:
        data = dict(row)
        data["is_done"] = bool(data.get("is_done"))
        return _row_to(cls, data)


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _row_to(cls: Any, data: dict[str, Any]) -> Any:
    allowed = set(cls.__dataclass_fields__)
    return cls(**{key: data.get(key) for key in allowed})

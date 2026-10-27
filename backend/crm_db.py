"""CRUD-слой мини-CRM на встроенном sqlite3.

Таблицы создаются при инициализации CrmDB, если их ещё нет в указанном файле.
Поиск по клиентам, сделкам и заказам — регистронезависимый LIKE (аналог ILIKE),
в том числе для кириллицы: в соединение регистрируется unicode_lower().
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator, Iterable, Sequence

from crm_models import (
    CLIENT_SEARCH_COLUMNS,
    CLIENT_STATUS_DEFAULT,
    CLIENT_STATUSES,
    CURRENCY_DEFAULT,
    DEAL_SEARCH_COLUMNS,
    DEAL_STATUS_DEFAULT,
    DEAL_STATUSES,
    ORDER_SEARCH_COLUMNS,
    ORDER_STATUS_DEFAULT,
    ORDER_STATUSES,
    TABLES,
    Client,
    Deal,
    Order,
    Task,
)

_PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = _PROJECT_DIR / "data" / "crm.sqlite3"

_CLIENT_UPDATABLE = {
    "name",
    "company",
    "phone",
    "email",
    "telegram",
    "notes",
    "status",
}
_DEAL_UPDATABLE = {
    "title",
    "client_id",
    "amount",
    "currency",
    "status",
    "description",
    "expected_close_at",
}
_ORDER_UPDATABLE = {
    "title",
    "client_id",
    "deal_id",
    "amount",
    "currency",
    "status",
    "description",
    "due_at",
}
_TASK_UPDATABLE = {
    "title",
    "description",
    "client_id",
    "deal_id",
    "due_at",
    "is_done",
}


class CRMNotFound(Exception):
    """Запись не найдена."""

    def __init__(self, entity: str, entity_id: int) -> None:
        self.entity = entity
        self.entity_id = entity_id
        super().__init__(f"{entity} id={entity_id} не найден")


class CRMValidationError(Exception):
    """Некорректные данные для записи в SQLite."""


class CrmDB:
    """Все CRUD-операции CRM над одним файлом SQLite."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        raw = str(db_path) if db_path is not None else os.getenv("CRM_DB_PATH", "")
        raw = raw.strip()
        path = Path(raw) if raw else DEFAULT_DB_PATH
        if not path.is_absolute():
            path = _PROJECT_DIR / path
        self.db_path = path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.create_function("unicode_lower", 1, _unicode_lower, deterministic=True)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            for table in TABLES:
                conn.execute(table.create_sql())
                for statement in table.index_sqls():
                    conn.execute(statement)

    # --- клиенты ---

    def create_client(
        self,
        name: str,
        *,
        company: str | None = None,
        phone: str | None = None,
        email: str | None = None,
        telegram: str | None = None,
        notes: str | None = None,
        status: str = CLIENT_STATUS_DEFAULT,
    ) -> Client:
        name = _required_text(name, "name")
        status = _status(status, CLIENT_STATUSES, "клиента")
        now = _now()
        archived_at = now if status == "archived" else None
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO clients (
                    name, company, phone, email, telegram, notes,
                    status, archived_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    _empty_to_none(company),
                    _empty_to_none(phone),
                    _empty_to_none(email),
                    _empty_to_none(telegram),
                    _empty_to_none(notes),
                    status,
                    archived_at,
                    now,
                    now,
                ),
            )
            return Client.from_row(_fetch_by_id(conn, "clients", cursor.lastrowid))

    def get_client(self, client_id: int) -> Client:
        with self._connect() as conn:
            return Client.from_row(_require(conn, "clients", client_id))

    def list_clients(
        self,
        *,
        q: str | None = None,
        status: str | None = None,
        include_archived: bool = False,
        limit: int = 200,
        offset: int = 0,
    ) -> dict[str, Any]:
        if status is not None:
            status = _status(status, CLIENT_STATUSES, "клиента")
        limit, offset = _page(limit, offset)
        where: list[str] = []
        params: list[Any] = []
        if q and q.strip():
            clause, values = _ilike_clause(CLIENT_SEARCH_COLUMNS, q)
            where.append(clause)
            params.extend(values)
        if status is not None:
            where.append("status = ?")
            params.append(status)
        elif not include_archived:
            where.append("status != 'archived'")
        return self._list("clients", Client, where, params, "name COLLATE NOCASE", limit, offset)

    def update_client(self, client_id: int, fields: dict[str, Any]) -> Client:
        data = _pick(fields, _CLIENT_UPDATABLE)
        if "name" in data:
            data["name"] = _required_text(data["name"], "name")
        if "status" in data:
            data["status"] = _status(data["status"], CLIENT_STATUSES, "клиента")
            data["archived_at"] = _now() if data["status"] == "archived" else None
        for key in ("company", "phone", "email", "telegram", "notes"):
            if key in data:
                data[key] = _empty_to_none(data[key])
        with self._connect() as conn:
            _require(conn, "clients", client_id)
            _update_row(conn, "clients", client_id, data)
            return Client.from_row(_require(conn, "clients", client_id))

    def archive_client(self, client_id: int) -> Client:
        return self.update_client(client_id, {"status": "archived"})

    def restore_client(self, client_id: int) -> Client:
        return self.update_client(client_id, {"status": "active"})

    def delete_client(self, client_id: int) -> None:
        self._delete("clients", client_id)

    # --- сделки ---

    def create_deal(
        self,
        title: str,
        *,
        client_id: int | None = None,
        amount: float | None = None,
        currency: str = CURRENCY_DEFAULT,
        status: str = DEAL_STATUS_DEFAULT,
        description: str | None = None,
        expected_close_at: str | None = None,
    ) -> Deal:
        title = _required_text(title, "title")
        status = _status(status, DEAL_STATUSES, "сделки")
        amount = _amount(amount)
        now = _now()
        with self._connect() as conn:
            _assert_optional_fk(conn, "clients", client_id)
            cursor = conn.execute(
                """
                INSERT INTO deals (
                    title, client_id, amount, currency, status,
                    description, expected_close_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    title,
                    client_id,
                    amount,
                    _required_text(currency, "currency"),
                    status,
                    _empty_to_none(description),
                    _empty_to_none(expected_close_at),
                    now,
                    now,
                ),
            )
            return Deal.from_row(_fetch_by_id(conn, "deals", cursor.lastrowid))

    def get_deal(self, deal_id: int) -> Deal:
        with self._connect() as conn:
            return Deal.from_row(_require_deal(conn, deal_id))

    def list_deals(
        self,
        *,
        q: str | None = None,
        status: str | None = None,
        client_id: int | None = None,
        unassigned: bool = False,
        limit: int = 200,
        offset: int = 0,
    ) -> dict[str, Any]:
        if status is not None:
            status = _status(status, DEAL_STATUSES, "сделки")
        limit, offset = _page(limit, offset)
        where: list[str] = []
        params: list[Any] = []
        if q and q.strip():
            clause, values = _ilike_clause(
                [f"deals.{col}" for col in DEAL_SEARCH_COLUMNS] + ["clients.name"],
                q,
            )
            where.append(clause)
            params.extend(values)
        if status is not None:
            where.append("deals.status = ?")
            params.append(status)
        if unassigned:
            where.append("deals.client_id IS NULL")
        elif client_id is not None:
            where.append("deals.client_id = ?")
            params.append(client_id)
        join = "LEFT JOIN clients ON clients.id = deals.client_id"
        return self._list(
            "deals",
            Deal,
            where,
            params,
            "deals.updated_at DESC",
            limit,
            offset,
            join=join,
            select="deals.*, clients.name AS client_name",
        )

    def update_deal(self, deal_id: int, fields: dict[str, Any]) -> Deal:
        data = _pick(fields, _DEAL_UPDATABLE)
        if "title" in data:
            data["title"] = _required_text(data["title"], "title")
        if "status" in data:
            data["status"] = _status(data["status"], DEAL_STATUSES, "сделки")
        if "amount" in data:
            data["amount"] = _amount(data["amount"])
        if "currency" in data:
            data["currency"] = _required_text(data["currency"], "currency")
        if "description" in data:
            data["description"] = _empty_to_none(data["description"])
        if "expected_close_at" in data:
            data["expected_close_at"] = _empty_to_none(data["expected_close_at"])
        with self._connect() as conn:
            _require(conn, "deals", deal_id)
            if "client_id" in data:
                _assert_optional_fk(conn, "clients", data["client_id"])
            _update_row(conn, "deals", deal_id, data)
            return Deal.from_row(_require_deal(conn, deal_id))

    def set_deal_status(self, deal_id: int, status: str) -> Deal:
        return self.update_deal(deal_id, {"status": status})

    def attach_deal_client(self, deal_id: int, client_id: int | None) -> Deal:
        return self.update_deal(deal_id, {"client_id": client_id})

    def delete_deal(self, deal_id: int) -> None:
        self._delete("deals", deal_id)

    # --- заказы ---

    def create_order(
        self,
        title: str,
        *,
        client_id: int | None = None,
        deal_id: int | None = None,
        amount: float | None = None,
        currency: str = CURRENCY_DEFAULT,
        status: str = ORDER_STATUS_DEFAULT,
        description: str | None = None,
        due_at: str | None = None,
    ) -> Order:
        title = _required_text(title, "title")
        status = _status(status, ORDER_STATUSES, "заказа")
        amount = _amount(amount)
        now = _now()
        with self._connect() as conn:
            _assert_optional_fk(conn, "clients", client_id)
            _assert_optional_fk(conn, "deals", deal_id)
            cursor = conn.execute(
                """
                INSERT INTO orders (
                    title, client_id, deal_id, amount, currency, status,
                    description, due_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    title,
                    client_id,
                    deal_id,
                    amount,
                    _required_text(currency, "currency"),
                    status,
                    _empty_to_none(description),
                    _empty_to_none(due_at),
                    now,
                    now,
                ),
            )
            return Order.from_row(_fetch_by_id(conn, "orders", cursor.lastrowid))

    def get_order(self, order_id: int) -> Order:
        with self._connect() as conn:
            return Order.from_row(_require_order(conn, order_id))

    def list_orders(
        self,
        *,
        q: str | None = None,
        status: str | None = None,
        client_id: int | None = None,
        deal_id: int | None = None,
        unassigned: bool = False,
        limit: int = 200,
        offset: int = 0,
    ) -> dict[str, Any]:
        if status is not None:
            status = _status(status, ORDER_STATUSES, "заказа")
        limit, offset = _page(limit, offset)
        where: list[str] = []
        params: list[Any] = []
        if q and q.strip():
            clause, values = _ilike_clause(
                [f"orders.{col}" for col in ORDER_SEARCH_COLUMNS] + ["clients.name"],
                q,
            )
            where.append(clause)
            params.extend(values)
        if status is not None:
            where.append("orders.status = ?")
            params.append(status)
        if deal_id is not None:
            where.append("orders.deal_id = ?")
            params.append(deal_id)
        if unassigned:
            where.append("orders.client_id IS NULL")
        elif client_id is not None:
            where.append("orders.client_id = ?")
            params.append(client_id)
        join = (
            "LEFT JOIN clients ON clients.id = orders.client_id "
            "LEFT JOIN deals ON deals.id = orders.deal_id"
        )
        return self._list(
            "orders",
            Order,
            where,
            params,
            "orders.updated_at DESC",
            limit,
            offset,
            join=join,
            select="orders.*, clients.name AS client_name, deals.title AS deal_title",
        )

    def update_order(self, order_id: int, fields: dict[str, Any]) -> Order:
        data = _pick(fields, _ORDER_UPDATABLE)
        if "title" in data:
            data["title"] = _required_text(data["title"], "title")
        if "status" in data:
            data["status"] = _status(data["status"], ORDER_STATUSES, "заказа")
        if "amount" in data:
            data["amount"] = _amount(data["amount"])
        if "currency" in data:
            data["currency"] = _required_text(data["currency"], "currency")
        for key in ("description", "due_at"):
            if key in data:
                data[key] = _empty_to_none(data[key])
        with self._connect() as conn:
            _require(conn, "orders", order_id)
            if "client_id" in data:
                _assert_optional_fk(conn, "clients", data["client_id"])
            if "deal_id" in data:
                _assert_optional_fk(conn, "deals", data["deal_id"])
            _update_row(conn, "orders", order_id, data)
            return Order.from_row(_require_order(conn, order_id))

    def set_order_status(self, order_id: int, status: str) -> Order:
        return self.update_order(order_id, {"status": status})

    def attach_order_client(self, order_id: int, client_id: int | None) -> Order:
        return self.update_order(order_id, {"client_id": client_id})

    def delete_order(self, order_id: int) -> None:
        self._delete("orders", order_id)

    # --- задачи и напоминания ---

    def create_task(
        self,
        title: str,
        *,
        description: str | None = None,
        client_id: int | None = None,
        deal_id: int | None = None,
        due_at: str | None = None,
        is_done: bool = False,
    ) -> Task:
        title = _required_text(title, "title")
        now = _now()
        with self._connect() as conn:
            _assert_optional_fk(conn, "clients", client_id)
            _assert_optional_fk(conn, "deals", deal_id)
            cursor = conn.execute(
                """
                INSERT INTO tasks (
                    title, description, client_id, deal_id, due_at,
                    is_done, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    title,
                    _empty_to_none(description),
                    client_id,
                    deal_id,
                    _empty_to_none(due_at),
                    int(bool(is_done)),
                    now,
                    now,
                ),
            )
            return Task.from_row(_fetch_by_id(conn, "tasks", cursor.lastrowid))

    def get_task(self, task_id: int) -> Task:
        with self._connect() as conn:
            return Task.from_row(_require_task(conn, task_id))

    def list_tasks(
        self,
        *,
        client_id: int | None = None,
        deal_id: int | None = None,
        is_done: bool | None = None,
        overdue: bool = False,
        limit: int = 200,
        offset: int = 0,
    ) -> dict[str, Any]:
        limit, offset = _page(limit, offset)
        where: list[str] = []
        params: list[Any] = []
        if client_id is not None:
            where.append("tasks.client_id = ?")
            params.append(client_id)
        if deal_id is not None:
            where.append("tasks.deal_id = ?")
            params.append(deal_id)
        if is_done is not None:
            where.append("tasks.is_done = ?")
            params.append(int(is_done))
        if overdue:
            where.append("tasks.is_done = 0 AND tasks.due_at IS NOT NULL AND tasks.due_at < ?")
            params.append(_now())
        return self._list(
            "tasks",
            Task,
            where,
            params,
            "tasks.due_at IS NULL, tasks.due_at ASC",
            limit,
            offset,
            join=(
                "LEFT JOIN clients ON clients.id = tasks.client_id "
                "LEFT JOIN deals ON deals.id = tasks.deal_id"
            ),
            select="tasks.*, clients.name AS client_name, deals.title AS deal_title",
        )

    def update_task(self, task_id: int, fields: dict[str, Any]) -> Task:
        data = _pick(fields, _TASK_UPDATABLE)
        if "title" in data:
            data["title"] = _required_text(data["title"], "title")
        if "is_done" in data:
            data["is_done"] = int(bool(data["is_done"]))
        for key in ("description", "due_at"):
            if key in data:
                data[key] = _empty_to_none(data[key])
        with self._connect() as conn:
            _require(conn, "tasks", task_id)
            if "client_id" in data:
                _assert_optional_fk(conn, "clients", data["client_id"])
            if "deal_id" in data:
                _assert_optional_fk(conn, "deals", data["deal_id"])
            _update_row(conn, "tasks", task_id, data)
            return Task.from_row(_require_task(conn, task_id))

    def complete_task(self, task_id: int) -> Task:
        return self.update_task(task_id, {"is_done": True})

    def reopen_task(self, task_id: int) -> Task:
        return self.update_task(task_id, {"is_done": False})

    def delete_task(self, task_id: int) -> None:
        self._delete("tasks", task_id)

    # --- сводка ---

    def stats(self) -> dict[str, Any]:
        now = _now()
        with self._connect() as conn:
            clients_total = _count(conn, "SELECT COUNT(*) FROM clients")
            clients_by_status = _counts_by(conn, "clients", "status", CLIENT_STATUSES)
            deals_total = _count(conn, "SELECT COUNT(*) FROM deals")
            deals_by_status = _counts_by(conn, "deals", "status", DEAL_STATUSES)
            open_deals_amount = conn.execute(
                """
                SELECT COALESCE(SUM(amount), 0)
                FROM deals
                WHERE status IN ('new', 'in_progress')
                """
            ).fetchone()[0]
            orders_total = _count(conn, "SELECT COUNT(*) FROM orders")
            orders_by_status = _counts_by(conn, "orders", "status", ORDER_STATUSES)
            tasks_open = _count(conn, "SELECT COUNT(*) FROM tasks WHERE is_done = 0")
            tasks_done = _count(conn, "SELECT COUNT(*) FROM tasks WHERE is_done = 1")
            tasks_overdue = _count(
                conn,
                """
                SELECT COUNT(*) FROM tasks
                WHERE is_done = 0 AND due_at IS NOT NULL AND due_at < ?
                """,
                (now,),
            )
        return {
            "clients": {"total": clients_total, "by_status": clients_by_status},
            "deals": {
                "total": deals_total,
                "by_status": deals_by_status,
                "open_amount": float(open_deals_amount or 0),
            },
            "orders": {"total": orders_total, "by_status": orders_by_status},
            "tasks": {
                "open": tasks_open,
                "done": tasks_done,
                "overdue": tasks_overdue,
            },
        }

    # --- общее ---

    def _list(
        self,
        table: str,
        factory: Any,
        where: Sequence[str],
        params: Sequence[Any],
        order_by: str,
        limit: int,
        offset: int,
        *,
        join: str = "",
        select: str = "*",
    ) -> dict[str, Any]:
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        from_sql = f"{table} {join}".strip()
        with self._connect() as conn:
            total = _count(conn, f"SELECT COUNT(*) FROM {from_sql} {where_sql}", params)
            rows = conn.execute(
                f"""
                SELECT {select} FROM {from_sql}
                {where_sql}
                ORDER BY {order_by}
                LIMIT ? OFFSET ?
                """,
                [*params, limit, offset],
            ).fetchall()
        return {
            "items": [factory.from_row(row) for row in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    def _delete(self, table: str, entity_id: int) -> None:
        with self._connect() as conn:
            _require(conn, table, entity_id)
            conn.execute(f"DELETE FROM {table} WHERE id = ?", (entity_id,))


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _unicode_lower(value: str | None) -> str:
    return "" if value is None else str(value).casefold()


def _empty_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def _required_text(value: str | None, field: str) -> str:
    text = (value or "").strip()
    if not text:
        raise CRMValidationError(f"Поле {field} обязательно")
    return text


def _status(value: str, allowed: Iterable[str], label: str) -> str:
    status = (value or "").strip()
    allowed_tuple = tuple(allowed)
    if status not in allowed_tuple:
        raise CRMValidationError(
            f"Недопустимый статус {label}: {value}. Допустимы: {', '.join(allowed_tuple)}"
        )
    return status


def _amount(value: float | int | None) -> float | None:
    if value is None:
        return None
    amount = float(value)
    if amount < 0:
        raise CRMValidationError("Сумма не может быть отрицательной")
    return amount


def _page(limit: int, offset: int) -> tuple[int, int]:
    if limit < 1 or limit > 5000:
        raise CRMValidationError("limit должен быть от 1 до 5000")
    if offset < 0:
        raise CRMValidationError("offset не может быть отрицательным")
    return limit, offset


def _pick(fields: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
    return {key: value for key, value in fields.items() if key in allowed}


def _like_pattern(query: str) -> str:
    escaped = (
        query.strip()
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
    return f"%{escaped.casefold()}%"


def _ilike_clause(columns: Sequence[str], query: str) -> tuple[str, list[str]]:
    pattern = _like_pattern(query)
    parts = [f"unicode_lower({column}) LIKE ? ESCAPE '\\'" for column in columns]
    return "(" + " OR ".join(parts) + ")", [pattern] * len(columns)


def _fetch_by_id(conn: sqlite3.Connection, table: str, entity_id: int | None) -> sqlite3.Row:
    if entity_id is None:
        raise CRMValidationError(f"Не удалось создать запись в {table}")
    row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (entity_id,)).fetchone()
    if row is None:
        raise CRMNotFound(table, entity_id)
    return row


def _require(conn: sqlite3.Connection, table: str, entity_id: int) -> sqlite3.Row:
    row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (entity_id,)).fetchone()
    if row is None:
        raise CRMNotFound(table, entity_id)
    return row


def _require_deal(conn: sqlite3.Connection, deal_id: int) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT deals.*, clients.name AS client_name
        FROM deals
        LEFT JOIN clients ON clients.id = deals.client_id
        WHERE deals.id = ?
        """,
        (deal_id,),
    ).fetchone()
    if row is None:
        raise CRMNotFound("deals", deal_id)
    return row


def _require_order(conn: sqlite3.Connection, order_id: int) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT orders.*, clients.name AS client_name, deals.title AS deal_title
        FROM orders
        LEFT JOIN clients ON clients.id = orders.client_id
        LEFT JOIN deals ON deals.id = orders.deal_id
        WHERE orders.id = ?
        """,
        (order_id,),
    ).fetchone()
    if row is None:
        raise CRMNotFound("orders", order_id)
    return row


def _require_task(conn: sqlite3.Connection, task_id: int) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT tasks.*, clients.name AS client_name, deals.title AS deal_title
        FROM tasks
        LEFT JOIN clients ON clients.id = tasks.client_id
        LEFT JOIN deals ON deals.id = tasks.deal_id
        WHERE tasks.id = ?
        """,
        (task_id,),
    ).fetchone()
    if row is None:
        raise CRMNotFound("tasks", task_id)
    return row


def _assert_optional_fk(conn: sqlite3.Connection, table: str, entity_id: int | None) -> None:
    if entity_id is None:
        return
    _require(conn, table, entity_id)


def _update_row(
    conn: sqlite3.Connection,
    table: str,
    entity_id: int,
    fields: dict[str, Any],
) -> None:
    if not fields:
        return
    fields = {**fields, "updated_at": _now()}
    assignments = ", ".join(f"{key} = ?" for key in fields)
    conn.execute(
        f"UPDATE {table} SET {assignments} WHERE id = ?",
        [*fields.values(), entity_id],
    )


def _count(conn: sqlite3.Connection, sql: str, params: Sequence[Any] = ()) -> int:
    return int(conn.execute(sql, params).fetchone()[0])


def _counts_by(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    known: Sequence[str],
) -> dict[str, int]:
    rows = conn.execute(
        f"SELECT {column} AS key, COUNT(*) AS total FROM {table} GROUP BY {column}"
    ).fetchall()
    result = {key: 0 for key in known}
    for row in rows:
        result[str(row["key"])] = int(row["total"])
    return result

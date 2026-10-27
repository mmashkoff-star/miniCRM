"""FastAPI-бэкенд мини-CRM: клиенты, сделки, заказы, задачи.

Запуск:
    python backend/crm.py
Документация: http://127.0.0.1:8000/docs
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from crm_db import CRMNotFound, CRMValidationError, CrmDB
from crm_models import (
    CLIENT_STATUSES,
    DEAL_STATUSES,
    ORDER_STATUSES,
)

_BACKEND_DIR = Path(__file__).resolve().parent
_PROJECT_DIR = _BACKEND_DIR.parent


def _load_dotenv(path: Path | None = None) -> None:
    env_path = path or _PROJECT_DIR / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'").strip('"'))


@asynccontextmanager
async def lifespan(app: FastAPI):
    _load_dotenv()
    app.state.db = CrmDB(os.getenv("CRM_DB_PATH"))
    yield


app = FastAPI(
    title="Excel Factory CRM",
    description="MVP мини-CRM: клиенты, сделки, заказы и задачи взаимодействия.",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db(request: Request) -> CrmDB:
    return request.app.state.db


@app.exception_handler(CRMNotFound)
async def not_found_handler(_request: Request, exc: CRMNotFound) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(CRMValidationError)
async def validation_handler(_request: Request, exc: CRMValidationError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


# --- схемы запросов ---

class ClientCreate(BaseModel):
    name: str = Field(min_length=1)
    company: str | None = None
    phone: str | None = None
    email: str | None = None
    telegram: str | None = None
    notes: str | None = None
    status: Literal["lead", "active", "archived"] = "active"


class ClientUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    company: str | None = None
    phone: str | None = None
    email: str | None = None
    telegram: str | None = None
    notes: str | None = None
    status: Literal["lead", "active", "archived"] | None = None


class DealCreate(BaseModel):
    title: str = Field(min_length=1)
    client_id: int | None = None
    amount: float | None = Field(default=None, ge=0)
    currency: str = "RUB"
    status: Literal["new", "in_progress", "won", "lost", "cancelled"] = "new"
    description: str | None = None
    expected_close_at: str | None = None


class DealUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1)
    client_id: int | None = None
    amount: float | None = Field(default=None, ge=0)
    currency: str | None = None
    status: Literal["new", "in_progress", "won", "lost", "cancelled"] | None = None
    description: str | None = None
    expected_close_at: str | None = None


class OrderCreate(BaseModel):
    title: str = Field(min_length=1)
    client_id: int | None = None
    deal_id: int | None = None
    amount: float | None = Field(default=None, ge=0)
    currency: str = "RUB"
    status: Literal["new", "confirmed", "in_progress", "paid", "done", "cancelled"] = "new"
    description: str | None = None
    due_at: str | None = None


class OrderUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1)
    client_id: int | None = None
    deal_id: int | None = None
    amount: float | None = Field(default=None, ge=0)
    currency: str | None = None
    status: Literal["new", "confirmed", "in_progress", "paid", "done", "cancelled"] | None = None
    description: str | None = None
    due_at: str | None = None


class TaskCreate(BaseModel):
    title: str = Field(min_length=1)
    description: str | None = None
    client_id: int | None = None
    deal_id: int | None = None
    due_at: str | None = None
    is_done: bool = False


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1)
    description: str | None = None
    client_id: int | None = None
    deal_id: int | None = None
    due_at: str | None = None
    is_done: bool | None = None


class StatusBody(BaseModel):
    status: str = Field(min_length=1)


class AttachClientBody(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {"client_id": 1}})
    client_id: int | None = None


def _dump(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, dict):
        return {key: _dump(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_dump(item) for item in value]
    return value


# --- служебные ---

@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/docs")


@app.get("/health", tags=["system"])
def health(db: CrmDB = Depends(get_db)) -> dict[str, Any]:
    return {"status": "ok", "db": str(db.db_path)}


@app.get("/stats", tags=["system"])
def stats(db: CrmDB = Depends(get_db)) -> dict[str, Any]:
    return db.stats()


@app.get("/meta", tags=["system"])
def meta() -> dict[str, Any]:
    return {
        "client_statuses": list(CLIENT_STATUSES),
        "deal_statuses": list(DEAL_STATUSES),
        "order_statuses": list(ORDER_STATUSES),
    }


# --- клиенты ---

@app.post("/clients", tags=["clients"], status_code=201)
def create_client(payload: ClientCreate, db: CrmDB = Depends(get_db)) -> dict[str, Any]:
    return _dump(db.create_client(**payload.model_dump()))


@app.get("/clients", tags=["clients"])
def list_clients(
    q: str | None = Query(default=None, description="Поиск ILIKE по имени, компании, телефону, email, telegram, заметкам"),
    status: Literal["lead", "active", "archived"] | None = None,
    include_archived: bool = False,
    limit: int = Query(default=200, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    db: CrmDB = Depends(get_db),
) -> dict[str, Any]:
    return _dump(
        db.list_clients(
            q=q,
            status=status,
            include_archived=include_archived,
            limit=limit,
            offset=offset,
        )
    )


@app.get("/clients/{client_id}", tags=["clients"])
def get_client(client_id: int, db: CrmDB = Depends(get_db)) -> dict[str, Any]:
    return _dump(db.get_client(client_id))


@app.patch("/clients/{client_id}", tags=["clients"])
def update_client(
    client_id: int,
    payload: ClientUpdate,
    db: CrmDB = Depends(get_db),
) -> dict[str, Any]:
    return _dump(db.update_client(client_id, payload.model_dump(exclude_unset=True)))


@app.delete("/clients/{client_id}", tags=["clients"], status_code=204)
def delete_client(client_id: int, db: CrmDB = Depends(get_db)) -> None:
    db.delete_client(client_id)


@app.post("/clients/{client_id}/archive", tags=["clients"])
def archive_client(client_id: int, db: CrmDB = Depends(get_db)) -> dict[str, Any]:
    return _dump(db.archive_client(client_id))


@app.post("/clients/{client_id}/restore", tags=["clients"])
def restore_client(client_id: int, db: CrmDB = Depends(get_db)) -> dict[str, Any]:
    return _dump(db.restore_client(client_id))


# --- сделки ---

@app.post("/deals", tags=["deals"], status_code=201)
def create_deal(payload: DealCreate, db: CrmDB = Depends(get_db)) -> dict[str, Any]:
    return _dump(db.create_deal(**payload.model_dump()))


@app.get("/deals", tags=["deals"])
def list_deals(
    q: str | None = Query(default=None, description="Поиск ILIKE по названию, описанию и имени клиента"),
    status: Literal["new", "in_progress", "won", "lost", "cancelled"] | None = None,
    client_id: int | None = None,
    unassigned: bool = Query(default=False, description="Только сделки без клиента"),
    limit: int = Query(default=200, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    db: CrmDB = Depends(get_db),
) -> dict[str, Any]:
    return _dump(
        db.list_deals(
            q=q,
            status=status,
            client_id=client_id,
            unassigned=unassigned,
            limit=limit,
            offset=offset,
        )
    )


@app.get("/deals/{deal_id}", tags=["deals"])
def get_deal(deal_id: int, db: CrmDB = Depends(get_db)) -> dict[str, Any]:
    return _dump(db.get_deal(deal_id))


@app.patch("/deals/{deal_id}", tags=["deals"])
def update_deal(deal_id: int, payload: DealUpdate, db: CrmDB = Depends(get_db)) -> dict[str, Any]:
    return _dump(db.update_deal(deal_id, payload.model_dump(exclude_unset=True)))


@app.delete("/deals/{deal_id}", tags=["deals"], status_code=204)
def delete_deal(deal_id: int, db: CrmDB = Depends(get_db)) -> None:
    db.delete_deal(deal_id)


@app.post("/deals/{deal_id}/status", tags=["deals"])
def set_deal_status(
    deal_id: int,
    payload: StatusBody,
    db: CrmDB = Depends(get_db),
) -> dict[str, Any]:
    return _dump(db.set_deal_status(deal_id, payload.status))


@app.post("/deals/{deal_id}/client", tags=["deals"])
def attach_deal_client(
    deal_id: int,
    payload: AttachClientBody,
    db: CrmDB = Depends(get_db),
) -> dict[str, Any]:
    return _dump(db.attach_deal_client(deal_id, payload.client_id))


# --- заказы ---

@app.post("/orders", tags=["orders"], status_code=201)
def create_order(payload: OrderCreate, db: CrmDB = Depends(get_db)) -> dict[str, Any]:
    return _dump(db.create_order(**payload.model_dump()))


@app.get("/orders", tags=["orders"])
def list_orders(
    q: str | None = Query(default=None, description="Поиск ILIKE по названию, описанию и имени клиента"),
    status: Literal["new", "confirmed", "in_progress", "paid", "done", "cancelled"] | None = None,
    client_id: int | None = None,
    deal_id: int | None = None,
    unassigned: bool = Query(default=False, description="Только заказы без клиента"),
    limit: int = Query(default=200, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    db: CrmDB = Depends(get_db),
) -> dict[str, Any]:
    return _dump(
        db.list_orders(
            q=q,
            status=status,
            client_id=client_id,
            deal_id=deal_id,
            unassigned=unassigned,
            limit=limit,
            offset=offset,
        )
    )


@app.get("/orders/{order_id}", tags=["orders"])
def get_order(order_id: int, db: CrmDB = Depends(get_db)) -> dict[str, Any]:
    return _dump(db.get_order(order_id))


@app.patch("/orders/{order_id}", tags=["orders"])
def update_order(
    order_id: int,
    payload: OrderUpdate,
    db: CrmDB = Depends(get_db),
) -> dict[str, Any]:
    return _dump(db.update_order(order_id, payload.model_dump(exclude_unset=True)))


@app.delete("/orders/{order_id}", tags=["orders"], status_code=204)
def delete_order(order_id: int, db: CrmDB = Depends(get_db)) -> None:
    db.delete_order(order_id)


@app.post("/orders/{order_id}/status", tags=["orders"])
def set_order_status(
    order_id: int,
    payload: StatusBody,
    db: CrmDB = Depends(get_db),
) -> dict[str, Any]:
    return _dump(db.set_order_status(order_id, payload.status))


@app.post("/orders/{order_id}/client", tags=["orders"])
def attach_order_client(
    order_id: int,
    payload: AttachClientBody,
    db: CrmDB = Depends(get_db),
) -> dict[str, Any]:
    return _dump(db.attach_order_client(order_id, payload.client_id))


# --- задачи ---

@app.post("/tasks", tags=["tasks"], status_code=201)
def create_task(payload: TaskCreate, db: CrmDB = Depends(get_db)) -> dict[str, Any]:
    return _dump(db.create_task(**payload.model_dump()))


@app.get("/tasks", tags=["tasks"])
def list_tasks(
    client_id: int | None = None,
    deal_id: int | None = None,
    is_done: bool | None = None,
    overdue: bool = Query(default=False, description="Только просроченные незакрытые задачи"),
    limit: int = Query(default=200, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    db: CrmDB = Depends(get_db),
) -> dict[str, Any]:
    return _dump(
        db.list_tasks(
            client_id=client_id,
            deal_id=deal_id,
            is_done=is_done,
            overdue=overdue,
            limit=limit,
            offset=offset,
        )
    )


@app.get("/tasks/{task_id}", tags=["tasks"])
def get_task(task_id: int, db: CrmDB = Depends(get_db)) -> dict[str, Any]:
    return _dump(db.get_task(task_id))


@app.patch("/tasks/{task_id}", tags=["tasks"])
def update_task(task_id: int, payload: TaskUpdate, db: CrmDB = Depends(get_db)) -> dict[str, Any]:
    return _dump(db.update_task(task_id, payload.model_dump(exclude_unset=True)))


@app.delete("/tasks/{task_id}", tags=["tasks"], status_code=204)
def delete_task(task_id: int, db: CrmDB = Depends(get_db)) -> None:
    db.delete_task(task_id)


@app.post("/tasks/{task_id}/complete", tags=["tasks"])
def complete_task(task_id: int, db: CrmDB = Depends(get_db)) -> dict[str, Any]:
    return _dump(db.complete_task(task_id))


@app.post("/tasks/{task_id}/reopen", tags=["tasks"])
def reopen_task(task_id: int, db: CrmDB = Depends(get_db)) -> dict[str, Any]:
    return _dump(db.reopen_task(task_id))


if __name__ == "__main__":
    import uvicorn

    _load_dotenv()
    uvicorn.run(
        "crm:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        app_dir=str(_BACKEND_DIR),
        reload_dirs=[str(_BACKEND_DIR)],
    )

# Code Patterns for New Slice

Reference templates. Replace `{Concept}` / `{concept}` with the domain name (e.g. `Member` / `member`).

---

## models.py

```python
# backend/app/{concept}/models.py
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import UUIDBase


class {Concept}(UUIDBase):
    __tablename__ = "{concept}s"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # add fields here
```

---

## repository.py

```python
# backend/app/{concept}/repository.py
from abc import abstractmethod
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base_repository import AbstractRepository
from app.{concept}.models import {Concept}


class Abstract{Concept}Repository(AbstractRepository[{Concept}]):
    @abstractmethod
    async def list_all(self) -> list[{Concept}]: ...
    # add domain-specific query methods here


class Sql{Concept}Repository(Abstract{Concept}Repository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, id: UUID) -> {Concept} | None:
        return await self._session.get({Concept}, str(id))

    async def add(self, entity: {Concept}) -> {Concept}:
        self._session.add(entity)
        await self._session.flush()
        return entity

    async def list_all(self) -> list[{Concept}]:
        result = await self._session.execute(select({Concept}))
        return list(result.scalars().all())
```

---

## schemas.py

```python
# backend/app/{concept}/schemas.py
from pydantic import BaseModel


class {Concept}Create(BaseModel):
    name: str


class {Concept}Read(BaseModel):
    id: str
    name: str

    model_config = {"from_attributes": True}
```

---

## dependencies.py (single-table — repo only)

```python
# backend/app/{concept}/dependencies.py
from collections.abc import AsyncGenerator
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import session_factory
from app.{concept}.repository import Abstract{Concept}Repository, Sql{Concept}Repository


async def _get_session() -> AsyncGenerator[AsyncSession, None]:
    async with session_factory() as session:
        yield session


async def get_{concept}_repo(
    session: AsyncSession = Depends(_get_session),
) -> Abstract{Concept}Repository:
    return Sql{Concept}Repository(session)
```

## dependencies.py (multi-table — use UoW)

```python
# backend/app/{concept}/dependencies.py
# When the router needs to write across 2+ tables, inject get_uow instead.
# In the router: uow: AbstractUnitOfWork = Depends(get_uow)
# Then: repo_a = SqlARepository(uow.session); repo_b = SqlBRepository(uow.session)
# Finally: await uow.commit()
from app.dependencies import get_uow as get_uow  # re-export for clarity
```

---

## router.py

```python
# backend/app/{concept}/router.py
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.{concept}.dependencies import get_{concept}_repo
from app.{concept}.models import {Concept}
from app.{concept}.repository import Abstract{Concept}Repository
from app.{concept}.schemas import {Concept}Create, {Concept}Read

router = APIRouter(prefix="/{concept}s", tags=["{concept}s"])


@router.get("/", response_model=list[{Concept}Read])
async def list_{concept}s(
    repo: Abstract{Concept}Repository = Depends(get_{concept}_repo),
) -> list[{Concept}Read]:
    items = await repo.list_all()
    return [{Concept}Read.model_validate(i) for i in items]


@router.get("/{id}", response_model={Concept}Read)
async def get_{concept}(
    id: UUID,
    repo: Abstract{Concept}Repository = Depends(get_{concept}_repo),
) -> {Concept}Read:
    item = await repo.get(id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return {Concept}Read.model_validate(item)


@router.post("/", response_model={Concept}Read, status_code=status.HTTP_201_CREATED)
async def create_{concept}(
    payload: {Concept}Create,
    repo: Abstract{Concept}Repository = Depends(get_{concept}_repo),
) -> {Concept}Read:
    item = {Concept}(name=payload.name)
    saved = await repo.add(item)
    return {Concept}Read.model_validate(saved)
```

---

## main.py registration

```python
from app.{concept}.router import router as {concept}_router
app.include_router({concept}_router)
```

---

## tests/test_{concept}.py

```python
# backend/tests/test_{concept}.py
from uuid import uuid4
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.{concept}.dependencies import get_{concept}_repo
from app.{concept}.models import {Concept}
from app.{concept}.repository import Abstract{Concept}Repository


class Stub{Concept}Repository(Abstract{Concept}Repository):
    """In-memory stub — no DB, no session, no I/O."""

    def __init__(self, items: list[{Concept}] | None = None) -> None:
        self._items: dict[str, {Concept}] = {i.id: i for i in (items or [])}

    async def get(self, id) -> {Concept} | None:
        return self._items.get(str(id))

    async def add(self, entity: {Concept}) -> {Concept}:
        self._items[entity.id] = entity
        return entity

    async def list_all(self) -> list[{Concept}]:
        return list(self._items.values())


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_list_{concept}s_returns_empty_list() -> None:
    app.dependency_overrides[get_{concept}_repo] = lambda: Stub{Concept}Repository()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/{concept}s/")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.anyio
async def test_get_{concept}_returns_404_when_not_found() -> None:
    app.dependency_overrides[get_{concept}_repo] = lambda: Stub{Concept}Repository()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/{concept}s/{uuid4()}")
    assert response.status_code == 404


@pytest.mark.anyio
async def test_create_{concept}_returns_201() -> None:
    stub = Stub{Concept}Repository()
    app.dependency_overrides[get_{concept}_repo] = lambda: stub
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/{concept}s/", json={"name": "Test"})
    assert response.status_code == 201
    assert response.json()["name"] == "Test"
    assert "id" in response.json()
```

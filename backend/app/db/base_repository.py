from abc import ABC, abstractmethod
from typing import Generic, TypeVar
from uuid import UUID

ModelT = TypeVar("ModelT")


class AbstractRepository(ABC, Generic[ModelT]):
    @abstractmethod
    async def get(self, id: UUID) -> ModelT | None: ...

    @abstractmethod
    async def add(self, entity: ModelT) -> ModelT: ...

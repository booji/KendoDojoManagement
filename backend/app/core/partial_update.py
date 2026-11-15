"""The body of a PUT or PATCH that changes only the fields it names (#585).

One rule for every update endpoint: a key left out leaves its field alone, and
a key sent as ``null`` clears it. A field the record cannot be without lists
itself in ``not_null``, so a ``null`` there is a 422 rather than a silent no-op
or a database error.
"""

from __future__ import annotations

from typing import Any, ClassVar, Self

from pydantic import BaseModel, model_validator


class PartialUpdate(BaseModel):
    not_null: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="after")
    def _refuse_null_where_required(self) -> Self:
        nulled = sorted(
            name
            for name in self.not_null & self.model_fields_set
            if getattr(self, name) is None
        )
        if nulled:
            raise ValueError(f"cannot be null: {', '.join(nulled)}")
        return self

    def changes(self) -> dict[str, Any]:
        """The fields the request named, with the values it gave them."""
        # Not model_dump(exclude_unset=True): that also drops the defaults of
        # nested models, such as a segment's, which the repositories expect.
        dumped = self.model_dump()
        return {name: dumped[name] for name in self.model_fields_set}

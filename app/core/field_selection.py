"""Sparse field selection for API responses.

Allows mobile clients to request only the fields they need via
`?fields=id,name,status` query parameter, reducing payload size.

Usage:
    @router.get("/jobs")
    async def list_jobs(
        field_selector: FieldSelector = Depends(get_field_selector),
    ) -> ...:
        result = ...
        return field_selector.apply(result)
"""

from __future__ import annotations

from typing import Any

from fastapi import Query
from pydantic import BaseModel


class FieldSelector:
    """Filters response data to include only requested fields."""

    def __init__(self, fields: set[str] | None = None):
        self._fields = fields

    @property
    def active(self) -> bool:
        return self._fields is not None

    def apply(self, data: Any) -> Any:
        """Filter a Pydantic model, dict, or list to include only selected fields."""
        if not self.active:
            return data

        if isinstance(data, list):
            return [self._filter_item(item) for item in data]

        return self._filter_item(data)

    def apply_page(self, page: BaseModel) -> dict[str, Any]:
        """Filter items within a CursorPage response."""
        if not self.active:
            return page.model_dump() if isinstance(page, BaseModel) else page

        result = page.model_dump() if isinstance(page, BaseModel) else dict(page)
        if "items" in result:
            result["items"] = [self._filter_item(item) for item in result["items"]]
        return result

    def _filter_item(self, item: Any) -> dict[str, Any]:
        assert self._fields is not None
        if isinstance(item, BaseModel):
            data = item.model_dump()
        elif isinstance(item, dict):
            data = item
        else:
            return item

        result = {}
        for field in self._fields:
            if "." in field:
                # Support nested fields: "owner.name"
                parts = field.split(".", 1)
                parent, child = parts[0], parts[1]
                if parent in data and isinstance(data[parent], dict):
                    if parent not in result:
                        result[parent] = {}
                    if child in data[parent]:
                        result[parent][child] = data[parent][child]
            elif field in data:
                result[field] = data[field]

        return result


def get_field_selector(
    fields: str | None = Query(
        None,
        description="Comma-separated list of fields to include in the response (e.g. id,name,status)",
        examples=["id,name,status"],
    ),
) -> FieldSelector:
    """FastAPI dependency for sparse field selection."""
    if not fields:
        return FieldSelector()

    field_set = {f.strip() for f in fields.split(",") if f.strip()}
    if not field_set:
        return FieldSelector()

    return FieldSelector(field_set)

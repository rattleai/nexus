"""Tests for domain event system and event handlers."""

import pytest

from app.core.events import (
    DomainEvent,
    JobCompleted,
    UserRegistered,
    clear_handlers,
    emit,
    on,
)


@pytest.fixture(autouse=True)
def _clean_handlers():
    """Clear handlers before and after each test."""
    clear_handlers()
    yield
    clear_handlers()


class TestDomainEvents:
    def test_event_name(self):
        event = UserRegistered(user_id="123", email="test@test.com", tenant_id="t1")
        assert event.event_name == "UserRegistered"

    def test_event_has_timestamp(self):
        event = DomainEvent()
        assert event.occurred_at is not None


class TestEventHandlers:
    @pytest.mark.asyncio
    async def test_handler_called_on_emit(self):
        called_with = []

        @on(UserRegistered)
        async def handle(event: UserRegistered):
            called_with.append(event)

        event = UserRegistered(user_id="1", email="a@b.com", tenant_id="t1")
        await emit(event)

        assert len(called_with) == 1
        assert called_with[0].user_id == "1"

    @pytest.mark.asyncio
    async def test_multiple_handlers(self):
        count = {"value": 0}

        @on(JobCompleted)
        async def handle1(event):
            count["value"] += 1

        @on(JobCompleted)
        async def handle2(event):
            count["value"] += 10

        await emit(JobCompleted(job_id="j1", tenant_id="t1", job_type="test"))
        assert count["value"] == 11

    @pytest.mark.asyncio
    async def test_handler_failure_isolated(self):
        called = {"good": False}

        @on(UserRegistered)
        async def bad_handler(event):
            raise RuntimeError("boom")

        @on(UserRegistered)
        async def good_handler(event):
            called["good"] = True

        await emit(UserRegistered(user_id="1", email="a@b.com", tenant_id="t1"))
        assert called["good"] is True

    @pytest.mark.asyncio
    async def test_no_handlers_does_not_error(self):
        await emit(UserRegistered(user_id="1", email="a@b.com", tenant_id="t1"))

    @pytest.mark.asyncio
    async def test_wrong_event_type_not_called(self):
        called = {"value": False}

        @on(JobCompleted)
        async def handle(event):
            called["value"] = True

        await emit(UserRegistered(user_id="1", email="a@b.com", tenant_id="t1"))
        assert called["value"] is False

    def test_clear_handlers(self):
        @on(UserRegistered)
        async def handle(event):
            pass

        from app.core.events import _handlers

        assert len(_handlers[UserRegistered]) == 1
        clear_handlers()
        assert len(_handlers) == 0

"""Replay-guard semantics: the same cart id passes once, then is rejected."""

from __future__ import annotations

import pytest
from apps.api.gateway.replay_guard import check_and_mark_seen
from fakeredis import FakeAsyncRedis


@pytest.fixture
async def redis():
    client = FakeAsyncRedis(decode_responses=True)
    yield client
    await client.aclose()


async def test_first_presentation_is_fresh(redis) -> None:
    assert await check_and_mark_seen(redis, "cart-1", ttl_seconds=3600) is True


async def test_second_presentation_of_the_same_cart_is_a_replay(redis) -> None:
    assert await check_and_mark_seen(redis, "cart-1", ttl_seconds=3600) is True
    assert await check_and_mark_seen(redis, "cart-1", ttl_seconds=3600) is False


async def test_different_cart_ids_are_independent(redis) -> None:
    assert await check_and_mark_seen(redis, "cart-1", ttl_seconds=3600) is True
    assert await check_and_mark_seen(redis, "cart-2", ttl_seconds=3600) is True

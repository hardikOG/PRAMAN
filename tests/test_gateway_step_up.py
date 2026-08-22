"""Step-up tokens: single-use, TTL-bound, mapping back to the decision."""

from __future__ import annotations

import pytest
from apps.api.gateway.step_up import issue_step_up_token, redeem_step_up_token
from fakeredis import FakeAsyncRedis


@pytest.fixture
async def redis():
    client = FakeAsyncRedis(decode_responses=True)
    yield client
    await client.aclose()


async def test_issued_token_redeems_to_the_decision_id(redis) -> None:
    token = await issue_step_up_token(redis, "dec-1", ttl_seconds=900)
    assert await redeem_step_up_token(redis, token) == "dec-1"


async def test_token_is_single_use(redis) -> None:
    token = await issue_step_up_token(redis, "dec-1", ttl_seconds=900)
    await redeem_step_up_token(redis, token)
    assert await redeem_step_up_token(redis, token) is None


async def test_unknown_token_redeems_to_none(redis) -> None:
    assert await redeem_step_up_token(redis, "not-a-real-token") is None


async def test_each_issued_token_is_unique(redis) -> None:
    tokens = {await issue_step_up_token(redis, "dec-1", ttl_seconds=900) for _ in range(20)}
    assert len(tokens) == 20

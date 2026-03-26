from contextlib import asynccontextmanager

import httpx
import pytest

from main import app, lifespan

BASE = "/api/v1"


@pytest.fixture
async def client():
    """Async test client — like WebApplicationFactory in .NET integration tests.

    We manually trigger the lifespan so app.state.service is initialized.
    Each test gets a fresh service/storage instance.
    """
    async with lifespan(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            yield ac


# --- Helper to create a rule ---


async def create_rule(
    client: httpx.AsyncClient,
    rule_id: str = "test_rule",
    algorithm: str = "token_bucket",
    max_requests: int = 5,
    window_seconds: int = 60,
) -> httpx.Response:
    return await client.post(
        f"{BASE}/rules",
        json={
            "rule_id": rule_id,
            "algorithm": algorithm,
            "max_requests": max_requests,
            "window_seconds": window_seconds,
        },
    )


# --- Health ---


async def test_health(client: httpx.AsyncClient):
    resp = await client.get(f"{BASE}/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "healthy"}


# --- Rules CRUD ---


async def test_create_rule(client: httpx.AsyncClient):
    resp = await create_rule(client, rule_id="my_rule", algorithm="fixed_window")
    assert resp.status_code == 201
    data = resp.json()
    assert data["rule_id"] == "my_rule"
    assert data["algorithm"] == "fixed_window"
    assert data["max_requests"] == 5
    assert data["window_seconds"] == 60


async def test_create_rule_with_refill_rate(client: httpx.AsyncClient):
    resp = await client.post(
        f"{BASE}/rules",
        json={
            "rule_id": "custom_refill",
            "algorithm": "token_bucket",
            "max_requests": 10,
            "window_seconds": 60,
            "refill_rate": 2.5,
        },
    )
    assert resp.status_code == 201
    assert resp.json()["refill_rate"] == 2.5


async def test_list_rules(client: httpx.AsyncClient):
    await create_rule(client, rule_id="rule_a")
    await create_rule(client, rule_id="rule_b")
    resp = await client.get(f"{BASE}/rules")
    assert resp.status_code == 200
    rule_ids = [r["rule_id"] for r in resp.json()]
    assert "rule_a" in rule_ids
    assert "rule_b" in rule_ids


async def test_get_rule(client: httpx.AsyncClient):
    await create_rule(client, rule_id="get_me")
    resp = await client.get(f"{BASE}/rules/get_me")
    assert resp.status_code == 200
    assert resp.json()["rule_id"] == "get_me"


async def test_get_rule_not_found(client: httpx.AsyncClient):
    resp = await client.get(f"{BASE}/rules/nonexistent")
    assert resp.status_code == 404


async def test_delete_rule(client: httpx.AsyncClient):
    await create_rule(client, rule_id="delete_me")
    resp = await client.delete(f"{BASE}/rules/delete_me")
    assert resp.status_code == 200
    assert resp.json() == {"deleted": True, "rule_id": "delete_me"}

    # Verify it's gone
    resp = await client.get(f"{BASE}/rules/delete_me")
    assert resp.status_code == 404


async def test_delete_rule_not_found(client: httpx.AsyncClient):
    resp = await client.delete(f"{BASE}/rules/nonexistent")
    assert resp.status_code == 404


# --- Check endpoint ---


async def test_check_allowed(client: httpx.AsyncClient):
    await create_rule(client, rule_id="check_rule", max_requests=5)
    resp = await client.post(
        f"{BASE}/check",
        json={"key": "user:1", "rule_id": "check_rule"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["allowed"] is True
    assert data["remaining"] >= 0
    assert data["retry_after"] is None


async def test_check_denied_after_limit(client: httpx.AsyncClient):
    await create_rule(client, rule_id="limit_rule", max_requests=2)
    for _ in range(2):
        resp = await client.post(
            f"{BASE}/check",
            json={"key": "user:2", "rule_id": "limit_rule"},
        )
        assert resp.json()["allowed"] is True

    resp = await client.post(
        f"{BASE}/check",
        json={"key": "user:2", "rule_id": "limit_rule"},
    )
    data = resp.json()
    assert data["allowed"] is False
    assert data["remaining"] == 0
    assert data["retry_after"] is not None


async def test_check_rule_not_found(client: httpx.AsyncClient):
    resp = await client.post(
        f"{BASE}/check",
        json={"key": "user:1", "rule_id": "no_such_rule"},
    )
    assert resp.status_code == 404


async def test_check_independent_keys(client: httpx.AsyncClient):
    await create_rule(client, rule_id="ind_rule", max_requests=1)

    resp = await client.post(
        f"{BASE}/check",
        json={"key": "user:a", "rule_id": "ind_rule"},
    )
    assert resp.json()["allowed"] is True

    # Different key should also be allowed
    resp = await client.post(
        f"{BASE}/check",
        json={"key": "user:b", "rule_id": "ind_rule"},
    )
    assert resp.json()["allowed"] is True


# --- Status endpoint ---


async def test_status(client: httpx.AsyncClient):
    await create_rule(client, rule_id="status_rule", max_requests=5)
    resp = await client.get(f"{BASE}/status/user:1", params={"rule_id": "status_rule"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["key"] == "user:1"
    assert data["rule_id"] == "status_rule"
    assert data["allowed"] is True
    assert data["remaining"] >= 0


async def test_status_rule_not_found(client: httpx.AsyncClient):
    resp = await client.get(f"{BASE}/status/user:1", params={"rule_id": "missing"})
    assert resp.status_code == 404


# --- All three algorithms work through API ---


async def test_check_with_token_bucket(client: httpx.AsyncClient):
    await create_rule(client, rule_id="tb", algorithm="token_bucket", max_requests=2)
    for _ in range(2):
        resp = await client.post(f"{BASE}/check", json={"key": "u1", "rule_id": "tb"})
        assert resp.json()["allowed"] is True
    resp = await client.post(f"{BASE}/check", json={"key": "u1", "rule_id": "tb"})
    assert resp.json()["allowed"] is False


async def test_check_with_fixed_window(client: httpx.AsyncClient):
    await create_rule(client, rule_id="fw", algorithm="fixed_window", max_requests=2)
    for _ in range(2):
        resp = await client.post(f"{BASE}/check", json={"key": "u1", "rule_id": "fw"})
        assert resp.json()["allowed"] is True
    resp = await client.post(f"{BASE}/check", json={"key": "u1", "rule_id": "fw"})
    assert resp.json()["allowed"] is False


async def test_check_with_sliding_window(client: httpx.AsyncClient):
    await create_rule(client, rule_id="sw", algorithm="sliding_window", max_requests=2)
    for _ in range(2):
        resp = await client.post(f"{BASE}/check", json={"key": "u1", "rule_id": "sw"})
        assert resp.json()["allowed"] is True
    resp = await client.post(f"{BASE}/check", json={"key": "u1", "rule_id": "sw"})
    assert resp.json()["allowed"] is False


# --- Validation ---


async def test_check_empty_key_rejected(client: httpx.AsyncClient):
    resp = await client.post(
        f"{BASE}/check",
        json={"key": "", "rule_id": "some_rule"},
    )
    assert resp.status_code == 422


async def test_create_rule_invalid_algorithm(client: httpx.AsyncClient):
    resp = await client.post(
        f"{BASE}/rules",
        json={
            "rule_id": "bad",
            "algorithm": "not_real",
            "max_requests": 10,
            "window_seconds": 60,
        },
    )
    assert resp.status_code == 422


async def test_create_rule_zero_max_requests(client: httpx.AsyncClient):
    resp = await client.post(
        f"{BASE}/rules",
        json={
            "rule_id": "bad",
            "algorithm": "token_bucket",
            "max_requests": 0,
            "window_seconds": 60,
        },
    )
    assert resp.status_code == 422

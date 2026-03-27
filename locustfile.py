"""
Locust load test for the Rate Limiter API.

Usage (headless, 100 users):
    locust -f locustfile.py --host http://44.203.138.45:8000 \
           --users 100 --spawn-rate 10 --run-time 60s --headless --csv results/load_100

Web UI:
    locust -f locustfile.py --host http://44.203.138.45:8000
    Then open http://localhost:8089
"""

import random

from locust import HttpUser, between, events, task


# ── Rules seeded once before the test run ──────────────────────────────
RULES = [
    {
        "rule_id": "token_bucket_default",
        "algorithm": "token_bucket",
        "max_requests": 1000,
        "window_seconds": 60,
        "refill_rate": 16.67,
    },
    {
        "rule_id": "fixed_window_default",
        "algorithm": "fixed_window",
        "max_requests": 500,
        "window_seconds": 60,
    },
    {
        "rule_id": "sliding_window_default",
        "algorithm": "sliding_window",
        "max_requests": 500,
        "window_seconds": 60,
    },
]

RULE_IDS = [r["rule_id"] for r in RULES]


@events.test_start.add_listener
def seed_rules(environment, **kwargs):
    """Create test rules once before any users spawn."""
    base = environment.host
    if not base:
        return

    import requests as req  # stdlib-free HTTP — only runs once

    for rule in RULES:
        resp = req.post(f"{base}/api/v1/rules", json=rule)
        if resp.status_code in (201, 409):
            print(f"  [seed] rule {rule['rule_id']}: {resp.status_code}")
        else:
            print(f"  [seed] WARN rule {rule['rule_id']}: {resp.status_code} {resp.text}")


# ── Simulated user ────────────────────────────────────────────────────
class RateLimiterUser(HttpUser):
    """
    Traffic mix: 80% check, 15% status, 5% list rules.
    Each user gets a unique key so rate limits don't instantly throttle everyone.
    """

    wait_time = between(0.1, 0.5)

    def on_start(self):
        self.user_key = f"user:{random.randint(1, 100_000)}"

    # 80 % — check if request is allowed
    @task(80)
    def check_request(self):
        rule_id = random.choice(RULE_IDS)
        self.client.post(
            "/api/v1/check",
            json={"key": self.user_key, "rule_id": rule_id},
            name="/api/v1/check",
        )

    # 15 % — get rate-limit status
    @task(15)
    def get_status(self):
        rule_id = random.choice(RULE_IDS)
        self.client.get(
            f"/api/v1/status/{self.user_key}",
            params={"rule_id": rule_id},
            name="/api/v1/status/{key}",
        )

    # 5 % — list all rules
    @task(5)
    def list_rules(self):
        self.client.get("/api/v1/rules", name="/api/v1/rules")

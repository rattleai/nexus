"""Load testing with Locust — tests key API endpoints under concurrent load.

Usage:
    locust -f tests/performance/locustfile.py --host http://localhost:8000

Configuration:
    Set environment variables:
      - API_KEY: A valid API key for the target environment
      - ADMIN_KEY: A valid admin key (for admin endpoints)
"""

import os

from locust import HttpUser, between, task


class SaaSPlatformUser(HttpUser):
    """Simulates a typical API consumer hitting key endpoints."""

    wait_time = between(0.5, 2)

    def on_start(self):
        self.api_key = os.environ.get("API_KEY", "sk_test_key")
        self.admin_key = os.environ.get("ADMIN_KEY", "test_admin_key")
        self.headers = {"X-API-Key": self.api_key}
        self.admin_headers = {"X-Admin-Key": self.admin_key}

    @task(5)
    def health_check(self):
        self.client.get("/api/v1/health/live")

    @task(3)
    def list_jobs(self):
        self.client.get("/api/v1/jobs", headers=self.headers)

    @task(2)
    def create_job(self):
        self.client.post(
            "/api/v1/jobs",
            json={"type": "load_test", "payload": {"test": True}},
            headers=self.headers,
        )

    @task(1)
    def get_job_status(self):
        # Create a job first, then check status
        response = self.client.post(
            "/api/v1/jobs",
            json={"type": "status_check", "payload": {}},
            headers=self.headers,
            name="/api/v1/jobs (create for status check)",
        )
        if response.status_code == 201:
            job_id = response.json().get("id")
            if job_id:
                self.client.get(f"/api/v1/jobs/{job_id}", headers=self.headers)


class AdminUser(HttpUser):
    """Simulates admin dashboard usage."""

    wait_time = between(2, 5)
    weight = 1  # Less frequent than regular users

    def on_start(self):
        self.admin_key = os.environ.get("ADMIN_KEY", "test_admin_key")
        self.headers = {"X-Admin-Key": self.admin_key}

    @task(3)
    def system_stats(self):
        self.client.get("/api/v1/admin/stats", headers=self.headers)

    @task(2)
    def list_tenants(self):
        self.client.get("/api/v1/admin/tenants", headers=self.headers)

    @task(1)
    def list_audit_logs(self):
        self.client.get("/api/v1/admin/audit-logs", headers=self.headers)

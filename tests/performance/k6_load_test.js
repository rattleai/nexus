/**
 * k6 Load Test — SaaS Platform API
 *
 * Tests key API endpoints under configurable concurrent load.
 * Validates response times, error rates, and throughput.
 *
 * Usage:
 *   k6 run --env API_KEY=xxx --env BASE_URL=http://localhost:8000 tests/performance/k6_load_test.js
 *
 * Stages:
 *   - Ramp up to 50 VUs over 1 minute
 *   - Sustain 50 VUs for 3 minutes
 *   - Spike to 100 VUs for 1 minute
 *   - Ramp down over 1 minute
 */

import http from "k6/http";
import { check, sleep, group } from "k6";
import { Rate, Trend } from "k6/metrics";

// Custom metrics
const errorRate = new Rate("error_rate");
const agentLatency = new Trend("agent_execution_latency", true);

// Configuration
const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const API_KEY = __ENV.API_KEY || "";
const ADMIN_KEY = __ENV.ADMIN_KEY || "";

// Fail fast if API_KEY is not provided
if (!API_KEY) {
  console.error("API_KEY is required. Use: k6 run --env API_KEY=xxx k6_load_test.js");
  // exec.test.abort is available at runtime; this guard runs at init time
}

export const options = {
  scenarios: {
    main: {
      executor: "ramping-vus",
      stages: [
        { duration: "1m", target: 50 },   // ramp up
        { duration: "3m", target: 50 },   // sustain
        { duration: "1m", target: 100 },  // spike
        { duration: "1m", target: 0 },    // ramp down
      ],
      exec: "default",
    },
    agents: {
      executor: "ramping-vus",
      stages: [
        { duration: "2m", target: 5 },
        { duration: "1m", target: 0 },
      ],
      exec: "agentExecution",
      startTime: "2m", // Start after main scenario has warmed up
    },
  },
  thresholds: {
    http_req_duration: ["p(95)<500", "p(99)<2000"],  // 95th < 500ms, 99th < 2s
    error_rate: ["rate<0.05"],                         // <5% error rate
    http_req_failed: ["rate<0.05"],
  },
};

const headers = {
  "Content-Type": "application/json",
  "X-API-Key": API_KEY,
};

const adminHeaders = {
  "Content-Type": "application/json",
  "X-Admin-Key": ADMIN_KEY,
};

export default function () {
  group("Health", function () {
    const res = http.get(`${BASE_URL}/api/v1/health/live`);
    check(res, { "health 200": (r) => r.status === 200 });
    errorRate.add(res.status !== 200);
  });

  group("Jobs API", function () {
    // List jobs
    const listRes = http.get(`${BASE_URL}/api/v1/jobs`, { headers });
    check(listRes, { "list jobs 200": (r) => r.status === 200 });
    errorRate.add(listRes.status !== 200);

    // Create job
    const createRes = http.post(
      `${BASE_URL}/api/v1/jobs`,
      JSON.stringify({ type: "k6_test", payload: { ts: Date.now() } }),
      { headers }
    );
    check(createRes, { "create job 201": (r) => r.status === 201 });
    errorRate.add(createRes.status !== 201);

    if (createRes.status === 201) {
      const jobId = createRes.json("id");
      const getRes = http.get(`${BASE_URL}/api/v1/jobs/${jobId}`, { headers });
      check(getRes, { "get job 200": (r) => r.status === 200 });
    }
  });

  group("Agent API", function () {
    // List agent definitions
    const listRes = http.get(`${BASE_URL}/api/v1/agents/definitions`, { headers });
    check(listRes, { "list agents 200": (r) => r.status === 200 });
    errorRate.add(listRes.status !== 200);

    // Get agent analytics
    const analyticsRes = http.get(
      `${BASE_URL}/api/v1/agents/analytics?days=7`,
      { headers }
    );
    check(analyticsRes, {
      "analytics 200": (r) => r.status === 200,
    });
  });

  group("Billing API", function () {
    // Get usage
    const usageRes = http.get(`${BASE_URL}/api/v1/billing/usage?days=30`, {
      headers,
    });
    check(usageRes, { "usage 200": (r) => r.status === 200 });
    errorRate.add(usageRes.status !== 200);
  });

  group("Files API", function () {
    const listRes = http.get(`${BASE_URL}/api/v1/files`, { headers });
    check(listRes, { "list files 200": (r) => r.status === 200 });
  });

  sleep(Math.random() * 2 + 0.5); // 0.5–2.5s think time
}

// Separate scenario for agent execution (heavier, fewer VUs)
export function agentExecution() {
  group("Agent Execution", function () {
    const listRes = http.get(`${BASE_URL}/api/v1/agents/definitions`, {
      headers,
    });
    if (listRes.status !== 200) return;

    const agents = listRes.json("items") || [];
    if (agents.length === 0) return;

    const agentId = agents[0].id;
    const start = Date.now();

    const execRes = http.post(
      `${BASE_URL}/api/v1/agents/definitions/${agentId}/instances`,
      JSON.stringify({
        input_data: { messages: [{ role: "user", content: "Hello from k6 load test" }] },
      }),
      { headers }
    );

    agentLatency.add(Date.now() - start);

    check(execRes, {
      "agent exec 201": (r) => r.status === 201,
    });
  });
}

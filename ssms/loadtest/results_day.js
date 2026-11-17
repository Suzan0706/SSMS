// Results day (NFR-04): thousands of students and parents open results at once.
//   k6 run -e BASE=https://staging.ssms.co.tz -e USERS=users.csv -e TERM=<term uuid> loadtest/results_day.js
// USERS: one "school_code,username,password" line per student account on the staging copy (never production).
// Parents sign in by SMS code; on staging the same pages are read with student accounts, which hit the same queries.
// Each round is what a student does that day (design/21 §21.3): home, results, progress, announcements, and every
// fifth round the report card PDF. RATE (requests started per second) and HOLD set the spike; a short low run
// (-e RATE=10 -e RAMP=10s -e HOLD=30s) checks the script itself before the real run.
import http from "k6/http";
import { check, sleep } from "k6";
import { SharedArray } from "k6/data";

const BASE = __ENV.BASE || "http://127.0.0.1:8000";
const TERM = __ENV.TERM;
const RATE = Number(__ENV.RATE || 500);
const users = new SharedArray("users", () =>
  open(__ENV.USERS || "users.csv").split("\n").map((l) => l.trim()).filter(Boolean).map((l) => l.split(",")));

export const options = {
  scenarios: {
    spike: {
      executor: "ramping-arrival-rate",
      startRate: Math.min(20, RATE), timeUnit: "1s", preAllocatedVUs: Math.min(500, RATE * 4), maxVUs: 5000,
      stages: [
        { target: RATE, duration: __ENV.RAMP || "2m" },   // results published
        { target: RATE, duration: __ENV.HOLD || "5m" },
        { target: 0, duration: "1m" },
      ],
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.005"],                                  // < 0.5 % errors
    "http_req_duration{kind:read}": ["p(95)<300"],                    // NFR-03 reads
    "http_req_duration{kind:login}": ["p(95)<800"],
    "http_req_duration{kind:pdf}": ["p(95)<1500"],                    // report card, drawn on request
    checks: ["rate>0.99"],
  },
};

const tokens = {};

// Each virtual user signs in once. A refused sign-in is not retried at once: hammering the sign-in would measure the
// rate limiter, not the system. All k6 users come from one address, so the staging API needs a higher
// SSMS_LOGIN_ATTEMPTS_PER_MINUTE (its per-address limit is 3x that) or several load generators.
function token() {
  const [school, username, password] = users[(__VU - 1) % users.length];
  if (!tokens[__VU]) {
    const res = http.post(`${BASE}/api/v1/auth/login`, JSON.stringify({ school_code: school, username, password }),
      { headers: { "Content-Type": "application/json" }, tags: { kind: "login" } });
    check(res, { "login 200": (r) => r.status === 200 });
    if (res.status !== 200) {
      sleep(10);
      return null;
    }
    tokens[__VU] = res.json("access_token");
  }
  return tokens[__VU];
}

export default function () {
  const bearer = token();
  if (!bearer) return;
  const headers = { Authorization: `Bearer ${bearer}`, "Accept-Language": "sw" };
  const me = http.get(`${BASE}/api/v1/me/student`, { headers, tags: { kind: "read" } });
  check(me, { "home 200": (r) => r.status === 200 });
  const id = me.json("student_id");
  if (id && TERM) {
    const results = http.get(`${BASE}/api/v1/students/${id}/results?term_id=${TERM}`, { headers, tags: { kind: "read" } });
    check(results, { "results 200": (r) => r.status === 200, "results < 100 KB": (r) => r.body.length < 100000 });
    const progress = http.get(`${BASE}/api/v1/students/${id}/progress`, { headers, tags: { kind: "read" } });
    check(progress, { "progress 200": (r) => r.status === 200 });
    if (__ITER % 5 === 4) {
      const pdf = http.get(`${BASE}/api/v1/students/${id}/report-card?term_id=${TERM}`, { headers, tags: { kind: "pdf" } });
      check(pdf, { "report card is a PDF": (r) => r.status === 200 && String(r.body).startsWith("%PDF") });
    }
  }
  http.get(`${BASE}/api/v1/announcements`, { headers, tags: { kind: "read" } });
  sleep(1);
}

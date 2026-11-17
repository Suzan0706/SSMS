// Morning registers (NFR-03 writes < 800 ms): every class teacher of many schools syncs at 07:30-08:00.
//   k6 run -e BASE=https://staging.ssms.co.tz -e TEACHERS=teachers.csv loadtest/register_sync.js
// TEACHERS: "school_code,username,password" of class teachers on the staging copy. Each iteration loads the
// teacher's first register and sends every student's mark (resending is idempotent by client_record_id).
import http from "k6/http";
import { check, sleep } from "k6";
import { SharedArray } from "k6/data";
import { uuidv4 } from "https://jslib.k6.io/k6-utils/1.4.0/index.js";

const BASE = __ENV.BASE || "http://127.0.0.1:8000";
const teachers = new SharedArray("teachers", () =>
  open(__ENV.TEACHERS || "teachers.csv").split("\n").map((l) => l.trim()).filter(Boolean).map((l) => l.split(",")));

export const options = {
  scenarios: { morning: { executor: "per-vu-iterations", vus: Math.min(teachers.length, 1000), iterations: 3, maxDuration: "10m" } },
  thresholds: {
    http_req_failed: ["rate<0.005"],
    "http_req_duration{kind:sync}": ["p(95)<800"],
    "http_req_duration{kind:read}": ["p(95)<300"],
  },
};

export default function () {
  const [school, username, password] = teachers[(__VU - 1) % teachers.length];
  const login = http.post(`${BASE}/api/v1/auth/login`, JSON.stringify({ school_code: school, username, password }),
    { headers: { "Content-Type": "application/json" } });
  const headers = { Authorization: `Bearer ${login.json("access_token")}`, "Content-Type": "application/json" };
  const streams = http.get(`${BASE}/api/v1/attendance/my-streams`, { headers, tags: { kind: "read" } }).json();
  if (!streams || !streams.length) return;
  const reg = http.get(`${BASE}/api/v1/attendance/register?stream_id=${streams[0].stream_id}`, { headers, tags: { kind: "read" } }).json();
  if (!reg.school_day) return;
  const now = new Date().toISOString();
  const items = reg.students.map((s) => ({
    client_record_id: uuidv4(), session_date: reg.session_date, stream_id: reg.stream_id, student_id: s.student_id,
    status: Math.random() < 0.92 ? "PRESENT" : "ABSENT", captured_at: now,
  }));
  const res = http.post(`${BASE}/api/v1/attendance/sync`, JSON.stringify({ items }), { headers, tags: { kind: "sync" } });
  check(res, { "sync 200": (r) => r.status === 200, "all synced": (r) => r.json("results").every((x) => x.result !== "error") });
  sleep(2);
}

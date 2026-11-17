// Payment-callback burst (NFR-03: callback answered in < 2 s; FR-51: a repeat never pays twice).
//   k6 run -e BASE=https://staging.ssms.co.tz -e SECRET=<SSMS_MOBILE_WEBHOOK_SECRET of staging>
//          -e REFS=refs.txt loadtest/payment_burst.js
// REFS: one "school_code.admission_no" per line (students of the staging copy). Every 10th request repeats an earlier
// transaction id on purpose: the answer must be DUPLICATE, never a second payment.
import http from "k6/http";
import crypto from "k6/crypto";
import { check } from "k6";
import { SharedArray } from "k6/data";

const BASE = __ENV.BASE || "http://127.0.0.1:8000";
const SECRET = __ENV.SECRET;
const refs = new SharedArray("refs", () =>
  open(__ENV.REFS || "refs.txt").split("\n").map((l) => l.trim()).filter(Boolean));

export const options = {
  scenarios: {
    burst: { executor: "constant-arrival-rate", rate: 100, timeUnit: "1s", duration: "3m", preAllocatedVUs: 200, maxVUs: 1000 },
  },
  thresholds: {
    http_req_failed: ["rate<0.005"],
    http_req_duration: ["p(95)<2000"],
    checks: ["rate>0.995"],
  },
};

export default function () {
  const n = __ITER % 10 === 9 ? __ITER - 9 : __ITER;                    // every 10th: a repeat
  const body = JSON.stringify({
    transaction_id: `K6-${__ENV.RUN || "x"}-${__VU}-${n}`,
    reference: refs[n % refs.length],
    amount: "5000",
    msisdn: "255700000001",
    payer_name: "LOAD TEST",
    timestamp: new Date().toISOString(),
  });
  const signature = crypto.hmac("sha256", SECRET, body, "hex");
  const res = http.post(`${BASE}/api/v1/webhooks/mpesa`, body, {
    headers: { "Content-Type": "application/json", "X-SSMS-Signature": `sha256=${signature}` },
  });
  check(res, {
    "200": (r) => r.status === 200,
    "accepted or duplicate": (r) => ["ACCEPTED", "DUPLICATE"].includes(r.json("status")),
  });
}

# Roadmap API — Frontend Integration Guide

> Covers **only the routes added in the latest release** (commit `feat: integrate roadmap context ingestion`).
> One new endpoint: **`POST /roadmap/submit`**.

The frontend scoring engine produces a roadmap result (classification + per-domain
scores). After the user finishes the assessment, POST that result **once** to this
endpoint. The backend stores it against the `user_id` (last write wins) and injects it
as context into every subsequent `/chat` turn for that user. **You don't fetch it back** —
there is no GET; the chatbot picks it up automatically on the next message.

---

## Endpoint

| | |
|---|---|
| **Method** | `POST` |
| **URL** | `/roadmap/submit` |
| **Content-Type** | `application/json` |
| **Auth** | none at the route (same origin/CORS as the rest of the API) |
| **Idempotency** | Upsert by `user_id`. Re-submitting overwrites the previous roadmap. |

Base URL is the same host as `/chat`. CORS is already allowed for
`localhost:5173`, `manascience.in`, `www.manascience.in`, `manascience.webflow.io`.

---

## Request body (what to send)

Send **either** a bare object **or** a one-element array wrapping it (the current
frontend wraps in an array — both work). A multi-element array is **rejected**.

### Field spec

| Field | Type | Required | Notes |
|---|---|---|---|
| `user_id` | string | ✅ | Non-empty. Must be the **same id you pass as `session_id` to `/chat`** — that's how the two are linked. |
| `Classification` | string | ✅ | One of `neurodivergent`, `neurotypical`, `ND`, `NT`. **Case-insensitive.** |
| `score` | array | ✅ | Non-empty list of domain objects (see below). Note the key is lowercase `score`. |
| `score[].domain` | string | ✅ | Non-empty domain name, e.g. `"communication"`. |
| `score[].Score` | string \| number | ✅ | Capital `S`. Stored **verbatim** — send `72`, `72.0`, or `"72%"`, whatever your engine produced. Never rounded/recomputed by backend. Booleans rejected. |
| `score[].Severity` | string | ⬜ optional | e.g. `"moderate"`. Omit or `null` if you don't have it. |

> ⚠️ **Casing matters.** Keys are `user_id`, `Classification`, `score`, `domain`,
> `Score`, `Severity` exactly as written. `Classification` and `Score` are capitalized;
> `score` and `domain` are lowercase.

### JS data format — example payload

```js
const payload = [
  {
    user_id: "u_demo",              // same string you send to /chat as session_id
    Classification: "neurodivergent", // or "ND" / "NT" / "neurotypical"
    score: [
      { domain: "communication",   Score: "72%",  Severity: "moderate" },
      { domain: "sensory",         Score: 45,     Severity: "mild" },
      { domain: "executive_function", Score: 88.5 }   // Severity optional
    ]
  }
];
```

### Fetch call

```js
async function submitRoadmap(payload) {
  const res = await fetch(`${API_BASE}/roadmap/submit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  const data = await res.json();

  if (!res.ok) {
    // data.detail.error = { code, message, field? }
    throw new Error(data?.detail?.error?.message || `Submit failed (${res.status})`);
  }
  return data; // success ack (see below)
}
```

---

## Success response — `200 OK`

The ack echoes identifiers/counts only — **never the scores back** (you already hold them).

```js
{
  status: "accepted",
  user_id: "u_demo",
  classification: "ND",      // normalized to ND | NT
  domains_received: 3,       // == score.length you sent
  context_ready: true        // stored; will be used on next /chat turn
}
```

---

## Error responses

All errors return `{ "detail": { "status": ..., "error": { "code", "message", "field?" } } }`.

| HTTP | `error.code` | When | `field` present? |
|---|---|---|---|
| `400` | *(plain string detail)* | Body isn't valid JSON | — |
| `422` | `missing_field` | `user_id` / `Classification` / `score` missing or empty | ✅ (e.g. `"user_id"`) |
| `422` | `invalid_classification` | `Classification` not in the accepted vocabulary | ✅ `"Classification"` |
| `422` | `empty_scores` | `score` is not a non-empty list | ✅ `"score"` |
| `422` | `invalid_score_entry` | A `score[i]` is malformed (missing `domain`/`Score`, bad type) | ✅ e.g. `"score[0].Score"` |
| `422` | `payload_not_object` | Body is empty list / not an object | — |
| `422` | `ambiguous_batch` | Array has more than one submission | — |
| `503` | `persistence_unavailable` | Store temporarily down — **safe to retry** | — |

### Error body example (`422`)

```js
{
  detail: {
    status: "rejected",
    error: {
      code: "missing_field",
      message: "Required field 'user_id' is missing.",
      field: "user_id"
    }
  }
}
```

The `field` string points at the exact offending path (`"score[0].domain"`, etc.) — you
can use it to highlight the failing input.

---

## Integration checklist

1. Use the **same `user_id` here and as `session_id` in `/chat`** — this is the link.
2. Submit **once** after the assessment completes (re-submit only if the user redoes it).
3. On `422`, surface `error.message` / highlight `error.field` — it's a client-side data bug.
4. On `503`, show a transient error and allow retry (data was **not** stored).
5. Nothing to fetch back — the chatbot consumes the roadmap automatically next `/chat`.

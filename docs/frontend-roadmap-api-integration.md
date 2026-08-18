# Roadmap Therapy Mapping API — Frontend Integration Guide

> **Audience:** Frontend developers integrating the Manasi dashboard.
> **You need nothing from the backend code.** This document is the complete
> contract: send the request shape in §3, render the response shape in §5.

---

## 1. Overview

### What this API does

The **Roadmap Therapy Mapping API** takes a user's completed assessment
(classification + per-domain scores) and returns, for each **actionable** domain,
the list of recommended **therapies** in priority order.

The frontend's job is simple:

1. Send the assessment JSON to **one** endpoint.
2. Receive a clean JSON response.
3. Render `mapped_domains` and their `therapies` exactly as returned.

You do **not** implement any scoring, filtering, or therapy-matching logic on the
frontend — the backend does all of it and hands you display-ready data.

### Backend flow (for context only — you never touch these steps)

```
Frontend JSON
        │
        ▼
roadmap_loader      → validates & normalizes the payload
        │
        ▼
severity_filter     → keeps only High / Moderate domains
        │
        ▼
mapping_loader      → loads the therapy reference data
        │
        ▼
therapy_mapper      → maps each domain to its therapies
        │
        ▼
serializer          → flattens to clean JSON
        │
        ▼
JSON Response       → what you render
```

You call the endpoint; the backend runs this whole pipeline and returns the final
JSON. **No internal implementation knowledge is required.**

### Two things the pipeline does that affect what you see

A domain appears in the response **only if both** are true:

1. Its `Severity` is **High** or **Moderate** (Low / missing / unrecognized
   severities are filtered out), **and**
2. Its `domain` name **matches** an entry in the therapy reference data.

So the response can legitimately contain **fewer domains than you sent**, or an
**empty list**. This is normal, not an error — see §9 and §14 for how to handle it.

---

## 2. Endpoint Information

| Item | Value |
|---|---|
| **HTTP Method** | `POST` |
| **Endpoint URL** | `/roadmap/mapped-therapies` |
| **Base URL** | Same host as the rest of the Manasi API (e.g. `https://api.manascience.in`). Use your environment's configured API base. |
| **Full example** | `POST https://api.manascience.in/roadmap/mapped-therapies` |
| **Content-Type (request)** | `application/json` |
| **Accept (response)** | `application/json` |
| **Authentication** | None at the route. Access is controlled by CORS (same-origin policy). Send no auth header unless your deployment adds one at the gateway. |
| **Idempotency** | Safe to retry. The endpoint is stateless — it stores nothing and returns the same output for the same input. |

**CORS:** the API already allows the standard frontend origins (local dev on
`localhost:5173` / `127.0.0.1:5173` and the production `manascience.in` domains). If
you call from a new origin and get a CORS error, ask the backend team to add it.

---

## 3. Request JSON Format

### Schema

```jsonc
{
  "user_id": "test001",            // string, REQUIRED
  "Classification": "ND",          // string, REQUIRED  (capital "C")
  "score": [                       // array,  REQUIRED  (lowercase "score")
    {
      "domain": "Sensory Processing", // string, REQUIRED (lowercase "domain")
      "domain_type": "Spine",         // string, OPTIONAL (lowercase "domain_type")
      "Score": 85,                    // number|string, REQUIRED (capital "S")
      "Severity": "High"              // string, OPTIONAL (capital "S")
    }
  ]
}
```

### ⚠️ Exact key casing matters

The backend reads these keys **exactly** as written — it does **not** accept
alternate casing for the keys:

| Purpose | Correct key | Common mistake |
|---|---|---|
| Classification | `Classification` (capital C) | ❌ `classification` |
| Score **array** | `score` (lowercase) | ❌ `Score` array |
| Per-entry score **value** | `Score` (capital S) | ❌ `score` |
| Per-entry severity | `Severity` (capital S) | ❌ `severity` |
| Domain name | `domain` (lowercase) | — |
| Domain type | `domain_type` (lowercase) | — |
| User id | `user_id` (lowercase) | — |

> **Note:** the *array* is lowercase `score`, but each entry's numeric value is
> capital `Score`. They are different keys. Send both exactly as shown above.

### Field-by-field

| Field | Type | Required | Description |
|---|---|---|---|
| `user_id` | string | ✅ | Non-empty identifier for the user. Use the same id you use elsewhere in the app (e.g. the chat `session_id`). |
| `Classification` | string | ✅ | The user's track. Accepts `ND`, `NT`, `neurodivergent`, or `neurotypical` (**value** is case-insensitive). Normalized to `ND` / `NT` in the response. |
| `score` | array | ✅ | Non-empty list of domain objects (below). |
| `score[].domain` | string | ✅ | The domain name, e.g. `"Sensory Processing"`. Must match a known domain to produce therapies. |
| `score[].domain_type` | string | ⬜ optional | A label your engine assigns, e.g. `"Spine"` / `"Complementary"`. Passed straight through to the response, unchanged. Free-form — the backend does not validate it. Omit or `null` if unused. |
| `score[].Score` | number or string | ✅ | The raw score, verbatim. Send `85`, `85.5`, or `"72%"` — whatever your engine produced. Never rounded or recomputed by the backend. **Booleans are rejected.** |
| `score[].Severity` | string | ⬜ optional | `High`, `Moderate`, or `Low` (case-insensitive). Drives filtering. Omit / `null` if unknown — but note a domain with no High/Moderate severity will not appear in the response. |

You may send the body as **a bare object** (above) **or as a one-element array**
wrapping it — both are accepted. A multi-element array is rejected (see §4).

---

## 4. Validation Rules

### Allowed values

| Field | Allowed values |
|---|---|
| `Classification` | `ND`, `NT`, `neurodivergent`, `neurotypical` (case-insensitive). Anything else → `422`. |
| `Severity` | `High`, `Moderate`, `Low` (case-insensitive, surrounding spaces ignored). Other words (e.g. `"Severe"`, `"Mild"`) or missing severity are treated as **not actionable** and the domain is silently filtered out — **not** an error. |
| `domain_type` | **Any string** (or omitted). Not validated, not restricted, carried through verbatim. |

### Required fields

`user_id`, `Classification`, `score` (non-empty), and for **every** entry
`domain` (non-empty) and `Score`.

### Data types

- `user_id` — non-empty string
- `Classification` — string
- `score` — non-empty array of objects
- `domain` — non-empty string
- `Score` — number or numeric/percent string (**not** a boolean)
- `Severity` / `domain_type` — string or omitted

### What causes a validation failure (`422`)

| Situation | Error `code` |
|---|---|
| Missing `user_id` (or empty) | `missing_field` |
| Missing `Classification` | `missing_field` |
| `Classification` not in the allowed set | `invalid_classification` |
| `score` missing or empty array | `empty_scores` |
| A `score[]` entry is not an object | `invalid_score_entry` |
| A `score[]` entry missing a non-empty `domain` | `invalid_score_entry` |
| A `score[]` entry missing `Score` | `invalid_score_entry` |
| `Score` is a boolean or wrong type | `invalid_score_entry` |
| Body is a multi-element array | `ambiguous_batch` |
| Body is not an object / empty array | `payload_not_object` |

### Other failures

| Situation | Status | Error `code` |
|---|---|---|
| Body is not valid JSON | `400` | (plain message) |
| `score` array has more than **500** domains | `413` | `payload_too_large` |

### Example validation error

Request missing `user_id`:

```json
{
  "detail": {
    "status": "rejected",
    "error": {
      "code": "missing_field",
      "message": "Required field 'user_id' is missing.",
      "field": "user_id"
    }
  }
}
```

---

## 5. Response JSON

`200 OK`, `Content-Type: application/json`:

```json
{
  "user_id": "test001",
  "classification": "ND",
  "mapped_domains": [
    {
      "domain": "Sensory Processing",
      "domain_type": "Spine",
      "score": 85,
      "severity": "High",
      "therapies": [
        {
          "therapy": "MNRI",
          "relevance": "Primary"
        },
        {
          "therapy": "Feldenkrais",
          "relevance": "Secondary"
        }
      ]
    }
  ]
}
```

> **Response keys are all lowercase** (`classification`, `score`, `severity`, …) —
> even though some request keys were capitalized. Read the response using the keys
> exactly as shown here.

**Empty result** — a valid, successful response when no domain was actionable or
none matched:

```json
{
  "user_id": "test001",
  "classification": "ND",
  "mapped_domains": []
}
```

---

## 6. Response Field Description

| Field | Type | Description |
|---|---|---|
| `user_id` | string | Echoes the `user_id` you sent. |
| `classification` | string | Normalized track: `"ND"` or `"NT"`. |
| `mapped_domains` | array | One entry per **actionable + matched** domain. May be empty. Render in the order given. |
| `mapped_domains[].domain` | string | The domain name. |
| `mapped_domains[].domain_type` | string \| null | The `domain_type` you sent, unchanged. May be `null` if you didn't send one. |
| `mapped_domains[].score` | number \| string | The raw score you sent for this domain, verbatim. |
| `mapped_domains[].severity` | string \| null | The severity you sent (e.g. `"High"`), preserved as-is. |
| `mapped_domains[].therapies` | array | Recommended therapies, **already ordered** by the backend. May be non-empty for every returned domain. |
| `therapies[].therapy` | string | Therapy / modality name, e.g. `"MNRI"`. |
| `therapies[].relevance` | string \| null | Priority label, e.g. `"Primary"`, `"Secondary"`. May be `null` if the source data has no label. |

---

## 7. HTTP Status Codes

| Status | Meaning | Body |
|---|---|---|
| **200 OK** | Success. Includes the empty-`mapped_domains` case. | §5 response |
| **400 Bad Request** | Request body was not valid JSON. | `{ "detail": "Request body is not valid JSON." }` |
| **401 Unauthorized** | **Not used** by this endpoint (no auth at the route). Only relevant if your gateway adds auth. | — |
| **404 Not Found** | **Not used** by this endpoint. This is a compute call with no resource lookup — you will not get a 404 for valid routing. A 404 means the URL/path is wrong. | — |
| **413 Payload Too Large** | More than 500 domains in `score`. | `{ "detail": { "status": "rejected", "error": { "code": "payload_too_large", ... } } }` |
| **422 Unprocessable Entity** | Validation failure (see §4). `error.field` names the offending field. | structured error |
| **500 Internal Server Error** | Backend problem (e.g. therapy reference data temporarily unavailable). Not your payload's fault — retry later. | `{ "detail": { "status": "error", "error": { "code": "mapping_data_unavailable" \| "therapy_mapping_failed" \| "internal_error", ... } } }` |

### Example error responses

**400 — bad JSON**
```json
{ "detail": "Request body is not valid JSON." }
```

**422 — invalid classification**
```json
{
  "detail": {
    "status": "rejected",
    "error": {
      "code": "invalid_classification",
      "message": "Classification 'maybe' is not one of neurodivergent/neurotypical/ND/NT.",
      "field": "Classification"
    }
  }
}
```

**413 — too many domains**
```json
{
  "detail": {
    "status": "rejected",
    "error": { "code": "payload_too_large", "message": "score array carries 501 domains; the maximum is 500." }
  }
}
```

**500 — reference data unavailable**
```json
{
  "detail": {
    "status": "error",
    "error": { "code": "mapping_data_unavailable", "message": "Therapy mapping data is temporarily unavailable." }
  }
}
```

### Reading errors on the frontend

For structured errors, the useful fields are:

- `error.code` — a stable machine string you can branch on.
- `error.message` — human-readable, safe to log (not necessarily to show users).
- `error.field` — present on validation errors; tells you which input to flag.

The `400` case is the exception: its `detail` is a plain string, not an object.

---

## 8. Frontend Integration Example

### 8.1 `fetch()`

```js
const API_BASE = import.meta.env.VITE_API_BASE; // e.g. "https://api.manascience.in"

async function getMappedTherapies(assessment) {
  const res = await fetch(`${API_BASE}/roadmap/mapped-therapies`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Accept": "application/json",
    },
    body: JSON.stringify(assessment),
  });

  if (!res.ok) {
    // Try to read the structured error; fall back to text for the 400 case.
    let detail;
    try { detail = (await res.json()).detail; } catch { detail = await res.text(); }
    const code = detail?.error?.code ?? "unknown_error";
    throw new Error(`API ${res.status} (${code})`);
  }

  return res.json(); // { user_id, classification, mapped_domains: [...] }
}
```

### 8.2 Axios

```js
import axios from "axios";

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE,
  headers: { "Content-Type": "application/json", Accept: "application/json" },
});

async function getMappedTherapies(assessment) {
  try {
    const { data } = await api.post("/roadmap/mapped-therapies", assessment);
    return data; // { user_id, classification, mapped_domains: [...] }
  } catch (err) {
    const detail = err.response?.data?.detail;
    const code = typeof detail === "object" ? detail?.error?.code : "invalid_json";
    throw new Error(`API ${err.response?.status ?? "?"} (${code ?? "unknown"})`);
  }
}
```

### 8.3 React component

```jsx
import { useEffect, useState } from "react";

function TherapyRoadmap({ assessment }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    getMappedTherapies(assessment)
      .then((res) => { if (!cancelled) setData(res); })
      .catch((e) => { if (!cancelled) setError(e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });

    return () => { cancelled = true; };
  }, [assessment]);

  if (loading) return <p>Loading your roadmap…</p>;
  if (error) return <p role="alert">Something went wrong: {error}</p>;

  const domains = data?.mapped_domains ?? [];
  if (domains.length === 0) {
    return <p>No priority domains were identified from this assessment.</p>;
  }

  return (
    <div className="roadmap">
      {domains.map((d) => (
        <section key={d.domain} className="domain-card">
          <header>
            <h3>{d.domain}</h3>
            {d.domain_type && <span className="tag">{d.domain_type}</span>}
            {d.severity && <span className={`sev sev-${d.severity.toLowerCase()}`}>{d.severity}</span>}
            <span className="score">Score: {d.score}</span>
          </header>

          {d.therapies.length === 0 ? (
            <p className="muted">No therapies listed for this domain.</p>
          ) : (
            <ol className="therapies">
              {/* Render in the exact order received — do NOT re-sort. */}
              {d.therapies.map((t, i) => (
                <li key={`${t.therapy}-${i}`}>
                  <span className="therapy-name">{t.therapy}</span>
                  {t.relevance && <span className="relevance">{t.relevance}</span>}
                </li>
              ))}
            </ol>
          )}
        </section>
      ))}
    </div>
  );
}
```

---

## 9. Dashboard Mapping Guide

How to surface each field in the UI:

| Data | Suggested UI |
|---|---|
| `domain` | Card / section heading. |
| `severity` | A colored badge (`High` = red/urgent, `Moderate` = amber). Show the string verbatim. |
| `score` | A number/percent next to the heading. **Display exactly as received** — don't reformat or round (it may already be `"72%"`). |
| `domain_type` | A small tag/chip (e.g. "Spine"). Hide if `null`. |
| `therapies` | An **ordered** list under the domain. |
| `therapy` | The list item's primary label. |
| `relevance` | A secondary label/badge on the item (e.g. "Primary"). Hide if `null`. |

**Ordering:** the `therapies` array is **already sorted by the backend** (priority
order from the reference data). **Render them in the exact order received.** Do not
sort alphabetically or by any other rule.

**Empty states:**
- `mapped_domains` empty → show a friendly "no priority domains identified" message.
- A domain with `therapies: []` → show a per-domain "no therapies listed" note.

---

## 10. Important Notes

- **Treat the backend response as the single source of truth.** Everything you need
  to display is in it.
- **Do not modify `domain_type`** — render it as received (or hide it if `null`).
- **Do not modify `therapies`** — do not rename, merge, add, or drop therapies.
- **Display therapies exactly as returned**, including their `relevance` labels.
- **Do not reorder therapies.** The order is meaningful (priority). Keep it.
- **Do not reformat `score`** — it may be a number or a string like `"72%"`.
- **Do not recompute severity or scoring** on the frontend.

---

## 11. Future Compatibility

The response may gain **additional top-level or per-domain fields** in future
releases, such as:

- `roadmap`
- `timeline`
- `email_status`
- `pdf`
- `recommendations`

These will be **additive** — existing fields (`user_id`, `classification`,
`mapped_domains`, and everything inside it) will keep their current names, types,
and meaning.

> **Build defensively:** read only the fields you use and **ignore unknown
> fields**. Do not use strict schemas that reject extra keys. This keeps your
> integration forward-compatible with no code changes when new fields appear.

---

## 12. API Testing

### cURL

```bash
curl -X POST "https://api.manascience.in/roadmap/mapped-therapies" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d '{
    "user_id": "test001",
    "Classification": "ND",
    "score": [
      { "domain": "Sensory Processing", "domain_type": "Spine", "Score": 85, "Severity": "High" }
    ]
  }'
```

### Postman

1. **Method:** `POST`
2. **URL:** `{{base_url}}/roadmap/mapped-therapies`
3. **Headers:** `Content-Type: application/json`, `Accept: application/json`
4. **Body:** select **raw → JSON**, paste the request from §3.
5. **Send** — expect `200` with the §5 body. Save it as a collection example for the team.

### Swagger / OpenAPI

The API auto-publishes interactive docs. Open **`{base_url}/docs`** in a browser,
find **`POST /roadmap/mapped-therapies`**, click **"Try it out"**, paste the §3
body, and **Execute**. The schema and a live response are shown inline. The raw
spec is at **`{base_url}/openapi.json`**.

---

## 13. Complete End-to-End Example

### Step 1 — Input (what the frontend sends)

```json
{
  "user_id": "test001",
  "Classification": "ND",
  "score": [
    { "domain": "Sensory Processing", "domain_type": "Spine", "Score": 85, "Severity": "High" },
    { "domain": "Cognitive Function", "domain_type": "Spine", "Score": 72, "Severity": "Moderate" },
    { "domain": "Fine Motor",         "domain_type": "Spine", "Score": 30, "Severity": "Low" }
  ]
}
```

### Step 2 — Backend processing (automatic; nothing to do)

```
validate payload  →  keep only High/Moderate  →  match domains to therapy data  →  serialize
```
- `Sensory Processing` (High) and `Cognitive Function` (Moderate) are actionable.
- `Fine Motor` (Low) is filtered out.
- Each actionable domain is matched against the therapy reference data.

### Step 3 — Output (what the frontend renders)

```json
{
  "user_id": "test001",
  "classification": "ND",
  "mapped_domains": [
    {
      "domain": "Sensory Processing",
      "domain_type": "Spine",
      "score": 85,
      "severity": "High",
      "therapies": [
        { "therapy": "MNRI",        "relevance": "Primary" },
        { "therapy": "Feldenkrais", "relevance": "Secondary" }
      ]
    },
    {
      "domain": "Cognitive Function",
      "domain_type": "Spine",
      "score": 72,
      "severity": "Moderate",
      "therapies": [
        { "therapy": "Cognitive Behavioral Therapy", "relevance": "Primary" }
      ]
    }
  ]
}
```

> The therapy names above are illustrative — the actual therapies come from the
> backend reference data. Render whatever is returned. Note `Fine Motor` is absent
> because it was Low severity.

---

## 14. Frontend Checklist

- [ ] Receive the assessment JSON from the scoring engine.
- [ ] Build the request body with the **exact key casing** from §3
      (`Classification`, lowercase `score` array, capital `Score` value).
- [ ] Call `POST /roadmap/mapped-therapies`.
- [ ] Show a **loading** state while the request is in flight.
- [ ] Handle **errors** by status/`error.code`; show a user-friendly message and
      log `error.message`.
- [ ] Parse the JSON response.
- [ ] Render each entry in `mapped_domains` (domain, severity, score, domain_type).
- [ ] Render each entry's `therapies` **in the order received** (no re-sorting).
- [ ] Render each therapy's `relevance` label (hide when `null`).
- [ ] Show an **empty state** when `mapped_domains` is `[]`.
- [ ] Show a per-domain empty note when a domain's `therapies` is `[]`.
- [ ] **Ignore unknown fields** so future response additions don't break the UI.

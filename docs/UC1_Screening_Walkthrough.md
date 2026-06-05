# UC1 — Sanctioned Name Screening

## Walkthrough for Fuel Retail / Energy Operator Demo

This document walks through how **Use Case 1 (Compliance Name Screening)** has been built on top of MongoDB Atlas Search, demonstrating bi-directional fuzzy matching tailored to Malaysian naming conventions.

---

## Architecture Overview

```
┌─────────────┐       ┌──────────────────┐       ┌──────────────────────────┐
│  SvelteKit   │──────▶│  FastAPI Router   │──────▶│  MongoDB Atlas (testcluster) │
│  Frontend    │◀──────│  /api/screening   │◀──────│  DB: FuelRetail_screening         │
└─────────────┘       └──────────────────┘       └──────────────────────────┘
                                                    ├── user_profiles (10,000 docs)
                                                    └── sanctioned_list (55 docs)
```

**Stack**: SvelteKit 5 frontend → FastAPI + Motor (async) backend → MongoDB Atlas with Atlas Search indexes

---

## Two Screening Flows

### Flow 1: Check New User (Onboarding)

**Direction**: User name → `sanctioned_list`

When a new customer registers, their name is searched against the sanctioned watchlist using Atlas Search fuzzy matching. This catches spelling variations, transliterations, and naming convention differences.

```javascript
db.sanctioned_list.aggregate([
  { $search: {
    index: "sanctions_fuzzy",
    compound: {
      should: [
        { text: {
          query: "<user_name>",
          path: "fullName",
          fuzzy: { maxEdits: 2, prefixLength: 1 },
          score: { boost: { value: 2 } }   // Primary name weighted higher
        }},
        { text: {
          query: "<user_name>",
          path: "aliases",                  // Also searches known aliases
          fuzzy: { maxEdits: 2, prefixLength: 1 }
        }}
      ],
      minimumShouldMatch: 1
    }
  }},
  { $addFields: { score: { $meta: "searchScore" } } },
  { $limit: 10 }
])
```

**Key points**:
- Searches both `fullName` and `aliases` fields with `should` (OR logic)
- Primary name match boosted 2x for ranking
- Optional date-of-birth filter via `compound.filter` (narrows results when DOB is known)
- `maxEdits: 2` allows up to 2 character insertions/deletions/substitutions

### Flow 2: Batch Watchlist Sweep (Ongoing Monitoring)

**Direction**: `sanctioned_list` → User profiles

Iterates through every sanctioned entry (including aliases) and searches each name against the full user base. Matches are flagged **in-place** inside the user's profile document.

```javascript
// For each sanctioned name/alias (executed sequentially):
db.user_profiles.aggregate([
  { $search: {
    index: "profiles_fuzzy",
    compound: {
      must: [
        { text: {
          query: "<sanctioned_name_or_alias>",
          path: "fullName",
          fuzzy: { maxEdits: 2, prefixLength: 1 }
        }}
      ]
    }
  }},
  { $addFields: { score: { $meta: "searchScore" } } },
  { $limit: 10 }
])

// Matches with score > 0.5 are flagged in the user's embedded document:
db.user_profiles.updateOne(
  { userId: "<matched_userId>" },
  {
    $set: {
      "screening.lastScreenedAt": ISODate(),
      "screening.riskFlag": true
    },
    $push: { "screening.matches": matchDocument }
  }
)
```

**Key points**:
- Uses `must` (AND) instead of `should` — stricter matching for batch processing
- Results stored **inside** `user_profiles.screening` sub-document (MongoDB embedded document pattern)
- No separate results collection needed — screening data lives alongside the user profile
- Sequential execution ensures consistent ordering and prevents overloading the search index

---

## Atlas Search Indexes

Two indexes are created on the `FuelRetail_screening` database, both sharing a custom analyzer:

### Custom Analyzer: `malay_name_analyzer`

Malaysian names commonly include patronymic connectors that complicate exact matching:
- **Malay**: `bin` (son of), `binti` (daughter of)
- **Indian**: `a/l` (anak lelaki), `a/p` (anak perempuan)

The custom analyzer strips these connectors **before** tokenization:

```json
{
  "name": "malay_name_analyzer",
  "charFilters": [{
    "type": "mapping",
    "mappings": {
      " bin ": " ",  " binti ": " ",
      " a/l ": " ",  " a/p ": " ",
      " BIN ": " ",  " BINTI ": " ",
      " A/L ": " ",  " A/P ": " "
    }
  }],
  "tokenizer": { "type": "standard" },
  "tokenFilters": [{ "type": "lowercase" }]
}
```

This means "Ahmad bin Ibrahim" and "Ahmad Ibrahim" produce the same tokens: `["ahmad", "ibrahim"]`.

### Index 1: `sanctions_fuzzy`

On collection: `sanctioned_list`

| Field | Type(s) | Purpose |
|-------|---------|---------|
| `fullName` | `string` + `autocomplete` | Fuzzy search + type-ahead suggestions |
| `aliases` | `string` + `autocomplete` | Known alternative names |
| `dateOfBirth` | `date` | Optional filter for exact DOB matching |

### Index 2: `profiles_fuzzy`

On collection: `user_profiles`

| Field | Type(s) | Purpose |
|-------|---------|---------|
| `fullName` | `string` + `autocomplete` | Fuzzy search + type-ahead suggestions |
| `dateOfBirth` | `date` | Optional filter |

Both indexes use **multi-type field mappings** (array syntax) to support both full fuzzy search (`text` operator) and type-ahead autocomplete (`autocomplete` operator with `edgeGram` tokenization) on the same field.

---

## Autocomplete (Type-Ahead)

The frontend provides real-time type-ahead suggestions as the user types a name in the "Check User" input:

```javascript
db.sanctioned_list.aggregate([
  { $search: {
    index: "sanctions_fuzzy",
    compound: {
      should: [
        { autocomplete: {
          query: "<partial_input>",
          path: "fullName",
          fuzzy: { maxEdits: 1, prefixLength: 1 }
        }},
        { autocomplete: {
          query: "<partial_input>",
          path: "aliases",
          fuzzy: { maxEdits: 1, prefixLength: 1 }
        }}
      ],
      minimumShouldMatch: 1
    }
  }},
  { $limit: 8 }
])
```

**How it works**:
- `edgeGram` tokenization pre-generates prefix tokens (e.g., "Ah", "Ahm", "Ahma", "Ahmad")
- `maxEdits: 1` (lower than search) keeps suggestions accurate while tolerating typos
- 200ms client-side debounce prevents excessive queries during fast typing
- Keyboard navigation (arrows + enter) and click selection supported

---

## Data Model

### `sanctioned_list` (55 entries)

```json
{
  "fullName": "Ahmad Razali bin Mohd Yusof",
  "aliases": ["Ahmad Razali Yusof", "A. Razali"],
  "dateOfBirth": ISODate("1978-03-15"),
  "country": "Malaysia",
  "source": "Bank Negara Malaysia",
  "category": "Money laundering",
  "addedAt": ISODate("2024-01-15"),
  "active": true
}
```

Sources include: OFAC, UN Security Council, EU Sanctions, Bank Negara Malaysia, FATF, AUSTRAC, Interpol.

### `user_profiles` (10,000 profiles)

```json
{
  "userId": "USR-00001",
  "fullName": "Nurul Izzah binti Ahmad",
  "ic": "901205-14-5678",
  "dateOfBirth": ISODate("1990-12-05"),
  "email": "nurul.izzah@example.com",
  "phone": "+601X-XXXXXXX",
  "status": "active",
  "kyc": {
    "status": "verified",
    "method": "eKYC",
    "documentType": "MyKad",
    "riskLevel": "low"
  },
  "wallet": {
    "balance": 245.50,
    "tier": "premium",
    "dailyLimit": 5000.00
  },
  "linkedCards": [
    { "type": "Visa", "last4": "4521", "bank": "RegionalBankB", "isDefault": true }
  ],
  "activitySummary": {
    "totalTransactions": 156,
    "totalSpend": 4230.00,
    "monthlyAvgSpend": 352.50,
    "favouriteStation": "EnergyOperator Bangsar"
  },
  "screening": {
    "riskFlag": false,
    "lastScreenedAt": null,
    "matches": []
  }
}
```

The `screening` sub-document is the embedded pattern — match results are stored directly inside the user profile, avoiding a separate join/lookup collection. When a batch sweep flags a user, the document is updated **in-place** via `$set` and `$push`.

---

## Demographic Distribution

The 10,000 seed profiles reflect Malaysia's population:

| Ethnicity | % | Naming Pattern |
|-----------|---|----------------|
| Malay | 60% | `<first> bin/binti <father's name>` |
| Chinese | 20% | `<surname> <given name>` |
| Indian | 15% | `<first> a/l <father's name>` or `<first> a/p <father's name>` |
| Other | 5% | Various patterns |

20 profiles are specifically planted with names designed to produce matches against sanctioned entries, demonstrating the fuzzy matching capability across naming conventions.

---

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `GET` | `/api/screening/stats` | Dashboard statistics |
| `GET` | `/api/screening/autocomplete/sanctioned?q=` | Type-ahead on sanctioned list |
| `GET` | `/api/screening/autocomplete/profiles?q=` | Type-ahead on user profiles |
| `POST` | `/api/screening/check-user` | Flow 1 — check name against watchlist |
| `POST` | `/api/screening/batch-sweep` | Flow 2 — sweep all sanctioned vs profiles |
| `GET` | `/api/screening/flagged-users` | List users with riskFlag = true |
| `GET` | `/api/screening/sanctioned` | Paginated sanctioned list |
| `GET` | `/api/screening/index-definitions` | Atlas Search index definitions |

---

## Demo Script

1. **Stats Overview**: Show the dashboard — 10K profiles, 55 sanctioned entries, source breakdown badges
2. **Autocomplete**: Type "Ahm" in the name field — watch sanctioned entries appear as suggestions in real time
3. **Check User (exact)**: Search "Ismail Ibrahim" — high-score match demonstrates the fuzzy engine finding exact-ish names
4. **Check User (fuzzy)**: Search "Muhammad Nasir" — matches "Mohd Nasir" via the name analyzer stripping connectors + fuzzy edits
5. **Check User (connector removal)**: Search "Ravi Ganesan" — matches "Ravi a/l Ganesan" because the `malay_name_analyzer` strips `a/l`
6. **Pipeline Viewer**: Click the `<->` button on the tab bar to show the actual Atlas Search aggregation pipeline and index definition being used
7. **Batch Sweep**: Run the full sweep — watch it process all 55 sanctioned names against 10K profiles, then see newly flagged users appear
8. **Flagged Users**: Expand a flagged user to show the full embedded document — identity, KYC, wallet, cards, activity, and screening matches all in one document

---

## File Structure

```
backend/
├── routers/screening.py          # API routes (own Motor client → testcluster)
├── services/screening_service.py  # Business logic + index definitions
├── models/screening.py            # Pydantic request/response models
└── seed/seed_screening.py         # Seed 10K profiles + 55 sanctioned entries

frontend/src/
├── routes/screening/+page.svelte  # Full screening UI
└── lib/api.ts                     # API client (screening section)
```

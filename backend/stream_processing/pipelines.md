# Atlas Stream Processing Pipelines — Fuel Retail Fraud Detection (UC3)

These pipelines run on the **existing Atlas Stream Processing instance** (`toffTest` workspace, singapore-sgp region), reused from the EnergyOperator Demo demo.

## Connections

| Connection Name | Type | Details |
|---|---|---|
| `UtilitymskKafkaConnection` | Kafka (MSK) | SASL_SSL, SCRAM-SHA-512, VPC peering to MSK cluster |
| `EnergyOperator_cluster` | Atlas Database | Target: Cluster0 → `FuelRetail_fraud` database |

## Topic

- **Kafka Topic:** `FuelRetail-fraud-events`
- Created on existing MSK cluster: `demo-cluster` (ap-southeast-1)

## Pipeline Summary (7 total)

| # | Name | Source | Window | Purpose |
|---|---|---|---|---|
| 0 | `FuelRetail-event-ingest` | MSK | None | Passthrough — all events → `events` collection (dashboard feed) |
| 0b | `FuelRetail-topup-state-writer` | MSK | **None** (windowless) | On each top-up, writes `fraud.lastTopupAt` to `user_profiles` (needed by S02/S03 lookups) |
| 1a | `FuelRetail-signal-s01-topup-cluster` | MSK | 15-min tumbling | Detects 2+ auto top-ups ≥ RM500 → writes state to `user_profiles.fraud.signals.s01` |
| 1b | `FuelRetail-signal-s01-transfer-check` | MSK | **None** (windowless) | On each `InstantTransfer_transfer_out`, `$lookup` user profile → if flagged + within 30 min → alert |
| 2 | `FuelRetail-signal-s02` | MSK | **None** (windowless) | Each `InstantTransfer_payment` > RM500 (non-ewallet), `$lookup` for `lastTopupAt` within 30 min → alert |
| 3 | `FuelRetail-signal-s03` | MSK | 30-min tumbling + `$lookup` | Counts `fund_out_transfer` > RM500, at window close if ≥ 2 then `$lookup` for recent top-up → alert |
| 4 | `FuelRetail-signal-s04` | MSK | 60-min tumbling | 3+ card_linked in same window → alert |

**Key architecture patterns:**
- **S01:** Two-stage pipeline with user profile as state handoff — the showcase. KSQL can't do this.
- **S02:** Windowless — each payment event enriched via `$lookup` to check topup recency. eWallet payments excluded (money stays in ecosystem).
- **S03:** Hybrid — window for counting fund-outs, `$lookup` for topup linkage. Detects layering (splitting funds across destinations).
- **Topup state writer:** Feeds S02 and S03 by maintaining `fraud.lastTopupAt` on every top-up event.

---

## Pipeline 0: Event Ingestion (`Fuel Retail-event-ingest`)

Passthrough — ingests all events from MSK into the `events` collection for the dashboard live event feed. Optional but visually impactful for the demo.

```javascript
[
  {
    $source: {
      connectionName: "UtilitymskKafkaConnection",
      topic: "FuelRetail-fraud-events"
    }
  },
  {
    $addFields: {
      _ingested_at: "$$NOW",
      _source_topic: "FuelRetail-fraud-events"
    }
  },
  {
    $merge: {
      into: {
        connectionName: "EnergyOperator_cluster",
        db: "FuelRetail_fraud",
        coll: "events"
      }
    }
  }
]
```

---

## Pipeline 0b: Top-Up State Writer (`Fuel Retail-topup-state-writer`)

**Windowless.** On every top-up event (`auto_topup` or `manual_topup`), updates the user's `fraud.lastTopupAt`, `fraud.lastTopupAmount`, and `fraud.lastTopupType` in `user_profiles`. This is a prerequisite for S02 and S03 — they `$lookup` against these fields to check if a payment/transfer happened soon after a top-up.

```javascript
[
  {
    $source: {
      connectionName: "UtilitymskKafkaConnection",
      topic: "FuelRetail-fraud-events"
    }
  },
  {
    $match: {
      name: { $in: ["auto_topup", "manual_topup"] }
    }
  },
  {
    $addFields: {
      userId: "$user_id",
      "fraud.lastTopupAt": "$timestamp",
      "fraud.lastTopupAmount": "$properties.amount",
      "fraud.lastTopupType": "$name"
    }
  },
  {
    $project: { userId: 1, fraud: 1 }
  },
  {
    $merge: {
      into: {
        connectionName: "EnergyOperator_cluster",
        db: "FuelRetail_fraud",
        coll: "user_profiles"
      },
      on: "userId",
      whenMatched: "merge"
    }
  }
]
```

---

## Pipeline 1a: S01 — Top-Up Cluster Detection (`Fuel Retail-signal-s01-topup-cluster`)

**Stage 1 of 2.** Detects 2+ auto top-ups ≥ RM500 within a 15-minute window. When detected, writes intermediate state to the user's `fraud.signals.s01` sub-document in `user_profiles`. This state is then read by Pipeline 1b.

**What gets written to the user profile:**
- `fraud.signals.s01.topupClusterDetected`: `true`
- `fraud.signals.s01.lastClusterAt`: timestamp of the last top-up in the cluster
- `fraud.signals.s01.topupCount`: number of qualifying top-ups
- `fraud.signals.s01.intervalSeconds`: seconds between first and last top-up
- `fraud.signals.s01.recentHighTopups[]`: array of the qualifying top-up events (eventId, amount, timestamp, source)

```javascript
[
  {
    $source: {
      connectionName: "UtilitymskKafkaConnection",
      topic: "FuelRetail-fraud-events"
    }
  },
  {
    $match: {
      name: "auto_topup",
      "properties.amount": { $gte: 500 }
    }
  },
  {
    $tumblingWindow: {
      interval: { size: 15, unit: "minute" },
      pipeline: [
        {
          $group: {
            _id: "$user_id",
            topupCount: { $sum: 1 },
            firstTopupAt: { $min: "$timestamp" },
            lastTopupAt: { $max: "$timestamp" },
            recentHighTopups: {
              $push: {
                eventId: "$eventId",
                amount: "$properties.amount",
                timestamp: "$timestamp",
                source: "$properties.source"
              }
            }
          }
        },
        {
          $match: {
            topupCount: { $gte: 2 }
          }
        },
        {
          $addFields: {
            intervalSeconds: {
              $dateDiff: {
                startDate: "$firstTopupAt",
                endDate: "$lastTopupAt",
                unit: "second"
              }
            }
          }
        }
      ]
    }
  },
  // Write intermediate state to user profile
  {
    $project: {
      userId: "$_id",
      "fraud.signals.s01.topupClusterDetected": { $literal: true },
      "fraud.signals.s01.lastClusterAt": "$lastTopupAt",
      "fraud.signals.s01.topupCount": "$topupCount",
      "fraud.signals.s01.intervalSeconds": "$intervalSeconds",
      "fraud.signals.s01.recentHighTopups": "$recentHighTopups"
    }
  },
  {
    $merge: {
      into: {
        connectionName: "EnergyOperator_cluster",
        db: "FuelRetail_fraud",
        coll: "user_profiles"
      },
      on: "userId",
      whenMatched: "merge"
    }
  }
]
```

---

## Pipeline 1b: S01 — Instant Transfer Transfer Check (`Fuel Retail-signal-s01-transfer-check`)

**Stage 2 of 2. Windowless.** For every `InstantTransfer_transfer_out` event, does a `$lookup` (or `$cachedLookup`) against `user_profiles` to check:
1. Is `fraud.signals.s01.topupClusterDetected == true`?
2. Is the transfer within 30 minutes of `fraud.signals.s01.lastClusterAt`?

If both conditions match → write S01 alert to `fraud_alerts` + update `user_profiles.fraud`.

**Why no window:** Each InstantTransfer transfer is checked individually on arrival. The 30-minute condition is a timestamp comparison against the stored state, not a stream window. This is event enrichment, not windowed aggregation.

**Performance note:** InstantTransfer transfers are very frequent in Malaysia. `$cachedLookup` with a short TTL (e.g., 5 min) avoids hitting `user_profiles` on every event. Most lookups return `topupClusterDetected: false` (or no match) and pass through harmlessly.

```javascript
[
  {
    $source: {
      connectionName: "UtilitymskKafkaConnection",
      topic: "FuelRetail-fraud-events"
    }
  },
  {
    $match: {
      name: "InstantTransfer_transfer_out"
    }
  },
  // Enrich with user profile state
  {
    $lookup: {
      connectionName: "EnergyOperator_cluster",
      from: {
        db: "FuelRetail_fraud",
        coll: "user_profiles"
      },
      localField: "user_id",
      foreignField: "userId",
      as: "userProfile"
    }
  },
  {
    $unwind: "$userProfile"
  },
  // Check S01 conditions: cluster detected + within 30 min
  {
    $match: {
      "userProfile.fraud.signals.s01.topupClusterDetected": true,
      $expr: {
        $lte: [
          {
            $dateDiff: {
              startDate: "$userProfile.fraud.signals.s01.lastClusterAt",
              endDate: "$timestamp",
              unit: "minute"
            }
          },
          30
        ]
      }
    }
  },
  // Build the alert document with full event payloads
  {
    $addFields: {
      alertId: { $concat: ["alert-s01-", { $toString: "$user_id" }, "-", { $toString: "$$NOW" }] },
      userId: "$user_id",
      signal: "S01",
      severity: "critical",
      status: "open",
      details: "Auto top-up >= RM500 x 2+ within 15min + InstantTransfer transfer out within 30min",
      ruleSnapshot: {
        topupAmountThreshold: 500,
        topupCountThreshold: 2,
        topupWindowMinutes: 15,
        transferWindowMinutes: 30
      },
      // Combine the stored topup events with this transfer event
      events: {
        $concatArrays: [
          "$userProfile.fraud.signals.s01.recentHighTopups",
          [{
            eventId: "$eventId",
            name: "$name",
            amount: "$properties.amount",
            timestamp: "$timestamp",
            properties: "$properties"
          }]
        ]
      },
      createdAt: "$$NOW"
    }
  },
  // Write alert
  {
    $project: {
      alertId: 1, userId: 1, signal: 1, severity: 1, status: 1,
      details: 1, ruleSnapshot: 1, events: 1, createdAt: 1
    }
  },
  {
    $merge: {
      into: {
        connectionName: "EnergyOperator_cluster",
        db: "FuelRetail_fraud",
        coll: "fraud_alerts"
      }
    }
  }
]
```

**After alert fires:** The application (or a separate pipeline/trigger) should:
1. Update `user_profiles.fraud` — add alert to `fraud.alerts[]`, set `riskLevel: "critical"`, etc.
2. Reset `fraud.signals.s01.topupClusterDetected` to `false` to prevent duplicate alerts

---

## Pipeline 2: Signal S02 — Instant Transfer Payment After Top-Up (`Fuel Retail-signal-s02`)

**Windowless.** Each qualifying `InstantTransfer_payment` event individually checks if the user had a recent top-up via `$lookup`.

**Why windowless:** The pattern is "money in → money out to bank". We don't need to see the top-up event and the payment in the same window — we just need to know *when* the last top-up happened. The topup-state-writer pipeline maintains `fraud.lastTopupAt` on every top-up, so S02 just checks that field.

**Why eWallet excluded:** An eWallet-to-eWallet InstantTransfer stays within FuelRetail's ecosystem — they can trace it, freeze it, reverse it. But once money hits a bank account, it's gone.

**Conditions:**
- `InstantTransfer_payment` with `amount > RM500` and `type != "ewallet"` (bank transfer only)
- User's `fraud.lastTopupAt` is within 30 minutes of the payment

```javascript
[
  {
    $source: {
      connectionName: "UtilitymskKafkaConnection",
      topic: "FuelRetail-fraud-events"
    }
  },
  {
    $match: {
      name: "InstantTransfer_payment",
      "properties.amount": { $gt: 500 },
      "properties.type": { $ne: "ewallet" }
    }
  },
  // Enrich with user profile to check lastTopupAt
  {
    $lookup: {
      connectionName: "EnergyOperator_cluster",
      from: { db: "FuelRetail_fraud", coll: "user_profiles" },
      localField: "user_id",
      foreignField: "userId",
      as: "userProfile"
    }
  },
  { $unwind: "$userProfile" },
  // Check: lastTopupAt exists AND within 30 minutes
  {
    $match: {
      "userProfile.fraud.lastTopupAt": { $exists: true },
      $expr: {
        $lte: [
          { $dateDiff: {
            startDate: "$userProfile.fraud.lastTopupAt",
            endDate: "$timestamp",
            unit: "minute"
          }},
          30
        ]
      }
    }
  },
  {
    $addFields: {
      alertId: { $concat: ["alert-s02-", { $toString: "$user_id" }, "-", { $toString: "$$NOW" }] },
      userId: "$user_id",
      signal: "S02",
      severity: "high",
      status: "open",
      details: "InstantTransfer payment > RM500 (non-ewallet) within 30min after top-up",
      ruleSnapshot: { amountThreshold: 500, windowMinutes: 30 },
      events: [{ eventId: "$eventId", name: "$name", amount: "$properties.amount",
                 timestamp: "$timestamp", properties: "$properties" }],
      topupInfo: {
        lastTopupAt: "$userProfile.fraud.lastTopupAt",
        lastTopupAmount: "$userProfile.fraud.lastTopupAmount",
        lastTopupType: "$userProfile.fraud.lastTopupType"
      },
      createdAt: "$$NOW"
    }
  },
  {
    $project: {
      alertId: 1, userId: 1, signal: 1, severity: 1, status: 1,
      details: 1, ruleSnapshot: 1, events: 1, topupInfo: 1, createdAt: 1
    }
  },
  {
    $merge: {
      into: { connectionName: "EnergyOperator_cluster", db: "FuelRetail_fraud", coll: "fraud_alerts" }
    }
  }
]
```

**Performance:** Use `$cachedLookup` if available — InstantTransfer payments are very frequent in Malaysia. Most lookups will find `lastTopupAt` is null or stale (> 30 min) and pass through harmlessly.

---

## Pipeline 3: Signal S03 — Fund-Out Layering After Top-Up (`Fuel Retail-signal-s03`)

**Hybrid — window for the count, lookup for the top-up linkage.**

**Why this pattern:** One fund-out after a top-up might be legitimate (paying rent). But 2+ large fund-out transfers in quick succession after a top-up looks like layering — splitting funds across multiple destinations to avoid detection. That's a textbook money laundering technique.

**How it works:**
1. 30-min tumbling window counts `fund_out_transfer` events > RM500 per user
2. At window close, if count ≥ 2, do a `$lookup` on `user_profiles` to check if the user had a recent top-up

**Conditions:**
- 2+ `fund_out_transfer` with `amount > RM500` within 30 minutes
- User's `fraud.lastTopupAt` is recent (within 60 min, giving buffer for the window lag)

```javascript
[
  {
    $source: {
      connectionName: "UtilitymskKafkaConnection",
      topic: "FuelRetail-fraud-events"
    }
  },
  {
    $match: {
      name: "fund_out_transfer",
      "properties.amount": { $gt: 500 }
    }
  },
  {
    $tumblingWindow: {
      interval: { size: 30, unit: "minute" },
      pipeline: [
        {
          $group: {
            _id: "$user_id",
            fundOutCount: { $sum: 1 },
            totalAmount: { $sum: "$properties.amount" },
            fundOuts: {
              $push: {
                eventId: "$eventId", name: "$name",
                amount: "$properties.amount", timestamp: "$timestamp",
                properties: "$properties"
              }
            }
          }
        },
        {
          $match: { fundOutCount: { $gte: 2 } }
        }
      ]
    }
  },
  // After window close: check if user had a recent top-up
  {
    $lookup: {
      connectionName: "EnergyOperator_cluster",
      from: { db: "FuelRetail_fraud", coll: "user_profiles" },
      localField: "_id",
      foreignField: "userId",
      as: "userProfile"
    }
  },
  { $unwind: "$userProfile" },
  {
    $match: {
      "userProfile.fraud.lastTopupAt": { $exists: true },
      $expr: {
        $lte: [
          { $dateDiff: {
            startDate: "$userProfile.fraud.lastTopupAt",
            endDate: "$$NOW",
            unit: "minute"
          }},
          60
        ]
      }
    }
  },
  {
    $addFields: {
      alertId: { $concat: ["alert-s03-", { $toString: "$_id" }, "-", { $toString: "$$NOW" }] },
      userId: "$_id",
      signal: "S03",
      severity: "high",
      status: "open",
      details: { $concat: [
        { $toString: "$fundOutCount" }, " fund-out transfers totalling RM",
        { $toString: { $round: ["$totalAmount", 2] } }, " within 30min after top-up"
      ]},
      events: "$fundOuts",
      ruleSnapshot: { amountThreshold: 500, countThreshold: 2, windowMinutes: 30 },
      topupInfo: {
        lastTopupAt: "$userProfile.fraud.lastTopupAt",
        lastTopupAmount: "$userProfile.fraud.lastTopupAmount",
        lastTopupType: "$userProfile.fraud.lastTopupType"
      },
      createdAt: "$$NOW"
    }
  },
  {
    $project: {
      alertId: 1, userId: 1, signal: 1, severity: 1, status: 1,
      details: 1, ruleSnapshot: 1, events: 1, topupInfo: 1, createdAt: 1
    }
  },
  {
    $merge: {
      into: { connectionName: "EnergyOperator_cluster", db: "FuelRetail_fraud", coll: "fraud_alerts" }
    }
  }
]
```

**Key difference from S02:** S02 checks one big InstantTransfer payment (exfiltration via InstantTransfer). S03 checks multiple fund-out transfers being split (layering via fund-out). Different exfiltration strategies, different detection approaches.

---

## Pipeline 4: Signal S04 — Card Linking Velocity (`Fuel Retail-signal-s04`)

**Single pipeline.** Simplest signal — just count events in a time window.

**Conditions:**
- Three or more new cards linked within 1 hour

```javascript
[
  {
    $source: {
      connectionName: "UtilitymskKafkaConnection",
      topic: "FuelRetail-fraud-events"
    }
  },
  {
    $match: {
      name: "card_linked"
    }
  },
  {
    $tumblingWindow: {
      interval: { size: 60, unit: "minute" },
      pipeline: [
        {
          $group: {
            _id: "$user_id",
            cardCount: { $sum: 1 },
            cards: {
              $push: {
                eventId: "$eventId", name: "$name",
                ts: "$timestamp", properties: "$properties"
              }
            }
          }
        },
        {
          $match: { cardCount: { $gte: 3 } }
        }
      ]
    }
  },
  {
    $addFields: {
      alertId: { $concat: ["alert-s04-", { $toString: "$$NOW" }] },
      userId: "$_id",
      signal: "S04",
      severity: "medium",
      status: "open",
      details: "3+ cards linked within 1 hour",
      events: "$cards",
      ruleSnapshot: { cardCountThreshold: 3, velocityWindowMinutes: 60 },
      createdAt: "$$NOW"
    }
  },
  {
    $merge: {
      into: {
        connectionName: "EnergyOperator_cluster",
        db: "FuelRetail_fraud",
        coll: "fraud_alerts"
      }
    }
  }
]
```

---

## Updated `user_profiles` Schema — `fraud.signals` Sub-Document

Pipeline 1a writes intermediate detection state to the user profile. This is what makes the two-stage S01 architecture work — the profile is the state handoff.

```
user_profiles.fraud
├── riskLevel            "low" | "medium" | "high" | "critical"
├── signalsSeen[]        ["S01", "S04"]
├── alertCount           2
├── lastAlertAt          ISODate | null
├── lastAlertSignal      "S01" | null
├── embedding            [float] (1024-dim Voyage AI)
├── alerts[]             embedded alert history (capped at 20)
│
├── lastTopupAt          ISODate | null    ← topup-state-writer updates this on every top-up
├── lastTopupAmount      500               ← amount of last top-up
├── lastTopupType        "auto_topup"      ← "auto_topup" or "manual_topup"
│
└── signals                                ← REAL-TIME DETECTION STATE
    └── s01
        ├── topupClusterDetected    true    ← Pipeline 1a sets this
        ├── lastClusterAt           ISODate ← timestamp of last topup in cluster
        ├── topupCount              2       ← how many qualifying topups
        ├── intervalSeconds         420     ← seconds between first and last topup
        └── recentHighTopups[]              ← the actual topup events
            ├── eventId
            ├── amount
            ├── timestamp
            └── source
```

**How detection state is used:**
- `lastTopupAt/Amount/Type`: Written by topup-state-writer on **every** top-up. Read by S02 (windowless `$lookup`) and S03 (post-window `$lookup`).
- `signals.s01`: Written by Pipeline 1a on **cluster detection** only. Read by Pipeline 1b (`$lookup` on each transfer).
- S04 doesn't need any intermediate state — pure windowed count.

---

## How Signal Rules Work

Each pipeline's thresholds (e.g., `$gte: 500` for amount, `$gte: 2` for count) can be made dynamic using `$lookup` against the `signal_rules` collection at pipeline start.

**Current approach:** Thresholds are embedded in the pipeline definition. To change:
1. Update the threshold in the `signal_rules` MongoDB collection via the dashboard
2. Stop and restart the pipeline — it reads new values on start
3. No redeployment, no code change needed

**Future improvement:** Use `$lookup` to read `signal_rules` at the start of the pipeline, storing threshold values in pipeline variables.

---

## Deploying Pipelines

Use `mongosh` connected to the Atlas Stream Processing instance:

```javascript
// Connect to ASP
// mongosh "mongodb+srv://<user>:<password>@<cluster>.mongodb.net/<db>"

// Create pipeline
sp.createStreamProcessor("FuelRetail-signal-s01-topup-cluster", [/* pipeline stages */])

// Start
sp.FuelRetail-signal-s01-topup-cluster.start()

// Check status
sp.FuelRetail-signal-s01-topup-cluster.stats()

// Stop & Drop
sp.FuelRetail-signal-s01-topup-cluster.stop()
sp.FuelRetail-signal-s01-topup-cluster.drop()
```

---

## Architecture Comparison

### Before (Current — Confluent)
```
FuelRetail App → Kafka (Confluent) → KSQL → NestJS → MongoDB
```
- KSQL can't run on AWS MSK (Confluent-proprietary)
- NestJS layer adds complexity
- Rule changes require code deployment

### After (Proposed — MSK + Atlas Stream Processing)
```
FuelRetail App → Amazon MSK → Atlas Stream Processing → MongoDB
                              │
                              ├─ Pipeline 0:   passthrough → events (dashboard feed)
                              ├─ Pipeline 0b:  windowless → user_profiles.fraud.lastTopupAt
                              ├─ Pipeline 1a:  15-min window → user_profiles.fraud.signals.s01 (state)
                              ├─ Pipeline 1b:  windowless $lookup → fraud_alerts (S01)
                              ├─ Pipeline 2:   windowless $lookup → fraud_alerts (S02)
                              ├─ Pipeline 3:   30-min window + $lookup → fraud_alerts (S03)
                              └─ Pipeline 4:   60-min window → fraud_alerts (S04)
```
- Runs natively on MSK (no vendor lock-in)
- Signal rules stored in MongoDB, read by pipeline
- No intermediate application layer
- S01 uses MongoDB as state store between two pipelines — the key demo moment
- Rule changes: update MongoDB doc → restart pipeline
- Lower, more predictable cost than self-managed Flink (no standing infra)

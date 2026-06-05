# Atlas Stream Processing — Setup & Operations Guide

**Last updated:** 12 March 2026

---

## Architecture

```
EC2 Kafka Producer (MSK-Admin-Host, 203.0.113.11)
        |  (OAUTHBEARER IAM auth, port 9098)
    Amazon MSK (topic: FuelRetail-fraud-events, 3 partitions)
        |  (UtilitymskKafkaConnection, private networking)
    Atlas Stream Processing (workspace: toffTest, singapore-sgp)
        |  (FuelRetail_cluster connection)
    MongoDB Atlas (testCluster → FuelRetail_fraud db)
```

---

## Connection Registry

| Name | Type | Target |
|------|------|--------|
| `UtilitymskKafkaConnection` | kafka | MSK `demo-cluster` via private networking |
| `FuelRetail_cluster` | atlas | `testCluster` (FuelRetail_fraud db) |

---

## Stream Processors (7 total)

### Windowless Processors (fire immediately per event)

| Processor | Source Filter | Output | Notes |
|-----------|-------------|--------|-------|
| `FuelRetail-event-ingest` | All events | `asp_ingested_events` collection | Adds `_ingestedAt` timestamp |
| `FuelRetail-topup-state-writer` | `auto_topup`, `manual_topup` | `user_profiles.fraud.lastTopup*` | Updates topup state for S02/S03 lookups |
| `FuelRetail-signal-s01b` | `InstantTransfer_transfer_out` | `fraud_alerts` (S01, critical) | $lookup user_profiles for S01a burst state |
| `FuelRetail-signal-s02` | `InstantTransfer_payment > RM500 (bank)` | `fraud_alerts` (S02, high) | $lookup user_profiles for recent topup |

### Windowed Processors (emit after window closes)

| Processor | Window | Source Filter | Output | Notes |
|-----------|--------|-------------|--------|-------|
| `FuelRetail-signal-s01a` | 15min tumbling | `auto_topup >= RM500` | `user_profiles.fraud.signals.s01.*` | Writes burst state for S01b |
| `FuelRetail-signal-s03` | 30min tumbling | `fund_out_transfer > RM500` | `fraud_alerts` (S03, high) | Hybrid: window + $lookup for topup |
| `FuelRetail-signal-s04` | 60min tumbling | `card_linked` | `fraud_alerts` (S04, medium) | Pure windowed, no $lookup |

---

## EC2 Instance (Kafka Producer)

| Property | Value |
|----------|-------|
| Instance ID | `<instance-id>` |
| Name | `MSK-Admin-Host` |
| Public IP | `203.0.113.11` |
| SSH Key | `~/Documents/demo_key.pem` |
| User | `ubuntu` |
| IAM Role | `demo-cluster` |
| Scripts | `/home/ubuntu/FuelRetail_test_producer.py`, `/home/ubuntu/FuelRetail_continuous_producer.py` |

### SSH & Run

```bash
# One-shot test (11 events, instant)
ssh -i ~/Documents/demo_key.pem ubuntu@203.0.113.11 "python3 /home/ubuntu/FuelRetail_test_producer.py"

# Continuous (~2.5 min, triggers windowed processors)
ssh -i ~/Documents/demo_key.pem ubuntu@203.0.113.11 "python3 /home/ubuntu/FuelRetail_continuous_producer.py"
```

---

## ASP Deployment

```bash
# Connect to ASP workspace
mongosh "mongodb+srv://<user>:<password>@<cluster>.mongodb.net/<db>"

# Deploy all 7 processors (stops/drops existing, creates, starts)
mongosh "<ASP_URI>" --file backend/stream_processing/deploy_all.js

# Check status
sp.listStreamProcessors().filter(p => p.name.startsWith("FuelRetail-"))

# Check stats for a processor
sp["FuelRetail-event-ingest"].stats()
```

---

## Key Fixes & Gotchas

1. **`$$NOW` not available in windowless stages** — Use `{ $toDate: "$_ts" }` instead. ASP adds `_ts` to every message.
2. **`$lookup` syntax** — ASP requires `connectionName` INSIDE `from`, not alongside it:
   ```js
   // CORRECT
   $lookup: { from: { connectionName: "FuelRetail_cluster", db: "FuelRetail_fraud", coll: "user_profiles" }, ... }
   // WRONG
   $lookup: { connectionName: "FuelRetail_cluster", from: { db: "FuelRetail_fraud", coll: "user_profiles" }, ... }
   ```
3. **`$emit` vs `$merge`** — `$emit` is for time-series collections only. Use `$merge` for regular collections.
4. **Connection target** — `EnergyOperator_cluster` points to `Cluster0`, NOT `testCluster`. Use `FuelRetail_cluster` for FuelRetail_fraud data.
5. **Windowed processors** — Need continuous event flow for the full window interval (15/30/60 min) before they emit. The `partitionIdleTimeout: 5s` helps close windows when traffic stops.
6. **Kafka topic** — `FuelRetail-fraud-events` (3 partitions, replication-factor 2). Created via Kafka CLI on EC2.

---

## Verified Results

| Pipeline | Status | Evidence |
|----------|--------|----------|
| Event Ingest | Working | 61+ events in `asp_ingested_events` with `_ingestedAt` |
| Topup State Writer | Working | `user_profiles.fraud.lastTopup*` updated in real-time |
| S02 (InstantTransfer Payment) | Working | 2 ASP-generated alerts in `fraud_alerts` |
| S01a (Topup Burst) | Deployed, needs 15min window | Window hasn't closed in test |
| S01b (Transfer Check) | Deployed, depends on S01a | Waiting for S01a state |
| S03 (Fund-Out) | Deployed, needs 30min window | Window hasn't closed in test |
| S04 (Card Linking) | Deployed, needs 60min window | Window hasn't closed in test |

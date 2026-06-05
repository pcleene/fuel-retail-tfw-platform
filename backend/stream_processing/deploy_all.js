// Deploy all 7 FuelRetail fraud ASP stream processors
// Run: mongosh "<ASP_URI>" --file deploy_all.js

const processors = [
  // 1. Event Ingestion Passthrough
  {
    name: "FuelRetail-event-ingest",
    pipeline: [
      {
        $source: {
          connectionName: "UtilitymskKafkaConnection",
          topic: "FuelRetail-fraud-events"
        }
      },
      { $addFields: { _ingestedAt: { $toDate: "$_ts" } } },
      {
        $merge: {
          into: {
            connectionName: "FuelRetail_cluster",
            db: "FuelRetail_fraud",
            coll: "asp_ingested_events"
          }
        }
      }
    ]
  },

  // 2. Top-Up State Writer
  {
    name: "FuelRetail-topup-state-writer",
    pipeline: [
      {
        $source: {
          connectionName: "UtilitymskKafkaConnection",
          topic: "FuelRetail-fraud-events"
        }
      },
      { $match: { name: { $in: ["auto_topup", "manual_topup"] } } },
      {
        $addFields: {
          userId: "$user_id",
          "fraud.lastTopupAt": { $toDate: "$timestamp" },
          "fraud.lastTopupAmount": "$properties.amount",
          "fraud.lastTopupType": "$name"
        }
      },
      {
        $project: {
          userId: 1,
          "fraud.lastTopupAt": 1,
          "fraud.lastTopupAmount": 1,
          "fraud.lastTopupType": 1
        }
      },
      {
        $merge: {
          into: {
            connectionName: "FuelRetail_cluster",
            db: "FuelRetail_fraud",
            coll: "user_profiles"
          },
          on: "userId",
          whenMatched: "merge"
        }
      }
    ]
  },

  // 3. S01a — Top-Up Cluster Detection (windowed)
  {
    name: "FuelRetail-signal-s01a",
    pipeline: [
      {
        $source: {
          connectionName: "UtilitymskKafkaConnection",
          topic: "FuelRetail-fraud-events",
          timeField: { $toDate: "$timestamp" },
          partitionIdleTimeout: { size: 5, unit: "second" }
        }
      },
      { $match: { name: "auto_topup", "properties.amount": { $gte: 500 } } },
      {
        $tumblingWindow: {
          interval: { size: 1, unit: "minute" },  // PRODUCTION: 15 minute
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
            { $match: { topupCount: { $gte: 2 } } },
            {
              $addFields: {
                intervalSeconds: {
                  $dateDiff: {
                    startDate: { $toDate: "$firstTopupAt" },
                    endDate: { $toDate: "$lastTopupAt" },
                    unit: "second"
                  }
                }
              }
            }
          ]
        }
      },
      {
        $project: {
          userId: "$_id",
          "fraud.signals.s01.topupBurstDetected": { $literal: true },
          "fraud.signals.s01.lastBurstAt": "$lastTopupAt",
          "fraud.signals.s01.topupCount": "$topupCount",
          "fraud.signals.s01.intervalSeconds": "$intervalSeconds",
          "fraud.signals.s01.recentHighTopups": "$recentHighTopups"
        }
      },
      {
        $merge: {
          into: {
            connectionName: "FuelRetail_cluster",
            db: "FuelRetail_fraud",
            coll: "user_profiles"
          },
          on: "userId",
          whenMatched: "merge"
        }
      }
    ]
  },

  // 4. S01b — InstantTransfer Transfer Check (windowless, lookup)
  {
    name: "FuelRetail-signal-s01b",
    pipeline: [
      {
        $source: {
          connectionName: "UtilitymskKafkaConnection",
          topic: "FuelRetail-fraud-events"
        }
      },
      { $match: { name: "InstantTransfer_transfer_out" } },
      {
        $lookup: {
          from: { connectionName: "FuelRetail_cluster", db: "FuelRetail_fraud", coll: "user_profiles" },
          localField: "user_id",
          foreignField: "userId",
          as: "userProfile"
        }
      },
      { $unwind: "$userProfile" },
      { $match: { "userProfile.fraud.signals.s01.topupBurstDetected": true } },
      {
        $match: {
          $expr: {
            $lte: [
              {
                $dateDiff: {
                  startDate: { $toDate: "$userProfile.fraud.signals.s01.lastBurstAt" },
                  endDate: { $toDate: "$timestamp" },
                  unit: "minute"
                }
              },
              30
            ]
          }
        }
      },
      {
        $addFields: {
          alertId: { $concat: ["alert-s01-", { $toString: "$user_id" }, "-", { $toString: { $toDate: "$_ts" } }] },
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
          createdAt: { $toDate: "$_ts" }
        }
      },
      {
        $project: {
          alertId: 1, userId: 1, signal: 1, severity: 1, status: 1,
          details: 1, ruleSnapshot: 1, events: 1, createdAt: 1
        }
      },
      {
        $merge: {
          into: {
            connectionName: "FuelRetail_cluster",
            db: "FuelRetail_fraud",
            coll: "fraud_alerts"
          }
        }
      }
    ]
  },

  // 5. S02 — InstantTransfer Payment After Top-Up (windowless, lookup)
  {
    name: "FuelRetail-signal-s02",
    pipeline: [
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
      {
        $lookup: {
          from: { connectionName: "FuelRetail_cluster", db: "FuelRetail_fraud", coll: "user_profiles" },
          localField: "user_id",
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
              {
                $dateDiff: {
                  startDate: { $toDate: "$userProfile.fraud.lastTopupAt" },
                  endDate: { $toDate: "$timestamp" },
                  unit: "minute"
                }
              },
              30
            ]
          }
        }
      },
      {
        $addFields: {
          alertId: { $concat: ["alert-s02-", { $toString: "$user_id" }, "-", { $toString: { $toDate: "$_ts" } }] },
          userId: "$user_id",
          signal: "S02",
          severity: "high",
          status: "open",
          details: "InstantTransfer payment > RM500 (bank transfer) within 30min after top-up",
          ruleSnapshot: { amountThreshold: 500, windowMinutes: 30 },
          topupInfo: {
            lastTopupAt: "$userProfile.fraud.lastTopupAt",
            lastTopupAmount: "$userProfile.fraud.lastTopupAmount",
            lastTopupType: "$userProfile.fraud.lastTopupType"
          },
          events: [{
            eventId: "$eventId", name: "$name",
            amount: "$properties.amount", timestamp: "$timestamp",
            properties: "$properties"
          }],
          createdAt: { $toDate: "$_ts" }
        }
      },
      {
        $project: {
          alertId: 1, userId: 1, signal: 1, severity: 1, status: 1,
          details: 1, ruleSnapshot: 1, topupInfo: 1, events: 1, createdAt: 1
        }
      },
      {
        $merge: {
          into: {
            connectionName: "FuelRetail_cluster",
            db: "FuelRetail_fraud",
            coll: "fraud_alerts"
          }
        }
      }
    ]
  },

  // 6. S03 — Multiple Fund-Outs After Top-Up (hybrid: window + lookup)
  {
    name: "FuelRetail-signal-s03",
    pipeline: [
      {
        $source: {
          connectionName: "UtilitymskKafkaConnection",
          topic: "FuelRetail-fraud-events",
          timeField: { $toDate: "$timestamp" },
          partitionIdleTimeout: { size: 5, unit: "second" }
        }
      },
      { $match: { name: "fund_out_transfer", "properties.amount": { $gt: 500 } } },
      {
        $tumblingWindow: {
          interval: { size: 2, unit: "minute" },  // PRODUCTION: 30 minute
          pipeline: [
            {
              $group: {
                _id: "$user_id",
                fundOutCount: { $sum: 1 },
                totalAmount: { $sum: "$properties.amount" },
                windowEnd: { $max: "$timestamp" },
                fundOutDetails: {
                  $push: {
                    eventId: "$eventId",
                    amount: "$properties.amount",
                    timestamp: "$timestamp",
                    recipient: "$properties.recipient"
                  }
                }
              }
            },
            { $match: { fundOutCount: { $gte: 2 } } }
          ]
        }
      },
      {
        $lookup: {
          from: { connectionName: "FuelRetail_cluster", db: "FuelRetail_fraud", coll: "user_profiles" },
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
              {
                $dateDiff: {
                  startDate: { $toDate: "$userProfile.fraud.lastTopupAt" },
                  endDate: { $toDate: "$windowEnd" },
                  unit: "minute"
                }
              },
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
          details: "2+ fund-out transfers > RM500 within 30min after top-up",
          ruleSnapshot: { amountThreshold: 500, countThreshold: 2, windowMinutes: 30 },
          topupInfo: {
            lastTopupAt: "$userProfile.fraud.lastTopupAt",
            lastTopupAmount: "$userProfile.fraud.lastTopupAmount",
            lastTopupType: "$userProfile.fraud.lastTopupType"
          },
          events: "$fundOutDetails",
          createdAt: "$$NOW"
        }
      },
      {
        $project: {
          alertId: 1, userId: 1, signal: 1, severity: 1, status: 1,
          details: 1, ruleSnapshot: 1, topupInfo: 1, events: 1,
          fundOutCount: 1, totalAmount: 1, createdAt: 1
        }
      },
      {
        $merge: {
          into: {
            connectionName: "FuelRetail_cluster",
            db: "FuelRetail_fraud",
            coll: "fraud_alerts"
          }
        }
      }
    ]
  },

  // 7. S04 — Rapid Card Linking (windowed, no lookup)
  {
    name: "FuelRetail-signal-s04",
    pipeline: [
      {
        $source: {
          connectionName: "UtilitymskKafkaConnection",
          topic: "FuelRetail-fraud-events",
          timeField: { $toDate: "$timestamp" },
          partitionIdleTimeout: { size: 5, unit: "second" }
        }
      },
      { $match: { name: "card_linked" } },
      {
        $tumblingWindow: {
          interval: { size: 2, unit: "minute" },  // PRODUCTION: 60 minute
          pipeline: [
            {
              $group: {
                _id: "$user_id",
                cardCount: { $sum: 1 },
                cards: {
                  $push: {
                    eventId: "$eventId",
                    name: "$name",
                    timestamp: "$timestamp",
                    properties: "$properties"
                  }
                }
              }
            },
            { $match: { cardCount: { $gte: 3 } } }
          ]
        }
      },
      {
        $addFields: {
          alertId: { $concat: ["alert-s04-", { $toString: "$_id" }, "-", { $toString: "$$NOW" }] },
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
        $project: {
          alertId: 1, userId: 1, signal: 1, severity: 1, status: 1,
          details: 1, events: 1, ruleSnapshot: 1, cardCount: 1, createdAt: 1
        }
      },
      {
        $merge: {
          into: {
            connectionName: "FuelRetail_cluster",
            db: "FuelRetail_fraud",
            coll: "fraud_alerts"
          }
        }
      }
    ]
  }
];

// Deploy each processor
for (const proc of processors) {
  print(`\n--- ${proc.name} ---`);

  // Try to stop and drop if it exists
  try {
    sp[proc.name].stop();
    print(`  Stopped existing ${proc.name}`);
  } catch (e) {
    // Not running or doesn't exist
  }
  try {
    sp[proc.name].drop();
    print(`  Dropped existing ${proc.name}`);
  } catch (e) {
    // Doesn't exist
  }

  // Create
  try {
    sp.createStreamProcessor(proc.name, proc.pipeline);
    print(`  Created ${proc.name}`);
  } catch (e) {
    print(`  ERROR creating ${proc.name}: ${e.message}`);
    continue;
  }

  // Start
  try {
    sp[proc.name].start();
    print(`  Started ${proc.name}`);
  } catch (e) {
    print(`  ERROR starting ${proc.name}: ${e.message}`);
  }
}

print("\n=== Listing all FuelRetail processors ===");
const all = sp.listStreamProcessors();
const FuelRetail = all.filter(p => p.name.startsWith("FuelRetail-"));
for (const p of FuelRetail) {
  print(`  ${p.name}: ${p.state} ${p.errorMsg ? '(ERROR: ' + p.errorMsg + ')' : ''}`);
}
print("\nDone!");

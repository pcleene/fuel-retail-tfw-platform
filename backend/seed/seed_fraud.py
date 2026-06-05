"""
Seed script for the FuelRetail_fraud MongoDB database (UC3 Fraud Detection).

Run from project root:
    python -m backend.seed.seed_fraud

Seeds:
  - signal_rules    (4 documents)
  - user_profiles   (500 documents, 15 pre-flagged)
  - events          (200+ documents)
  - fraud_alerts    (15-20 documents)
  - Indexes on all collections
  - Voyage AI embeddings for pre-flagged users
"""

import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
from motor.motor_asyncio import AsyncIOMotorClient

# ── Logging ──────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────

MONGO_URI = "mongodb+srv://<user>:<password>@<cluster>.mongodb.net/<db>"
TLS_CERT_PATH = "<local-path>"
DB_NAME = "FuelRetail_fraud"

VOYAGE_API_KEY = "<voyage-key>"
VOYAGE_MODEL = "voyage-4-large"

NOW = datetime(2026, 3, 9, 12, 0, 0)
SEVEN_DAYS_AGO = NOW - timedelta(days=7)

TOTAL_USERS = 500
NUM_PREFLAGGED = 15

# ── Malaysian Name Data ──────────────────────────────────────────────

MALAY_MALE_FIRST = [
    "Ahmad", "Mohd", "Ismail", "Faizal", "Hafiz", "Azman", "Razak",
    "Zulkifli", "Hakim", "Amir", "Rizal", "Shahrul", "Firdaus",
    "Khairul", "Nizam", "Roslan", "Hamdan", "Aziz", "Kamal", "Saiful",
    "Syahmi", "Izzat", "Danial", "Arif", "Luqman",
]

MALAY_FEMALE_FIRST = [
    "Nurul", "Siti", "Aisyah", "Fatimah", "Norazlina", "Rahmah",
    "Zaiton", "Aminah", "Haslinda", "Norhayati", "Farah", "Nadia",
    "Syahirah", "Aini", "Hidayah", "Zarina", "Salina", "Roslina",
    "Mariam", "Suraya", "Aida", "Izzati", "Adlina", "Liyana", "Hana",
]

MALAY_FAMILY = [
    "Abdullah", "Ibrahim", "Hassan", "Yusof", "Osman", "Sulaiman",
    "Md Noor", "Razali", "Ismail", "Mat Hussin", "Bakar", "Mohd Ali",
    "Jaafar", "Kadir", "Hamid",
]

CHINESE_FAMILY = [
    "Tan", "Lim", "Wong", "Lee", "Chan", "Ng", "Ong", "Goh", "Koh",
    "Teh", "Yeoh", "Cheah", "Chin", "Foo", "Ho",
]

CHINESE_MALE_GIVEN = [
    "Wei Ming", "Jian Hong", "Zhi Wei", "Jun Jie", "Hao Wen",
    "Yi Xuan", "Kai Wen", "Zheng Yang", "Jia Le", "Ren Jie",
    "Kok Leong", "Wai Kit", "Chee Keong", "Seng Huat", "Boon Keat",
]

CHINESE_FEMALE_GIVEN = [
    "Jia Wen", "Hui Ling", "Xin Yi", "Mei Ling", "Shu Ting",
    "Pei Shan", "Wen Xin", "Jia Yi", "Yi Wen", "Xin Ying",
    "Siew Lan", "Li Hua", "May Chen", "Su Lin", "Chia Yee",
]

INDIAN_MALE_FIRST = [
    "Rajesh", "Anand", "Kumar", "Suresh", "Vikram", "Ganesh",
    "Prakash", "Ramesh", "Harish", "Dinesh", "Sathish", "Mohan",
    "Arvind", "Navin", "Ravi",
]

INDIAN_FEMALE_FIRST = [
    "Priya", "Lakshmi", "Kavitha", "Deepa", "Anitha", "Revathi",
    "Shalini", "Nirmala", "Indra", "Meena", "Vasanthi", "Devi",
    "Sushila", "Geetha", "Kamala",
]

INDIAN_FAMILY = [
    "Krishnan", "Muthu", "Rajan", "Pillai", "Nair", "Subramaniam",
    "Ramasamy", "Muniandy", "Suppiah", "Thuraisingam", "Naidu",
    "Govindan", "Shanmugam", "Veloo", "Arumugam",
]

BANKS = ["RegionalBankB", "CIMB", "Public Bank", "RHB", "Alliance Bank", "AmBank", "Bank Islam", "OCBC"]
CARD_TYPES = ["visa", "mastercard"]
TIERS = ["basic", "standard", "premium"]
STATIONS = [
    "EnergyOperator Bangsar", "EnergyOperator KLCC", "EnergyOperator Damansara",
    "EnergyOperator Subang", "EnergyOperator Petaling Jaya", "EnergyOperator Shah Alam",
    "EnergyOperator Cyberjaya", "EnergyOperator Putrajaya", "EnergyOperator Cheras",
    "EnergyOperator Ampang", "EnergyOperator Kepong", "EnergyOperator Setapak",
    "EnergyOperator Puchong", "EnergyOperator Sunway", "EnergyOperator Bukit Jalil",
    "EnergyOperator Mont Kiara", "EnergyOperator Hartamas", "EnergyOperator Kelana Jaya",
    "EnergyOperator Ara Damansara", "EnergyOperator USJ",
]
DEVICES = ["iPhone 15", "iPhone 14 Pro", "iPhone 13", "Samsung Galaxy S24", "Samsung Galaxy S23",
           "Xiaomi 14", "OPPO Find X7", "Huawei P60", "Google Pixel 8", "Samsung Galaxy A54"]
KYC_METHODS = ["eKYC", "branch_verification", "video_call"]
KYC_DOC_TYPES = ["MyKad", "Passport"]

# ── Helper Functions ─────────────────────────────────────────────────


def _random_ip() -> str:
    return f"203.0.113.{random.randint(1, 254)}"


def _random_session() -> str:
    return f"sess-{uuid4().hex[:12]}"


def _user_id(n: int) -> str:
    return f"USR-{n:05d}"


def _evt_id() -> str:
    return f"evt-{uuid4().hex[:12]}"


def _alert_id(signal: str, user_num: int, seq: int) -> str:
    return f"alert-{signal.lower()}-usr{user_num:03d}-{seq:03d}"


def _random_dt(start: datetime, end: datetime) -> datetime:
    delta = end - start
    secs = random.randint(0, int(delta.total_seconds()))
    return start + timedelta(seconds=secs)


def _random_dob() -> datetime:
    year = random.randint(1970, 2002)
    month = random.randint(1, 12)
    day = random.randint(1, 28)
    return datetime(year, month, day)


def _ic_from_dob(dob: datetime) -> str:
    yy = f"{dob.year % 100:02d}"
    mm = f"{dob.month:02d}"
    dd = f"{dob.day:02d}"
    state = f"{random.randint(1, 16):02d}"
    seq = f"{random.randint(1, 9999):04d}"
    return f"{yy}{mm}{dd}-{state}-{seq}"


def _generate_malaysian_name() -> tuple[str, str]:
    """Return (full_name, gender) for a random Malaysian person."""
    ethnicity = random.choices(["malay", "chinese", "indian"], weights=[55, 30, 15])[0]
    gender = random.choice(["male", "female"])

    if ethnicity == "malay":
        if gender == "male":
            first = random.choice(MALAY_MALE_FIRST)
            father = random.choice(MALAY_MALE_FIRST)
            family = random.choice(MALAY_FAMILY)
            name = f"{first} bin {family}"
        else:
            first = random.choice(MALAY_FEMALE_FIRST)
            family = random.choice(MALAY_FAMILY)
            name = f"{first} binti {family}"
    elif ethnicity == "chinese":
        family = random.choice(CHINESE_FAMILY)
        given = random.choice(CHINESE_MALE_GIVEN if gender == "male" else CHINESE_FEMALE_GIVEN)
        name = f"{family} {given}"
    else:  # indian
        first = random.choice(INDIAN_MALE_FIRST if gender == "male" else INDIAN_FEMALE_FIRST)
        family = random.choice(INDIAN_FAMILY)
        connector = "a/l" if gender == "male" else "a/p"
        name = f"{first} {connector} {family}"

    return name, gender


def _email_from_name(name: str, idx: int) -> str:
    parts = name.lower().replace("/", "").replace(" ", ".").replace("..", ".")
    return f"{parts}{idx}@example.com"


def _phone() -> str:
    prefix = random.choice(["12", "13", "14", "16", "17", "18", "19"])
    num = random.randint(1000000, 9999999)
    return f"+60{prefix}{num}"


def _last4() -> str:
    return f"{random.randint(1000, 9999)}"


def _linked_cards(n: int) -> list[dict]:
    cards = []
    for i in range(n):
        cards.append({
            "last4": _last4(),
            "type": random.choice(CARD_TYPES),
            "bank": random.choice(BANKS),
            "linkedAt": _random_dt(datetime(2024, 1, 1), datetime(2026, 2, 1)),
            "isDefault": i == 0,
        })
    return cards


def _make_event(event_id: str, name: str, user_id: str, timestamp: datetime,
                properties: dict, partition: int = 0, offset: int = 0) -> dict:
    return {
        "eventId": event_id,
        "origin": "FuelRetail-app",
        "name": name,
        "user_id": user_id,
        "timestamp": timestamp,
        "properties": properties,
        "metadata": {
            "device": random.choice(DEVICES),
            "ip": _random_ip(),
            "sessionId": _random_session(),
        },
        "_ingested_at": timestamp + timedelta(seconds=1),
        "_source_topic": "FuelRetail-fraud-events",
        "_partition": partition,
        "_offset": offset,
    }


# ── compose_fraud_profile_text (mirrors fraud_service.py) ───────────

def compose_fraud_profile_text(user: dict) -> str:
    """Compose a text representation of a user's fraud profile for embedding."""
    parts = []

    for alert in user.get("fraud", {}).get("alerts", []):
        parts.append(f"Signal {alert['signal']}: {alert['details']}. Severity: {alert['severity']}.")
        for evt in alert.get("events", []):
            props = evt.get("properties", {})
            parts.append(
                f"Event: {evt['name']}, amount: {props.get('amount', 'N/A')}, "
                f"recipient: {props.get('recipient', 'N/A')}"
            )

    activity = user.get("activitySummary", {})
    wallet = user.get("wallet", {})
    kyc = user.get("kyc", {})
    cards = user.get("linkedCards", [])

    parts.append(f"Wallet tier: {wallet.get('tier', 'unknown')}, balance: {wallet.get('balance', 0)} MYR")
    parts.append(f"KYC status: {kyc.get('status', 'unknown')}, risk level: {kyc.get('riskLevel', 'unknown')}")
    parts.append(
        f"Total transactions: {activity.get('totalTransactions', 0)}, "
        f"total spend: {activity.get('totalSpend', 0)} MYR, "
        f"monthly avg: {activity.get('monthlyAvgSpend', 0)} MYR"
    )
    parts.append(f"Linked cards: {len(cards)}")

    signals = user.get("fraud", {}).get("signalsSeen", [])
    if signals:
        parts.append(f"Signals triggered: {', '.join(signals)}")

    return " | ".join(parts)


# ── Voyage AI embedding ─────────────────────────────────────────────

async def generate_embedding(text: str) -> list[float] | None:
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.voyageai.com/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {VOYAGE_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": VOYAGE_MODEL,
                    "input": [text],
                    "input_type": "document",
                },
                timeout=30.0,
            )
            resp.raise_for_status()
            return resp.json()["data"][0]["embedding"]
    except Exception as e:
        logger.error("Voyage AI embedding failed: %s", e)
        return None


# ── Signal Rules ─────────────────────────────────────────────────────

def _build_signal_rules() -> list[dict]:
    base_ts = 1771570727

    def _rule(key_suffix: str, description: str, enabled_value: dict) -> dict:
        key = f"ai_defence_{key_suffix}_signal_config"
        return {
            "key": key,
            "name": key,
            "type": "json",
            "group": "platform",
            "description": description,
            "isToggled": True,
            "version": 1,
            "isArchived": False,
            "state": "ready",
            "variants": {
                "Disabled": {"key": "Disabled", "value": {"enabled": False}},
                "Enabled": {"key": "Enabled", "value": {"enabled": True, **enabled_value}},
            },
            "onVariation": [{"percent": 100, "variantKey": "Enabled"}],
            "offVariation": "Disabled",
            "createdAt": base_ts,
            "updatedAt": base_ts,
        }

    return [
        _rule("s01",
              "AI Fraud S-01: Auto top-up velocity + InstantTransfer transfer out",
              {"topupAmountThreshold": 500, "topupCountThreshold": 2,
               "topupWindowMinutes": 15, "transferWindowMinutes": 30}),
        _rule("s02",
              "AI Fraud S-02: Top-up + InstantTransfer payment exceeding threshold",
              {"amountThreshold": 500, "windowMinutes": 30}),
        _rule("s03",
              "AI Fraud S-03: Top-up + multiple fund-out exceeding threshold",
              {"amountThreshold": 500, "countThreshold": 2, "windowMinutes": 30}),
        _rule("s04",
              "AI Fraud S-04: Rapid card linking velocity",
              {"cardCountThreshold": 3, "velocityWindowMinutes": 60}),
    ]


# ── Pre-flagged User Builders ───────────────────────────────────────

# Use a global offset counter for events so IDs are deterministic.
_global_offset = [0]


def _next_offset() -> int:
    _global_offset[0] += 1
    return _global_offset[0]


def _build_s01_user(user_num: int, base_time: datetime) -> tuple[dict, list[dict], dict]:
    """
    S01: 2+ auto_topup >= RM500 within 15 min + InstantTransfer_transfer_out within 30 min.
    Users 1-5 have SIMILAR patterns for vector similarity testing.
    """
    uid = _user_id(user_num)

    # Similar pattern: amounts between 500-650, short window
    topup_amount_1 = 500 + (user_num * 20)  # 520, 540, 560, 580, 600
    topup_amount_2 = 500 + (user_num * 25)  # 525, 550, 575, 600, 625
    transfer_amount = topup_amount_1 + topup_amount_2 - random.randint(50, 150)

    card_last4 = _last4()
    recipient = f"60{random.randint(10, 19)}{random.randint(1000000, 9999999)}"

    t1 = base_time
    t2 = t1 + timedelta(minutes=random.randint(3, 12))
    t3 = t2 + timedelta(minutes=random.randint(5, 25))

    evt1_id = _evt_id()
    evt2_id = _evt_id()
    evt3_id = _evt_id()

    evt1 = _make_event(evt1_id, "auto_topup", uid, t1,
                       {"amount": topup_amount_1, "source": f"card_ending_{card_last4}", "currency": "MYR"},
                       offset=_next_offset())
    evt2 = _make_event(evt2_id, "auto_topup", uid, t2,
                       {"amount": topup_amount_2, "source": f"card_ending_{card_last4}", "currency": "MYR"},
                       offset=_next_offset())
    evt3 = _make_event(evt3_id, "InstantTransfer_transfer_out", uid, t3,
                       {"amount": transfer_amount, "recipient": recipient, "currency": "MYR"},
                       offset=_next_offset())

    events = [evt1, evt2, evt3]

    # Build alert event payloads (embedded in alert)
    alert_events = []
    for e in events:
        alert_events.append({
            "eventId": e["eventId"],
            "name": e["name"],
            "timestamp": e["timestamp"],
            "properties": e["properties"],
        })

    alert = {
        "alertId": _alert_id("S01", user_num, 1),
        "userId": uid,
        "signal": "S01",
        "details": f"Auto top-up >= RM500 x 2 in 15min + InstantTransfer transfer out within 30min",
        "severity": "critical",
        "status": "open",
        "ruleSnapshot": {
            "topupAmountThreshold": 500,
            "topupCountThreshold": 2,
            "topupWindowMinutes": 15,
            "transferWindowMinutes": 30,
        },
        "events": alert_events,
        "createdAt": t3 + timedelta(minutes=1),
    }

    # Real-time detection state written by Pipeline 1a
    interval_secs = int((t2 - t1).total_seconds())
    signals_state = {
        "s01": {
            "topupClusterDetected": True,
            "lastClusterAt": t2,
            "topupCount": 2,
            "intervalSeconds": interval_secs,
            "recentHighTopups": [
                {"eventId": evt1_id, "amount": topup_amount_1, "timestamp": t1, "source": f"card_ending_{card_last4}"},
                {"eventId": evt2_id, "amount": topup_amount_2, "timestamp": t2, "source": f"card_ending_{card_last4}"},
            ],
        }
    }

    fraud_sub = {
        "riskLevel": "critical",
        "signalsSeen": ["S01"],
        "alertCount": 1,
        "lastAlertAt": alert["createdAt"],
        "lastAlertSignal": "S01",
        "alerts": [alert],
        "embedding": None,
        "signals": signals_state,
        "lastTopupAt": t2,
        "lastTopupAmount": topup_amount_2,
        "lastTopupType": "auto_topup",
    }

    return fraud_sub, events, alert


def _build_s04_user(user_num: int, base_time: datetime) -> tuple[dict, list[dict], dict]:
    """S04: 3+ card_linked in 1 hour."""
    uid = _user_id(user_num)

    card_events = []
    alert_events = []
    for i in range(3 + random.randint(0, 1)):
        t = base_time + timedelta(minutes=random.randint(0, 55))
        eid = _evt_id()
        last4 = _last4()
        evt = _make_event(eid, "card_linked", uid, t,
                          {"last4": last4, "cardType": random.choice(CARD_TYPES),
                           "bank": random.choice(BANKS)},
                          offset=_next_offset())
        card_events.append(evt)
        alert_events.append({
            "eventId": evt["eventId"],
            "name": evt["name"],
            "timestamp": evt["timestamp"],
            "properties": evt["properties"],
        })

    card_events.sort(key=lambda e: e["timestamp"])
    alert_events.sort(key=lambda e: e["timestamp"])

    alert = {
        "alertId": _alert_id("S04", user_num, 1),
        "userId": uid,
        "signal": "S04",
        "details": f"3+ cards linked within 60 minutes",
        "severity": "medium",
        "status": "open",
        "ruleSnapshot": {
            "cardCountThreshold": 3,
            "velocityWindowMinutes": 60,
        },
        "events": alert_events,
        "createdAt": card_events[-1]["timestamp"] + timedelta(minutes=1),
    }

    fraud_sub = {
        "riskLevel": "medium",
        "signalsSeen": ["S04"],
        "alertCount": 1,
        "lastAlertAt": alert["createdAt"],
        "lastAlertSignal": "S04",
        "alerts": [alert],
        "embedding": None,
        "signals": {},
        "lastTopupAt": None,
        "lastTopupAmount": None,
        "lastTopupType": None,
    }

    return fraud_sub, card_events, alert


def _build_s02_user(user_num: int, base_time: datetime) -> tuple[dict, list[dict], dict]:
    """S02: top-up + InstantTransfer payment > RM500 within 30 min."""
    uid = _user_id(user_num)

    topup_amount = random.randint(300, 600)
    payment_amount = random.randint(550, 900)  # InstantTransfer payment > RM500 threshold

    t1 = base_time
    t2 = t1 + timedelta(minutes=random.randint(5, 25))

    evt1_id = _evt_id()
    evt2_id = _evt_id()

    evt1 = _make_event(evt1_id, "auto_topup", uid, t1,
                       {"amount": topup_amount, "source": f"card_ending_{_last4()}", "currency": "MYR"},
                       offset=_next_offset())
    evt2 = _make_event(evt2_id, "InstantTransfer_payment", uid, t2,
                       {"amount": payment_amount, "type": "bank_transfer",
                        "merchant": f"merchant_{random.randint(100,999)}", "currency": "MYR"},
                       offset=_next_offset())

    events = [evt1, evt2]
    alert_events = [
        {"eventId": e["eventId"], "name": e["name"], "timestamp": e["timestamp"], "properties": e["properties"]}
        for e in events
    ]

    alert = {
        "alertId": _alert_id("S02", user_num, 1),
        "userId": uid,
        "signal": "S02",
        "details": f"InstantTransfer payment RM{payment_amount} > RM500 within 30min after top-up",
        "severity": "high",
        "status": "open",
        "ruleSnapshot": {
            "amountThreshold": 500,
            "windowMinutes": 30,
        },
        "events": alert_events,
        "createdAt": t2 + timedelta(minutes=1),
    }

    fraud_sub = {
        "riskLevel": "high",
        "signalsSeen": ["S02"],
        "alertCount": 1,
        "lastAlertAt": alert["createdAt"],
        "lastAlertSignal": "S02",
        "alerts": [alert],
        "embedding": None,
        "signals": {},
        "lastTopupAt": t1,
        "lastTopupAmount": topup_amount,
        "lastTopupType": "auto_topup",
    }

    return fraud_sub, events, alert


def _build_s03_user(user_num: int, base_time: datetime) -> tuple[dict, list[dict], dict]:
    """S03: top-up + 2+ fund_out > RM500 within 30 min."""
    uid = _user_id(user_num)

    topup_amount = random.randint(400, 700)
    fund_out_1 = random.randint(550, 800)  # > RM500 threshold
    fund_out_2 = random.randint(550, 800)  # > RM500 threshold

    t1 = base_time
    t2 = t1 + timedelta(minutes=random.randint(3, 12))
    t3 = t2 + timedelta(minutes=random.randint(3, 15))

    evt1_id = _evt_id()
    evt2_id = _evt_id()
    evt3_id = _evt_id()

    evt1 = _make_event(evt1_id, "auto_topup", uid, t1,
                       {"amount": topup_amount, "source": f"card_ending_{_last4()}", "currency": "MYR"},
                       offset=_next_offset())
    evt2 = _make_event(evt2_id, "fund_out_transfer", uid, t2,
                       {"amount": fund_out_1, "recipient": f"60{random.randint(10,19)}{random.randint(1000000,9999999)}",
                        "currency": "MYR"},
                       offset=_next_offset())
    evt3 = _make_event(evt3_id, "fund_out_transfer", uid, t3,
                       {"amount": fund_out_2, "recipient": f"60{random.randint(10,19)}{random.randint(1000000,9999999)}",
                        "currency": "MYR"},
                       offset=_next_offset())

    events = [evt1, evt2, evt3]
    alert_events = [
        {"eventId": e["eventId"], "name": e["name"], "timestamp": e["timestamp"], "properties": e["properties"]}
        for e in events
    ]

    alert = {
        "alertId": _alert_id("S03", user_num, 1),
        "userId": uid,
        "signal": "S03",
        "details": f"Top-up + 2 fund-out totalling > RM500 within 30min",
        "severity": "high",
        "status": "open",
        "ruleSnapshot": {
            "amountThreshold": 500,
            "countThreshold": 2,
            "windowMinutes": 30,
        },
        "events": alert_events,
        "createdAt": t3 + timedelta(minutes=1),
    }

    fraud_sub = {
        "riskLevel": "high",
        "signalsSeen": ["S03"],
        "alertCount": 1,
        "lastAlertAt": alert["createdAt"],
        "lastAlertSignal": "S03",
        "alerts": [alert],
        "embedding": None,
        "signals": {},
        "lastTopupAt": t1,
        "lastTopupAmount": topup_amount,
        "lastTopupType": "auto_topup",
    }

    return fraud_sub, events, alert


# ── Pre-flagged User Names (handpicked for realism) ─────────────────

PREFLAGGED_NAMES = [
    # 1-5: S01 (critical)
    ("Ahmad bin Mohd Razali", "male"),
    ("Mohd Faizal bin Ibrahim", "male"),
    ("Siti Aisyah binti Hassan", "female"),
    ("Nurul Hidayah binti Yusof", "female"),
    ("Tan Wei Ming", "male"),
    # 6-8: S04 (medium)
    ("Lim Jia Wen", "female"),
    ("Rajesh a/l Krishnan", "male"),
    ("Hafiz bin Osman", "male"),
    # 9-10: S02 (high)
    ("Priya a/p Rajan", "female"),
    ("Wong Kai Wen", "male"),
    # 11-12: S03 (high)
    ("Kavitha a/p Subramaniam", "female"),
    ("Zulkifli bin Sulaiman", "male"),
    # 13-15: Multiple signals
    ("Azman bin Md Noor", "male"),       # S01 + S04
    ("Chan Hui Ling", "female"),          # S01 + S02
    ("Anand a/l Muniandy", "male"),       # S03 + S04
]


def _build_preflagged_user(user_num: int) -> tuple[dict, list[dict], list[dict]]:
    """Build a pre-flagged user profile, its events, and its alerts."""
    name, gender = PREFLAGGED_NAMES[user_num - 1]
    uid = _user_id(user_num)

    # Base time staggered per user so they are not all simultaneous
    base_time = datetime(2026, 3, 9, 8 + (user_num % 4), 10 + user_num * 2, 0)

    all_events = []
    all_alerts = []
    fraud_sub = None

    if 1 <= user_num <= 5:
        # S01 - critical
        fraud_sub, events, alert = _build_s01_user(user_num, base_time)
        all_events.extend(events)
        all_alerts.append(alert)
    elif 6 <= user_num <= 8:
        # S04 - medium
        fraud_sub, events, alert = _build_s04_user(user_num, base_time)
        all_events.extend(events)
        all_alerts.append(alert)
    elif 9 <= user_num <= 10:
        # S02 - high
        fraud_sub, events, alert = _build_s02_user(user_num, base_time)
        all_events.extend(events)
        all_alerts.append(alert)
    elif 11 <= user_num <= 12:
        # S03 - high
        fraud_sub, events, alert = _build_s03_user(user_num, base_time)
        all_events.extend(events)
        all_alerts.append(alert)
    elif user_num == 13:
        # S01 + S04
        fs1, evts1, al1 = _build_s01_user(user_num, base_time)
        fs4, evts4, al4 = _build_s04_user(user_num, base_time + timedelta(hours=2))
        all_events.extend(evts1)
        all_events.extend(evts4)
        all_alerts.extend([al1, al4])
        # Merge fraud sub: highest severity wins; carry S01 signals state + topup tracking
        fraud_sub = {
            "riskLevel": "critical",
            "signalsSeen": ["S01", "S04"],
            "alertCount": 2,
            "lastAlertAt": max(al1["createdAt"], al4["createdAt"]),
            "lastAlertSignal": "S01" if al1["createdAt"] >= al4["createdAt"] else "S04",
            "alerts": [al1, al4],
            "embedding": None,
            "signals": fs1.get("signals", {}),
            "lastTopupAt": fs1.get("lastTopupAt"),
            "lastTopupAmount": fs1.get("lastTopupAmount"),
            "lastTopupType": fs1.get("lastTopupType"),
        }
    elif user_num == 14:
        # S01 + S02
        fs1, evts1, al1 = _build_s01_user(user_num, base_time)
        fs2, evts2, al2 = _build_s02_user(user_num, base_time + timedelta(hours=3))
        all_events.extend(evts1)
        all_events.extend(evts2)
        all_alerts.extend([al1, al2])
        fraud_sub = {
            "riskLevel": "critical",
            "signalsSeen": ["S01", "S02"],
            "alertCount": 2,
            "lastAlertAt": max(al1["createdAt"], al2["createdAt"]),
            "lastAlertSignal": "S01" if al1["createdAt"] >= al2["createdAt"] else "S02",
            "alerts": [al1, al2],
            "embedding": None,
            "signals": fs1.get("signals", {}),
            "lastTopupAt": fs2.get("lastTopupAt") or fs1.get("lastTopupAt"),
            "lastTopupAmount": fs2.get("lastTopupAmount") or fs1.get("lastTopupAmount"),
            "lastTopupType": fs2.get("lastTopupType") or fs1.get("lastTopupType"),
        }
    elif user_num == 15:
        # S03 + S04
        fs3, evts3, al3 = _build_s03_user(user_num, base_time)
        fs4, evts4, al4 = _build_s04_user(user_num, base_time + timedelta(hours=1))
        all_events.extend(evts3)
        all_events.extend(evts4)
        all_alerts.extend([al3, al4])
        fraud_sub = {
            "riskLevel": "high",
            "signalsSeen": ["S03", "S04"],
            "alertCount": 2,
            "lastAlertAt": max(al3["createdAt"], al4["createdAt"]),
            "lastAlertSignal": "S03" if al3["createdAt"] >= al4["createdAt"] else "S04",
            "alerts": [al3, al4],
            "embedding": None,
            "signals": {},
            "lastTopupAt": fs3.get("lastTopupAt"),
            "lastTopupAmount": fs3.get("lastTopupAmount"),
            "lastTopupType": fs3.get("lastTopupType"),
        }

    # Build full user profile
    dob = _random_dob()
    created_at = _random_dt(datetime(2023, 1, 1), datetime(2024, 6, 1))
    total_txn = random.randint(80, 350)
    total_spend = round(random.uniform(2000, 12000), 2)
    monthly_avg = round(total_spend / max(1, (NOW - created_at).days / 30), 2)
    balance = round(random.uniform(100, 3000), 2)

    num_cards = random.randint(1, 3)
    cards = _linked_cards(num_cards)

    user = {
        "userId": uid,
        "fullName": name,
        "dateOfBirth": dob,
        "ic": _ic_from_dob(dob),
        "email": _email_from_name(name, user_num),
        "phone": _phone(),
        "status": "active",
        "kyc": {
            "status": "verified",
            "verifiedAt": _random_dt(datetime(2024, 1, 1), datetime(2025, 6, 1)),
            "method": random.choice(KYC_METHODS),
            "documentType": "MyKad",
            "riskLevel": "low",
        },
        "wallet": {
            "balance": balance,
            "currency": "MYR",
            "tier": random.choice(["standard", "premium"]),
            "dailyLimit": 5000.00,
        },
        "linkedCards": cards,
        "activitySummary": {
            "totalTransactions": total_txn,
            "totalSpend": total_spend,
            "lastTransactionAt": _random_dt(datetime(2026, 3, 5), NOW),
            "favouriteStation": random.choice(STATIONS),
            "monthlyAvgSpend": monthly_avg,
        },
        "screening": {
            "lastScreenedAt": _random_dt(datetime(2026, 2, 1), datetime(2026, 3, 8)),
            "riskFlag": False,
            "matches": [],
        },
        "fraud": fraud_sub,
        "createdAt": created_at,
        "updatedAt": _random_dt(datetime(2026, 3, 5), NOW),
    }

    return user, all_events, all_alerts


# ── Normal User Builder ──────────────────────────────────────────────

def _build_normal_user(user_num: int) -> dict:
    name, gender = _generate_malaysian_name()
    uid = _user_id(user_num)
    dob = _random_dob()
    created_at = _random_dt(datetime(2023, 1, 1), datetime(2025, 12, 1))
    total_txn = random.randint(1, 500)
    total_spend = round(random.uniform(50, 15000), 2)
    monthly_avg = round(total_spend / max(1, (NOW - created_at).days / 30), 2)
    balance = round(random.uniform(10, 5000), 2)
    num_cards = random.randint(0, 3)

    user = {
        "userId": uid,
        "fullName": name,
        "dateOfBirth": dob,
        "ic": _ic_from_dob(dob),
        "email": _email_from_name(name, user_num),
        "phone": _phone(),
        "status": random.choices(["active", "inactive", "suspended"], weights=[90, 8, 2])[0],
        "kyc": {
            "status": random.choices(["verified", "pending", "rejected"], weights=[85, 10, 5])[0],
            "verifiedAt": _random_dt(datetime(2024, 1, 1), datetime(2025, 12, 1)),
            "method": random.choice(KYC_METHODS),
            "documentType": random.choice(KYC_DOC_TYPES),
            "riskLevel": "low",
        },
        "wallet": {
            "balance": balance,
            "currency": "MYR",
            "tier": random.choices(TIERS, weights=[30, 45, 25])[0],
            "dailyLimit": random.choice([1000.00, 3000.00, 5000.00]),
        },
        "linkedCards": _linked_cards(num_cards),
        "activitySummary": {
            "totalTransactions": total_txn,
            "totalSpend": total_spend,
            "lastTransactionAt": _random_dt(datetime(2026, 1, 1), NOW),
            "favouriteStation": random.choice(STATIONS),
            "monthlyAvgSpend": monthly_avg,
        },
        "screening": {
            "lastScreenedAt": _random_dt(datetime(2026, 1, 1), datetime(2026, 3, 8)),
            "riskFlag": False,
            "matches": [],
        },
        "fraud": {
            "riskLevel": "low",
            "signalsSeen": [],
            "alertCount": 0,
            "lastAlertAt": None,
            "lastAlertSignal": None,
            "alerts": [],
            "embedding": None,
            "signals": {},
            "lastTopupAt": None,
            "lastTopupAmount": None,
            "lastTopupType": None,
        },
        "createdAt": created_at,
        "updatedAt": _random_dt(datetime(2026, 2, 1), NOW),
    }

    return user


# ── Normal Events Builder ────────────────────────────────────────────

def _build_normal_events(normal_user_ids: list[str]) -> list[dict]:
    """Build ~150 normal + ~20 suspicious-but-not-triggering events."""
    events = []

    # Pick 55 random normal users for normal events
    sampled_users = random.sample(normal_user_ids, min(55, len(normal_user_ids)))

    # ── ~150 normal events across 55 users ──
    for uid in sampled_users:
        num_events = random.randint(2, 4)
        for _ in range(num_events):
            event_type = random.choices(
                ["fuel_purchase", "auto_topup", "InstantTransfer_payment", "card_linked"],
                weights=[50, 20, 20, 10],
            )[0]

            ts = _random_dt(SEVEN_DAYS_AGO, NOW)
            eid = _evt_id()

            if event_type == "fuel_purchase":
                props = {
                    "amount": round(random.uniform(20, 200), 2),
                    "station": random.choice(STATIONS),
                    "fuelType": random.choice(["RON95", "RON97", "Diesel"]),
                    "litres": round(random.uniform(5, 60), 2),
                    "currency": "MYR",
                }
            elif event_type == "auto_topup":
                # Small top-ups below RM500
                props = {
                    "amount": random.choice([50, 100, 150, 200, 250, 300]),
                    "source": f"card_ending_{_last4()}",
                    "currency": "MYR",
                }
            elif event_type == "InstantTransfer_payment":
                props = {
                    "amount": round(random.uniform(5, 200), 2),
                    "recipient": f"merchant_{random.randint(100, 999)}",
                    "currency": "MYR",
                }
            else:  # card_linked (single card, not suspicious)
                props = {
                    "last4": _last4(),
                    "cardType": random.choice(CARD_TYPES),
                    "bank": random.choice(BANKS),
                }

            events.append(_make_event(eid, event_type, uid, ts, props, offset=_next_offset()))

    # ── ~20 suspicious-but-not-triggering events ──
    suspicious_users = random.sample(normal_user_ids, min(20, len(normal_user_ids)))
    for uid in suspicious_users:
        scenario = random.choice(["large_topup_single", "two_cards_in_hour", "large_payment_only"])
        ts = _random_dt(SEVEN_DAYS_AGO, NOW)
        eid = _evt_id()

        if scenario == "large_topup_single":
            # Single large auto_topup >= RM500 but only 1 (S01 needs 2)
            props = {
                "amount": random.choice([500, 550, 600, 700]),
                "source": f"card_ending_{_last4()}",
                "currency": "MYR",
            }
            events.append(_make_event(eid, "auto_topup", uid, ts, props, offset=_next_offset()))
        elif scenario == "two_cards_in_hour":
            # 2 cards linked in 1 hour (S04 needs 3)
            for i in range(2):
                eid = _evt_id()
                props = {
                    "last4": _last4(),
                    "cardType": random.choice(CARD_TYPES),
                    "bank": random.choice(BANKS),
                }
                events.append(_make_event(eid, "card_linked", uid,
                                          ts + timedelta(minutes=i * 20), props, offset=_next_offset()))
        else:
            # Large InstantTransfer payment but no preceding top-up in window
            props = {
                "amount": round(random.uniform(400, 800), 2),
                "recipient": f"merchant_{random.randint(100, 999)}",
                "currency": "MYR",
            }
            events.append(_make_event(eid, "InstantTransfer_payment", uid, ts, props, offset=_next_offset()))

    return events


# ── Index Creation ───────────────────────────────────────────────────

async def _create_indexes(db) -> None:
    logger.info("Creating indexes...")
    await db["events"].create_index([("user_id", 1), ("name", 1), ("timestamp", -1)])
    await db["events"].create_index("timestamp", expireAfterSeconds=604800)
    await db["fraud_alerts"].create_index([("userId", 1), ("createdAt", -1)])
    await db["fraud_alerts"].create_index([("signal", 1), ("createdAt", -1)])
    await db["user_profiles"].create_index("userId", unique=True)
    await db["user_profiles"].create_index("fraud.riskLevel")
    logger.info("Indexes created.")


# ── Embedding Generation ────────────────────────────────────────────

async def _generate_embeddings(db) -> None:
    """Generate Voyage AI embeddings for all pre-flagged users."""
    logger.info("Generating Voyage AI embeddings for pre-flagged users...")
    cursor = db["user_profiles"].find(
        {"fraud.riskLevel": {"$ne": "low"}, "fraud.embedding": None},
        {"userId": 1, "fraud": 1, "activitySummary": 1, "wallet": 1, "kyc": 1, "linkedCards": 1},
    )

    count = 0
    async for user in cursor:
        text = compose_fraud_profile_text(user)
        embedding = await generate_embedding(text)
        if embedding:
            await db["user_profiles"].update_one(
                {"userId": user["userId"]},
                {"$set": {"fraud.embedding": embedding}},
            )
            count += 1
            logger.info("  Embedded %s (%d dims)", user["userId"], len(embedding))
        else:
            logger.warning("  Failed to embed %s", user["userId"])

    logger.info("Embeddings generated for %d users.", count)


# ── Main Seed Function ──────────────────────────────────────────────

async def seed() -> None:
    random.seed(42)  # Reproducible data

    client = AsyncIOMotorClient(
        MONGO_URI,
        tls=True,
        tlsCertificateKeyFile=TLS_CERT_PATH,
    )
    db = client[DB_NAME]

    # ── Drop existing collections ──
    logger.info("Dropping existing collections...")
    for coll in ["signal_rules", "user_profiles", "events", "fraud_alerts"]:
        await db[coll].drop()

    # ── 1. Seed signal_rules (4 documents) ──
    rules = _build_signal_rules()
    await db["signal_rules"].insert_many(rules)
    logger.info("Inserted %d signal_rules.", len(rules))

    # ── 2. Seed pre-flagged users + their events & alerts ──
    all_users = []
    all_events = []
    all_alerts = []

    for i in range(1, NUM_PREFLAGGED + 1):
        user, events, alerts = _build_preflagged_user(i)
        all_users.append(user)
        all_events.extend(events)
        if isinstance(alerts, list):
            all_alerts.extend(alerts)
        else:
            all_alerts.append(alerts)

    logger.info("Built %d pre-flagged users with %d events and %d alerts.",
                NUM_PREFLAGGED, len(all_events), len(all_alerts))

    # ── 3. Seed normal users (485) ──
    for i in range(NUM_PREFLAGGED + 1, TOTAL_USERS + 1):
        all_users.append(_build_normal_user(i))

    logger.info("Built %d total user profiles.", len(all_users))

    # ── 4. Build normal + suspicious events ──
    normal_user_ids = [_user_id(i) for i in range(NUM_PREFLAGGED + 1, TOTAL_USERS + 1)]
    normal_events = _build_normal_events(normal_user_ids)
    all_events.extend(normal_events)
    logger.info("Built %d total events (fraud-triggering + normal + suspicious).", len(all_events))

    # ── Insert everything ──
    await db["user_profiles"].insert_many(all_users)
    logger.info("Inserted %d user_profiles.", len(all_users))

    await db["events"].insert_many(all_events)
    logger.info("Inserted %d events.", len(all_events))

    await db["fraud_alerts"].insert_many(all_alerts)
    logger.info("Inserted %d fraud_alerts.", len(all_alerts))

    # ── 5. Create indexes ──
    await _create_indexes(db)

    # ── 6. Generate embeddings ──
    await _generate_embeddings(db)

    # ── Summary ──
    for coll_name in ["signal_rules", "user_profiles", "events", "fraud_alerts"]:
        count = await db[coll_name].count_documents({})
        logger.info("  %s: %d documents", coll_name, count)

    flagged = await db["user_profiles"].count_documents({"fraud.riskLevel": {"$ne": "low"}})
    logger.info("  Pre-flagged users: %d", flagged)

    embedded = await db["user_profiles"].count_documents({"fraud.embedding": {"$ne": None}})
    logger.info("  Users with embeddings: %d", embedded)

    print("\nSeeding complete!")
    client.close()


if __name__ == "__main__":
    asyncio.run(seed())

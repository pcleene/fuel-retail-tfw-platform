"""
Seed script for the FuelRetail_screening MongoDB database (UC1 Name Screening).

Run from project root:
    python -m backend.seed.seed_screening

Seeds:
  - user_profiles   (10,000 documents, ~20 pre-flagged)
  - sanctioned_list (55 documents, ~15 designed to match profiles)
  - Indexes on both collections
"""

import asyncio
import logging
import random
from datetime import datetime, timedelta
from hashlib import md5

from motor.motor_asyncio import AsyncIOMotorClient

# ── Logging ──────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────

MONGO_URI = "mongodb+srv://<user>:<password>@<cluster>.mongodb.net/<db>"
TLS_CERT_PATH = "<local-path>"
DB_NAME = "FuelRetail_screening"

NOW = datetime(2026, 3, 9, 12, 0, 0)
TOTAL_USERS = 10_000

# ── Malaysian Name Data ──────────────────────────────────────────────

MALAY_MALE_FIRST = [
    "Ahmad", "Muhammad", "Mohd", "Ismail", "Faizal", "Hafiz", "Azman", "Razak",
    "Zulkifli", "Hakim", "Amir", "Rizal", "Shahrul", "Firdaus", "Khairul",
    "Nizam", "Roslan", "Hamdan", "Aziz", "Kamal", "Saiful", "Syahmi", "Izzat",
    "Danial", "Arif", "Luqman", "Nasir", "Haris", "Fitri", "Amin", "Irfan",
    "Haziq", "Farhan", "Zakaria", "Idris", "Omar", "Ali", "Yusof", "Halim",
    "Redzuan", "Zamri", "Bakar", "Zainal", "Sulaiman", "Imran", "Farid",
    "Azhar", "Nazri", "Rafiq", "Shafiq",
]

MALAY_FEMALE_FIRST = [
    "Nurul", "Siti", "Aisyah", "Fatimah", "Norazlina", "Rahmah", "Zaiton",
    "Aminah", "Haslinda", "Norhayati", "Farah", "Nadia", "Syahirah", "Aini",
    "Hidayah", "Zarina", "Salina", "Roslina", "Mariam", "Suraya", "Aida",
    "Izzati", "Adlina", "Liyana", "Hana", "Noor", "Nur", "Azizah", "Rosnah",
    "Norhaiza", "Zurina", "Safiah", "Latifah", "Khadijah", "Hamidah",
    "Rashidah", "Mazlina", "Rohana", "Halimah", "Sabariah",
]

MALAY_FAMILY = [
    "Abdullah", "Ibrahim", "Hassan", "Yusof", "Osman", "Sulaiman", "Razali",
    "Ismail", "Mat Hussin", "Bakar", "Jaafar", "Kadir", "Hamid", "Rahman",
    "Ahmad", "Mohd Ali", "Hashim", "Salleh", "Awang", "Md Noor", "Zahari",
    "Daud", "Latif", "Wahab", "Nordin", "Ramli", "Samad", "Ghani", "Rahim",
    "Mamat",
]

CHINESE_FAMILY = [
    "Tan", "Lim", "Wong", "Lee", "Chan", "Ng", "Ong", "Goh", "Koh", "Teh",
    "Yeoh", "Cheah", "Chin", "Foo", "Ho", "Yap", "Chong", "Sia", "Low", "Heng",
]

CHINESE_MALE_GIVEN = [
    "Wei Ming", "Jian Hong", "Zhi Wei", "Jun Jie", "Hao Wen", "Yi Xuan",
    "Kai Wen", "Zheng Yang", "Jia Le", "Ren Jie", "Kok Leong", "Wai Kit",
    "Chee Keong", "Seng Huat", "Boon Keat", "Wei Liang", "Chun Kiat",
    "Zi Hao", "Hong Wei", "Teck Heng",
]

CHINESE_FEMALE_GIVEN = [
    "Jia Wen", "Hui Ling", "Xin Yi", "Mei Ling", "Shu Ting", "Pei Shan",
    "Wen Xin", "Jia Yi", "Yi Wen", "Xin Ying", "Siew Lan", "Li Hua",
    "May Chen", "Su Lin", "Chia Yee", "Hui Min", "Ai Ling", "Bee Leng",
    "Mei Yee", "Shu Fang",
]

INDIAN_MALE_FIRST = [
    "Rajesh", "Anand", "Kumar", "Suresh", "Vikram", "Ganesh", "Prakash",
    "Ramesh", "Harish", "Dinesh", "Sathish", "Mohan", "Arvind", "Navin",
    "Ravi", "Muthu", "Bala", "Mani", "Kannan", "Selvam",
]

INDIAN_FEMALE_FIRST = [
    "Priya", "Lakshmi", "Kavitha", "Deepa", "Anitha", "Revathi", "Shalini",
    "Nirmala", "Indra", "Meena", "Vasanthi", "Devi", "Sushila", "Geetha",
    "Kamala", "Pavithra", "Subashini", "Malathi", "Usha", "Renuga",
]

INDIAN_FAMILY = [
    "Krishnan", "Muthu", "Rajan", "Pillai", "Nair", "Subramaniam", "Ramasamy",
    "Muniandy", "Suppiah", "Thuraisingam", "Naidu", "Govindan", "Shanmugam",
    "Veloo", "Arumugam",
]

BANKS = ["RegionalBankB", "CIMB", "Public Bank", "RHB", "Alliance Bank", "AmBank", "Bank Islam", "BSN", "OCBC", "UOB"]
CARD_TYPES = ["visa", "mastercard"]
STATIONS = [
    "EnergyOperator Bangsar", "EnergyOperator Damansara", "EnergyOperator KLCC", "EnergyOperator Subang",
    "EnergyOperator Shah Alam", "EnergyOperator Petaling Jaya", "EnergyOperator Ampang",
    "EnergyOperator Cheras", "EnergyOperator Puchong", "EnergyOperator Cyberjaya",
    "EnergyOperator Putrajaya", "EnergyOperator Johor Bahru", "EnergyOperator Penang",
    "EnergyOperator Ipoh", "EnergyOperator Kota Kinabalu", "EnergyOperator Kuching",
    "EnergyOperator Melaka", "EnergyOperator Seremban", "EnergyOperator Kuantan",
    "EnergyOperator Alor Setar",
]


# ── Name generators ──────────────────────────────────────────────────

def _gen_malay_name(gender: str) -> str:
    """Generate a Malay name with bin/binti connector."""
    first_pool = MALAY_MALE_FIRST if gender == "M" else MALAY_FEMALE_FIRST
    first = random.choice(first_pool)
    family = random.choice(MALAY_FAMILY)
    connector = "bin" if gender == "M" else "binti"

    # Randomly use Muhammad/Mohd/Muhd/Md variations
    if first == "Muhammad":
        first = random.choice(["Muhammad", "Mohd", "Muhd", "Md"])
    if first == "Siti":
        first = random.choice(["Siti", "St"])
    if first == "Noor":
        first = random.choice(["Noor", "Nur", "Nor"])
    if first == "Abdul":
        first = random.choice(["Abdul", "Abd"])

    return f"{first} {connector} {family}"


def _gen_chinese_name(gender: str) -> str:
    """Generate a Chinese Malaysian name. Sometimes reversed order."""
    family = random.choice(CHINESE_FAMILY)
    given_pool = CHINESE_MALE_GIVEN if gender == "M" else CHINESE_FEMALE_GIVEN
    given = random.choice(given_pool)
    # 20% chance of reversed order
    if random.random() < 0.2:
        return f"{given} {family}"
    return f"{family} {given}"


def _gen_indian_name(gender: str) -> str:
    """Generate an Indian Malaysian name with a/l or a/p connector."""
    first_pool = INDIAN_MALE_FIRST if gender == "M" else INDIAN_FEMALE_FIRST
    first = random.choice(first_pool)
    family = random.choice(INDIAN_FAMILY)
    connector = "a/l" if gender == "M" else "a/p"
    return f"{first} {connector} {family}"


def _gen_other_name(gender: str) -> str:
    """Generate a miscellaneous name."""
    first_names = (
        ["John", "James", "David", "Michael", "Robert", "William", "Daniel"]
        if gender == "M"
        else ["Sarah", "Emma", "Hannah", "Rachel", "Grace", "Emily", "Sophia"]
    )
    surnames = ["Smith", "Williams", "Brown", "Wilson", "Taylor", "Anderson", "Thomas"]
    return f"{random.choice(first_names)} {random.choice(surnames)}"


def _generate_name() -> tuple[str, str]:
    """Generate a name based on ethnic distribution. Returns (fullName, ethnicity)."""
    r = random.random()
    gender = random.choice(["M", "F"])
    if r < 0.60:
        return _gen_malay_name(gender), "malay"
    elif r < 0.80:
        return _gen_chinese_name(gender), "chinese"
    elif r < 0.95:
        return _gen_indian_name(gender), "indian"
    else:
        return _gen_other_name(gender), "other"


def _gen_ic(dob: datetime) -> str:
    """Generate a Malaysian IC number from DOB."""
    yy = dob.strftime("%y")
    mm = dob.strftime("%m")
    dd = dob.strftime("%d")
    state = random.choice(["01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12", "13", "14"])
    seq = f"{random.randint(1000, 9999)}"
    return f"{yy}{mm}{dd}-{state}-{seq}"


def _gen_email(name: str, idx: int) -> str:
    """Generate an email from a name."""
    parts = name.lower().replace(" bin ", " ").replace(" binti ", " ").replace(" a/l ", " ").replace(" a/p ", " ")
    tokens = parts.split()
    if len(tokens) >= 2:
        base = f"{tokens[0]}.{tokens[-1]}"
    else:
        base = tokens[0]
    base = base.replace("/", "").replace(" ", "")
    domains = ["gmail.com", "yahoo.com", "hotmail.com", "outlook.com"]
    suffix = f"{idx % 100}" if idx % 3 == 0 else ""
    return f"{base}{suffix}@{random.choice(domains)}"


def _gen_phone() -> str:
    """Generate a Malaysian mobile number."""
    prefix = random.choice(["10", "11", "12", "13", "14", "16", "17", "18", "19"])
    num = f"{random.randint(1000000, 9999999)}"
    return f"+60{prefix}{num}"


# ── Profile generator ────────────────────────────────────────────────

def _generate_profile(idx: int) -> dict:
    """Generate a single user profile document."""
    full_name, ethnicity = _generate_name()
    dob = datetime(
        random.randint(1960, 2005),
        random.randint(1, 12),
        random.randint(1, 28),
    )
    created = datetime(
        random.randint(2020, 2025),
        random.randint(1, 12),
        random.randint(1, 28),
        random.randint(0, 23),
        random.randint(0, 59),
    )
    updated = created + timedelta(days=random.randint(0, 365))
    if updated > NOW:
        updated = NOW

    # Status distribution: 85% active, 8% inactive, 5% suspended, 2% closed
    status_r = random.random()
    if status_r < 0.85:
        status = "active"
    elif status_r < 0.93:
        status = "inactive"
    elif status_r < 0.98:
        status = "suspended"
    else:
        status = "closed"

    # KYC distribution: 90% verified, 5% pending, 3% failed, 2% expired
    kyc_r = random.random()
    if kyc_r < 0.90:
        kyc_status = "verified"
    elif kyc_r < 0.95:
        kyc_status = "pending"
    elif kyc_r < 0.98:
        kyc_status = "failed"
    else:
        kyc_status = "expired"

    risk_levels = ["low", "low", "low", "low", "medium", "medium", "high"]
    tiers = ["basic", "basic", "basic", "standard", "standard", "premium"]

    # Wallet balance skewed low
    balance = round(random.expovariate(1 / 500), 2)
    if balance > 10000:
        balance = round(random.uniform(0, 10000), 2)

    # Linked cards: 0-4, most have 1-2
    num_cards = random.choices([0, 1, 2, 3, 4], weights=[10, 35, 35, 15, 5])[0]
    linked_cards = []
    for ci in range(num_cards):
        card_linked = created + timedelta(days=random.randint(0, 365))
        if card_linked > NOW:
            card_linked = NOW
        linked_cards.append({
            "last4": f"{random.randint(1000, 9999)}",
            "type": random.choice(CARD_TYPES),
            "bank": random.choice(BANKS),
            "linkedAt": card_linked,
            "isDefault": ci == 0,
        })

    total_txns = random.randint(0, 500)
    total_spend = round(random.uniform(0, 50000), 2) if total_txns > 0 else 0.0
    monthly_avg = round(total_spend / max(1, random.randint(1, 24)), 2)
    last_txn = NOW - timedelta(days=random.randint(0, 90)) if total_txns > 0 else None

    return {
        "userId": f"USR-{idx:05d}",
        "fullName": full_name,
        "dateOfBirth": dob,
        "ic": _gen_ic(dob),
        "email": _gen_email(full_name, idx),
        "phone": _gen_phone(),
        "status": status,
        "kyc": {
            "status": kyc_status,
            "verifiedAt": created + timedelta(days=random.randint(1, 30)) if kyc_status == "verified" else None,
            "method": random.choice(["eKYC", "manual", "video"]),
            "documentType": random.choice(["MyKad", "Passport", "iKad"]),
            "riskLevel": random.choice(risk_levels),
        },
        "wallet": {
            "balance": balance,
            "currency": "MYR",
            "tier": random.choice(tiers),
            "dailyLimit": random.choice([1000.0, 2000.0, 5000.0, 10000.0]),
        },
        "linkedCards": linked_cards,
        "activitySummary": {
            "totalTransactions": total_txns,
            "totalSpend": total_spend,
            "lastTransactionAt": last_txn,
            "favouriteStation": random.choice(STATIONS),
            "monthlyAvgSpend": monthly_avg,
        },
        "screening": {
            "lastScreenedAt": None,
            "riskFlag": False,
            "matches": [],
        },
        "createdAt": created,
        "updatedAt": updated,
    }


# ── Profiles that will be found by sanctioned entries ─────────────────
# These are planted at specific indices so the demo reliably finds matches

PLANTED_PROFILES = [
    # Will match sanctioned "Ismail Ibrahim"
    {"idx": 100, "fullName": "Ismail bin Ibrahim"},
    # Will match sanctioned "Muhammad Nasir" (via abbreviation Mohd)
    {"idx": 101, "fullName": "Mohd Nasir bin Razali"},
    # Will match sanctioned "Ravi Ganesan" (via a/l connector)
    {"idx": 102, "fullName": "Ravi a/l Ganesan"},
    # Will match sanctioned "Tan Wei Kiat" (reversed order)
    {"idx": 103, "fullName": "Wei Kiat Tan"},
    # Will match sanctioned "Abdul Rahman" (via abbreviation Abd)
    {"idx": 104, "fullName": "Abd Rahman bin Hassan"},
    # Will match sanctioned "Siti Aminah" (via abbreviation St)
    {"idx": 105, "fullName": "St Aminah binti Yusof"},
    # Will match sanctioned "Noor Aisyah" (via Nur variant)
    {"idx": 106, "fullName": "Nur Aisyah binti Abdullah"},
    # Will match sanctioned "Ahmad Razali"
    {"idx": 107, "fullName": "Ahmad bin Mohd Razali"},
    # Will match sanctioned "Kumar Rajendran" (via a/l connector)
    {"idx": 108, "fullName": "Kumar a/l Rajendran"},
    # Will match sanctioned "Lee Chong Wei" (reversed)
    {"idx": 109, "fullName": "Chong Wei Lee"},
    # Will match sanctioned "Mohd Faizal" (direct)
    {"idx": 110, "fullName": "Mohd Faizal bin Ismail"},
    # Will match sanctioned "Nor Azizah" (Noor variant)
    {"idx": 111, "fullName": "Noor Azizah binti Osman"},
    # Will match sanctioned "Suresh Pillai" (via a/l connector)
    {"idx": 112, "fullName": "Suresh a/l Pillai"},
    # Will match sanctioned "Wong Mei Ling" (direct)
    {"idx": 113, "fullName": "Wong Mei Ling"},
    # Will match sanctioned "Muhd Hafiz" (Muhammad variant)
    {"idx": 114, "fullName": "Muhammad Hafiz bin Kadir"},
    # Will match sanctioned "Fatimah Zahra"
    {"idx": 115, "fullName": "Fatimah Zahra binti Ibrahim"},
    # Will match sanctioned "Priya Subramaniam"
    {"idx": 116, "fullName": "Priya a/p Subramaniam"},
    # Will match sanctioned "Ng Kok Leong"
    {"idx": 117, "fullName": "Ng Kok Leong"},
    # Will match sanctioned "Zulkifli Nordin"
    {"idx": 118, "fullName": "Zulkifli bin Nordin"},
    # Will match sanctioned "Lim Siew Lan"
    {"idx": 119, "fullName": "Lim Siew Lan"},
]

# ── Sanctioned list ──────────────────────────────────────────────────

SANCTIONED_ENTRIES = [
    # ── Entries designed to match profiles (~20) ──
    {
        "fullName": "Ismail Ibrahim",
        "aliases": ["Ismail bin Ibrahim", "Ismail B Ibrahim"],
        "dateOfBirth": datetime(1985, 3, 15),
        "country": "MY",
        "source": "OFAC",
        "category": "Financial fraud",
        "details": {"reason": "Money laundering through digital wallet services", "referenceId": "OFAC-2026-MY-0042"},
    },
    {
        "fullName": "Muhammad Nasir",
        "aliases": ["Mohd Nasir", "Muhd Nasir", "Md Nasir"],
        "dateOfBirth": datetime(1990, 7, 22),
        "country": "MY",
        "source": "Bank Negara Malaysia",
        "category": "Money laundering",
        "details": {"reason": "Suspicious digital wallet transfers", "referenceId": "BNM-2026-0118"},
    },
    {
        "fullName": "Ravi Ganesan",
        "aliases": ["Ravi a/l Ganesan"],
        "dateOfBirth": datetime(1978, 11, 5),
        "country": "MY",
        "source": "OFAC",
        "category": "Terrorism financing",
        "details": {"reason": "Linked to terror financing network", "referenceId": "OFAC-2026-MY-0056"},
    },
    {
        "fullName": "Tan Wei Kiat",
        "aliases": ["Wei Kiat Tan", "Tan WK"],
        "dateOfBirth": datetime(1992, 4, 18),
        "country": "MY",
        "source": "EU Sanctions",
        "category": "Sanctions evasion",
        "details": {"reason": "Circumventing EU financial sanctions", "referenceId": "EU-2026-SEA-0089"},
    },
    {
        "fullName": "Abdul Rahman",
        "aliases": ["Abd Rahman", "A Rahman"],
        "dateOfBirth": datetime(1975, 9, 30),
        "country": "MY",
        "source": "UN Security Council",
        "category": "Terrorism financing",
        "details": {"reason": "UN designated individual", "referenceId": "UNSC-2026-0234"},
    },
    {
        "fullName": "Siti Aminah",
        "aliases": ["St Aminah", "Siti Aminah Abdullah"],
        "dateOfBirth": datetime(1988, 1, 12),
        "country": "MY",
        "source": "Bank Negara Malaysia",
        "category": "Financial fraud",
        "details": {"reason": "E-wallet fraud ring participant", "referenceId": "BNM-2026-0203"},
    },
    {
        "fullName": "Noor Aisyah",
        "aliases": ["Nur Aisyah", "Nor Aisyah"],
        "dateOfBirth": datetime(1995, 6, 8),
        "country": "MY",
        "source": "FATF",
        "category": "Money laundering",
        "details": {"reason": "Flagged in FATF grey list review", "referenceId": "FATF-2026-MY-0067"},
    },
    {
        "fullName": "Ahmad Razali",
        "aliases": ["Ahmad Mohd Razali", "Ahmad bin Razali"],
        "dateOfBirth": datetime(1990, 5, 12),
        "country": "MY",
        "source": "OFAC",
        "category": "Corruption",
        "details": {"reason": "Corruption and illicit fund transfers", "referenceId": "OFAC-2026-MY-0071"},
    },
    {
        "fullName": "Kumar Rajendran",
        "aliases": ["Kumar a/l Rajendran", "K Rajendran"],
        "dateOfBirth": datetime(1982, 8, 25),
        "country": "MY",
        "source": "AUSTRAC",
        "category": "Money laundering",
        "details": {"reason": "International money laundering network", "referenceId": "AUSTRAC-2026-0145"},
    },
    {
        "fullName": "Lee Chong Wei",
        "aliases": ["Chong Wei Lee", "CW Lee"],
        "dateOfBirth": datetime(1983, 10, 21),
        "country": "MY",
        "source": "EU Sanctions",
        "category": "Sanctions evasion",
        "details": {"reason": "Facilitating sanctioned trade", "referenceId": "EU-2026-SEA-0102"},
    },
    {
        "fullName": "Mohd Faizal",
        "aliases": ["Muhammad Faizal", "Muhd Faizal"],
        "dateOfBirth": datetime(1987, 12, 3),
        "country": "MY",
        "source": "Bank Negara Malaysia",
        "category": "Financial fraud",
        "details": {"reason": "Fraudulent card-linked e-wallet scheme", "referenceId": "BNM-2026-0221"},
    },
    {
        "fullName": "Nor Azizah",
        "aliases": ["Noor Azizah", "Nur Azizah", "Azizah Osman"],
        "dateOfBirth": datetime(1991, 2, 14),
        "country": "MY",
        "source": "FATF",
        "category": "Money laundering",
        "details": {"reason": "Cross-border money mule activity", "referenceId": "FATF-2026-MY-0078"},
    },
    {
        "fullName": "Suresh Pillai",
        "aliases": ["Suresh a/l Pillai", "S Pillai"],
        "dateOfBirth": datetime(1980, 5, 19),
        "country": "MY",
        "source": "Interpol",
        "category": "Financial fraud",
        "details": {"reason": "International fraud warrant", "referenceId": "INTERPOL-2026-0891"},
    },
    {
        "fullName": "Wong Mei Ling",
        "aliases": ["Mei Ling Wong", "ML Wong"],
        "dateOfBirth": datetime(1993, 3, 27),
        "country": "MY",
        "source": "OFAC",
        "category": "Sanctions evasion",
        "details": {"reason": "Shell company facilitator", "referenceId": "OFAC-2026-MY-0083"},
    },
    {
        "fullName": "Muhd Hafiz",
        "aliases": ["Muhammad Hafiz", "Mohd Hafiz", "Md Hafiz"],
        "dateOfBirth": datetime(1996, 7, 11),
        "country": "MY",
        "source": "Bank Negara Malaysia",
        "category": "Money laundering",
        "details": {"reason": "Structured deposits to avoid reporting", "referenceId": "BNM-2026-0244"},
    },
    {
        "fullName": "Fatimah Zahra",
        "aliases": ["Fatimah binti Zahra", "Fatimah Z"],
        "dateOfBirth": datetime(1989, 4, 5),
        "country": "MY",
        "source": "UN Security Council",
        "category": "Terrorism financing",
        "details": {"reason": "Linked to designated terror entity", "referenceId": "UNSC-2026-0256"},
    },
    {
        "fullName": "Priya Subramaniam",
        "aliases": ["Priya a/p Subramaniam", "P Subramaniam"],
        "dateOfBirth": datetime(1994, 9, 16),
        "country": "MY",
        "source": "AUSTRAC",
        "category": "Financial fraud",
        "details": {"reason": "Cross-border fraud scheme", "referenceId": "AUSTRAC-2026-0167"},
    },
    {
        "fullName": "Ng Kok Leong",
        "aliases": ["Kok Leong Ng", "KL Ng"],
        "dateOfBirth": datetime(1986, 11, 28),
        "country": "MY",
        "source": "EU Sanctions",
        "category": "Corruption",
        "details": {"reason": "Corrupt procurement facilitator", "referenceId": "EU-2026-SEA-0115"},
    },
    {
        "fullName": "Zulkifli Nordin",
        "aliases": ["Zulkifli bin Nordin", "Z Nordin"],
        "dateOfBirth": datetime(1979, 6, 2),
        "country": "MY",
        "source": "OFAC",
        "category": "Money laundering",
        "details": {"reason": "Hawala network operator", "referenceId": "OFAC-2026-MY-0095"},
    },
    {
        "fullName": "Lim Siew Lan",
        "aliases": ["Siew Lan Lim", "SL Lim"],
        "dateOfBirth": datetime(1984, 8, 14),
        "country": "MY",
        "source": "Bank Negara Malaysia",
        "category": "Financial fraud",
        "details": {"reason": "Unauthorized fund transfer operations", "referenceId": "BNM-2026-0261"},
    },
    # ── International entries with no match (~35) ──
    {
        "fullName": "Boris Petrov",
        "aliases": ["Boris Andreevich Petrov"],
        "dateOfBirth": datetime(1970, 3, 12),
        "country": "RU",
        "source": "OFAC",
        "category": "Sanctions evasion",
        "details": {"reason": "Russian oligarch sanctions evasion", "referenceId": "OFAC-2026-RU-0312"},
    },
    {
        "fullName": "Yuki Tanaka",
        "aliases": ["Tanaka Yuki"],
        "dateOfBirth": datetime(1985, 9, 5),
        "country": "JP",
        "source": "UN Security Council",
        "category": "Money laundering",
        "details": {"reason": "Designated under UNSCR 1718", "referenceId": "UNSC-2026-0189"},
    },
    {
        "fullName": "Hans Mueller",
        "aliases": ["Hans-Peter Mueller", "HP Mueller"],
        "dateOfBirth": datetime(1968, 5, 22),
        "country": "DE",
        "source": "EU Sanctions",
        "category": "Sanctions evasion",
        "details": {"reason": "Dual-use technology export violations", "referenceId": "EU-2026-DE-0045"},
    },
    {
        "fullName": "Chen Wei",
        "aliases": ["Wei Chen", "Chen W"],
        "dateOfBirth": datetime(1991, 11, 30),
        "country": "CN",
        "source": "OFAC",
        "category": "Terrorism financing",
        "details": {"reason": "WMD proliferation financing", "referenceId": "OFAC-2026-CN-0178"},
    },
    {
        "fullName": "Dmitry Volkov",
        "aliases": ["Dmitri Volkov", "D Volkov"],
        "dateOfBirth": datetime(1973, 7, 8),
        "country": "RU",
        "source": "EU Sanctions",
        "category": "Corruption",
        "details": {"reason": "State-linked corruption", "referenceId": "EU-2026-RU-0067"},
    },
    {
        "fullName": "Fatima Al-Hassan",
        "aliases": ["Fatima Hassan", "F Al-Hassan"],
        "dateOfBirth": datetime(1990, 2, 15),
        "country": "SY",
        "source": "UN Security Council",
        "category": "Terrorism financing",
        "details": {"reason": "ISIL financing network", "referenceId": "UNSC-2026-0301"},
    },
    {
        "fullName": "Sergei Kozlov",
        "aliases": ["Sergey Kozlov"],
        "dateOfBirth": datetime(1965, 12, 1),
        "country": "RU",
        "source": "OFAC",
        "category": "Sanctions evasion",
        "details": {"reason": "Energy sector sanctions circumvention", "referenceId": "OFAC-2026-RU-0421"},
    },
    {
        "fullName": "Kim Sung-ho",
        "aliases": ["Kim Sungho", "Sung-ho Kim"],
        "dateOfBirth": datetime(1982, 4, 18),
        "country": "KP",
        "source": "UN Security Council",
        "category": "Sanctions evasion",
        "details": {"reason": "DPRK weapons program financing", "referenceId": "UNSC-2026-0345"},
    },
    {
        "fullName": "Ali Rezaei",
        "aliases": ["Ali R", "A Rezaei"],
        "dateOfBirth": datetime(1977, 8, 22),
        "country": "IR",
        "source": "OFAC",
        "category": "Terrorism financing",
        "details": {"reason": "IRGC-linked entity", "referenceId": "OFAC-2026-IR-0234"},
    },
    {
        "fullName": "Marco Rossi",
        "aliases": ["M Rossi"],
        "dateOfBirth": datetime(1988, 6, 10),
        "country": "IT",
        "source": "EU Sanctions",
        "category": "Financial fraud",
        "details": {"reason": "Mafia-linked financial fraud", "referenceId": "EU-2026-IT-0089"},
    },
    {
        "fullName": "Vladimir Sorokin",
        "aliases": ["V Sorokin", "Vlad Sorokin"],
        "dateOfBirth": datetime(1971, 1, 25),
        "country": "RU",
        "source": "OFAC",
        "category": "Corruption",
        "details": {"reason": "Government corruption facilitator", "referenceId": "OFAC-2026-RU-0456"},
    },
    {
        "fullName": "Ahmed Al-Bakri",
        "aliases": ["Ahmad Al-Bakri", "A Bakri"],
        "dateOfBirth": datetime(1983, 10, 5),
        "country": "YE",
        "source": "UN Security Council",
        "category": "Terrorism financing",
        "details": {"reason": "Houthi financing network", "referenceId": "UNSC-2026-0378"},
    },
    {
        "fullName": "Liu Xiaoming",
        "aliases": ["Xiaoming Liu"],
        "dateOfBirth": datetime(1979, 3, 20),
        "country": "CN",
        "source": "OFAC",
        "category": "Sanctions evasion",
        "details": {"reason": "Chip technology export violations", "referenceId": "OFAC-2026-CN-0201"},
    },
    {
        "fullName": "Olga Kuznetsova",
        "aliases": ["O Kuznetsova"],
        "dateOfBirth": datetime(1986, 7, 14),
        "country": "RU",
        "source": "EU Sanctions",
        "category": "Sanctions evasion",
        "details": {"reason": "Luxury goods sanctions circumvention", "referenceId": "EU-2026-RU-0098"},
    },
    {
        "fullName": "Hassan Abdullahi",
        "aliases": ["H Abdullahi"],
        "dateOfBirth": datetime(1981, 5, 3),
        "country": "SO",
        "source": "UN Security Council",
        "category": "Terrorism financing",
        "details": {"reason": "Al-Shabaab financing", "referenceId": "UNSC-2026-0401"},
    },
    {
        "fullName": "Park Jae-sung",
        "aliases": ["Jae-sung Park", "Park JS"],
        "dateOfBirth": datetime(1990, 9, 28),
        "country": "KP",
        "source": "OFAC",
        "category": "Sanctions evasion",
        "details": {"reason": "DPRK front company operator", "referenceId": "OFAC-2026-KP-0134"},
    },
    {
        "fullName": "Jean-Claude Mbeki",
        "aliases": ["JC Mbeki"],
        "dateOfBirth": datetime(1975, 11, 12),
        "country": "CD",
        "source": "UN Security Council",
        "category": "Corruption",
        "details": {"reason": "Armed group financing in DRC", "referenceId": "UNSC-2026-0423"},
    },
    {
        "fullName": "Nikolai Federov",
        "aliases": ["N Federov", "Nikolay Federov"],
        "dateOfBirth": datetime(1969, 2, 8),
        "country": "RU",
        "source": "OFAC",
        "category": "Sanctions evasion",
        "details": {"reason": "Defense sector sanctions evasion", "referenceId": "OFAC-2026-RU-0489"},
    },
    {
        "fullName": "Samir Haddad",
        "aliases": ["S Haddad"],
        "dateOfBirth": datetime(1984, 4, 16),
        "country": "LB",
        "source": "OFAC",
        "category": "Terrorism financing",
        "details": {"reason": "Hezbollah financial network", "referenceId": "OFAC-2026-LB-0156"},
    },
    {
        "fullName": "Zhang Yifei",
        "aliases": ["Yifei Zhang"],
        "dateOfBirth": datetime(1993, 8, 7),
        "country": "CN",
        "source": "OFAC",
        "category": "Sanctions evasion",
        "details": {"reason": "Military-industrial complex financing", "referenceId": "OFAC-2026-CN-0223"},
    },
    {
        "fullName": "Carlos Mendoza",
        "aliases": ["C Mendoza"],
        "dateOfBirth": datetime(1976, 6, 30),
        "country": "VE",
        "source": "OFAC",
        "category": "Corruption",
        "details": {"reason": "Kleptocracy and state asset theft", "referenceId": "OFAC-2026-VE-0078"},
    },
    {
        "fullName": "Andrei Popov",
        "aliases": ["A Popov", "Andrey Popov"],
        "dateOfBirth": datetime(1972, 10, 19),
        "country": "RU",
        "source": "EU Sanctions",
        "category": "Corruption",
        "details": {"reason": "State media disinformation financing", "referenceId": "EU-2026-RU-0112"},
    },
    {
        "fullName": "Bakr Al-Saud",
        "aliases": ["B Al-Saud"],
        "dateOfBirth": datetime(1987, 1, 22),
        "country": "SA",
        "source": "FATF",
        "category": "Money laundering",
        "details": {"reason": "Trade-based money laundering", "referenceId": "FATF-2026-SA-0034"},
    },
    {
        "fullName": "Mikhail Orlov",
        "aliases": ["M Orlov"],
        "dateOfBirth": datetime(1966, 12, 5),
        "country": "RU",
        "source": "OFAC",
        "category": "Sanctions evasion",
        "details": {"reason": "Oligarch asset concealment", "referenceId": "OFAC-2026-RU-0501"},
    },
    {
        "fullName": "Nguyen Van Thanh",
        "aliases": ["Van Thanh Nguyen"],
        "dateOfBirth": datetime(1989, 3, 14),
        "country": "VN",
        "source": "Interpol",
        "category": "Financial fraud",
        "details": {"reason": "International wire fraud", "referenceId": "INTERPOL-2026-0923"},
    },
    {
        "fullName": "Tatiana Ivanova",
        "aliases": ["T Ivanova"],
        "dateOfBirth": datetime(1980, 7, 26),
        "country": "RU",
        "source": "EU Sanctions",
        "category": "Sanctions evasion",
        "details": {"reason": "Crypto-based sanctions circumvention", "referenceId": "EU-2026-RU-0134"},
    },
    {
        "fullName": "Omar Suleiman",
        "aliases": ["O Suleiman"],
        "dateOfBirth": datetime(1974, 5, 11),
        "country": "EG",
        "source": "OFAC",
        "category": "Corruption",
        "details": {"reason": "Misappropriation of state funds", "referenceId": "OFAC-2026-EG-0045"},
    },
    {
        "fullName": "Li Jianming",
        "aliases": ["Jianming Li"],
        "dateOfBirth": datetime(1981, 9, 3),
        "country": "CN",
        "source": "OFAC",
        "category": "Sanctions evasion",
        "details": {"reason": "North Korea trade facilitation", "referenceId": "OFAC-2026-CN-0245"},
    },
    {
        "fullName": "Aleksei Morozov",
        "aliases": ["A Morozov", "Alexei Morozov"],
        "dateOfBirth": datetime(1978, 11, 17),
        "country": "RU",
        "source": "OFAC",
        "category": "Sanctions evasion",
        "details": {"reason": "Shipment rerouting to evade sanctions", "referenceId": "OFAC-2026-RU-0523"},
    },
    {
        "fullName": "Abdul Karim Patel",
        "aliases": ["AK Patel"],
        "dateOfBirth": datetime(1985, 2, 28),
        "country": "PK",
        "source": "FATF",
        "category": "Terrorism financing",
        "details": {"reason": "Terror financing via informal channels", "referenceId": "FATF-2026-PK-0056"},
    },
    {
        "fullName": "Kwame Asante",
        "aliases": ["K Asante"],
        "dateOfBirth": datetime(1983, 6, 20),
        "country": "GH",
        "source": "Interpol",
        "category": "Financial fraud",
        "details": {"reason": "West African fraud syndicate", "referenceId": "INTERPOL-2026-0945"},
    },
    {
        "fullName": "Elena Vasiliev",
        "aliases": ["E Vasiliev"],
        "dateOfBirth": datetime(1992, 4, 9),
        "country": "RU",
        "source": "EU Sanctions",
        "category": "Corruption",
        "details": {"reason": "Russian state bank money flows", "referenceId": "EU-2026-RU-0156"},
    },
    {
        "fullName": "Ricardo Silva",
        "aliases": ["R Silva"],
        "dateOfBirth": datetime(1977, 8, 15),
        "country": "BR",
        "source": "OFAC",
        "category": "Money laundering",
        "details": {"reason": "Narcotics-linked money laundering", "referenceId": "OFAC-2026-BR-0034"},
    },
    {
        "fullName": "Youssef Ben Ali",
        "aliases": ["Y Ben Ali"],
        "dateOfBirth": datetime(1986, 10, 2),
        "country": "TN",
        "source": "FATF",
        "category": "Money laundering",
        "details": {"reason": "Cross-Mediterranean money laundering", "referenceId": "FATF-2026-TN-0023"},
    },
    {
        "fullName": "Artur Grigoryan",
        "aliases": ["A Grigoryan"],
        "dateOfBirth": datetime(1970, 1, 30),
        "country": "AM",
        "source": "OFAC",
        "category": "Sanctions evasion",
        "details": {"reason": "Sanctions evasion intermediary", "referenceId": "OFAC-2026-AM-0012"},
    },
]


# ── Pre-flag ~20 profiles for demo ───────────────────────────────────

def _apply_preflag(profiles: list[dict]) -> None:
    """Pre-flag ~20 profiles with screening match data so the dashboard has data on load."""
    flagged_sources = [
        ("Ismail Ibrahim", "OFAC", "Ismail Ibrahim", "primary"),
        ("Muhammad Nasir", "Bank Negara Malaysia", "Mohd Nasir", "alias"),
        ("Ravi Ganesan", "OFAC", "Ravi a/l Ganesan", "alias"),
        ("Tan Wei Kiat", "EU Sanctions", "Wei Kiat Tan", "alias"),
        ("Abdul Rahman", "UN Security Council", "Abd Rahman", "alias"),
        ("Siti Aminah", "Bank Negara Malaysia", "St Aminah", "alias"),
        ("Noor Aisyah", "FATF", "Nur Aisyah", "alias"),
        ("Ahmad Razali", "OFAC", "Ahmad Mohd Razali", "alias"),
        ("Kumar Rajendran", "AUSTRAC", "Kumar a/l Rajendran", "alias"),
        ("Lee Chong Wei", "EU Sanctions", "Chong Wei Lee", "alias"),
        ("Mohd Faizal", "Bank Negara Malaysia", "Muhammad Faizal", "alias"),
        ("Nor Azizah", "FATF", "Noor Azizah", "alias"),
        ("Suresh Pillai", "Interpol", "Suresh a/l Pillai", "alias"),
        ("Wong Mei Ling", "OFAC", "Mei Ling Wong", "alias"),
        ("Muhd Hafiz", "Bank Negara Malaysia", "Muhammad Hafiz", "alias"),
        ("Fatimah Zahra", "UN Security Council", "Fatimah binti Zahra", "alias"),
        ("Priya Subramaniam", "AUSTRAC", "Priya a/p Subramaniam", "alias"),
        ("Ng Kok Leong", "EU Sanctions", "Kok Leong Ng", "alias"),
        ("Zulkifli Nordin", "OFAC", "Zulkifli bin Nordin", "alias"),
        ("Lim Siew Lan", "Bank Negara Malaysia", "Siew Lan Lim", "alias"),
    ]

    for i, (sanctioned_name, source, matched_against, match_type) in enumerate(flagged_sources):
        profile_idx = 100 + i
        if profile_idx < len(profiles):
            profiles[profile_idx]["screening"] = {
                "lastScreenedAt": datetime(2026, 3, 1),
                "riskFlag": True,
                "matches": [
                    {
                        "sanctionedName": sanctioned_name,
                        "source": source,
                        "score": round(random.uniform(3.0, 12.0), 2),
                        "matchedAgainst": matched_against,
                        "matchType": match_type,
                        "detectedAt": datetime(2026, 3, 1),
                    }
                ],
            }


# ── Main seed logic ──────────────────────────────────────────────────

async def seed():
    logger.info("Connecting to MongoDB Atlas...")
    client = AsyncIOMotorClient(
        MONGO_URI, tls=True, tlsCertificateKeyFile=TLS_CERT_PATH
    )
    await client.admin.command("ping")
    logger.info("Connected.")

    db = client[DB_NAME]

    # Drop existing collections
    logger.info("Dropping existing collections...")
    await db["user_profiles"].drop()
    await db["sanctioned_list"].drop()

    # ── Generate user profiles ────────────────────────────────────
    logger.info(f"Generating {TOTAL_USERS} user profiles...")
    profiles = []
    planted_idx_map = {p["idx"]: p["fullName"] for p in PLANTED_PROFILES}

    for i in range(TOTAL_USERS):
        profile = _generate_profile(i)
        # Override name for planted profiles
        if i in planted_idx_map:
            profile["fullName"] = planted_idx_map[i]
            profile["email"] = _gen_email(planted_idx_map[i], i)
        profiles.append(profile)

    # Apply pre-flagging
    _apply_preflag(profiles)

    # Insert in batches of 2000
    batch_size = 2000
    for start in range(0, len(profiles), batch_size):
        batch = profiles[start : start + batch_size]
        await db["user_profiles"].insert_many(batch)
        logger.info(f"  Inserted profiles {start}–{start + len(batch) - 1}")

    # ── Insert sanctioned entries ─────────────────────────────────
    logger.info(f"Inserting {len(SANCTIONED_ENTRIES)} sanctioned entries...")
    sanctioned_docs = []
    for entry in SANCTIONED_ENTRIES:
        doc = {
            **entry,
            "addedAt": datetime(2026, 1, 15) + timedelta(days=random.randint(0, 60)),
            "isActive": True,
            "details": {
                **(entry.get("details", {})),
                "lastUpdated": datetime(2026, 2, 20) + timedelta(days=random.randint(0, 15)),
            },
        }
        if "aliases" not in doc:
            doc["aliases"] = []
        sanctioned_docs.append(doc)

    await db["sanctioned_list"].insert_many(sanctioned_docs)
    logger.info(f"  Inserted {len(sanctioned_docs)} sanctioned entries")

    # ── Create indexes ────────────────────────────────────────────
    logger.info("Creating indexes...")
    await db["user_profiles"].create_index("userId", unique=True)
    await db["user_profiles"].create_index("screening.riskFlag")
    await db["user_profiles"].create_index("screening.lastScreenedAt")
    await db["user_profiles"].create_index("fullName")
    await db["sanctioned_list"].create_index("fullName")
    await db["sanctioned_list"].create_index("source")
    await db["sanctioned_list"].create_index("isActive")
    logger.info("Indexes created.")

    # ── Summary ───────────────────────────────────────────────────
    profiles_count = await db["user_profiles"].count_documents({})
    sanctioned_count = await db["sanctioned_list"].count_documents({})
    flagged_count = await db["user_profiles"].count_documents({"screening.riskFlag": True})

    logger.info("=" * 60)
    logger.info("SEED COMPLETE")
    logger.info(f"  User profiles:      {profiles_count:,}")
    logger.info(f"  Sanctioned entries:  {sanctioned_count}")
    logger.info(f"  Pre-flagged users:   {flagged_count}")
    logger.info("=" * 60)
    logger.info("")
    logger.info("NEXT STEPS:")
    logger.info("  1. Create Atlas Search index 'profiles_fuzzy' on user_profiles")
    logger.info("  2. Create Atlas Search index 'sanctions_fuzzy' on sanctioned_list")
    logger.info("  3. Index definitions available at GET /api/screening/index-definitions")

    client.close()


if __name__ == "__main__":
    asyncio.run(seed())

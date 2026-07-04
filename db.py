import sqlite3
import threading
from datetime import datetime, timedelta

DB_PATH = "/data/bot.db"  # Railway Volume shu yerga ulanadi (persistent storage uchun)

_lock = threading.Lock()


def _connect():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def init_db():
    with _lock, _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                phone TEXT,
                full_name TEXT,
                birth_date TEXT,
                registered_at TEXT,
                first_voice_at TEXT,
                premium_until TEXT
            )
        """)
        conn.commit()


def get_user(user_id: int):
    with _lock, _connect() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


def upsert_partial(user_id: int, **fields):
    """Foydalanuvchi haqida ma'lumotni bosqichma-bosqich saqlash (ro'yxatdan o'tish jarayonida)."""
    user = get_user(user_id)
    with _lock, _connect() as conn:
        if user is None:
            columns = ["user_id"] + list(fields.keys())
            values = [user_id] + list(fields.values())
            placeholders = ", ".join(["?"] * len(columns))
            conn.execute(
                f"INSERT INTO users ({', '.join(columns)}) VALUES ({placeholders})",
                values,
            )
        else:
            set_clause = ", ".join(f"{k} = ?" for k in fields)
            conn.execute(
                f"UPDATE users SET {set_clause} WHERE user_id = ?",
                list(fields.values()) + [user_id],
            )
        conn.commit()


def is_registered(user_id: int) -> bool:
    user = get_user(user_id)
    return bool(user and user.get("full_name") and user.get("phone") and user.get("birth_date"))


def mark_first_voice_if_needed(user_id: int):
    user = get_user(user_id)
    if user and not user.get("first_voice_at"):
        upsert_partial(user_id, first_voice_at=datetime.utcnow().isoformat())


def get_trial_minutes_elapsed(user_id: int) -> float:
    user = get_user(user_id)
    if not user or not user.get("first_voice_at"):
        return 0.0
    started = datetime.fromisoformat(user["first_voice_at"])
    return (datetime.utcnow() - started).total_seconds() / 60


def is_premium(user_id: int) -> bool:
    user = get_user(user_id)
    if not user or not user.get("premium_until"):
        return False
    return datetime.fromisoformat(user["premium_until"]) > datetime.utcnow()


def grant_premium(user_id: int, days: int = 30):
    until = datetime.utcnow() + timedelta(days=days)
    upsert_partial(user_id, premium_until=until.isoformat())
    return until

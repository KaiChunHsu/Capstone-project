from __future__ import annotations
import os
import sqlite3
import hashlib
import hmac
from typing import Any, Dict, List, Optional

PBKDF_ITERATIONS = 200_000


def _pbkdf2(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF_ITERATIONS)


class DB:
    """SQLite wrapper for HealthyLife (local persistence).

    WARNING (Streamlit Cloud): Ephemeral filesystem. For production, use a managed DB.
    """

    def __init__(self, path: str = "healthylife.db") -> None:
        self.path = path
        if os.path.dirname(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
        self.init_schema()

    def connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON;")
        return con

# ---------- schema ----------
    def init_schema(self) -> None:
        with self.connect() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    email TEXT PRIMARY KEY,
                    password_salt BLOB NOT NULL,
                    password_hash BLOB NOT NULL,
                    name TEXT
                );

                CREATE TABLE IF NOT EXISTS profiles (
                    email TEXT PRIMARY KEY REFERENCES users(email) ON DELETE CASCADE,
                    sex TEXT,
                    dob TEXT,
                    height_cm REAL,
                    weight_kg REAL,
                    activity_level TEXT DEFAULT 'light'
                );

                CREATE TABLE IF NOT EXISTS settings (
                    email TEXT PRIMARY KEY REFERENCES users(email) ON DELETE CASCADE,
                    unit_system TEXT DEFAULT 'metric',
                    show_hydration INTEGER DEFAULT 0,
                    nudge_opt_in INTEGER DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS goals (
                    email TEXT PRIMARY KEY REFERENCES users(email) ON DELETE CASCADE,
                    kcal INTEGER,
                    protein_g INTEGER,
                    carbs_g INTEGER,
                    fat_g INTEGER,
                    fiber_g INTEGER,
                    water_ml INTEGER
                );

                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT REFERENCES users(email) ON DELETE CASCADE,
                    date TEXT,
                    weight_kg REAL,
                    kcal_in INTEGER,
                    protein_g INTEGER,
                    carbs_g INTEGER,
                    fat_g INTEGER,
                    steps INTEGER
                );
                """
            )

# ---------- users & auth ----------
    def create_user(self, email: str, password: str, name: str = "") -> Optional[str]:
        salt = os.urandom(16)
        pwd = _pbkdf2(password, salt)
        try:
            with self.connect() as con:
                con.execute(
                    "INSERT INTO users(email, password_salt, password_hash, name) VALUES (?,?,?,?)",
                    (email, salt, pwd, name),
                )
                con.execute("INSERT INTO profiles(email) VALUES (?)", (email,))
                con.execute("INSERT INTO settings(email) VALUES (?)", (email,))
        except sqlite3.IntegrityError:
            return "This email has been registered."
        return None

    def verify_user(self, email: str, password: str) -> bool:
        with self.connect() as con:
            row = con.execute(
                "SELECT password_salt, password_hash FROM users WHERE email=?",
                (email,),
            ).fetchone()
        if not row:
            return False
        salt, hashed = row[0], row[1]
        test = _pbkdf2(password, salt)
        return hmac.compare_digest(test, hashed)

    def update_user_name(self, email: str, name: str) -> None:
        with self.connect() as con:
            con.execute("UPDATE users SET name=? WHERE email=?", (name, email))

# ---------- profile ----------
    def get_profile(self, email: str) -> Dict[str, Any]:
        with self.connect() as con:
            row = con.execute("SELECT * FROM profiles WHERE email=?", (email,)).fetchone()
        return dict(row) if row else {}

    def upsert_profile(self, email: str, profile: Dict[str, Any]) -> None:
        keys = ["sex", "dob", "height_cm", "weight_kg", "activity_level"]
        vals = [profile.get(k) for k in keys]
        with self.connect() as con:
            con.execute(
                """
                INSERT INTO profiles(email, sex, dob, height_cm, weight_kg, activity_level)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(email) DO UPDATE SET
                    sex=excluded.sex,
                    dob=excluded.dob,
                    height_cm=excluded.height_cm,
                    weight_kg=excluded.weight_kg,
                    activity_level=excluded.activity_level
                """,
                (email, *vals),
            )

# ---------- settings ----------
    def get_settings(self, email: str) -> Dict[str, Any]:
        with self.connect() as con:
            row = con.execute("SELECT * FROM settings WHERE email=?", (email,)).fetchone()
        d = dict(row) if row else {}
        if d:
            d["show_hydration"] = bool(d.get("show_hydration"))
            d["nudge_opt_in"] = bool(d.get("nudge_opt_in"))
        return d

    def upsert_settings(self, email: str, settings: Dict[str, Any]) -> None:
        unit = settings.get("unit_system", "metric")
        show_h = 1 if settings.get("show_hydration") else 0
        nudges = 1 if settings.get("nudge_opt_in") else 0
        with self.connect() as con:
            con.execute(
                """
                INSERT INTO settings(email, unit_system, show_hydration, nudge_opt_in)
                VALUES (?,?,?,?)
                ON CONFLICT(email) DO UPDATE SET
                    unit_system=excluded.unit_system,
                    show_hydration=excluded.show_hydration,
                    nudge_opt_in=excluded.nudge_opt_in
                """,
                (email, unit, show_h, nudges),
            )

# ---------- goals ----------
    def get_goals(self, email: str) -> Dict[str, Any]:
        with self.connect() as con:
            row = con.execute("SELECT * FROM goals WHERE email=?", (email,)).fetchone()
        return dict(row) if row else {}

    def upsert_goals(self, email: str, goals: Dict[str, Any]) -> None:
        keys = ["kcal", "protein_g", "carbs_g", "fat_g", "fiber_g", "water_ml"]
        vals = [goals.get(k) for k in keys]
        with self.connect() as con:
            con.execute(
                """
                INSERT INTO goals(email, kcal, protein_g, carbs_g, fat_g, fiber_g, water_ml)
                VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(email) DO UPDATE SET
                    kcal=excluded.kcal,
                    protein_g=excluded.protein_g,
                    carbs_g=excluded.carbs_g,
                    fat_g=excluded.fat_g,
                    fiber_g=excluded.fiber_g,
                    water_ml=excluded.water_ml
                """,
                (email, *vals),
            )

# ---------- logs ----------
    def add_log(
        self,
        email: str,
        date_iso: str,
        weight_kg: Optional[float] = None,
        kcal_in: Optional[int] = None,
        protein_g: Optional[int] = None,
        carbs_g: Optional[int] = None,
        fat_g: Optional[int] = None,
        steps: Optional[int] = None,
    ) -> None:
        with self.connect() as con:
            con.execute(
                """
                INSERT INTO logs(email, date, weight_kg, kcal_in, protein_g, carbs_g, fat_g, steps)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (email, date_iso, weight_kg, kcal_in, protein_g, carbs_g, fat_g, steps),
            )

    def get_logs(self, email: str) -> List[Dict[str, Any]]:
        with self.connect() as con:
            rows = con.execute(
                "SELECT date, weight_kg, kcal_in, protein_g, carbs_g, fat_g, steps FROM logs WHERE email=? ORDER BY date",
                (email,),
            ).fetchall()
        return [dict(r) for r in rows]

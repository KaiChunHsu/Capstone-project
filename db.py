import os
import sqlite3
import hashlib
import hmac # Hash-based Message Authentication Code
from typing import Any, Dict, List, Optional # just for code clarification that I learned from Leetcode new version of Python

# Put PBKDF2 in hashing algorithms to enhance security
PBKDF_ITERATIONS = 200_000

# https://python.readthedocs.io/fr/hack-in-language/library/hashlib.html
# Here is the website that I reference how to create security of password and import hashlib&hmac
def pbkdf2(password: str, salt: bytes) -> bytes:
    # generate password with PBKDF2 (SHA256)
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF_ITERATIONS)


class DB:
    """SQLite wrapper for HealthyLife (local persistence).

    This temporary filesystem only for the small data.
    """
    # Initialize the database file, if it does not exist, it will be created.
    def __init__(self, path: str = "healthylife.db") -> None:
        self.path = path
        if os.path.dirname(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
        self.init_schema()

    def connect(self) -> sqlite3.Connection:
        # create connection, use FK to check 
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON;") # default is OFF should turn it on if FK needed
        return con

    # schema 
    # set up the reference that if delete the email all the 
    # https://docs.python.org/3/library/sqlite3.html
    # Here is the website that I created the SQLite3 for user authentication
    def init_schema(self) -> None:
    # Initialize all database table schemas
    # auto connect and exit 
        with self.connect() as con:
            # set up the delete cascade means if users' table got delete all the record from this account will delete as well
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
                    hydration_goal REAL DEFAULT 2.0 
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
    


# users & auth 
    def create_user(self, email: str, password: str, name: str = "") -> Optional[str]:
        # create new user, establish profile and settings
        salt = os.urandom(16)
        pwd = pbkdf2(password, salt)
        try:
            with self.connect() as con:
                con.execute(
                    "INSERT INTO users(email, password_salt, password_hash, name) VALUES (?,?,?,?)",
                    (email, salt, pwd, name),
                )
                con.execute("INSERT INTO profiles(email) VALUES (?)", (email,)) # set this email for tuple, afraid of being string
                con.execute("INSERT INTO settings(email) VALUES (?)", (email,))
        except sqlite3.IntegrityError:
            return "This email has been registered."
        return None

    # check the user validation
    def verify_user(self, email: str, password: str) -> bool:
        # verify users authentication
        with self.connect() as con:
            # check from the users database
            # get one info
            row = con.execute(
                "SELECT password_salt, password_hash FROM users WHERE email=?",
                (email,),
            ).fetchone()
        if not row:
            return False
        
        salt, hashed = row[0], row[1]
        test = pbkdf2(password, salt)
        return hmac.compare_digest(test, hashed) # avoid time attack

    def update_user_name(self, email: str, name: str) -> None:
        # update the users' name
        with self.connect() as con:
            con.execute("UPDATE users SET name=? WHERE email=?", (name, email)) 

# profile
    def get_profile(self, email: str) -> Dict[str, Any]:
        # get the data with fetchone
        # start from first record
        with self.connect() as con:
            row = con.execute("SELECT * FROM profiles WHERE email=?", (email,)).fetchone()
        # if exist user data return to dict else with empty
        return dict(row) if row else {}

    # update or insert 
    def upsert_profile(self, email: str, profile: Dict[str, Any]) -> None:
        # add or update users' profile
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
                # record email and all value
                (email, *vals),
            )

# settings for water intake
    def get_settings(self, email: str) -> Dict[str, Any]:
        # get users' settings for water intake 
        with self.connect() as con:
            row = con.execute("SELECT * FROM settings WHERE email=?", (email,)).fetchone()
        d = dict(row) if row else {}
        if d:
            d["show_hydration"] = bool(d.get("show_hydration"))
        return d


    def upsert_settings(self, email: str, settings: Dict[str, Any]) -> None:
        unit = settings.get("unit_system", "metric")
        # check box for true or false
        show_h = 1 if settings.get("show_hydration") else 0
        #  hydration_goal（liter）save as 2.0 if not provide
        hydration_goal = settings.get("hydration_goal")
    
        with self.connect() as con:
            # if not provide hydration_goal，it will default as 2.0 
            if hydration_goal is None:
                row = con.execute("SELECT hydration_goal FROM settings WHERE email=?", (email,)).fetchone()
                hydration_goal = (row["hydration_goal"] if row and row["hydration_goal"] is not None else 2.0)
    
            con.execute(
                """
                INSERT INTO settings(email, unit_system, show_hydration, hydration_goal)
                VALUES (?,?,?,?)
                ON CONFLICT(email) DO UPDATE SET
                    unit_system=excluded.unit_system,
                    show_hydration=excluded.show_hydration,
                    hydration_goal=excluded.hydration_goal
                """,
                (email, unit, show_h, float(hydration_goal)),
            )


# goals for nutrition intake
    def get_goals(self, email: str) -> Dict[str, Any]:
        # get the users' nutrition
        with self.connect() as con:
            row = con.execute("SELECT * FROM goals WHERE email=?", (email,)).fetchone()
        return dict(row) if row else {}

    def upsert_goals(self, email: str, goals: Dict[str, Any]) -> None:
        # add or update users' goals
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

# logs (for daily record)
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
        # add the daily record
        with self.connect() as con:
            con.execute(
                """
                INSERT INTO logs(email, date, weight_kg, kcal_in, protein_g, carbs_g, fat_g, steps)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (email, date_iso, weight_kg, kcal_in, protein_g, carbs_g, fat_g, steps),
            )

    def get_logs(self, email: str) -> List[Dict[str, Any]]:
        # get all the daily record from users with sequence
        with self.connect() as con:
            rows = con.execute(
                "SELECT date, weight_kg, kcal_in, protein_g, carbs_g, fat_g, steps FROM logs WHERE email=? ORDER BY date",
                (email,),
            ).fetchall()
        return [dict(r) for r in rows]

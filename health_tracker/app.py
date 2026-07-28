"""
Health Tracking System
Based on: HEALTH_TRACKING_SYSTEM_PROJECT_PROPOSAL (Roy Mwaura Maina, KCA University)

A working prototype covering the proposal's core software components:
 - User registration / login
 - Health data tracking (activity, heart rate, blood pressure, sleep, weight, nutrition)
 - Cloud-style central storage (Turso / libSQL - a hosted, SQLite-compatible database)
 - Data processing & analytics (trends, averages)
 - Real-time notifications & alerts (rule-based health flags)
 - Personalized health insights

NOTE ON DATABASE:
Vercel's serverless functions run on a READ-ONLY filesystem (except /tmp, which is
ephemeral and not shared across invocations). A local SQLite file cannot be used for
real persistence there. This version uses Turso (hosted libSQL, SQLite-compatible)
so the same SQL and mostly the same code works locally AND in production.

Required environment variables (set locally in a .env file or shell, and in
Vercel under Project Settings -> Environment Variables):
    TURSO_DATABASE_URL   e.g. libsql://your-db-name-yourorg.turso.io
    TURSO_AUTH_TOKEN     token generated via `turso db tokens create <db-name>`
"""

from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from werkzeug.security import generate_password_hash, check_password_hash
import libsql_experimental as libsql
import os
from datetime import datetime, timedelta
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")

TURSO_DATABASE_URL = os.environ.get("TURSO_DATABASE_URL")
TURSO_AUTH_TOKEN = os.environ.get("TURSO_AUTH_TOKEN")

_db_ready = False  # guards against re-running init_db() on every warm invocation


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
def get_db():
    """
    Open a connection to the remote Turso database.
    Requires TURSO_DATABASE_URL and TURSO_AUTH_TOKEN to be set as environment
    variables. Falls back to a local file 'health_tracker.db' ONLY for quick
    local testing when those variables are absent (not suitable for Vercel).
    """
    if TURSO_DATABASE_URL and TURSO_AUTH_TOKEN:
        return libsql.connect(TURSO_DATABASE_URL, auth_token=TURSO_AUTH_TOKEN)
    # Local fallback (dev machine only - will NOT work on Vercel)
    return libsql.connect("health_tracker.db")


def _fetchall_dicts(cursor):
    """Convert cursor results into a list of dicts so templates can keep
    using row["field"] the same way they did with sqlite3.Row."""
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _fetchone_dict(cursor):
    columns = [d[0] for d in cursor.description]
    row = cursor.fetchone()
    return dict(zip(columns, row)) if row else None


def init_db():
    global _db_ready
    if _db_ready:
        return
    conn = get_db()
    conn.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        age INTEGER,
        created_at TEXT NOT NULL
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        entry_date TEXT NOT NULL,
        steps INTEGER,
        heart_rate INTEGER,
        bp_systolic INTEGER,
        bp_diastolic INTEGER,
        sleep_hours REAL,
        weight_kg REAL,
        calories INTEGER,
        created_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        entry_id INTEGER,
        severity TEXT NOT NULL,
        message TEXT NOT NULL,
        created_at TEXT NOT NULL,
        acknowledged INTEGER DEFAULT 0,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)
    conn.commit()
    _db_ready = True


# Ensure tables exist as soon as the module is imported - this runs both
# locally (python app.py) AND on Vercel (which imports `app` directly and
# never hits the `if __name__ == "__main__"` block below).
init_db()


# ---------------------------------------------------------------------------
# Health rule-engine: turns raw readings into alerts + insights
# (Stands in for the proposal's "Data processing and analytics" component)
# ---------------------------------------------------------------------------
def evaluate_entry(entry_dict):
    """Return a list of (severity, message) tuples for out-of-range readings."""
    alerts = []

    hr = entry_dict.get("heart_rate")
    if hr is not None:
        if hr > 100:
            alerts.append(("high", f"Elevated resting heart rate: {hr} bpm (normal 60-100)."))
        elif hr < 50:
            alerts.append(("high", f"Low heart rate: {hr} bpm (normal 60-100)."))

    sys_bp = entry_dict.get("bp_systolic")
    dia_bp = entry_dict.get("bp_diastolic")
    if sys_bp is not None and dia_bp is not None:
        if sys_bp >= 140 or dia_bp >= 90:
            alerts.append(("high", f"High blood pressure reading: {sys_bp}/{dia_bp} mmHg (hypertensive range)."))
        elif sys_bp < 90 or dia_bp < 60:
            alerts.append(("medium", f"Low blood pressure reading: {sys_bp}/{dia_bp} mmHg."))

    sleep = entry_dict.get("sleep_hours")
    if sleep is not None:
        if sleep < 6:
            alerts.append(("medium", f"Low sleep recorded: {sleep} hrs. Aim for 7-9 hrs."))
        elif sleep > 10:
            alerts.append(("low", f"Unusually high sleep recorded: {sleep} hrs."))

    steps = entry_dict.get("steps")
    if steps is not None and steps < 3000:
        alerts.append(("low", f"Low activity day: {steps} steps. Consider a short walk."))

    return alerts


def generate_insights(rows):
    """Simple trend-based insights from a user's recent entries."""
    if not rows:
        return ["Log your first entry to start getting personalized insights."]

    insights = []
    n = len(rows)

    avg_steps = sum(r["steps"] or 0 for r in rows) / n
    avg_sleep = sum(r["sleep_hours"] or 0 for r in rows if r["sleep_hours"]) / max(1, sum(1 for r in rows if r["sleep_hours"]))
    avg_hr = sum(r["heart_rate"] or 0 for r in rows if r["heart_rate"]) / max(1, sum(1 for r in rows if r["heart_rate"]))

    if avg_steps < 5000:
        insights.append(f"Your average is {avg_steps:.0f} steps/day — below the general 7,000-10,000 target. Try adding a daily walk.")
    else:
        insights.append(f"Nice consistency — you're averaging {avg_steps:.0f} steps/day.")

    if avg_sleep and avg_sleep < 7:
        insights.append(f"Average sleep over this period is {avg_sleep:.1f} hrs, under the recommended 7-9 hrs.")

    if avg_hr and avg_hr > 90:
        insights.append(f"Your average resting heart rate ({avg_hr:.0f} bpm) trends high — worth discussing with a doctor if it persists.")

    weights = [r["weight_kg"] for r in rows if r["weight_kg"]]
    if len(weights) >= 2:
        change = weights[0] - weights[-1]  # rows ordered latest first
        if abs(change) >= 1:
            direction = "lost" if change > 0 else "gained"
            insights.append(f"You've {direction} {abs(change):.1f} kg over the logged period.")

    if not insights:
        insights.append("All your recent readings are within typical healthy ranges. Keep it up!")

    return insights


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return wrapper


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        age = request.form.get("age") or None
        password = request.form["password"]

        if not name or not email or not password:
            flash("All fields are required.", "error")
            return render_template("register.html")

        conn = get_db()
        cur = conn.execute("SELECT id FROM users WHERE email = ?", (email,))
        existing = _fetchone_dict(cur)
        if existing:
            flash("An account with that email already exists.", "error")
            return render_template("register.html")

        conn.execute(
            "INSERT INTO users (name, email, password_hash, age, created_at) VALUES (?, ?, ?, ?, ?)",
            (name, email, generate_password_hash(password), age, datetime.now().isoformat()),
        )
        conn.commit()
        flash("Account created. Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        conn = get_db()
        cur = conn.execute("SELECT * FROM users WHERE email = ?", (email,))
        user = _fetchone_dict(cur)

        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            return redirect(url_for("dashboard"))

        flash("Invalid email or password.", "error")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    conn = get_db()
    cur = conn.execute(
        "SELECT * FROM entries WHERE user_id = ? ORDER BY entry_date DESC LIMIT 30",
        (session["user_id"],),
    )
    rows = _fetchall_dicts(cur)

    cur = conn.execute(
        "SELECT * FROM alerts WHERE user_id = ? AND acknowledged = 0 ORDER BY created_at DESC LIMIT 10",
        (session["user_id"],),
    )
    alerts = _fetchall_dicts(cur)

    latest = rows[0] if rows else None
    insights = generate_insights(rows)

    chart_rows = list(reversed(rows))  # chronological order for charts
    chart_data = {
        "labels": [r["entry_date"] for r in chart_rows],
        "steps": [r["steps"] for r in chart_rows],
        "heart_rate": [r["heart_rate"] for r in chart_rows],
        "weight": [r["weight_kg"] for r in chart_rows],
        "sleep": [r["sleep_hours"] for r in chart_rows],
        "bp_systolic": [r["bp_systolic"] for r in chart_rows],
        "bp_diastolic": [r["bp_diastolic"] for r in chart_rows],
    }

    return render_template(
        "dashboard.html",
        latest=latest,
        alerts=alerts,
        insights=insights,
        chart_data=chart_data,
        user_name=session.get("user_name"),
    )


@app.route("/entry/new", methods=["GET", "POST"])
@login_required
def new_entry():
    if request.method == "POST":
        data = {
            "entry_date": request.form.get("entry_date") or datetime.now().strftime("%Y-%m-%d"),
            "steps": _to_int(request.form.get("steps")),
            "heart_rate": _to_int(request.form.get("heart_rate")),
            "bp_systolic": _to_int(request.form.get("bp_systolic")),
            "bp_diastolic": _to_int(request.form.get("bp_diastolic")),
            "sleep_hours": _to_float(request.form.get("sleep_hours")),
            "weight_kg": _to_float(request.form.get("weight_kg")),
            "calories": _to_int(request.form.get("calories")),
        }

        conn = get_db()
        cur = conn.execute(
            """INSERT INTO entries
               (user_id, entry_date, steps, heart_rate, bp_systolic, bp_diastolic, sleep_hours, weight_kg, calories, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session["user_id"], data["entry_date"], data["steps"], data["heart_rate"],
                data["bp_systolic"], data["bp_diastolic"], data["sleep_hours"], data["weight_kg"],
                data["calories"], datetime.now().isoformat(),
            ),
        )

        # Fetch the id of the entry we just inserted
        cur2 = conn.execute(
            "SELECT id FROM entries WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (session["user_id"],),
        )
        entry_row = _fetchone_dict(cur2)
        entry_id = entry_row["id"] if entry_row else None

        # Real-time alert generation
        for severity, message in evaluate_entry(data):
            conn.execute(
                "INSERT INTO alerts (user_id, entry_id, severity, message, created_at) VALUES (?, ?, ?, ?, ?)",
                (session["user_id"], entry_id, severity, message, datetime.now().isoformat()),
            )

        conn.commit()
        flash("Entry logged.", "success")
        return redirect(url_for("dashboard"))

    return render_template("new_entry.html", today=datetime.now().strftime("%Y-%m-%d"))


@app.route("/alerts/<int:alert_id>/ack", methods=["POST"])
@login_required
def ack_alert(alert_id):
    conn = get_db()
    conn.execute(
        "UPDATE alerts SET acknowledged = 1 WHERE id = ? AND user_id = ?",
        (alert_id, session["user_id"]),
    )
    conn.commit()
    return redirect(url_for("dashboard"))


@app.route("/history")
@login_required
def history():
    conn = get_db()
    cur = conn.execute(
        "SELECT * FROM entries WHERE user_id = ? ORDER BY entry_date DESC",
        (session["user_id"],),
    )
    rows = _fetchall_dicts(cur)
    return render_template("history.html", rows=rows)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _to_int(v):
    try:
        return int(v) if v not in (None, "") else None
    except ValueError:
        return None


def _to_float(v):
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


if __name__ == "__main__":
    print("\nHealth Tracking System running at http://127.0.0.1:5000\n")
    app.run(debug=True, port=5000)
   

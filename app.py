from flask import Flask, render_template, request, redirect, url_for, session, flash, Response, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timezone
from functools import wraps
import os
import psycopg
from psycopg.rows import dict_row

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "CHANGE_THIS_SECRET_KEY")

DATABASE_URL = os.environ.get("DATABASE_URL", "")
APP_NAME = os.environ.get("APP_NAME", "MeTime")


# ---------------------------------------------------------------- database
def db():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row, autocommit=False)


SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        role TEXT NOT NULL DEFAULT 'client',
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        phone TEXT,
        password_hash TEXT NOT NULL,
        office_notes TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS client_intake (
        user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        date_of_birth TEXT,
        address TEXT,
        occupation TEXT,
        emergency_name TEXT,
        emergency_phone TEXT,
        referral TEXT,
        conditions TEXT,
        medications TEXT,
        allergies TEXT,
        surgeries TEXT,
        pregnant TEXT,
        pressure_preference TEXT,
        areas_of_concern TEXT,
        goals TEXT,
        consent_treatment BOOLEAN NOT NULL DEFAULT FALSE,
        consent_privacy BOOLEAN NOT NULL DEFAULT FALSE,
        signature TEXT,
        created_at TEXT,
        updated_at TEXT
    )
    """,
]


def init_db():
    try:
        conn = db()
        cur = conn.cursor()
        for stmt in SCHEMA:
            cur.execute(stmt)
        conn.commit()
        conn.close()
    except Exception as e:
        print("init_db skipped/failed:", e)


# ---------------------------------------------------------------- helpers
def now_iso():
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def admin_exists():
    try:
        conn = db()
        row = conn.execute("SELECT 1 FROM users WHERE role = 'admin' LIMIT 1").fetchone()
        conn.close()
        return bool(row)
    except Exception:
        return False


def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    conn = db()
    user = conn.execute("SELECT * FROM users WHERE id = %s", (uid,)).fetchone()
    conn.close()
    return user


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if session.get("role") != "admin":
            return redirect(url_for("admin_login"))
        return fn(*args, **kwargs)
    return wrapper


@app.context_processor
def inject_globals():
    logo_exists = os.path.exists(os.path.join(app.static_folder, "logo.png"))
    return dict(
        app_name=APP_NAME,
        session_role=session.get("role"),
        session_name=session.get("name"),
        logo_exists=logo_exists,
    )


# ---------------------------------------------------------------- client area
@app.route("/")
def index():
    if session.get("role") == "admin":
        return redirect(url_for("admin_dashboard"))
    if session.get("user_id"):
        return redirect(url_for("home"))
    return render_template("landing.html")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        if not name or not email or not password:
            flash("Please fill in your name, email, and a password.")
            return render_template("signup.html", name=name, email=email, phone=phone)
        conn = db()
        existing = conn.execute("SELECT id FROM users WHERE email = %s", (email,)).fetchone()
        if existing:
            conn.close()
            flash("An account with that email already exists. Please log in.")
            return redirect(url_for("login"))
        new_user = conn.execute(
            "INSERT INTO users (role, name, email, phone, password_hash, created_at) VALUES ('client', %s, %s, %s, %s, %s) RETURNING id",
            (name, email, phone, generate_password_hash(password), now_iso())
        ).fetchone()
        conn.commit()
        conn.close()
        session["user_id"] = new_user["id"]
        session["role"] = "client"
        session["name"] = name
        flash("Welcome! Please complete your health intake form.")
        return redirect(url_for("intake"))
    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        conn = db()
        user = conn.execute("SELECT * FROM users WHERE email = %s", (email,)).fetchone()
        conn.close()
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["role"] = user["role"]
            session["name"] = user["name"]
            if user["role"] == "admin":
                return redirect(url_for("admin_dashboard"))
            return redirect(url_for("home"))
        flash("Invalid email or password.")
        return render_template("login.html", email=email)
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/home")
@login_required
def home():
    conn = db()
    intake = conn.execute("SELECT * FROM client_intake WHERE user_id = %s", (session["user_id"],)).fetchone()
    conn.close()
    return render_template("home.html", intake=intake)


@app.route("/intake", methods=["GET", "POST"])
@login_required
def intake():
    conn = db()
    if request.method == "POST":
        fields = {
            "date_of_birth": request.form.get("date_of_birth", "").strip(),
            "address": request.form.get("address", "").strip(),
            "occupation": request.form.get("occupation", "").strip(),
            "emergency_name": request.form.get("emergency_name", "").strip(),
            "emergency_phone": request.form.get("emergency_phone", "").strip(),
            "referral": request.form.get("referral", "").strip(),
            "conditions": request.form.get("conditions", "").strip(),
            "medications": request.form.get("medications", "").strip(),
            "allergies": request.form.get("allergies", "").strip(),
            "surgeries": request.form.get("surgeries", "").strip(),
            "pregnant": request.form.get("pregnant", "").strip(),
            "pressure_preference": request.form.get("pressure_preference", "").strip(),
            "areas_of_concern": request.form.get("areas_of_concern", "").strip(),
            "goals": request.form.get("goals", "").strip(),
            "consent_treatment": "consent_treatment" in request.form,
            "consent_privacy": "consent_privacy" in request.form,
            "signature": request.form.get("signature", "").strip(),
        }
        if not fields["consent_treatment"] or not fields["consent_privacy"]:
            conn.close()
            flash("Please check both consent boxes to submit your intake form.")
            return redirect(url_for("intake"))
        conn.execute(
            """
            INSERT INTO client_intake
            (user_id, date_of_birth, address, occupation, emergency_name, emergency_phone, referral,
             conditions, medications, allergies, surgeries, pregnant, pressure_preference, areas_of_concern,
             goals, consent_treatment, consent_privacy, signature, created_at, updated_at)
            VALUES (%(user_id)s, %(date_of_birth)s, %(address)s, %(occupation)s, %(emergency_name)s, %(emergency_phone)s, %(referral)s,
                    %(conditions)s, %(medications)s, %(allergies)s, %(surgeries)s, %(pregnant)s, %(pressure_preference)s, %(areas_of_concern)s,
                    %(goals)s, %(consent_treatment)s, %(consent_privacy)s, %(signature)s, %(now)s, %(now)s)
            ON CONFLICT (user_id) DO UPDATE SET
                date_of_birth = EXCLUDED.date_of_birth, address = EXCLUDED.address, occupation = EXCLUDED.occupation,
                emergency_name = EXCLUDED.emergency_name, emergency_phone = EXCLUDED.emergency_phone, referral = EXCLUDED.referral,
                conditions = EXCLUDED.conditions, medications = EXCLUDED.medications, allergies = EXCLUDED.allergies,
                surgeries = EXCLUDED.surgeries, pregnant = EXCLUDED.pregnant, pressure_preference = EXCLUDED.pressure_preference,
                areas_of_concern = EXCLUDED.areas_of_concern, goals = EXCLUDED.goals,
                consent_treatment = EXCLUDED.consent_treatment, consent_privacy = EXCLUDED.consent_privacy,
                signature = EXCLUDED.signature, updated_at = EXCLUDED.updated_at
            """,
            {**fields, "user_id": session["user_id"], "now": now_iso()}
        )
        conn.commit()
        conn.close()
        flash("Thank you! Your intake form has been saved.")
        return redirect(url_for("home"))
    intake = conn.execute("SELECT * FROM client_intake WHERE user_id = %s", (session["user_id"],)).fetchone()
    conn.close()
    return render_template("intake.html", intake=intake or {})


# ---------------------------------------------------------------- office / admin
@app.route("/admin/setup", methods=["GET", "POST"])
def admin_setup():
    if admin_exists():
        flash("An office admin already exists. Please log in.")
        return redirect(url_for("admin_login"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not name or not email or len(password) < 6:
            flash("Enter a name, email, and a password of at least 6 characters.")
            return render_template("admin_setup.html", name=name, email=email)
        conn = db()
        conn.execute(
            "INSERT INTO users (role, name, email, password_hash, created_at) VALUES ('admin', %s, %s, %s, %s)",
            (name, email, generate_password_hash(password), now_iso())
        )
        conn.commit()
        conn.close()
        flash("Office admin created. Please log in.")
        return redirect(url_for("admin_login"))
    return render_template("admin_setup.html")


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if not admin_exists():
        return redirect(url_for("admin_setup"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        conn = db()
        user = conn.execute("SELECT * FROM users WHERE email = %s AND role = 'admin'", (email,)).fetchone()
        conn.close()
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["role"] = "admin"
            session["name"] = user["name"]
            return redirect(url_for("admin_dashboard"))
        flash("Invalid office login.")
        return render_template("admin_login.html", email=email)
    return render_template("admin_login.html")


@app.route("/admin")
@admin_required
def admin_dashboard():
    q = request.args.get("q", "").strip()
    conn = db()
    if q:
        like = f"%{q}%"
        clients = conn.execute(
            "SELECT * FROM users WHERE role = 'client' AND (name ILIKE %s OR email ILIKE %s OR phone ILIKE %s) ORDER BY name",
            (like, like, like)
        ).fetchall()
    else:
        clients = conn.execute("SELECT * FROM users WHERE role = 'client' ORDER BY created_at DESC").fetchall()
    total = conn.execute("SELECT COUNT(*) AS n FROM users WHERE role = 'client'").fetchone()["n"]
    conn.close()
    return render_template("admin_dashboard.html", clients=clients, q=q, total=total)


@app.route("/admin/client/<int:client_id>", methods=["GET", "POST"])
@admin_required
def admin_client(client_id):
    conn = db()
    client = conn.execute("SELECT * FROM users WHERE id = %s AND role = 'client'", (client_id,)).fetchone()
    if not client:
        conn.close()
        flash("Client not found.")
        return redirect(url_for("admin_dashboard"))
    if request.method == "POST":
        conn.execute("UPDATE users SET office_notes = %s WHERE id = %s",
                     (request.form.get("office_notes", "").strip(), client_id))
        conn.commit()
        conn.close()
        flash("Office notes saved.")
        return redirect(url_for("admin_client", client_id=client_id))
    intake = conn.execute("SELECT * FROM client_intake WHERE user_id = %s", (client_id,)).fetchone()
    conn.close()
    return render_template("admin_client.html", client=client, intake=intake)


# ---------------------------------------------------------------- misc / pwa
@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/sw.js")
def service_worker():
    response = app.send_static_file("sw.js")
    response.headers["Content-Type"] = "application/javascript"
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.route("/health")
def health_check():
    return "ok"


init_db()

if __name__ == "__main__":
    app.run(debug=True, port=5001)

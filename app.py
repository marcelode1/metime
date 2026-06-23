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
        full_name TEXT,
        date_of_birth TEXT,
        age TEXT,
        phone TEXT,
        email TEXT,
        address TEXT,
        city TEXT,
        state TEXT,
        zip TEXT,
        emergency_name TEXT,
        emergency_phone TEXT,
        conditions TEXT,
        conditions_other TEXT,
        physician_care TEXT,
        physician_explain TEXT,
        medications_flag TEXT,
        medications TEXT,
        allergies_flag TEXT,
        allergies TEXT,
        visit_reason TEXT,
        visit_reason_other TEXT,
        areas_of_concern TEXT,
        pain_level TEXT,
        pain_description TEXT,
        issue_duration TEXT,
        pressure_preference TEXT,
        referral TEXT,
        consent_treatment BOOLEAN NOT NULL DEFAULT FALSE,
        consent_privacy BOOLEAN NOT NULL DEFAULT FALSE,
        consent_reminders BOOLEAN NOT NULL DEFAULT FALSE,
        consent_cancellation BOOLEAN NOT NULL DEFAULT FALSE,
        consent_photo_release BOOLEAN NOT NULL DEFAULT FALSE,
        client_signature TEXT,
        signed_date TEXT,
        created_at TEXT,
        updated_at TEXT
    )
    """,
]

# Columns added after the first version - safe to run on every boot.
MIGRATIONS = [
    "ALTER TABLE client_intake ADD COLUMN IF NOT EXISTS full_name TEXT",
    "ALTER TABLE client_intake ADD COLUMN IF NOT EXISTS age TEXT",
    "ALTER TABLE client_intake ADD COLUMN IF NOT EXISTS phone TEXT",
    "ALTER TABLE client_intake ADD COLUMN IF NOT EXISTS email TEXT",
    "ALTER TABLE client_intake ADD COLUMN IF NOT EXISTS city TEXT",
    "ALTER TABLE client_intake ADD COLUMN IF NOT EXISTS state TEXT",
    "ALTER TABLE client_intake ADD COLUMN IF NOT EXISTS zip TEXT",
    "ALTER TABLE client_intake ADD COLUMN IF NOT EXISTS conditions_other TEXT",
    "ALTER TABLE client_intake ADD COLUMN IF NOT EXISTS physician_care TEXT",
    "ALTER TABLE client_intake ADD COLUMN IF NOT EXISTS physician_explain TEXT",
    "ALTER TABLE client_intake ADD COLUMN IF NOT EXISTS medications_flag TEXT",
    "ALTER TABLE client_intake ADD COLUMN IF NOT EXISTS allergies_flag TEXT",
    "ALTER TABLE client_intake ADD COLUMN IF NOT EXISTS visit_reason TEXT",
    "ALTER TABLE client_intake ADD COLUMN IF NOT EXISTS visit_reason_other TEXT",
    "ALTER TABLE client_intake ADD COLUMN IF NOT EXISTS pain_level TEXT",
    "ALTER TABLE client_intake ADD COLUMN IF NOT EXISTS pain_description TEXT",
    "ALTER TABLE client_intake ADD COLUMN IF NOT EXISTS issue_duration TEXT",
    "ALTER TABLE client_intake ADD COLUMN IF NOT EXISTS consent_reminders BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE client_intake ADD COLUMN IF NOT EXISTS consent_cancellation BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE client_intake ADD COLUMN IF NOT EXISTS consent_photo_release BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE client_intake ADD COLUMN IF NOT EXISTS client_signature TEXT",
    "ALTER TABLE client_intake ADD COLUMN IF NOT EXISTS signed_date TEXT",
]

CONDITION_OPTIONS = [
    "High Blood Pressure", "Low Blood Pressure", "Heart Disease", "Diabetes", "Arthritis",
    "Osteoporosis", "Cancer", "Fibromyalgia", "Migraines/Headaches", "Chronic Pain",
    "Sciatica", "Varicose Veins", "Blood Clotting Disorder", "Recent Surgery",
    "Skin Conditions", "Anxiety/Stress", "Pregnancy",
]
VISIT_REASON_OPTIONS = [
    "Relaxation", "Stress Relief", "Neck Pain", "Shoulder Pain", "Back Pain", "Hip Pain",
    "Leg Pain", "Headaches", "Sports Recovery", "Injury Recovery",
]
PAIN_DESCRIPTION_OPTIONS = ["Sharp", "Dull", "Aching", "Burning", "Tingling", "Constant", "Intermittent"]
PRESSURE_OPTIONS = ["Light", "Medium", "Firm", "Deep Tissue"]


def init_db():
    try:
        conn = db()
        cur = conn.cursor()
        for stmt in SCHEMA:
            cur.execute(stmt)
        for stmt in MIGRATIONS:
            try:
                cur.execute(stmt)
            except Exception as me:
                print("migration skipped:", me)
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
        def text(name):
            return request.form.get(name, "").strip()

        def joinlist(name):
            return ", ".join(request.form.getlist(name))

        fields = {
            "full_name": text("full_name"),
            "date_of_birth": text("date_of_birth"),
            "age": text("age"),
            "phone": text("phone"),
            "email": text("email"),
            "address": text("address"),
            "city": text("city"),
            "state": text("state"),
            "zip": text("zip"),
            "emergency_name": text("emergency_name"),
            "emergency_phone": text("emergency_phone"),
            "conditions": joinlist("conditions"),
            "conditions_other": text("conditions_other"),
            "physician_care": text("physician_care"),
            "physician_explain": text("physician_explain"),
            "medications_flag": text("medications_flag"),
            "medications": text("medications"),
            "allergies_flag": text("allergies_flag"),
            "allergies": text("allergies"),
            "visit_reason": joinlist("visit_reason"),
            "visit_reason_other": text("visit_reason_other"),
            "areas_of_concern": text("areas_of_concern"),
            "pain_level": text("pain_level"),
            "pain_description": joinlist("pain_description"),
            "issue_duration": text("issue_duration"),
            "pressure_preference": text("pressure_preference"),
            "referral": text("referral"),
            "consent_treatment": "consent_treatment" in request.form,
            "consent_privacy": "consent_privacy" in request.form,
            "consent_reminders": "consent_reminders" in request.form,
            "consent_cancellation": "consent_cancellation" in request.form,
            "consent_photo_release": "consent_photo_release" in request.form,
            "client_signature": text("client_signature"),
            "signed_date": text("signed_date") or now_iso()[:10],
        }
        if not fields["consent_treatment"] or not fields["consent_cancellation"] or not fields["consent_privacy"]:
            conn.close()
            flash("Please check the required consent boxes to submit your intake form.")
            return redirect(url_for("intake"))
        if not fields["client_signature"]:
            conn.close()
            flash("Please type your name as your signature.")
            return redirect(url_for("intake"))

        cols = list(fields.keys())
        params = {**fields, "user_id": session["user_id"], "now": now_iso()}
        collist = "user_id, " + ", ".join(cols) + ", created_at, updated_at"
        placeholders = "%(user_id)s, " + ", ".join(f"%({c})s" for c in cols) + ", %(now)s, %(now)s"
        updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols) + ", updated_at = EXCLUDED.updated_at"
        conn.execute(
            f"INSERT INTO client_intake ({collist}) VALUES ({placeholders}) "
            f"ON CONFLICT (user_id) DO UPDATE SET {updates}",
            params
        )
        # keep the account name/phone in sync if provided
        if fields["full_name"] or fields["phone"]:
            conn.execute(
                "UPDATE users SET name = COALESCE(NULLIF(%s,''), name), phone = COALESCE(NULLIF(%s,''), phone) WHERE id = %s",
                (fields["full_name"], fields["phone"], session["user_id"])
            )
            if fields["full_name"]:
                session["name"] = fields["full_name"]
        conn.commit()
        conn.close()
        flash("Thank you! Your intake form has been saved.")
        return redirect(url_for("home"))

    intake = conn.execute("SELECT * FROM client_intake WHERE user_id = %s", (session["user_id"],)).fetchone()
    user = conn.execute("SELECT name, email, phone FROM users WHERE id = %s", (session["user_id"],)).fetchone()
    conn.close()
    return render_template(
        "intake.html",
        intake=intake or {},
        user=user or {},
        condition_options=CONDITION_OPTIONS,
        visit_reason_options=VISIT_REASON_OPTIONS,
        pain_description_options=PAIN_DESCRIPTION_OPTIONS,
        pressure_options=PRESSURE_OPTIONS,
    )


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

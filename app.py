from flask import Flask, render_template, request, redirect, url_for, session, flash, Response, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timezone, timedelta, date, time as dtime
from functools import wraps
import calendar as pycalendar
import os, base64, mimetypes, re, time, threading, secrets, urllib.parse, urllib.request, urllib.error
import psycopg
from psycopg.rows import dict_row

try:
    import segno
except Exception:
    segno = None

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "CHANGE_THIS_SECRET_KEY")
# "Keep me logged in" sessions last this long; otherwise the session ends when the browser closes.
app.permanent_session_lifetime = timedelta(days=30)

DATABASE_URL = os.environ.get("DATABASE_URL", "")
APP_NAME = os.environ.get("APP_NAME", "MeTime")


# ---------------------------------------------------------------- database
def db():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row, autocommit=False)


SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS app_settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """,
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
        pregnant TEXT,
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
        promo_opt_in BOOLEAN NOT NULL DEFAULT FALSE,
        client_signature TEXT,
        signed_date TEXT,
        created_at TEXT,
        updated_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS appointments (
        id SERIAL PRIMARY KEY,
        client_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
        client_name TEXT NOT NULL,
        client_phone TEXT,
        service TEXT,
        start_at TIMESTAMP NOT NULL,
        duration_min INTEGER NOT NULL DEFAULT 60,
        notes TEXT,
        status TEXT NOT NULL DEFAULT 'booked',
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
    "ALTER TABLE client_intake ADD COLUMN IF NOT EXISTS pregnant TEXT",
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
    "ALTER TABLE client_intake ADD COLUMN IF NOT EXISTS promo_opt_in BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE appointments ADD COLUMN IF NOT EXISTS reminder_24h_sent_at TEXT",
    "ALTER TABLE appointments ADD COLUMN IF NOT EXISTS reminder_6h_sent_at TEXT",
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


CARD_TEXT_KEYS = [
    "card_business_name", "card_contact_name", "card_title", "card_tagline",
    "card_license", "card_phone", "card_email", "card_website", "card_address",
    "card_instagram", "card_facebook",
]
DEFAULT_LICENSE = "MA109774"


def get_setting(key, default=""):
    try:
        conn = db()
        row = conn.execute("SELECT value FROM app_settings WHERE key = %s", (key,)).fetchone()
        conn.close()
        return (row["value"] if row and row["value"] is not None else default)
    except Exception:
        return default


def set_setting(key, value):
    conn = db()
    conn.execute(
        "INSERT INTO app_settings (key, value) VALUES (%s, %s) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
        (key, value)
    )
    conn.commit()
    conn.close()


def card_data():
    d = {k: get_setting(k, "") for k in CARD_TEXT_KEYS}
    d["banner"] = get_setting("card_banner_data", "")   # data URI or ""
    d["photo"] = get_setting("card_photo_data", "")     # data URI or ""
    if not d.get("card_business_name"):
        d["card_business_name"] = APP_NAME
    if not d.get("card_license"):
        d["card_license"] = DEFAULT_LICENSE
    return d


def normalized_website_url(value):
    value = (value or "").strip()
    if not value:
        return ""
    return value if re.match(r"^https?://", value, re.I) else "https://" + value


def social_url(kind, value):
    value = (value or "").strip()
    if not value:
        return ""
    if re.match(r"^https?://", value, re.I):
        return value
    handle = value.lstrip("@").strip("/")
    if kind == "instagram":
        return "https://instagram.com/" + handle
    if kind == "facebook":
        return "https://facebook.com/" + handle
    return "https://" + value


def card_qr_svg(url):
    if not segno or not url:
        return ""
    try:
        return segno.make(url, error="m").svg_inline(scale=7, border=0, dark="#6d28d9")
    except Exception:
        return ""


def _vcard_escape(v):
    return str(v or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def card_vcard_text(d):
    name = d.get("card_contact_name") or d.get("card_business_name") or "Contact"
    name_parts = name.split()
    if len(name_parts) > 1:
        given = " ".join(name_parts[:-1])
        family = name_parts[-1]
    else:
        given, family = name, ""
    lines = ["BEGIN:VCARD", "VERSION:3.0",
             f"N:{_vcard_escape(family)};{_vcard_escape(given)};;;",
             f"FN:{_vcard_escape(name)}"]
    if d.get("card_business_name"):
        lines.append(f"ORG:{_vcard_escape(d['card_business_name'])}")
    if d.get("card_title"):
        lines.append(f"TITLE:{_vcard_escape(d['card_title'])}")
    if d.get("card_phone"):
        lines.append(f"TEL;TYPE=CELL:{_vcard_escape(d['card_phone'])}")
    if d.get("card_email"):
        lines.append(f"EMAIL;TYPE=WORK:{_vcard_escape(d['card_email'])}")
    if d.get("card_website"):
        lines.append(f"URL:{_vcard_escape(d['card_website'])}")
    if d.get("card_address"):
        lines.append(f"ADR;TYPE=WORK:;;{_vcard_escape(d['card_address'])};;;;")
    if d.get("card_license"):
        lines.append(f"NOTE:License # {_vcard_escape(d['card_license'])}")
    lines.append("END:VCARD")
    return "\r\n".join(lines)


def image_to_data_uri(file_storage):
    raw = file_storage.read()
    if not raw:
        return None, "empty"
    if len(raw) > 1_500_000:
        return None, "too_big"
    mime = file_storage.mimetype or mimetypes.guess_type(file_storage.filename or "")[0] or "image/png"
    return f"data:{mime};base64," + base64.b64encode(raw).decode("ascii"), None


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
    # Clients no longer create accounts — "Become a Client" goes straight to the public intake form.
    return redirect(url_for("intake"))


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
            "pregnant": text("pregnant"),
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
            "promo_opt_in": "promo_opt_in" in request.form,
            "client_signature": text("client_signature"),
            "signed_date": text("signed_date") or now_iso()[:10],
        }
        if not fields["full_name"]:
            conn.close()
            flash("Please enter your full name.")
            return redirect(url_for("intake"))
        if not fields["consent_treatment"] or not fields["consent_cancellation"] or not fields["consent_privacy"]:
            conn.close()
            flash("Please check the required consent boxes to submit your intake form.")
            return redirect(url_for("intake"))
        if not fields["client_signature"]:
            conn.close()
            flash("Please type your name as your signature.")
            return redirect(url_for("intake"))

        # Resolve which client this belongs to. No client login/account is required:
        # find an existing client by email (so re-submitting updates), otherwise create a new client record.
        email = fields["email"].strip().lower()
        existing = None
        if email:
            existing = conn.execute("SELECT id, role FROM users WHERE email = %s", (email,)).fetchone()
        if existing and existing.get("role") == "client":
            user_id = existing["id"]
            conn.execute(
                "UPDATE users SET name = %s, phone = COALESCE(NULLIF(%s,''), phone) WHERE id = %s",
                (fields["full_name"], fields["phone"], user_id)
            )
        else:
            # If the email is taken by a non-client (e.g. the office), store the client without a login email.
            insert_email = None if (existing and existing.get("role") != "client") else (email or None)
            row = conn.execute(
                "INSERT INTO users (role, name, email, phone, password_hash, created_at) "
                "VALUES ('client', %s, %s, %s, %s, %s) RETURNING id",
                (fields["full_name"], insert_email, fields["phone"], "", now_iso())
            ).fetchone()
            user_id = row["id"]

        cols = list(fields.keys())
        params = {**fields, "user_id": user_id, "now": now_iso()}
        collist = "user_id, " + ", ".join(cols) + ", created_at, updated_at"
        placeholders = "%(user_id)s, " + ", ".join(f"%({c})s" for c in cols) + ", %(now)s, %(now)s"
        updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols) + ", updated_at = EXCLUDED.updated_at"
        conn.execute(
            f"INSERT INTO client_intake ({collist}) VALUES ({placeholders}) "
            f"ON CONFLICT (user_id) DO UPDATE SET {updates}",
            params
        )
        conn.commit()
        conn.close()
        return render_template("intake_thanks.html", name=fields["full_name"])

    conn.close()
    return render_template(
        "intake.html",
        intake={},
        user={},
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
            session.permanent = bool(request.form.get("stay_logged_in"))
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
    return render_template("admin_dashboard.html", clients=clients, q=q, total=total,
                           intake_url=url_for("intake", _external=True),
                           business_name=get_setting("card_business_name", APP_NAME))


@app.route("/admin/promotions")
@admin_required
def admin_promotions():
    conn = db()
    clients = conn.execute(
        "SELECT full_name, email FROM client_intake "
        "WHERE promo_opt_in = TRUE AND COALESCE(email, '') <> '' "
        "ORDER BY lower(full_name)"
    ).fetchall()
    conn.close()
    emails = [c["email"] for c in clients]
    return render_template("admin_promotions.html", clients=clients, emails=emails, total=len(clients),
                           business_name=get_setting("card_business_name", APP_NAME))


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


@app.route("/admin/client/<int:client_id>/delete", methods=["POST"])
@admin_required
def admin_client_delete(client_id):
    conn = db()
    client = conn.execute("SELECT id, name FROM users WHERE id = %s AND role = 'client'", (client_id,)).fetchone()
    if not client:
        conn.close()
        flash("Client not found.")
        return redirect(url_for("admin_dashboard"))
    # Deleting the user row also removes their intake (client_intake has ON DELETE CASCADE).
    conn.execute("DELETE FROM users WHERE id = %s AND role = 'client'", (client_id,))
    conn.commit()
    conn.close()
    flash(f'Client "{client["name"]}" was deleted.')
    return redirect(url_for("admin_dashboard"))


# ---------------------------------------------------------------- appointment calendar
APPT_SERVICES = [
    "Swedish Massage", "Deep Tissue", "Hot Stone", "Prenatal Massage",
    "Sports Massage", "Reflexology", "Chair Massage", "Consultation",
]
APPT_DURATIONS = [30, 45, 60, 75, 90, 120]
WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def local_now():
    """Business-local time (the server runs in UTC on Render)."""
    tz_name = get_setting("cal_timezone", "America/New_York") or "America/New_York"
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(tz_name)).replace(tzinfo=None)
    except Exception:
        return datetime.now()


def _parse_hhmm(value, fallback):
    try:
        dtime.fromisoformat(value)
        return value
    except Exception:
        return fallback


def cal_settings():
    open_t = _parse_hhmm(get_setting("cal_open_time", "09:00") or "09:00", "09:00")
    close_t = _parse_hhmm(get_setting("cal_close_time", "18:00") or "18:00", "18:00")
    if close_t <= open_t:
        open_t, close_t = "09:00", "18:00"
    try:
        slot = max(15, min(240, int(get_setting("cal_slot_minutes", "60") or 60)))
    except Exception:
        slot = 60
    closed_raw = get_setting("cal_closed_days", "6")
    closed_days = {int(x) for x in closed_raw.split(",") if x.strip().isdigit() and 0 <= int(x) <= 6}
    return {"open": open_t, "close": close_t, "slot": slot, "closed_days": closed_days}


def fmt12(dt):
    return dt.strftime("%I:%M %p").lstrip("0")


def day_time_options(d, settings):
    """Every slot time between open and close for a given date."""
    out = []
    t = datetime.combine(d, dtime.fromisoformat(settings["open"]))
    end = datetime.combine(d, dtime.fromisoformat(settings["close"]))
    while t < end:
        out.append({"value": t.strftime("%H:%M"), "label": fmt12(t)})
        t += timedelta(minutes=settings["slot"])
    return out


def appointment_conflict(conn, start_at, duration_min, exclude_id=None):
    """Return the booked appointment overlapping [start, start+duration), if any."""
    end_at = start_at + timedelta(minutes=duration_min)
    row = conn.execute(
        "SELECT id, client_name, start_at, duration_min FROM appointments "
        "WHERE status = 'booked' AND id <> %s "
        "AND start_at < %s AND start_at + make_interval(mins => duration_min) > %s "
        "ORDER BY start_at LIMIT 1",
        (exclude_id or 0, end_at, start_at)
    ).fetchone()
    return row


def load_appointment(conn, appt_id):
    return conn.execute("SELECT * FROM appointments WHERE id = %s", (appt_id,)).fetchone()


def clients_for_picker(conn):
    return conn.execute(
        "SELECT id, name, COALESCE(phone,'') AS phone FROM users WHERE role = 'client' ORDER BY lower(name)"
    ).fetchall()


@app.route("/admin/calendar")
@admin_required
def admin_calendar():
    now = local_now()
    settings = cal_settings()
    try:
        y = int(request.args.get("y", now.year))
        m = int(request.args.get("m", now.month))
        d = int(request.args.get("d", 0))
        date(y, m, 1)
    except Exception:
        y, m, d = now.year, now.month, 0
    if d:
        try:
            selected = date(y, m, d)
        except Exception:
            selected = now.date()
    else:
        selected = now.date() if (now.year, now.month) == (y, m) else date(y, m, 1)

    # Month grid (weeks start on Sunday), including spill-over days.
    weeks = pycalendar.Calendar(firstweekday=6).monthdatescalendar(y, m)
    grid_start, grid_end = weeks[0][0], weeks[-1][-1] + timedelta(days=1)

    conn = db()
    month_rows = conn.execute(
        "SELECT id, start_at FROM appointments WHERE status = 'booked' AND start_at >= %s AND start_at < %s",
        (datetime.combine(grid_start, dtime.min), datetime.combine(grid_end, dtime.min))
    ).fetchall()
    counts = {}
    for r in month_rows:
        counts[r["start_at"].date()] = counts.get(r["start_at"].date(), 0) + 1

    day_appts = conn.execute(
        "SELECT a.*, u.name AS linked_name FROM appointments a LEFT JOIN users u ON u.id = a.client_id "
        "WHERE a.start_at >= %s AND a.start_at < %s ORDER BY a.start_at",
        (datetime.combine(selected, dtime.min), datetime.combine(selected + timedelta(days=1), dtime.min))
    ).fetchall()
    clients = clients_for_picker(conn)
    conn.close()

    for a in day_appts:
        a["end_at"] = a["start_at"] + timedelta(minutes=a["duration_min"])
        a["time_label"] = fmt12(a["start_at"]) + " – " + fmt12(a["end_at"])
        a["time_value"] = a["start_at"].strftime("%H:%M")
        a["date_value"] = a["start_at"].strftime("%Y-%m-%d")

    booked = [a for a in day_appts if a["status"] == "booked"]
    slots = []
    t = datetime.combine(selected, dtime.fromisoformat(settings["open"]))
    day_end = datetime.combine(selected, dtime.fromisoformat(settings["close"]))
    step = timedelta(minutes=settings["slot"])
    while t < day_end:
        hit = next((a for a in booked if a["start_at"] < t + step and a["end_at"] > t), None)
        slots.append({
            "label": fmt12(t),
            "value": t.strftime("%H:%M"),
            "appt": hit,
            "starts_here": bool(hit and t <= hit["start_at"] < t + step),
            "past": t < now,
        })
        t += step

    prev_m = date(y, m, 15) - timedelta(days=31)
    next_m = date(y, m, 15) + timedelta(days=31)
    saved_id = request.args.get("saved", type=int)
    saved_appt = next((a for a in day_appts if a["id"] == saved_id), None) if saved_id else None

    return render_template(
        "admin_calendar.html",
        settings=settings, weeks=weeks, counts=counts, year=y, month=m,
        month_label=date(y, m, 1).strftime("%B %Y"),
        prev_y=prev_m.year, prev_m=prev_m.month, next_y=next_m.year, next_m=next_m.month,
        selected=selected, selected_label=selected.strftime("%A, %B %d").replace(" 0", " "),
        today=now.date(), slots=slots, day_appts=day_appts,
        cancelled=[a for a in day_appts if a["status"] == "cancelled"],
        time_options=day_time_options(selected, settings),
        clients=clients, services=APPT_SERVICES, durations=APPT_DURATIONS,
        weekday_names=WEEKDAY_NAMES, closed_today=selected.weekday() in settings["closed_days"],
        saved_appt=saved_appt,
    )


def _appointment_fields_from_form():
    client_id = request.form.get("client_id", type=int) or None
    name = request.form.get("client_name", "").strip()
    phone = request.form.get("client_phone", "").strip()
    service = request.form.get("service", "").strip()
    notes = request.form.get("notes", "").strip()
    duration = request.form.get("duration_min", type=int) or 60
    if duration not in APPT_DURATIONS:
        duration = max(15, min(240, duration))
    try:
        start_at = datetime.combine(
            date.fromisoformat(request.form.get("date", "")),
            dtime.fromisoformat(request.form.get("time", ""))
        )
    except Exception:
        start_at = None
    return client_id, name, phone, service, notes, duration, start_at


def _back_to_day(d, extra=""):
    return redirect(url_for("admin_calendar", y=d.year, m=d.month, d=d.day) + extra)


@app.route("/admin/calendar/new", methods=["POST"])
@admin_required
def admin_calendar_new():
    client_id, name, phone, service, notes, duration, start_at = _appointment_fields_from_form()
    if not start_at:
        flash("Please pick a valid date and time.")
        return redirect(url_for("admin_calendar"))
    if not name:
        flash("Please enter the client's name.")
        return _back_to_day(start_at.date())
    conn = db()
    clash = appointment_conflict(conn, start_at, duration)
    if clash:
        conn.close()
        flash(f'That time overlaps {clash["client_name"]} at {fmt12(clash["start_at"])}. Pick another slot.')
        return _back_to_day(start_at.date())
    row = conn.execute(
        "INSERT INTO appointments (client_id, client_name, client_phone, service, start_at, duration_min, notes, status, created_at, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, 'booked', %s, %s) RETURNING id",
        (client_id, name, phone, service, start_at, duration, notes, now_iso(), now_iso())
    ).fetchone()
    conn.commit()
    conn.close()
    return _back_to_day(start_at.date(), f'&saved={row["id"]}')


@app.route("/admin/appointment/<int:appt_id>/update", methods=["POST"])
@admin_required
def admin_appointment_update(appt_id):
    action = request.form.get("action", "save")
    conn = db()
    appt = load_appointment(conn, appt_id)
    if not appt:
        conn.close()
        flash("Appointment not found.")
        return redirect(url_for("admin_calendar"))

    if action in ("complete", "cancel"):
        new_status = "completed" if action == "complete" else "cancelled"
        conn.execute("UPDATE appointments SET status = %s, updated_at = %s WHERE id = %s",
                     (new_status, now_iso(), appt_id))
        conn.commit()
        conn.close()
        flash("Appointment marked completed." if action == "complete" else "Appointment cancelled — that slot is open again.")
        return _back_to_day(appt["start_at"].date())

    if action == "rebook":
        clash = appointment_conflict(conn, appt["start_at"], appt["duration_min"], exclude_id=appt_id)
        if clash:
            conn.close()
            flash(f'Cannot rebook — that time now overlaps {clash["client_name"]} at {fmt12(clash["start_at"])}.')
            return _back_to_day(appt["start_at"].date())
        conn.execute("UPDATE appointments SET status = 'booked', updated_at = %s WHERE id = %s", (now_iso(), appt_id))
        conn.commit()
        conn.close()
        flash("Appointment re-booked.")
        return _back_to_day(appt["start_at"].date())

    if action == "delete":
        conn.execute("DELETE FROM appointments WHERE id = %s", (appt_id,))
        conn.commit()
        conn.close()
        flash("Appointment deleted.")
        return _back_to_day(appt["start_at"].date())

    # action == "save": edit details / move time
    client_id, name, phone, service, notes, duration, start_at = _appointment_fields_from_form()
    if not start_at or not name:
        conn.close()
        flash("Please enter a name and a valid date and time.")
        return _back_to_day(appt["start_at"].date())
    if appt["status"] == "booked":
        clash = appointment_conflict(conn, start_at, duration, exclude_id=appt_id)
        if clash:
            conn.close()
            flash(f'That time overlaps {clash["client_name"]} at {fmt12(clash["start_at"])}. Pick another slot.')
            return _back_to_day(appt["start_at"].date())
    conn.execute(
        "UPDATE appointments SET client_id = %s, client_name = %s, client_phone = %s, service = %s, "
        "start_at = %s, duration_min = %s, notes = %s, updated_at = %s WHERE id = %s",
        (client_id, name, phone, service, start_at, duration, notes, now_iso(), appt_id)
    )
    conn.commit()
    conn.close()
    flash("Appointment updated.")
    return _back_to_day(start_at.date(), f"&saved={appt_id}")


def _ics_escape(v):
    return str(v or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


@app.route("/admin/appointment/<int:appt_id>.ics")
@admin_required
def admin_appointment_ics(appt_id):
    conn = db()
    appt = load_appointment(conn, appt_id)
    conn.close()
    if not appt:
        flash("Appointment not found.")
        return redirect(url_for("admin_calendar"))
    start = appt["start_at"]
    end = start + timedelta(minutes=appt["duration_min"])
    business = get_setting("card_business_name", APP_NAME)
    address = get_setting("card_address", "")
    summary = f'{appt["service"] or "Appointment"} – {appt["client_name"]}'
    desc_parts = [f'Client: {appt["client_name"]}']
    if appt["client_phone"]:
        desc_parts.append(f'Phone: {appt["client_phone"]}')
    if appt["notes"]:
        desc_parts.append(f'Notes: {appt["notes"]}')
    desc_parts.append(f'Booked with {business}')
    # Floating local times so the event lands at the right wall-clock time on the phone.
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:-//{_ics_escape(business)}//Appointments//EN",
        "BEGIN:VEVENT",
        f"UID:metime-appt-{appt['id']}@metime",
        "DTSTAMP:" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "DTSTART:" + start.strftime("%Y%m%dT%H%M%S"),
        "DTEND:" + end.strftime("%Y%m%dT%H%M%S"),
        f"SUMMARY:{_ics_escape(summary)}",
        f"DESCRIPTION:{_ics_escape(chr(10).join(desc_parts))}",
    ]
    if address:
        lines.append(f"LOCATION:{_ics_escape(address)}")
    lines += [
        "BEGIN:VALARM", "TRIGGER:-PT1H", "ACTION:DISPLAY",
        f"DESCRIPTION:{_ics_escape('Upcoming appointment: ' + summary)}", "END:VALARM",
        "BEGIN:VALARM", "TRIGGER:-PT24H", "ACTION:DISPLAY",
        f"DESCRIPTION:{_ics_escape('Tomorrow: ' + summary)}", "END:VALARM",
        "END:VEVENT", "END:VCALENDAR",
    ]
    return Response("\r\n".join(lines), mimetype="text/calendar",
                    headers={"Content-Disposition": f"inline; filename=appointment-{appt['id']}.ics"})


@app.route("/admin/api/upcoming")
@admin_required
def admin_api_upcoming():
    """Booked appointments for the next 7 days — powers the in-app reminders."""
    now = local_now()
    conn = db()
    rows = conn.execute(
        "SELECT id, client_name, service, start_at, duration_min FROM appointments "
        "WHERE status = 'booked' AND start_at >= %s AND start_at < %s ORDER BY start_at",
        (now - timedelta(hours=3), now + timedelta(days=7))
    ).fetchall()
    conn.close()
    return jsonify({
        "now": now.strftime("%Y-%m-%dT%H:%M:%S"),
        "appointments": [{
            "id": r["id"],
            "client": r["client_name"],
            "service": r["service"] or "Appointment",
            "start": r["start_at"].strftime("%Y-%m-%dT%H:%M:%S"),
            "label": r["start_at"].strftime("%a %b %d, ") + fmt12(r["start_at"]),
            "duration": r["duration_min"],
        } for r in rows],
    })


@app.route("/admin/calendar/settings", methods=["POST"])
@admin_required
def admin_calendar_settings():
    open_t = _parse_hhmm(request.form.get("open_time", ""), "09:00")
    close_t = _parse_hhmm(request.form.get("close_time", ""), "18:00")
    if close_t <= open_t:
        flash("Closing time must be after opening time — hours were not changed.")
    else:
        set_setting("cal_open_time", open_t)
        set_setting("cal_close_time", close_t)
    try:
        slot = max(15, min(240, int(request.form.get("slot_minutes", "60"))))
        set_setting("cal_slot_minutes", str(slot))
    except Exception:
        pass
    closed = [v for v in request.form.getlist("closed_days") if v.isdigit() and 0 <= int(v) <= 6]
    set_setting("cal_closed_days", ",".join(closed))
    flash("Calendar settings saved.")
    d = request.form.get("return_day", "")
    try:
        rd = date.fromisoformat(d)
        return _back_to_day(rd)
    except Exception:
        return redirect(url_for("admin_calendar"))


# ---------------------------------------------------------------- SMS appointment reminders
DEFAULT_REMINDER_24H = ("Hi {name}, reminder from {biz}: your {service} appointment is on {date} at {time}. "
                        "Call us if you need to reschedule. Reply STOP to opt out.")
DEFAULT_REMINDER_6H = ("Hi {name}, reminder from {biz}: your {service} appointment is today at {time}. "
                       "See you soon! Reply STOP to opt out.")


def sms_setting(db_key, env_key, default=""):
    """DB setting wins (editable in the admin panel); falls back to an environment variable."""
    val = (get_setting(db_key, "") or "").strip()
    if val:
        return val
    return os.environ.get(env_key, default)


def twilio_sid():
    return sms_setting("twilio_account_sid", "TWILIO_ACCOUNT_SID")


def twilio_token():
    return sms_setting("twilio_auth_token", "TWILIO_AUTH_TOKEN")


def twilio_from():
    return sms_setting("twilio_from_number", "TWILIO_FROM_NUMBER")


def reminders_enabled():
    return get_setting("sms_reminders_enabled", "0") == "1"


def sms_configured():
    return bool(twilio_sid() and twilio_token() and twilio_from())


def cron_secret():
    secret = (get_setting("cron_secret", "") or "").strip() or os.environ.get("CRON_SECRET", "").strip()
    if not secret:
        secret = secrets.token_urlsafe(18)
        try:
            set_setting("cron_secret", secret)
        except Exception:
            pass
    return secret


def phone_to_e164(raw, default_country="1"):
    raw = (raw or "").strip()
    if not raw:
        return ""
    digits = re.sub(r"[^0-9]", "", raw)
    if not digits:
        return ""
    if raw.startswith("+"):
        return "+" + digits
    if len(digits) == 10:
        return "+" + default_country + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    return "+" + digits


def send_sms(to, body):
    """Send one text through Twilio's REST API (stdlib only). Returns (ok, error)."""
    sid, token, from_num = twilio_sid(), twilio_token(), twilio_from()
    if not (sid and token and from_num):
        return False, "SMS is not configured."
    if not to:
        return False, "No phone number."
    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    data = urllib.parse.urlencode({"To": to, "From": from_num, "Body": body}).encode()
    auth = base64.b64encode(f"{sid}:{token}".encode()).decode()
    req = urllib.request.Request(url, data=data, headers={"Authorization": "Basic " + auth})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return (200 <= resp.status < 300), None
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode()[:300]
        except Exception:
            pass
        return False, f"Twilio error {e.code}: {detail}"
    except Exception as e:
        return False, str(e)


def render_reminder_text(kind, appt):
    biz = get_setting("card_business_name", APP_NAME) or APP_NAME
    start = appt["start_at"]
    template = get_setting(
        "reminder_24h_template" if kind == "24h" else "reminder_6h_template",
        DEFAULT_REMINDER_24H if kind == "24h" else DEFAULT_REMINDER_6H,
    )
    fields = {
        "name": (appt.get("client_name") or "there").split(" ")[0],
        "biz": biz,
        "service": appt.get("service") or "appointment",
        "date": start.strftime("%A, %b %d").replace(" 0", " "),
        "time": fmt12(start),
    }
    try:
        return template.format(**fields)
    except Exception:
        return DEFAULT_REMINDER_24H.format(**fields) if kind == "24h" else DEFAULT_REMINDER_6H.format(**fields)


_reminder_lock = threading.Lock()
_last_reminder_sweep = [0.0]


def send_due_reminders():
    """Send any 24h / 6h reminders that are now due. Safe to call repeatedly."""
    if not reminders_enabled():
        return {"skipped": "disabled"}
    if not _reminder_lock.acquire(blocking=False):
        return {"skipped": "busy"}
    result = {"sent_24h": 0, "sent_6h": 0, "skipped_no_phone": 0, "skipped_no_consent": 0, "failed": 0}
    try:
        conn = db()
        now = local_now()
        rows = conn.execute(
            """
            SELECT a.*, ci.consent_reminders AS consent
            FROM appointments a
            LEFT JOIN client_intake ci ON ci.user_id = a.client_id
            WHERE a.status = 'booked'
              AND a.start_at > %s
              AND a.start_at <= %s
              AND (a.reminder_24h_sent_at IS NULL OR a.reminder_6h_sent_at IS NULL)
            ORDER BY a.start_at
            """,
            (now, now + timedelta(hours=24))
        ).fetchall()
        for a in rows:
            hrs = (a["start_at"] - now).total_seconds() / 3600.0
            phone = phone_to_e164(a.get("client_phone"))
            # A linked client who explicitly declined reminders is skipped; walk-ins are allowed.
            consent_ok = (a.get("client_id") is None) or (a.get("consent") is None) or bool(a.get("consent"))

            for kind, col, lo, hi in (("24h", "reminder_24h_sent_at", 6, 24), ("6h", "reminder_6h_sent_at", 0, 6)):
                if a.get(col) is not None:
                    continue
                if not (lo < hrs <= hi):
                    continue
                if not phone:
                    result["skipped_no_phone"] += 1
                    conn.execute(f"UPDATE appointments SET {col} = %s WHERE id = %s", (now_iso(), a["id"]))
                    continue
                if not consent_ok:
                    result["skipped_no_consent"] += 1
                    conn.execute(f"UPDATE appointments SET {col} = %s WHERE id = %s", (now_iso(), a["id"]))
                    continue
                ok, err = send_sms(phone, render_reminder_text(kind, a))
                if ok:
                    result["sent_24h" if kind == "24h" else "sent_6h"] += 1
                    conn.execute(f"UPDATE appointments SET {col} = %s WHERE id = %s", (now_iso(), a["id"]))
                else:
                    # Leave unstamped so a later sweep retries once the config/number is fixed.
                    result["failed"] += 1
                    print(f"reminder SMS failed for appt {a['id']}: {err}")
            conn.commit()
        conn.close()
    except Exception as e:
        print("send_due_reminders failed:", e)
        result["error"] = str(e)
    finally:
        _reminder_lock.release()
    return result


@app.before_request
def _reminder_sweep_hook():
    # Fallback trigger: run the sweep in the background at most once every 5 minutes on live
    # traffic, so reminders still go out even without an external cron pinger. Never blocks the request.
    try:
        now = time.time()
        if now - _last_reminder_sweep[0] < 300:
            return
        _last_reminder_sweep[0] = now
        if reminders_enabled():
            threading.Thread(target=send_due_reminders, daemon=True).start()
    except Exception:
        pass


@app.route("/cron/send-reminders", methods=["GET", "POST"])
def cron_send_reminders():
    if request.args.get("key", "") != cron_secret():
        return Response("forbidden", status=403)
    return jsonify(send_due_reminders())


@app.route("/admin/reminders", methods=["GET", "POST"])
@admin_required
def admin_reminders():
    if request.method == "POST":
        action = request.form.get("action", "save")
        if action == "test":
            to = phone_to_e164(request.form.get("test_phone", ""))
            if not sms_configured():
                flash("Enter and save your Twilio Account SID, Auth Token, and From number first.")
            elif not to:
                flash("Enter a valid phone number to send the test to.")
            else:
                biz = get_setting("card_business_name", APP_NAME) or APP_NAME
                ok, err = send_sms(to, f"Test message from {biz}: your appointment reminders are working. Reply STOP to opt out.")
                flash("Test text sent." if ok else f"Test failed — {err}")
            return redirect(url_for("admin_reminders"))

        set_setting("sms_reminders_enabled", "1" if request.form.get("enabled") else "0")
        set_setting("twilio_account_sid", request.form.get("twilio_account_sid", "").strip())
        # Only overwrite the token if a new one was typed (the field shows a masked placeholder).
        new_token = request.form.get("twilio_auth_token", "").strip()
        if new_token and set(new_token) != {"•"} and "•" not in new_token:
            set_setting("twilio_auth_token", new_token)
        set_setting("twilio_from_number", request.form.get("twilio_from_number", "").strip())
        set_setting("reminder_24h_template", request.form.get("reminder_24h_template", "").strip() or DEFAULT_REMINDER_24H)
        set_setting("reminder_6h_template", request.form.get("reminder_6h_template", "").strip() or DEFAULT_REMINDER_6H)
        flash("Reminder settings saved.")
        return redirect(url_for("admin_reminders"))

    token = twilio_token()
    cron_url = url_for("cron_send_reminders", key=cron_secret(), _external=True)
    return render_template(
        "admin_reminders.html",
        enabled=reminders_enabled(),
        configured=sms_configured(),
        twilio_account_sid=twilio_sid(),
        token_set=bool(token),
        twilio_from_number=twilio_from(),
        reminder_24h_template=get_setting("reminder_24h_template", DEFAULT_REMINDER_24H),
        reminder_6h_template=get_setting("reminder_6h_template", DEFAULT_REMINDER_6H),
        cron_url=cron_url,
    )


# ---------------------------------------------------------------- business card
@app.route("/admin/card", methods=["GET", "POST"])
@admin_required
def admin_card():
    if request.method == "POST":
        for k in CARD_TEXT_KEYS:
            set_setting(k, request.form.get(k, "").strip())
        banner = request.files.get("card_banner")
        if banner and banner.filename:
            uri, err = image_to_data_uri(banner)
            if err == "too_big":
                flash("Banner image is too large — keep it under 1.5 MB.")
            elif uri:
                set_setting("card_banner_data", uri)
        elif request.form.get("remove_banner"):
            set_setting("card_banner_data", "")
        photo = request.files.get("card_photo")
        if photo and photo.filename:
            uri, err = image_to_data_uri(photo)
            if err == "too_big":
                flash("Photo image is too large — keep it under 1.5 MB.")
            elif uri:
                set_setting("card_photo_data", uri)
        elif request.form.get("remove_photo"):
            set_setting("card_photo_data", "")
        flash("Business card saved.")
        return redirect(url_for("admin_card"))
    return render_template("admin_card.html", d=card_data())


@app.route("/card")
def card():
    d = card_data()
    try:
        card_url = url_for("card", _external=True)
    except Exception:
        card_url = ""
    is_admin = session.get("role") == "admin"
    if is_admin:
        back_url = url_for("admin_dashboard")
    elif session.get("user_id"):
        back_url = url_for("home")
    else:
        back_url = url_for("index")
    return render_template(
        "card.html",
        d=d,
        card_url=card_url,
        website_url=normalized_website_url(d.get("card_website")),
        instagram_url=social_url("instagram", d.get("card_instagram")),
        facebook_url=social_url("facebook", d.get("card_facebook")),
        qr_svg=card_qr_svg(card_url),
        is_admin=is_admin,
        back_url=back_url,
    )


@app.route("/card.vcf")
def card_vcf():
    d = card_data()
    text = card_vcard_text(d)
    fname = secure_filename(d.get("card_business_name") or "contact") or "contact"
    # Serve inline (not as an attachment) so phones open the "Add Contact" screen
    # with the fields pre-filled instead of just downloading a file.
    return Response(text, mimetype="text/vcard",
                    headers={"Content-Disposition": f"inline; filename={fname}.vcf"})


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

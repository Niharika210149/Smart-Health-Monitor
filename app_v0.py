#!/usr/bin/env python3
"""
Regenerated Flask app (app_v0.py)

This version is designed to be robust with your existing SQLite DB.
It does not assume the DB schema — instead it:
  - Defines the expected application model (pulse_sp02_data with CSV-preserved fields)
  - Ensures missing columns are added automatically via ALTER TABLE when possible
  - Imports /mnt/data/spo2.csv on first run mapping person_id -> user_id
  - Creates user_auth rows for each person_id if missing
  - Provides routes: login, dashboard (Recent/Analysis/Reports/Admin/About), API endpoints, admin actions

Security / Notes:
 - Plaintext password storage remains available for demo only (plain_pwd column). Do NOT use in production.
 - The app will inspect and alter the SQLite table at startup. If your DB is critical, BACK IT UP before running.
 - I could not read your local DB from here; this script will read and adapt at runtime when you run it locally.

Run:
  pip install -r requirements.txt  # flask flask_sqlalchemy flask_login cryptography
  python app_v0.py

"""

import os
import csv
import sqlite3
from datetime import datetime, date, timedelta
from pathlib import Path

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, current_user, logout_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import timezone, timedelta
IST = timezone(timedelta(hours=5, minutes=30))

try:
    from cryptography.fernet import Fernet
except Exception:
    Fernet = None

# --- Paths & config ---
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / 'data'
TEMPLATES_DIR = BASE_DIR / 'templates'
STATIC_DIR = BASE_DIR / 'static'
DB_PATH = DATA_DIR / 'app.db'
CSV_SEED_PATH = Path('/mnt/data/spo2.csv')

SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-please-change')
FERNET_KEY = os.environ.get('FERNET_KEY')
if FERNET_KEY is None and Fernet is not None:
    FERNET_KEY = Fernet.generate_key().decode()

for d in (DATA_DIR, TEMPLATES_DIR, STATIC_DIR, STATIC_DIR / 'css', STATIC_DIR / 'js', STATIC_DIR / 'img'):
    d.mkdir(parents=True, exist_ok=True)

# --- Flask app ---
app = Flask(__name__, template_folder=str(TEMPLATES_DIR), static_folder=str(STATIC_DIR))
app.config['SECRET_KEY'] = SECRET_KEY
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DB_PATH}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# --- Encryption helper ---
fernet = None
if Fernet is not None and FERNET_KEY:
    try:
        fernet = Fernet(FERNET_KEY.encode())
    except Exception:
        fernet = None


def encrypt_pwd(plaintext: str) -> str:
    if fernet:
        return fernet.encrypt(plaintext.encode()).decode()
    return ''


def decrypt_pwd(token: str) -> str:
    if fernet and token:
        try:
            return fernet.decrypt(token.encode()).decode()
        except Exception:
            return ''
    return ''

# --- Expected schema for pulse_sp02_data (CSV-preserving) ---
EXPECTED_PULSE_COLS = {
    'id':'INTEGER PRIMARY KEY',
    'user_id':'TEXT',
    'gender':'TEXT',
    'age':'INTEGER',
    'age_group':'TEXT',
    'is_exercise':'TEXT',
    'session_val':'TEXT',
    'reading_no':'INTEGER',
    'csv_date':'TEXT',
    'csv_time':'TEXT',
    'csv_period':'TEXT',
    'activity':'TEXT',
    'hr_raw':'REAL',
    'spo2_raw':'REAL',
    'recorded_at':'TEXT',
    'pulse':'INTEGER',
    'spo2':'INTEGER',
    'context':'TEXT',
    'created_at':'DATETIME'
}

# Ensure DB file location exists
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# --- Helper to ensure columns exist in SQLite ---
def ensure_columns(db_path: str, table: str, expected: dict):
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute(f"PRAGMA table_info({table});")
    rows = cur.fetchall()
    existing = {r[1] for r in rows}
    for col, coltype in expected.items():
        if col in existing:
            continue
        if col == 'id':
            # primary key should already exist; skip trying to add
            continue
        sql = f"ALTER TABLE {table} ADD COLUMN {col} {coltype};"
        try:
            cur.execute(sql)
            print(f"ensure_columns: added column {col} {coltype}")
        except Exception as e:
            print('ensure_columns: failed to add', col, '->', e)
    con.commit()
    con.close()


def dt_to_iso_utc(dt):
    """Return ISO8601 string in UTC (so JS Date() shows local time correctly)."""
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)  # assume saved in IST
    utc_dt = dt.astimezone(timezone.utc)
    return utc_dt.strftime('%Y-%m-%dT%H:%M:%SZ')



# --- Models (SQLAlchemy) ---
class PulseSpO2(db.Model):
    __tablename__ = 'pulse_sp02_data'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String, index=True, nullable=False)
    gender = db.Column(db.String)
    age = db.Column(db.Integer)
    age_group = db.Column(db.String)
    is_exercise = db.Column(db.String)
    session_val = db.Column(db.String)
    reading_no = db.Column(db.Integer)
    csv_date = db.Column(db.String)
    csv_time = db.Column(db.String)
    csv_period = db.Column(db.String)
    activity = db.Column(db.String)
    hr_raw = db.Column(db.Float)
    spo2_raw = db.Column(db.Float)
    recorded_at = db.Column(db.DateTime)
    pulse = db.Column(db.Integer)
    spo2 = db.Column(db.Integer)
    context = db.Column(db.String)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class UserAuth(UserMixin, db.Model):
    __tablename__ = 'user_auth'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String, unique=True, nullable=False)
    plain_pwd = db.Column(db.String)          # demo only — insecure
    encrypted_pwd = db.Column(db.String)      # fernet encrypted
    pwd_hash = db.Column(db.String)           # werkzeug hash for authentication
    role = db.Column(db.String, default='user')
    is_private = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class HealthScores(db.Model):
    __tablename__ = 'health_scores'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String, index=True, nullable=False)
    score_date = db.Column(db.Date, nullable=False)
    sleep_score = db.Column(db.Integer)
    exercise_score = db.Column(db.Integer)
    resting_hr_score = db.Column(db.Integer)
    spo2_score = db.Column(db.Integer)
    overall_score = db.Column(db.Integer)
    notes = db.Column(db.String)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class FamilyMapping(db.Model):
    __tablename__ = 'family_mapping'
    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.String, index=True, nullable=False)
    member_user_id = db.Column(db.String, nullable=False)
    is_head = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# --- Login loader ---
@login_manager.user_loader
@login_manager.user_loader
def load_user(user_id):
    try:
        # Use session.get to avoid legacy Query.get warning
        return db.session.get(UserAuth, int(user_id))
    except Exception:
        return None

# --- Scoring helpers (same as before) ---
def spo2_to_score(spo2):
    if spo2 is None:
        return 0
    if spo2 >= 98:
        return 100
    if spo2 >= 95:
        return 90 + (spo2 - 95) * 2
    if spo2 >= 90:
        return int(60 + (spo2 - 90) * 7.25)
    return int(max(0, 30 - (90 - spo2) * 5))

def resting_hr_score(hr):
    if hr is None:
        return 0
    if 60 <= hr <= 80:
        return 100
    if 50 <= hr < 60 or 81 <= hr <= 90:
        return 70
    if 45 <= hr < 50 or 91 <= hr <= 100:
        return 50
    return 20

def sleep_to_score(hours):
    if hours is None:
        return 0
    if 7 <= hours <= 9:
        return 100
    if 6 <= hours < 7:
        return 80
    if 5 <= hours < 6:
        return 60
    if hours < 5:
        return 30
    return 80

def exercise_to_score(minutes):
    if minutes is None:
        return 0
    if minutes >= 30:
        return 100
    return int(minutes / 30 * 100)

def compute_daily_score_for_user(user_id, target_date=None):
    if target_date is None:
        day_end = datetime.utcnow()
        day_start = day_end - timedelta(days=1)
    else:
        day_start = datetime.combine(target_date, datetime.min.time())
        day_end = datetime.combine(target_date, datetime.max.time())
    readings = PulseSpO2.query.filter(PulseSpO2.user_id == user_id,
                                      PulseSpO2.recorded_at >= day_start,
                                      PulseSpO2.recorded_at <= day_end).all()
    if not readings:
        return None
    spo2_vals = [r.spo2 for r in readings if r.spo2 is not None]
    pulse_vals = [r.pulse for r in readings if r.pulse is not None]
    sleep_minutes = sum(1 for r in readings if r.activity and 'sleep' in r.activity.lower())
    exercise_minutes = sum(1 for r in readings if r.activity and ('exercise' in r.activity.lower() or 'walk' in r.activity.lower()))
    sleep_hours = sleep_minutes / 60.0
    exercise_mins = exercise_minutes
    avg_spo2 = int(sum(spo2_vals) / len(spo2_vals)) if spo2_vals else None
    avg_pulse = int(sum(pulse_vals) / len(pulse_vals)) if pulse_vals else None
    s_spo2 = spo2_to_score(avg_spo2)
    s_hr = resting_hr_score(avg_pulse)
    s_sleep = sleep_to_score(sleep_hours)
    s_ex = exercise_to_score(exercise_mins)
    overall = int(0.3 * s_sleep + 0.25 * s_ex + 0.25 * s_spo2 + 0.2 * s_hr)
    hs = HealthScores(user_id=user_id,
                      score_date=(target_date or date.today()),
                      sleep_score=int(s_sleep),
                      exercise_score=int(s_ex),
                      resting_hr_score=int(s_hr),
                      spo2_score=int(s_spo2),
                      overall_score=overall,
                      notes='Auto-computed')
    db.session.add(hs)
    db.session.commit()
    return hs

# --- CSV parsing helpers ---

def parse_recorded_at(csv_date, csv_time, csv_period):
    if not csv_date:
        return None

    dt_part = None
    # Try day-first dd/mm/YYYY then ISO YYYY-MM-DD
    for fmt in ('%d/%m/%Y', '%Y-%m-%d'):
        try:
            dt_part = datetime.strptime(csv_date.strip(), fmt).date()
            break
        except Exception:
            dt_part = None

    if dt_part is None:
        try:
            dt_part = datetime.fromisoformat(csv_date.strip()).date()
        except Exception:
            return None

    time_str = (csv_time or '').strip()
    period = (csv_period or '').strip().upper()

    if not time_str:
        return datetime.combine(dt_part, datetime.min.time())

    # Try a couple of time formats
    t = None
    try:
        # prefer HH:MM:SS or H:MM:SS
        if period in ('AM', 'PM'):
            t = datetime.strptime(time_str + ' ' + period, '%I:%M:%S %p').time()
        else:
            t = datetime.strptime(time_str, '%H:%M:%S').time()
    except Exception:
        try:
            if period in ('AM', 'PM'):
                t = datetime.strptime(time_str + ' ' + period, '%I:%M %p').time()
            else:
                t = datetime.strptime(time_str, '%H:%M').time()
        except Exception:
            # fallback to midnight of that day
            return datetime.combine(dt_part, datetime.min.time())

    return datetime.combine(dt_part, t)

# --- DB init & import ---

def seed_from_csv(path: Path):
    print('Seeding from CSV:', path)
    with path.open('r', encoding='utf-8', errors='ignore') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    added = 0
    for r in rows:
        pid = r.get('person_id') or r.get('user_id') or r.get('person') or 'unknown'
        gender = r.get('gender')
        try:
            age = int(float(r.get('age'))) if r.get('age') else None
        except Exception:
            age = None
        age_group = r.get('age_group')
        # handle various ambiguous merged columns conservatively
        is_exercise = r.get('is_exercise') or r.get('is_exercise...reading_no') or None
        session_val = r.get('session_val') or r.get('session') or None
        try:
            reading_no = int(float(r.get('reading_no'))) if r.get('reading_no') else None
        except Exception:
            reading_no = None
        raw_date = r.get('date') or r.get('Date')
        raw_time = r.get('time') or r.get('Time')
        raw_period = r.get('period') or r.get('Period')
        activity = r.get('activity')
        try:
            hr_raw = float(r.get('hr')) if r.get('hr') else None
        except Exception:
            hr_raw = None
        try:
            spo2_raw = float(r.get('spo2')) if r.get('spo2') else None
        except Exception:
            spo2_raw = None
        recorded_at = parse_recorded_at(raw_date, raw_time, raw_period)
        if recorded_at and recorded_at.tzinfo is None:
            try:
                recorded_at = recorded_at.replace(tzinfo=IST)
            except Exception:
                pass

        pulse = int(round(hr_raw)) if hr_raw is not None else None
        spo2 = int(round(spo2_raw)) if spo2_raw is not None else None
        p = PulseSpO2(user_id=str(pid), gender=gender, age=age, age_group=age_group,
                      is_exercise=is_exercise, session_val=session_val, reading_no=reading_no,
                      csv_date=raw_date, csv_time=raw_time, csv_period=raw_period,
                      activity=activity, hr_raw=hr_raw, spo2_raw=spo2_raw,
                      recorded_at=recorded_at, pulse=pulse, spo2=spo2)
        db.session.add(p)
        # ensure user_auth exists
        if not UserAuth.query.filter_by(user_id=pid).first():
            ua = UserAuth(user_id=pid, plain_pwd=None, encrypted_pwd=encrypt_pwd('changeme'), pwd_hash=generate_password_hash('changeme'), role='user')
            db.session.add(ua)
        added += 1
        if added % 500 == 0:
            db.session.commit()
    db.session.commit()
    print(f'Added {added} rows to pulse_sp02_data')

def init_db():
    with app.app_context():
        # create tables if missing (does nothing to alter existing tables)
        db.create_all()
        # ensure pulse_sp02_data has expected columns (adds missing ones)
        ensure_columns(str(DB_PATH), 'pulse_sp02_data', EXPECTED_PULSE_COLS)
        # create demo admin if missing
        if not UserAuth.query.filter_by(user_id='admin').first():
            admin = UserAuth(user_id='admin', plain_pwd='AdminPass123', encrypted_pwd=encrypt_pwd('AdminPass123'), pwd_hash=generate_password_hash('AdminPass123'), role='admin')
            db.session.add(admin)
            db.session.commit()
            print('Created admin user (admin / AdminPass123)')
        # seed CSV if present and if table empty
        count = PulseSpO2.query.count()
        if CSV_SEED_PATH.exists() and count == 0:
            print('CSV found and table empty — importing...')
            seed_from_csv(CSV_SEED_PATH)
        else:
            print('Skipping CSV import (either not present or table already has data)', CSV_SEED_PATH.exists(), 'rows=', count)

# --- Routes & APIs ---
@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html')
    user_id = request.form.get('user_id')
    password = request.form.get('password')
    user = UserAuth.query.filter_by(user_id=user_id).first()
    if not user:
        flash('Invalid credentials')
        return redirect(url_for('index'))
    if user.pwd_hash and check_password_hash(user.pwd_hash, password):
        login_user(user)
        flash('Logged in')
        return redirect(url_for('dashboard'))
    flash('Invalid credentials')
    return redirect(url_for('index'))

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html')

@app.route('/api/recent-data')
@login_required
def api_recent_data():
    target_user = request.args.get('user_id') or current_user.user_id

    # Restrict access unless admin or same user
    if current_user.role != 'admin' and target_user != current_user.user_id:
        return jsonify([])

    # Find the most recent recorded date
    latest_record = (
        PulseSpO2.query.filter_by(user_id=target_user)
        .filter(PulseSpO2.recorded_at.isnot(None))
        .order_by(PulseSpO2.recorded_at.desc())
        .first()
    )

    if not latest_record:
        return jsonify([])

    # Extract just the date (ignore time)
    latest_date = latest_record.recorded_at.date()

    # Fetch all records from that date
    rows = (
        PulseSpO2.query.filter_by(user_id=target_user)
        .filter(
            db.func.date(PulseSpO2.recorded_at) == latest_date
        )
        .order_by(PulseSpO2.recorded_at.asc())
        .all()
    )

    out = [
        {
            'recorded_at': dt_to_iso_utc(r.recorded_at),
            'pulse': r.pulse,
            'spo2': r.spo2,
            'activity': r.activity,
        }
        for r in rows
    ]

    return jsonify(out)

@app.route('/api/summary')
@login_required
def api_summary():
    target_user = request.args.get('user_id') or current_user.user_id
    if current_user.role != 'admin' and target_user != current_user.user_id:
        return jsonify({})

    rows = PulseSpO2.query.filter_by(user_id=target_user).all()
    if not rows:
        return jsonify({})

    spo2_vals = [r.spo2 for r in rows if r.spo2 is not None]
    pulse_vals = [r.pulse for r in rows if r.pulse is not None]

    def stats(vals):
        if not vals:
            return {'avg': None, 'min': None, 'max': None}
        return {'avg': int(sum(vals) / len(vals)), 'min': min(vals), 'max': max(vals)}

    return jsonify({
        'count': len(rows),
        'spo2': stats(spo2_vals),
        'pulse': stats(pulse_vals),
        'abnormal_spo2_count': sum(1 for v in spo2_vals if v < 90),
        'abnormal_hr_count': sum(1 for v in pulse_vals if v < 50 or v > 120),
    })

@app.route('/api/data')
@login_required
def api_data():
    target_user = request.args.get('user_id') or current_user.user_id
    q = PulseSpO2.query.filter_by(user_id=target_user)
    ffrom = request.args.get('from')
    fto = request.args.get('to')
    if ffrom:
        try:
            d = datetime.fromisoformat(ffrom)
            q = q.filter(PulseSpO2.recorded_at >= d)
        except Exception:
            pass
    if fto:
        try:
            d = datetime.fromisoformat(fto)
            q = q.filter(PulseSpO2.recorded_at <= d)
        except Exception:
            pass
    activity = request.args.get('activity')
    if activity:
        q = q.filter(PulseSpO2.activity.ilike(f'%{activity}%'))
    rows = q.order_by(PulseSpO2.recorded_at.asc()).limit(2000).all()
    out = [
        {
            'recorded_at': dt_to_iso_utc(r.recorded_at),
            'pulse': r.pulse,
            'spo2': r.spo2,
            'activity': r.activity
        }
        for r in rows
    ]

    return jsonify(out)


@app.route('/api/sensor-data', methods=['POST'])
def api_sensor_data():
    """
    Receive sensor data (JSON) and insert into pulse_sp02_data.

    Accepts many field names (keeps backward compatibility):
    Preferred: user_id OR device_id (fallback), timestamp (unix seconds),
               heart_rate + heart_rate_valid, spo2 + spo2_valid
    Backwards: recorded_at (ISO8601) OR csv_date/csv_time/csv_period,
               hr_raw / pulse, spo2_raw / spo2
    """
    api_key = os.environ.get('API_KEY')
    if api_key:
        header_key = request.headers.get('X-API-KEY')
        if header_key != api_key:
            return jsonify({'error': 'invalid api key'}), 401

    if not request.is_json:
        return jsonify({'error': 'expected application/json'}), 400

    payload = request.get_json()

    # Resolve user identity: prefer user_id, fall back to device_id if present
    uid = payload.get('user_id') or payload.get('device_id')
    if not uid:
        return jsonify({'error': 'user_id or device_id required'}), 400

    # Parse recorded_at:
    rec = None
    # 1) explicit ISO recorded_at
    if payload.get('recorded_at'):
        try:
            rec = datetime.fromisoformat(payload.get('recorded_at'))
        except Exception:
            rec = None

    # 2) unix timestamp (seconds)
    if rec is None and payload.get('timestamp') is not None:
        try:
            ts = int(payload.get('timestamp'))
            rec = datetime.utcfromtimestamp(ts)
        except Exception:
            rec = None

    # 3) csv_date/csv_time/csv_period fallback (existing helper)
    if rec is None:
        try:
            rec = parse_recorded_at(payload.get('csv_date'), payload.get('csv_time'), payload.get('csv_period'))
        except Exception:
            rec = None

    # If we still don't have rec, set to now (in IST if IST is defined)
    if rec:
        try:
            recorded_at = rec.astimezone(IST)
        except Exception:
            # If IST isn't defined or astimezone fails, fallback to rec as-is
            recorded_at = rec
    else:
        try:
            recorded_at = datetime.now(IST)
        except Exception:
            recorded_at = datetime.utcnow()

    # Numeric parsing:
    # Accept hr_raw, pulse, heart_rate; prefer hr_raw/pulse if present and valid,
    # but accept 'heart_rate' from ESP too (respecting heart_rate_valid if provided).
    hr_raw = None
    spo2_raw = None

    # 1) explicit hr_raw or pulse
    if 'hr_raw' in payload and payload.get('hr_raw') is not None:
        try:
            hr_raw = float(payload.get('hr_raw'))
        except Exception:
            hr_raw = None
    elif 'pulse' in payload and payload.get('pulse') is not None:
        try:
            hr_raw = float(payload.get('pulse'))
        except Exception:
            hr_raw = None

    # 2) ESP-style heart_rate + heart_rate_valid
    if hr_raw is None and payload.get('heart_rate') is not None:
        try:
            hr_val = payload.get('heart_rate')
            hr_valid_flag = payload.get('heart_rate_valid')
            # If valid flag explicitly false or zero, treat as invalid
            if hr_valid_flag is None or bool(hr_valid_flag):
                hr_raw = float(hr_val)
            else:
                hr_raw = None
        except Exception:
            hr_raw = None

    # SPO2 parsing: spo2_raw or spo2 or spo2_raw (ESP style)
    if 'spo2_raw' in payload and payload.get('spo2_raw') is not None:
        try:
            spo2_raw = float(payload.get('spo2_raw'))
        except Exception:
            spo2_raw = None
    elif 'spo2' in payload and payload.get('spo2') is not None:
        try:
            spo2_raw = float(payload.get('spo2'))
        except Exception:
            spo2_raw = None

    # ESP-style spo2 + spo2_valid (override only if spo2_raw not already set)
    if spo2_raw is None and payload.get('spo2') is not None:
        try:
            spo2_val = payload.get('spo2')
            spo2_valid_flag = payload.get('spo2_valid')
            if spo2_valid_flag is None or bool(spo2_valid_flag):
                spo2_raw = float(spo2_val)
            else:
                spo2_raw = None
        except Exception:
            spo2_raw = None

    # final integer values stored in DB: convert to ints where possible
    try:
        pulse = int(round(hr_raw)) if hr_raw is not None else (int(payload['heart_rate']) if payload.get('heart_rate') is not None else None)
    except Exception:
        pulse = None

    try:
        spo2 = int(round(spo2_raw)) if spo2_raw is not None else (int(payload['spo2']) if payload.get('spo2') is not None else None)
    except Exception:
        spo2 = None

    # Build ORM object (PulseSpO2 assumed available)
    p = PulseSpO2(
        user_id=str(uid),
        gender=payload.get('gender'),
        age=payload.get('age'),
        age_group=payload.get('age_group'),
        is_exercise=payload.get('is_exercise'),
        session_val=payload.get('session_val'),
        reading_no=payload.get('reading_no'),
        csv_date=payload.get('csv_date'),
        csv_time=payload.get('csv_time'),
        csv_period=payload.get('csv_period'),
        activity=payload.get('activity'),
        hr_raw=hr_raw,  # preserve parsed float
        spo2_raw=spo2_raw,  # preserve parsed float
        recorded_at=recorded_at,
        pulse=pulse,
        spo2=spo2,
        context=payload.get('context')
    )

    # DB insert + ensure user exists
    try:
        db.session.add(p)
        # ensure user exists in user_auth (create with default pwd == user_id)
        if not UserAuth.query.filter_by(user_id=str(uid)).first():
            ua = UserAuth(
                user_id=str(uid),
                plain_pwd=str(uid),
                encrypted_pwd=encrypt_pwd(str(uid)),
                pwd_hash=generate_password_hash(str(uid)),
                role='user'
            )
            db.session.add(ua)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': 'db error', 'details': str(e)}), 500

    return jsonify({'message': 'ok', 'id': p.id}), 201



@app.route('/api/reports')
@login_required
def api_reports():
    target_user = request.args.get('user_id') or current_user.user_id
    rows = PulseSpO2.query.filter_by(user_id=target_user).order_by(PulseSpO2.recorded_at.desc()).limit(1000).all()
    if not rows:
        return jsonify({'message':'no data'})
    spo2_vals = [r.spo2 for r in rows if r.spo2 is not None]
    pulse_vals = [r.pulse for r in rows if r.pulse is not None]
    sleep_count = sum(1 for r in rows if r.activity and 'sleep' in (r.activity or '').lower())
    exercise_count = sum(1 for r in rows if r.activity and ('exercise' in r.activity.lower() or 'walk' in r.activity.lower()))
    abnormal_spo2 = sum(1 for r in rows if r.spo2 is not None and r.spo2 < 90)
    abnormal_hr = sum(1 for r in rows if r.pulse is not None and (r.pulse < 50 or r.pulse > 120))
    latest_score = HealthScores.query.filter_by(user_id=target_user).order_by(HealthScores.score_date.desc()).first()
    return jsonify({
        'avg_spo2': int(sum(spo2_vals)/len(spo2_vals)) if spo2_vals else None,
        'avg_pulse': int(sum(pulse_vals)/len(pulse_vals)) if pulse_vals else None,
        'sleep_points': sleep_count,
        'exercise_points': exercise_count,
        'abnormal_spo2': abnormal_spo2,
        'abnormal_hr': abnormal_hr,
        'latest_score': latest_score.overall_score if latest_score else None
    })

@app.route('/admin/change-password', methods=['POST'])
@login_required
def admin_change_password():
    if not current_user.is_authenticated:
        flash('login required')
        return redirect(url_for('index'))
    new = request.form.get('new_password')
    if not new:
        flash('provide new password')
        return redirect(url_for('dashboard'))
    u = UserAuth.query.get(current_user.id)
    u.plain_pwd = new
    u.encrypted_pwd = encrypt_pwd(new)
    u.pwd_hash = generate_password_hash(new)
    db.session.commit()
    flash('password changed')
    return redirect(url_for('dashboard'))

@app.route('/admin/toggle-privacy', methods=['POST'])
@login_required
def admin_toggle_privacy():
    if current_user.role != 'admin':
        flash('admin only')
        return redirect(url_for('dashboard'))
    uid = request.form.get('user_id')
    is_private = int(request.form.get('is_private') or 0)
    user = UserAuth.query.filter_by(user_id=uid).first()
    if not user:
        flash('user not found')
        return redirect(url_for('dashboard'))
    user.is_private = is_private
    db.session.commit()
    flash('privacy updated')
    return redirect(url_for('dashboard'))

@app.route('/admin/recompute-scores')
@login_required
def recompute_scores():
    if current_user.role != 'admin':
        return 'admin only', 403
    users = db.session.query(PulseSpO2.user_id).distinct().all()
    count = 0
    for (uid,) in users:
        compute_daily_score_for_user(uid)
        count += 1
    return f'recomputed for {count} users'

@app.route('/static/img/<path:fn>')
def static_img(fn):
    return send_from_directory(STATIC_DIR / 'img', fn)

# --- Template bootstrapping (minimal) ---
BASE_HTML = '''<!doctype html>\n<html lang="en">\n  <head>\n    <meta charset="utf-8">\n    <meta name="viewport" content="width=device-width, initial-scale=1">\n    <title>Pulse & SpO2 Monitor</title>\n    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">\n    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>\n    <link rel="stylesheet" href="/static/css/style.css">\n  </head>\n  <body class="light-theme">\n    <nav class="navbar navbar-expand-lg navbar-light bg-light">\n      <div class="container-fluid">\n        <a class="navbar-brand" href="#">PulseSpO2</a>\n        <div class="d-flex">\n          <button id="theme-toggle" class="btn btn-outline-secondary me-2">Toggle Theme</button>\n          {% if current_user.is_authenticated %}\n            <div class="dropdown">\n              <a class="btn btn-sm btn-outline-primary dropdown-toggle" href="#" role="button" data-bs-toggle="dropdown">{{ current_user.user_id }}</a>\n              <ul class="dropdown-menu dropdown-menu-end">\n                <li><a class="dropdown-item" href="/logout">Logout</a></li>\n              </ul>\n            </div>\n          {% endif %}\n        </div>\n      </div>\n    </nav>\n    <div class="container my-3">{% with messages = get_flashed_messages() %}\n      {% if messages %}\n        {% for m in messages %}\n          <div class="alert alert-info">{{ m }}</div>\n        {% endfor %}\n      {% endif %}\n    {% endwith %}\n    {% block content %}{% endblock %}</div>\n\n    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>\n    <script src="/static/js/app.js"></script>\n  </body>\n</html>'''

LOGIN_HTML = '''{% extends 'base.html' %}\n{% block content %}\n<div class="row justify-content-center">\n  <div class="col-12 col-md-6">\n    <div class="card">\n      <div class="card-body">\n        <h5 class="card-title">Login</h5>\n        <form method="post" action="/login">\n          <div class="mb-3">\n            <label class="form-label">User ID</label>\n            <input class="form-control" name="user_id" required>\n          </div>\n          <div class="mb-3">\n            <label class="form-label">Password</label>\n            <input type="password" class="form-control" name="password" required>\n          </div>\n          <button class="btn btn-primary">Login</button>\n          <a class="btn btn-link" href="/forgot-password">Forgot password?</a>\n        </form>\n      </div>\n    </div>\n  </div>\n</div>\n{% endblock %}'''

DASH_HTML = '''{% extends 'base.html' %}\n{% block content %}\n<ul class="nav nav-tabs" id="mainTabs">\n  <li class="nav-item"><a class="nav-link active" data-bs-toggle="tab" href="#recent">Recent</a></li>\n  <li class="nav-item"><a class="nav-link" data-bs-toggle="tab" href="#analysis">Analysis</a></li>\n  <li class="nav-item"><a class="nav-link" data-bs-toggle="tab" href="#reports">Reports</a></li>\n  <li class="nav-item"><a class="nav-link" data-bs-toggle="tab" href="#admin">Admin</a></li>\n  <li class="nav-item"><a class="nav-link" data-bs-toggle="tab" href="#about">About</a></li>\n</ul>\n<div class="tab-content mt-3">\n  <div class="tab-pane fade show active" id="recent">\n    <h5>Most Recent Data</h5>\n    <div class="row">\n      <div class="col-12 col-md-6 mb-3"><canvas id="pulseChart"></canvas></div>\n      <div class="col-12 col-md-6 mb-3"><canvas id="spo2Chart"></canvas></div>\n    </div>\n  </div>\n  <div class="tab-pane fade" id="analysis">\n    <h5>Analysis</h5>\n    <form id="analysisForm" class="row g-2">\n      <div class="col-12 col-md-3"><label>From</label><input type="date" name="from" class="form-control"></div>\n      <div class="col-12 col-md-3"><label>To</label><input type="date" name="to" class="form-control"></div>\n      <div class="col-12 col-md-3"><label>Activity</label><input name="activity" class="form-control" placeholder="e.g. resting, walking"></div>\n      <div class="col-12 col-md-3 align-self-end"><button id="applyFilters" class="btn btn-primary">Apply</button></div>\n    </form>\n    <div class="mt-3"><canvas id="analysisPulse"></canvas></div>\n    <div class="mt-3"><canvas id="analysisSpo2"></canvas></div>\n  </div>\n  <div class="tab-pane fade" id="reports">\n    <h5>Reports</h5>\n    <div id="reportCards" class="row"></div>\n  </div>\n  <div class="tab-pane fade" id="admin">\n    <h5>Admin / Account</h5>\n    <form id="changePwd" method="post" action="/admin/change-password">\n      <div class="mb-2"><label>New Password</label><input type="password" name="new_password" class="form-control"></div>\n      <button class="btn btn-warning">Change Password</button>\n    </form>\n    <hr>\n    <form id="setPrivacy" method="post" action="/admin/toggle-privacy">\n      <div class="mb-2"><label>User ID (to toggle privacy)</label><input name="user_id" class="form-control"></div>\n      <div class="mb-2"><label>Private?</label>\n        <select name="is_private" class="form-select"><option value="0">No</option><option value="1">Yes</option></select>\n      </div>\n      <button class="btn btn-secondary">Set</button>\n    </form>\n  </div>\n  <div class="tab-pane fade" id="about">\n    <h5>About</h5>\n    <p>Pulse & SpO2 analysis demo app. Contact: <strong>support@example.com</strong></p>\n    <img src="/static/img/heart.png" alt="heart" style="max-width:120px">\n  </div>\n</div>\n<script>\nconst CURRENT_USER = "{{ current_user.user_id if current_user.is_authenticated else '' }}"\n</script>\n{% endblock %}'''

STYLE_CSS = ''':root{\n  --bg:#ffffff; --text:#111;\n}\nbody.dark-theme{ --bg:#0f1720; --text:#e6eef8; background:var(--bg); color:var(--text)}\nbody.light-theme{ background:#f8f9fa; color:#111}\n.card{box-shadow:0 6px 18px rgba(0,0,0,0.06)}\n@media (max-width:768px){ .nav-tabs{ overflow-x:auto; white-space:nowrap} }\n'''

APP_JS = '''document.addEventListener('DOMContentLoaded',function(){\n  const btn=document.getElementById('theme-toggle');\n  function applyTheme(t){ document.body.className = t+'-theme'; localStorage.setItem('ps_theme', t)}\n  const t = localStorage.getItem('ps_theme') || 'light'; applyTheme(t);\n  btn.addEventListener('click', ()=>{ applyTheme((document.body.className.includes('light')?'dark':'light')) });\n  async function fetchRecent(){\n    const res = await fetch('/api/recent-data');\n    const j = await res.json();\n    drawCharts(j);\n  }\n  function drawCharts(data){\n    const times = data.map(r=>r.recorded_at);\n    const pulses = data.map(r=>r.pulse);\n    const spo2s = data.map(r=>r.spo2);\n    const ctx1 = document.getElementById('pulseChart');\n    const ctx2 = document.getElementById('spo2Chart');\n    if(window._pulse) window._pulse.destroy();\n    if(window._spo2) window._spo2.destroy();\n    window._pulse = new Chart(ctx1,{ type:'line', data:{labels:times, datasets:[{label:'Pulse (bpm)', data:pulses, tension:0.2}]}, options:{scales:{x:{display:true}}}});\n    window._spo2 = new Chart(ctx2,{ type:'line', data:{labels:times, datasets:[{label:'SpO2 (%)', data:spo2s, tension:0.2}]}, options:{scales:{y:{min:50,max:100}}}});\n  }\n  fetchRecent();\n  document.getElementById('analysisForm').addEventListener('submit', async function(e){\n    e.preventDefault();\n    const form = new FormData(e.target);\n    const q = new URLSearchParams(); for(const p of form.entries()) if(p[1]) q.append(p[0], p[1]);\n    const res = await fetch('/api/data?'+q.toString()); const j = await res.json();\n    const times = j.map(r=>r.recorded_at);\n    const pulses = j.map(r=>r.pulse);\n    const spo2s = j.map(r=>r.spo2);\n    const a1 = document.getElementById('analysisPulse'); if(window._a1) window._a1.destroy();\n    window._a1 = new Chart(a1,{type:'line', data:{labels:times, datasets:[{label:'Pulse',data:pulses}]}});\n    const a2 = document.getElementById('analysisSpo2'); if(window._a2) window._a2.destroy();\n    window._a2 = new Chart(a2,{type:'line', data:{labels:times, datasets:[{label:'SpO2',data:spo2s}]}, options:{scales:{y:{min:50,max:100}}}});\n  });\n});\n'''

# write templates/static if missing
Path(TEMPLATES_DIR / 'base.html').write_text(BASE_HTML, encoding='utf-8') if not (TEMPLATES_DIR / 'base.html').exists() else None
Path(TEMPLATES_DIR / 'login.html').write_text(LOGIN_HTML, encoding='utf-8') if not (TEMPLATES_DIR / 'login.html').exists() else None
Path(TEMPLATES_DIR / 'dashboard.html').write_text(DASH_HTML, encoding='utf-8') if not (TEMPLATES_DIR / 'dashboard.html').exists() else None
Path(STATIC_DIR / 'css' / 'style.css').write_text(STYLE_CSS, encoding='utf-8') if not (STATIC_DIR / 'css' / 'style.css').exists() else None
Path(STATIC_DIR / 'js' / 'app.js').write_text(APP_JS, encoding='utf-8') if not (STATIC_DIR / 'js' / 'app.js').exists() else None
Path(STATIC_DIR / 'img' / 'heart.png').write_text('<svg></svg>', encoding='utf-8') if not (STATIC_DIR / 'img' / 'heart.png').exists() else None

# --- Initialize DB on startup ---
init_db()

@app.after_request
def add_no_cache_headers(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

if __name__ == '__main__':
    # disable Flask's static file caching during development
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
    app.run(host="0.0.0.0", port=5000, debug=True)

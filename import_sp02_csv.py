# import_spo2_csv.py
import csv
from pathlib import Path
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text
from sqlalchemy.orm import declarative_base, sessionmaker
from werkzeug.security import generate_password_hash

# CONFIG - point to your sqlite DB
DB_PATH = Path('data/app.db')    # same DB used by Flask app
CSV_PATH = Path('spo2.csv')

Base = declarative_base()

class PulseSpO2(Base):
    __tablename__ = 'pulse_sp02_data'
    id = Column(Integer, primary_key=True)
    user_id = Column(String, nullable=False, index=True)
    gender = Column(String)
    age = Column(Integer)
    age_group = Column(String)
    is_exercise = Column(String)
    session_val = Column(String)
    reading_no = Column(Integer)
    csv_date = Column(String)
    csv_time = Column(String)
    csv_period = Column(String)
    activity = Column(String)
    hr_raw = Column(Float)
    spo2_raw = Column(Float)
    recorded_at = Column(DateTime)
    pulse = Column(Integer)
    spo2 = Column(Integer)
    created_at = Column(DateTime)

class UserAuth(Base):
    __tablename__ = 'user_auth'
    id = Column(Integer, primary_key=True)
    user_id = Column(String, unique=True, nullable=False)
    plain_pwd = Column(String)
    encrypted_pwd = Column(String)
    pwd_hash = Column(String)
    role = Column(String, default='user')
    is_private = Column(Integer, default=0)

def parse_recorded_at(csv_date, csv_time, csv_period):
    # We assume DAY-FIRST date format: dd/mm/YYYY (India)
    # csv_time like '05:51:48', csv_period like 'AM' or 'PM'
    if not csv_date:
        return None
    try:
        # normalize date
        dt_part = datetime.strptime(csv_date.strip(), '%d/%m/%Y').date()
    except Exception:
        # fallback: try ISO
        try:
            dt_part = datetime.fromisoformat(csv_date.strip()).date()
        except Exception:
            return None
    # handle time + period
    time_str = (csv_time or '').strip()
    period = (csv_period or '').strip().upper()
    if not time_str:
        return datetime.combine(dt_part, datetime.min.time())
    # build full time with period if provided
    try:
        if period in ('AM','PM'):
            t = datetime.strptime(time_str + ' ' + period, '%I:%M:%S %p').time()
        else:
            # assume 24-hour time
            t = datetime.strptime(time_str, '%H:%M:%S').time()
    except Exception:
        # last resort: try parsing without seconds
        try:
            if period in ('AM','PM'):
                t = datetime.strptime(time_str + ' ' + period, '%I:%M %p').time()
            else:
                t = datetime.strptime(time_str, '%H:%M').time()
        except Exception:
            # give up
            return datetime.combine(dt_part, datetime.min.time())
    return datetime.combine(dt_part, t)

def main():
    engine = create_engine(f'sqlite:///{DB_PATH}', echo=False, future=True)
    Session = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    session = Session()

    if not CSV_PATH.exists():
        print('CSV file not found at', CSV_PATH)
        return

    with CSV_PATH.open('r', encoding='utf-8', errors='ignore') as f:
        reader = csv.DictReader(f)
        count = 0
        for row in reader:
            pid = row.get('person_id') or row.get('user_id') or 'unknown'
            gender = row.get('gender')
            age = None
            try:
                age = int(float(row.get('age'))) if row.get('age') else None
            except:
                age = None
            age_group = row.get('age_group')
            # Because header had merged columns, try to fetch likely cells
            # We'll map conservatively:
            is_exercise = row.get('is_exercise') or row.get('is_exercise...reading_no') or row.get('is_exercise...reading_no', None)
            # session_val might be present as a numeric string in that merged area. We'll pick any numeric-looking value that isn't reading_no.
            session_val = None
            reading_no = None
            # fallback: check keys present in row
            # The file might have cells after the merged header; use positional approach:
            # Convert row to list of values (DictReader keeps order), then inspect by index if needed.
            values = list(row.values())
            # attempt to find numeric fields after age_group
            try:
                # safe: find the column after age_group in header by name location
                # but simplest: attempt to parse reading_no from 'reading_no' key or last few columns
                reading_no = int(float(row.get('reading_no'))) if row.get('reading_no') else None
            except:
                reading_no = None

            raw_date = row.get('date') or row.get('Date')
            raw_time = row.get('time') or row.get('Time')
            raw_period = row.get('period') or row.get('Period')
            activity = row.get('activity')
            try:
                hr_raw = float(row.get('hr')) if row.get('hr') else None
            except:
                hr_raw = None
            try:
                spo2_raw = float(row.get('spo2')) if row.get('spo2') else None
            except:
                spo2_raw = None

            recorded_at = parse_recorded_at(raw_date, raw_time, raw_period)
            pulse = int(round(hr_raw)) if hr_raw is not None else None
            spo2 = int(round(spo2_raw)) if spo2_raw is not None else None

            rec = PulseSpO2(
                user_id = pid,
                gender = gender,
                age = age,
                age_group = age_group,
                is_exercise = is_exercise,
                session_val = row.get('session_val') or row.get('session') or None,
                reading_no = reading_no,
                csv_date = raw_date,
                csv_time = raw_time,
                csv_period = raw_period,
                activity = activity,
                hr_raw = hr_raw,
                spo2_raw = spo2_raw,
                recorded_at = recorded_at,
                pulse = pulse,
                spo2 = spo2,
            )
            session.add(rec)
            # create user_auth row if missing
            if not session.query(UserAuth).filter_by(user_id=pid).first():
                ua = UserAuth(user_id=pid, plain_pwd=None, encrypted_pwd=None, pwd_hash=generate_password_hash('changeme'), role='user')
                session.add(ua)
            count += 1
            if count % 500 == 0:
                session.commit()
        session.commit()
    print('Imported', count, 'rows into pulse_sp02_data')

if __name__ == '__main__':
    main()

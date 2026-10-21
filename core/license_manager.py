import uuid
import json
import base64
import hmac
import hashlib
import sqlite3
import os
from datetime import datetime, timedelta

# ⚠️ CHANGE THIS TO YOUR OWN SECRET 32-BYTE KEY. Keep it safe!
def _get_secret_key():
    secret_key = os.environ.get("FISCALINK_LICENSE_SECRET")
    if not secret_key or len(secret_key.encode("utf-8")) < 32:
        raise RuntimeError(
            "FISCALINK_LICENSE_SECRET must be set to a secret of at least 32 bytes."
        )
    return secret_key.encode("utf-8")

# Ensure we use the exact same database file as the rest of the app
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fiscalink.db")

def ensure_tables():
    """Automatically creates the system_config table if it doesn't exist."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS system_config (key TEXT PRIMARY KEY, value TEXT)''')
            conn.commit()
    except Exception as e:
        print(f"❌ Error creating system_config table: {e}")

def get_machine_id():
    """Generates a unique ID based on the computer's MAC address."""
    mac = uuid.getnode()
    return f"MID-{mac:X}"

def generate_license_key(machine_id, days_valid=30):
    """Generates a license key for a specific machine and duration."""
    expiry_date = (datetime.now() + timedelta(days=days_valid)).strftime("%Y-%m-%d")
    payload = {"mid": machine_id, "exp": expiry_date}
    payload_json = json.dumps(payload, separators=(',', ':'))
    signature = hmac.new(_get_secret_key(), payload_json.encode('utf-8'), hashlib.sha256).hexdigest()
    raw_key = f"{payload_json}|{signature}"
    return base64.urlsafe_b64encode(raw_key.encode('utf-8')).decode('utf-8')

def validate_license_key(license_key):
    """Validates a license key and returns (is_valid, message, expiry_date)"""
    secret_key = _get_secret_key()
    try:
        raw_key = base64.urlsafe_b64decode(license_key.encode('utf-8')).decode('utf-8')
        payload_str, signature = raw_key.split('|')
        
        expected_sig = hmac.new(secret_key, payload_str.encode('utf-8'), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected_sig, signature):
            return False, "Invalid license signature.", None
            
        payload = json.loads(payload_str)
        if payload.get('mid') != get_machine_id():
            return False, "License is not valid for this computer.", None
            
        expiry_date = datetime.strptime(payload.get('exp'), "%Y-%m-%d")
        if datetime.now() > expiry_date:
            return False, f"License expired on {payload.get('exp')}.", payload.get('exp')
            
        return True, "License is valid.", payload.get('exp')
    except Exception as e:
        return False, f"Corrupted license key: {str(e)}", None

def save_license_to_db(license_key, expiry_date):
    """Saves the activated license to the SQLite database."""
    ensure_tables()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT OR REPLACE INTO system_config (key, value) VALUES ('license_key', ?)", (license_key,))
        conn.execute("INSERT OR REPLACE INTO system_config (key, value) VALUES ('license_expiry', ?)", (expiry_date,))
        conn.commit()

def get_license_status():
    """Checks the current license status from the database."""
    ensure_tables()
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM system_config WHERE key = 'license_key'")
            key_row = cursor.fetchone()
            
            if not key_row or not key_row[0]:
                return {"is_valid": False, "message": "No license activated.", "days_left": 0, "status": "NOT_SET"}
                
            is_valid, message, exp_date = validate_license_key(key_row[0])
            days_left = 0
            if is_valid and exp_date:
                days_left = (datetime.strptime(exp_date, "%Y-%m-%d") - datetime.now()).days
                
            if not is_valid:
                status = "EXPIRED" if "expired" in message.lower() else "INVALID"
            else:
                status = "VALID"
                
            return {"is_valid": is_valid, "message": message, "days_left": max(0, days_left), "expiry": exp_date, "status": status}
    except Exception as e:
        return {"is_valid": False, "message": str(e), "days_left": 0, "status": "ERROR"}
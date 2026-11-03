import hashlib
import platform
import uuid
import sqlite3
import os
from datetime import datetime, timedelta

# ============================================================
# THE SHARED SECRET
# This MUST be identical in the Generator Dashboard and the EXE.
# ============================================================
LICENSE_SECRET = "AIBES_FISCALISATION_SUPER_SECRET_KEY_2026_V2"

def get_machine_id():
    """Generates a unique, consistent Machine ID based on hardware."""
    try:
        mac = uuid.getnode()
        node = platform.node()
        raw_id = f"{mac}-{node}"
        return hashlib.sha256(raw_id.encode()).hexdigest()[:16].upper()
    except Exception:
        return "UNKNOWN00000000"

def generate_license_key(target_machine_id, days_valid=365):
    """Generates a license key locked to a SPECIFIC client machine."""
    target_machine_id = str(target_machine_id).strip().upper()
    expiry_date = (datetime.now() + timedelta(days=days_valid)).strftime("%Y-%m-%d")
    payload = f"{target_machine_id}|{expiry_date}"
    checksum = hashlib.sha256(f"{payload}{LICENSE_SECRET}".encode()).hexdigest()[:16].upper()
    return f"{target_machine_id}_{expiry_date}_{checksum}"

def validate_license_key(license_key):
    """Validates the license key on the client's EXE."""
    if not license_key:
        return False, "No license key provided.", None
    
    license_key = str(license_key).strip().upper()
    parts = license_key.split('_')
    
    if len(parts) != 3:
        return False, "Invalid license format.", None
        
    machine_id, expiry_date, checksum = parts
    
    # 1. Verify Checksum
    payload = f"{machine_id}|{expiry_date}"
    expected_checksum = hashlib.sha256(f"{payload}{LICENSE_SECRET}".encode()).hexdigest()[:16].upper()
    if checksum != expected_checksum:
        return False, "Invalid license signature.", None
        
    # 2. Verify Machine ID
    current_machine_id = get_machine_id()
    if machine_id != current_machine_id:
        return False, "Machine ID mismatch.", None
        
    # 3. Verify Expiry
    try:
        expiry_dt = datetime.strptime(expiry_date, "%Y-%m-%d")
        if datetime.now() > expiry_dt:
            return False, f"License expired on {expiry_date}.", None
    except ValueError:
        return False, "Invalid date format.", None
        
    return True, "License is valid and active.", expiry_date

def save_license_to_db(license_key, expiry_date):
    """Saves the validated license key to the local database."""
    from core.zimra_client import DB_PATH, db_lock
    try:
        with db_lock:
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("INSERT OR REPLACE INTO system_config (key, value) VALUES ('license_key', ?)", (license_key.strip(),))
                conn.execute("INSERT OR REPLACE INTO system_config (key, value) VALUES ('license_expiry', ?)", (expiry_date,))
    except Exception as e:
        print(f"Error saving license to DB: {e}")

def get_license_status():
    """Checks the database for a saved license and calculates days left."""
    from core.zimra_client import DB_PATH, db_lock
    try:
        with db_lock:
            with sqlite3.connect(DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute("SELECT value FROM system_config WHERE key = 'license_key'").fetchone()
                
                if row and row['value']:
                    is_valid, message, expiry = validate_license_key(row['value'])
                    
                    # FIX: Calculate Days Left
                    days_left = 0
                    if is_valid and expiry:
                        try:
                            expiry_dt = datetime.strptime(expiry, "%Y-%m-%d")
                            days_left = (expiry_dt - datetime.now()).days
                            if days_left < 0: 
                                days_left = 0
                        except Exception:
                            days_left = 0
                            
                    return {
                        "status": "VALID" if is_valid else "INVALID",
                        "message": message,
                        "is_valid": is_valid,
                        "expiry": expiry,
                        "days_left": days_left,  # <--- ADDED THIS
                        "machine_id": get_machine_id()
                    }
                    
                return {
                    "status": "NOT_SET", 
                    "message": "No license key installed.", 
                    "is_valid": False, 
                    "expiry": None,
                    "days_left": 0, # <--- ADDED THIS
                    "machine_id": get_machine_id()
                }
    except Exception as e:
        return {"status": "ERROR", "message": str(e), "is_valid": False, "expiry": None, "days_left": 0, "machine_id": get_machine_id()}
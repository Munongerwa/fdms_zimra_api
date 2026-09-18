import os
import sys
import json

def load_external_config():
    """Loads configuration from config.json, with safe defaults."""
    config_file = "config.json"
    
    # If running as a PyInstaller EXE, look in the same directory as the EXE
    if getattr(sys, 'frozen', False):
        config_file = os.path.join(os.path.dirname(sys.executable), "config.json")
    
    # Sensible defaults in case config.json is missing or corrupted
    defaults = {
        "device_id": 46058,
        "device_serial_number": "UNKNOWN",
        "cert_path": "C:\\certs",
        "zimra_api_url": "https://fdmsapi.zimra.co.zw",
        "qr_base_url": "https://fdms.zimra.co.zw/"
    }
    
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                user_config = json.load(f)
                # Merge user config with defaults
                for key in defaults:
                    if key in user_config:
                        defaults[key] = user_config[key]
            print(f"✅ Loaded external configuration from: {config_file}")
        except Exception as e:
            print(f"⚠️ Warning: Could not read config.json: {e}. Using defaults.")
    else:
        print(f"⚠️ Warning: config.json not found at {config_file}. Using defaults.")
        
    return defaults

# Load the configuration at module import time
ext_config = load_external_config()

class Config:
    # Device Credentials (Loaded from external file)
    DEVICE_ID = ext_config["device_id"]
    DEVICE_SERIAL_NUMBER = ext_config["device_serial_number"]
    
    # Device Model Info (Required by ZimraClient)
    DEVICE_MODEL_NAME = "server"
    DEVICE_MODEL_VERSION = "v1"
    
    # Certificate Paths (Named exactly as ZimraClient expects them)
    CERTS_DIR = ext_config["cert_path"]
    CERT_PATH = os.path.join(CERTS_DIR, "client_cert.pem")
    KEY_PATH = os.path.join(CERTS_DIR, "client_key.key")
    
    # ZIMRA FDMS API Endpoints
    ZIMRA_API_URL = ext_config["zimra_api_url"]
    QR_BASE_URL = ext_config["qr_base_url"]
    
    # Database and App Settings
    DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "fiscal.db")
    if getattr(sys, 'frozen', False):
        DB_PATH = os.path.join(os.path.dirname(sys.executable), "data", "fiscal.db")
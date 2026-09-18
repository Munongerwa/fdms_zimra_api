"""
ZIMRA Client - Handles all communication with ZIMRA FDMS API,
database state management, receipt audit logging, and cryptographic signing.
"""
import os
import sys
import requests
import hashlib
import base64
import json
import sqlite3
import threading
from datetime import datetime
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, ec

# Import config (handles both dev and EXE modes)
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import Config

# Use paths from Config (writable DB path, bundled cert paths)
DB_PATH = Config.DB_PATH
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

db_lock = threading.Lock()

# ZIMRA counter type ordering for signature generation
COUNTER_TYPE_ORDER = {
    "SALEBYTAX": 0, "SALETAXBYTAX": 1, "CREDITNOTEBYTAX": 2,
    "CREDITNOTETAXBYTAX": 3, "DEBITNOTEBYTAX": 4, "DEBITNOTETAXBYTAX": 5,
    "BALANCEBYMONEYTYPE": 6
}


def init_db():
    """Initialize all database tables with migrations for older databases."""
    with db_lock:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            
            # Fiscal state table (tracks counters per device)
            cursor.execute('''CREATE TABLE IF NOT EXISTS fiscal_state (
                device_id TEXT PRIMARY KEY, 
                fiscal_day_no INTEGER DEFAULT 1, 
                fiscal_day_opened_date TEXT,
                receipt_counter INTEGER DEFAULT 1, 
                receipt_global_no INTEGER DEFAULT 1, 
                previous_receipt_hash TEXT DEFAULT ""
            )''')
            
            # Receipt audit table (logs every receipt submission)
            cursor.execute('''CREATE TABLE IF NOT EXISTS receipt_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT, 
                zimra_receipt_id INTEGER, 
                device_id TEXT, 
                fiscal_day_no INTEGER,
                receipt_counter INTEGER, 
                receipt_global_no INTEGER, 
                receipt_type TEXT, 
                invoice_no TEXT, 
                receipt_date TEXT,
                total_amount REAL, 
                receipt_currency TEXT DEFAULT 'USD',
                hash_b64 TEXT, 
                verification_code TEXT, 
                qr_code TEXT, 
                zimra_response TEXT, 
                status TEXT, 
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )''')
            
            # Z-reports table (stores fiscal day closures)
            cursor.execute('''CREATE TABLE IF NOT EXISTS z_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT, 
                fiscal_day_no INTEGER, 
                device_id TEXT, 
                close_date TEXT,
                total_receipts INTEGER, 
                currencies_json TEXT, 
                total_sales REAL, 
                total_tax REAL,
                zimra_response_json TEXT, 
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )''')
            
            # Scanner logs table (for dashboard history)
            cursor.execute('''CREATE TABLE IF NOT EXISTS scanner_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                message TEXT,
                status TEXT
            )''')
            
            # System config table (stores user preferences)
            cursor.execute('''CREATE TABLE IF NOT EXISTS system_config (
                key TEXT PRIMARY KEY,
                value TEXT
            )''')
            cursor.execute("INSERT OR IGNORE INTO system_config (key, value) VALUES ('scanner_print_format', 'InvoiceA4')")
            cursor.execute("INSERT OR IGNORE INTO system_config (key, value) VALUES ('scanner_folder', 'C:\\Receipt')")
            cursor.execute("INSERT OR IGNORE INTO system_config (key, value) VALUES ('receipt_template', 'melivo')")
            
            # Receipt items table (for analytics - top products)
            cursor.execute('''CREATE TABLE IF NOT EXISTS receipt_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                receipt_audit_id INTEGER,
                invoice_no TEXT,
                receipt_date TEXT,
                receipt_currency TEXT DEFAULT 'USD',
                item_name TEXT,
                quantity REAL,
                price REAL,
                total REAL,
                tax_code TEXT,
                tax_percent REAL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (receipt_audit_id) REFERENCES receipt_audit(id)
            )''')
            
            # Migrations for older databases
            cursor.execute("PRAGMA table_info(receipt_audit)")
            columns = [col[1] for col in cursor.fetchall()]
            if 'receipt_currency' not in columns:
                cursor.execute("ALTER TABLE receipt_audit ADD COLUMN receipt_currency TEXT DEFAULT 'USD'")
            
            cursor.execute("PRAGMA table_info(receipt_items)")
            columns = [col[1] for col in cursor.fetchall()]
            if 'receipt_currency' not in columns:
                cursor.execute("ALTER TABLE receipt_items ADD COLUMN receipt_currency TEXT DEFAULT 'USD'")
            
            conn.commit()
            print(f"✅ Database initialized at: {DB_PATH}")


class ZimraClient:
    """Client for interacting with ZIMRA FDMS API."""
    
    def __init__(self):
        self.api_url = Config.ZIMRA_API_URL
        self.device_id = Config.DEVICE_ID
        self.headers = {
            "Content-Type": "application/json",
            "DeviceModelName": Config.DEVICE_MODEL_NAME,
            "DeviceModelVersion": Config.DEVICE_MODEL_VERSION
        }
        self.cert = (Config.CERT_PATH, Config.KEY_PATH)
        
        # Verify certificate files exist
        if not os.path.exists(Config.CERT_PATH):
            raise FileNotFoundError(f"Certificate not found: {Config.CERT_PATH}")
        if not os.path.exists(Config.KEY_PATH):
            raise FileNotFoundError(f"Private key not found: {Config.KEY_PATH}")
        
        with open(Config.KEY_PATH, 'rb') as f:
            self.private_key = serialization.load_pem_private_key(f.read(), password=None)
        
        print(f"✅ ZimraClient initialized for device {self.device_id}")

    # ============ STATE MANAGEMENT ============
    
    def get_state(self):
        """Get the current fiscal state for this device."""
        with db_lock:
            with sqlite3.connect(DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("SELECT * FROM fiscal_state WHERE device_id = ?", (self.device_id,))
                row = cursor.fetchone()
                if row: 
                    return dict(row)
                conn.execute("INSERT INTO fiscal_state (device_id) VALUES (?)", (self.device_id,))
                return {
                    "device_id": self.device_id, 
                    "fiscal_day_no": 1, 
                    "receipt_counter": 1, 
                    "receipt_global_no": 1, 
                    "previous_receipt_hash": "", 
                    "fiscal_day_opened_date": ""
                }

    def update_state_after_success(self, hash_b64):
        """Increment counters after a successful receipt submission."""
        with db_lock:
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("""UPDATE fiscal_state SET receipt_counter = receipt_counter + 1, 
                    receipt_global_no = receipt_global_no + 1, previous_receipt_hash = ? WHERE device_id = ?""", 
                    (hash_b64, self.device_id))

    def reset_daily_counter(self, fiscal_day_no, opened_date):
        """Reset counters when opening a new fiscal day."""
        with db_lock:
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("""UPDATE fiscal_state SET receipt_counter = 1, previous_receipt_hash = '',
                    fiscal_day_no = ?, fiscal_day_opened_date = ? WHERE device_id = ?""", 
                    (fiscal_day_no, opened_date, self.device_id))

    # ============ AUDIT LOGGING ============
    
    def log_receipt_audit(self, audit_data):
        """Log a receipt submission attempt (success or failure). Returns the audit ID."""
        with db_lock:
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.execute("""INSERT INTO receipt_audit 
                    (zimra_receipt_id, device_id, fiscal_day_no, receipt_counter, 
                    receipt_global_no, receipt_type, invoice_no, receipt_date, total_amount, 
                    receipt_currency, hash_b64, verification_code, qr_code, zimra_response, status) 
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (audit_data.get('zimra_receipt_id'), 
                     audit_data.get('device_id'), 
                     audit_data.get('fiscal_day_no'),
                     audit_data.get('receipt_counter'), 
                     audit_data.get('receipt_global_no'), 
                     audit_data.get('receipt_type'),
                     audit_data.get('invoice_no'), 
                     audit_data.get('receipt_date'), 
                     audit_data.get('total_amount'),
                     audit_data.get('receipt_currency', 'USD'), 
                     audit_data.get('hash_b64'), 
                     audit_data.get('verification_code'), 
                     audit_data.get('qr_code'), 
                     audit_data.get('zimra_response'), 
                     audit_data.get('status')))
                return cursor.lastrowid

    def log_receipt_items(self, receipt_audit_id, invoice_no, receipt_date, receipt_currency, items):
        """Store individual product line items for analytics (top products by currency)."""
        try:
            with db_lock:
                with sqlite3.connect(DB_PATH) as conn:
                    for item in items:
                        conn.execute("""INSERT INTO receipt_items 
                            (receipt_audit_id, invoice_no, receipt_date, receipt_currency, 
                             item_name, quantity, price, total, tax_code, tax_percent) 
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (receipt_audit_id, 
                             invoice_no, 
                             receipt_date, 
                             receipt_currency,
                             item.get('name', 'Unknown'),
                             item.get('qty', 0),
                             item.get('price', 0),
                             item.get('total', 0),
                             item.get('tax_code', 'A'),
                             item.get('tax_pct', 0)))
        except Exception as e:
            print(f"Error logging receipt items: {e}")

    # ============ HTTP REQUESTS ============
    
    def _make_request(self, endpoint, payload=None, method="POST"):
        """Make an HTTP request to the ZIMRA API."""
        url = f"{self.api_url}/Device/v1/{self.device_id}/{endpoint}"
        try:
            if method.upper() == "GET":
                response = requests.get(url, headers=self.headers, cert=self.cert, timeout=30)
            else:
                response = requests.post(url, json=payload, headers=self.headers, cert=self.cert, timeout=30)
            
            if 'application/json' in response.headers.get('content-type', ''):
                return response.status_code, response.json()
            return response.status_code, response.text
        except Exception as e:
            print(f"Request error: {e}")
            return 500, {"error": str(e)}

    # ============ CRYPTOGRAPHIC OPERATIONS ============
    
    def _sign_data(self, data_string):
        """Sign data using the device's private key."""
        if isinstance(self.private_key, ec.EllipticCurvePrivateKey):
            return self.private_key.sign(data_string.encode('utf-8'), ec.ECDSA(hashes.SHA256()))
        return self.private_key.sign(data_string.encode('utf-8'), padding.PKCS1v15(), hashes.SHA256())

    def _format_cents(self, amount):
        """Format an amount as cents (integer string) for signature."""
        return str(int(round(float(amount) * 100)))

    def _build_receipt_signature_string(self, receipt_data, previous_hash=""):
        """Build the canonical string for receipt signature generation."""
        device_id = str(receipt_data['deviceID'])
        receipt_type = receipt_data['receipt']['receiptType'].upper()
        currency = receipt_data['receipt']['receiptCurrency'].upper()
        global_no = str(receipt_data['receipt']['receiptGlobalNo'])
        receipt_date = receipt_data['receipt']['receiptDate']
        total_cents = self._format_cents(receipt_data['receipt']['receiptTotal'])
        
        taxes_str = ""
        sorted_taxes = sorted(receipt_data['receipt']['receiptTaxes'], 
                              key=lambda x: (x.get('taxID', 0), x.get('taxCode', '')))
        for tax in sorted_taxes:
            tax_code = tax.get('taxCode', '')
            tax_percent = tax.get('taxPercent')
            tax_percent_str = f"{float(tax_percent):.2f}" if tax_percent is not None else ""
            tax_amount_cents = self._format_cents(tax['taxAmount'])
            sales_with_tax_cents = self._format_cents(tax['salesAmountWithTax'])
            taxes_str += f"{tax_code}{tax_percent_str}{tax_amount_cents}{sales_with_tax_cents}"
            
        return f"{device_id}{receipt_type}{currency}{global_no}{receipt_date}{total_cents}{taxes_str}{previous_hash}"

    def _build_close_day_signature_string(self, fiscal_day_no, fiscal_day_date, fiscal_counters):
        """Build the canonical string for close-day signature generation."""
        counters_str = ""
        
        def sort_key(c):
            c_type = c.get('fiscalCounterType', '').upper()
            c_curr = c.get('fiscalCounterCurrency', '').upper()
            type_order = COUNTER_TYPE_ORDER.get(c_type, 99)
            if 'TAX' in c_type: 
                identifier = c.get('fiscalCounterTaxID', 0) or 0
            else: 
                identifier = c.get('fiscalCounterMoneyType', '').upper()
            return (type_order, c_curr, identifier)

        for c in sorted(fiscal_counters, key=sort_key):
            c_type = c['fiscalCounterType'].upper()
            c_curr = c['fiscalCounterCurrency'].upper()
            c_tax_percent = c.get('fiscalCounterTaxPercent')
            c_money_type = c.get('fiscalCounterMoneyType', '').upper()
            identifier_str = f"{float(c_tax_percent):.2f}" if c_tax_percent is not None else c_money_type
            c_value = self._format_cents(c['fiscalCounterValue'])
            counters_str += f"{c_type}{c_curr}{identifier_str}{c_value}"
            
        return f"{self.device_id}{fiscal_day_no}{fiscal_day_date}{counters_str}"

    def _generate_verification_code(self, signature_bytes):
        """Generate a human-readable verification code from the signature."""
        md5_hex = hashlib.md5(signature_bytes).hexdigest()
        return f"{md5_hex[0:4]}-{md5_hex[4:8]}-{md5_hex[8:12]}-{md5_hex[12:16]}"

    def _generate_qr_code(self, receipt_date, global_no, signature_bytes):
        """Generate the ZIMRA QR code URL for receipt verification."""
        qr_base_url = Config.QR_BASE_URL
        device_id_padded = str(self.device_id).zfill(10)
        date_formatted = datetime.strptime(receipt_date, "%Y-%m-%dT%H:%M:%S").strftime("%d%m%Y")
        global_no_padded = str(global_no).zfill(10)
        qr_data = hashlib.md5(signature_bytes).hexdigest()[0:16].upper()
        return f"{qr_base_url}{device_id_padded}{date_formatted}{global_no_padded}{qr_data}"

    # ============ PUBLIC API METHODS ============
    
    def get_config(self):
        """Get device configuration from ZIMRA."""
        return self._make_request("getConfig", method="GET")
    
    def get_status(self):
        """Get device status from ZIMRA."""
        return self._make_request("getStatus", method="GET")

    def open_day(self, fiscal_day_no=None):
        """Open a new fiscal day."""
        payload = {
            "deviceID": int(self.device_id), 
            "fiscalDayOpened": datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        }
        if fiscal_day_no is not None: 
            payload["fiscalDayNo"] = int(fiscal_day_no)
        return self._make_request("openDay", payload)

    def submit_receipt(self, receipt_data):
        """
        Submit a receipt to ZIMRA.
        Returns: (status_code, response, verification_code, qr_code, hash_b64, receipt_audit_id)
        """
        state = self.get_state()
        previous_hash = state['previous_receipt_hash']
        
        # Build signature
        concat_str = self._build_receipt_signature_string(receipt_data, previous_hash)
        hash_bytes = hashlib.sha256(concat_str.encode('utf-8')).digest()
        hash_b64 = base64.b64encode(hash_bytes).decode('utf-8')
        
        signature_bytes = self._sign_data(concat_str)
        signature_b64 = base64.b64encode(signature_bytes).decode('utf-8')
        
        # Add signature to payload
        receipt_data['receipt']['receiptDeviceSignature'] = {
            "hash": hash_b64, 
            "signature": signature_b64
        }
        
        # Submit to ZIMRA
        status_code, response = self._make_request("submitReceipt", receipt_data)
        
        # Generate verification code and QR code
        verification_code = self._generate_verification_code(signature_bytes)
        qr_code = self._generate_qr_code(
            receipt_data['receipt']['receiptDate'], 
            receipt_data['receipt']['receiptGlobalNo'], 
            signature_bytes
        )
        
        # Log the audit
        audit_data = {
            'zimra_receipt_id': response.get('receiptID') if isinstance(response, dict) else None,
            'device_id': self.device_id, 
            'fiscal_day_no': state['fiscal_day_no'],
            'receipt_counter': receipt_data['receipt']['receiptCounter'],
            'receipt_global_no': receipt_data['receipt']['receiptGlobalNo'],
            'receipt_type': receipt_data['receipt']['receiptType'], 
            'invoice_no': receipt_data['receipt']['invoiceNo'],
            'receipt_date': receipt_data['receipt']['receiptDate'], 
            'total_amount': receipt_data['receipt']['receiptTotal'],
            'receipt_currency': receipt_data['receipt']['receiptCurrency'],
            'hash_b64': hash_b64, 
            'verification_code': verification_code, 
            'qr_code': qr_code,
            'zimra_response': json.dumps(response), 
            'status': 'SUCCESS' if status_code == 200 else 'FAILED'
        }
        receipt_audit_id = self.log_receipt_audit(audit_data)
        
        # Update state on success
        if status_code == 200: 
            self.update_state_after_success(hash_b64)
        
        return status_code, response, verification_code, qr_code, hash_b64, receipt_audit_id

    def close_day(self, fiscal_day_no, receipt_counter, fiscal_counters):
        """Close the current fiscal day and generate Z-report."""
        state = self.get_state()
        fiscal_day_date = state.get('fiscal_day_opened_date') or datetime.now().strftime("%Y-%m-%d")
        
        # Build signature
        concat_str = self._build_close_day_signature_string(fiscal_day_no, fiscal_day_date, fiscal_counters)
        hash_bytes = hashlib.sha256(concat_str.encode('utf-8')).digest()
        hash_b64 = base64.b64encode(hash_bytes).decode('utf-8')
        
        signature_bytes = self._sign_data(concat_str)
        signature_b64 = base64.b64encode(signature_bytes).decode('utf-8')
        
        payload = {
            "deviceID": int(self.device_id), 
            "fiscalDayNo": int(fiscal_day_no),
            "fiscalDayCounters": fiscal_counters,
            "fiscalDayDeviceSignature": {"hash": hash_b64, "signature": signature_b64},
            "receiptCounter": int(receipt_counter)
        }
        return self._make_request("closeDay", payload)
import os
import time
import shutil
import sqlite3
import threading
import json
import io
import csv
import requests
from flask import Flask, request, jsonify, Response
from datetime import datetime, timedelta, time as dt_time
from flasgger import Swagger
from collections import defaultdict
from core.zimra_client import ZimraClient, init_db, DB_PATH, db_lock
from core.pdf_generator import generate_zimra_a4_pdf, generate_z_report_pdf
from core.receipt_parser import parse_receipt_file, build_zimra_payload
from core.zimra_validator import validate_zimra_payload
from config import Config

app = Flask(__name__)

swagger_config = {
    "headers": [],
    "specs": [{"endpoint": 'apispec_1', "route": '/apispec_1.json', "rule_filter": lambda rule: True, "model_filter": lambda tag: True}],
    "static_url_path": "/flasgger_static", "swagger_ui": True, "specs_route": "/docs/",
    "title": "FISCALINK API", "description": "Comprehensive API for interfacing with the ZIMRA Fiscal Device Gateway (FDMS v7.2).",
    "version": "1.0.0", "uiversion": 3
}
swagger = Swagger(app, config=swagger_config)

init_db()
zimra = ZimraClient()

def send_os_notification(title, message):
    """Sends a native Windows OS notification that auto-dismisses after 5 seconds."""
    try:
        from plyer import notification
        notification.notify(
            title=title,
            message=message,
            app_name="FISCALINK",
            timeout=5
        )
    except Exception as e:
        print(f"OS Notification failed: {e}")

# ============================================================
# AUTO FISCAL DAY SCHEDULER
# ============================================================
def auto_fiscal_day_scheduler():
    """Background thread to automatically open and close the fiscal day."""
    print("⏰ Fiscal Day Auto-Scheduler started.")
    scheduler_state = {'last_opened_date': None, 'last_closed_date': None}
    
    while True:
        try:
            now = datetime.now()
            current_time = now.time()
            today_str = now.strftime("%Y-%m-%d")
            
            # Reset trackers at midnight
            if current_time < dt_time(0, 5):
                scheduler_state['last_opened_date'] = None
                scheduler_state['last_closed_date'] = None

            # Get current ZIMRA status
            try:
                status_code, status_resp = zimra.get_status()
                current_status = status_resp.get("fiscalDayStatus", "") if status_code == 200 else ""
            except Exception as e:
                print(f"⚠️ [SCHEDULER] Could not get ZIMRA status: {e}")
                current_status = ""

            # 1. Auto Close at 5:00 PM (17:00)
            if current_time >= dt_time(17, 0) and current_time < dt_time(17, 30):
                if "Opened" in current_status and scheduler_state['last_closed_date'] != today_str:
                    print(f"\n⏰ [AUTO-SCHEDULER] 5:00 PM reached. Closing fiscal day...")
                    try:
                        res = requests.post("http://localhost:5000/api/close_day", json={}, timeout=60)
                        if res.status_code == 200:
                            data = res.json()
                            if data.get("http_status") == 200:
                                print("✅ [AUTO-SCHEDULER] Fiscal day closed successfully!")
                                scheduler_state['last_closed_date'] = today_str
                                send_os_notification("🌙 Auto Closed", "Fiscal day closed automatically at 5:00 PM.")
                            else:
                                print(f"⚠️ [AUTO-SCHEDULER] ZIMRA rejected close: {data.get('zimra_response')}")
                    except Exception as e:
                        print(f"❌ [AUTO-SCHEDULER] Error closing day: {e}")

            # 2. Auto Open at 8:30 AM (08:30)
            if current_time >= dt_time(8, 30) and current_time < dt_time(8, 40):
                if scheduler_state['last_opened_date'] != today_str:
                    if "Closed" in current_status:
                        print(f"\n⏰ [AUTO-SCHEDULER] 8:30 AM reached. Opening new fiscal day...")
                        try:
                            res_details = requests.get("http://localhost:5000/api/device_details", timeout=10)
                            next_day = 1
                            if res_details.status_code == 200:
                                current_day = res_details.json().get("fiscal_day_no", "0")
                                try: next_day = int(current_day) + 1
                                except: next_day = 1
                            
                            res = requests.post("http://localhost:5000/api/open_day", json={"fiscalDayNo": next_day}, timeout=30)
                            if res.status_code == 200:
                                data = res.json()
                                if data.get("http_status") == 200:
                                    print("✅ [AUTO-SCHEDULER] Fiscal day opened successfully!")
                                    scheduler_state['last_opened_date'] = today_str
                                    send_os_notification("☀️ Auto Opened", f"Fiscal day {next_day} opened automatically at 8:30 AM.")
                                else:
                                    print(f"⚠️ [AUTO-SCHEDULER] ZIMRA rejected open: {data.get('zimra_response')}")
                        except Exception as e:
                            print(f"❌ [AUTO-SCHEDULER] Error opening day: {e}")
                            
                    elif "Opened" in current_status:
                        # Fallback: If yesterday's day is still open at 8:30 AM, close it first
                        print(f"⚠️ [AUTO-SCHEDULER] Previous day is still open at 8:30 AM. Closing it first...")
                        try:
                            res_close = requests.post("http://localhost:5000/api/close_day", json={}, timeout=60)
                            if res_close.status_code == 200 and res_close.json().get("http_status") == 200:
                                scheduler_state['last_closed_date'] = today_str
                                print("✅ [AUTO-SCHEDULER] Previous day closed. Now opening today's day...")
                                
                                res_details = requests.get("http://localhost:5000/api/device_details", timeout=10)
                                next_day = 1
                                if res_details.status_code == 200:
                                    current_day = res_details.json().get("fiscal_day_no", "0")
                                    try: next_day = int(current_day) + 1
                                    except: next_day = 1
                                
                                res_open = requests.post("http://localhost:5000/api/open_day", json={"fiscalDayNo": next_day}, timeout=30)
                                if res_open.status_code == 200 and res_open.json().get("http_status") == 200:
                                    scheduler_state['last_opened_date'] = today_str
                                    send_os_notification("☀️ Auto Opened", f"Previous day closed & Day {next_day} opened automatically.")
                        except Exception as e:
                            print(f"❌ [AUTO-SCHEDULER] Error in fallback close/open: {e}")

        except Exception as e:
            print(f"❌ [AUTO-SCHEDULER] Unexpected error: {e}")
            
        # Sleep for 60 seconds
        time.sleep(60)

# ============================================================
# DATABASE & SCANNER SETUP
# ============================================================
def ensure_scanner_tables():
    with db_lock:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            
            # 1. Create scanner_logs table
            cursor.execute('''CREATE TABLE IF NOT EXISTS scanner_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, 
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, 
                message TEXT, 
                status TEXT
            )''')
            
            # 2. Create system_config table
            cursor.execute('''CREATE TABLE IF NOT EXISTS system_config (key TEXT PRIMARY KEY, value TEXT)''')
            
            # 3. Insert default configurations
            cursor.execute("INSERT OR IGNORE INTO system_config (key, value) VALUES ('scanner_print_format', 'InvoiceA4')")
            cursor.execute("INSERT OR IGNORE INTO system_config (key, value) VALUES ('scanner_folder', 'C:\\Receipt')")
            cursor.execute("INSERT OR IGNORE INTO system_config (key, value) VALUES ('process_pdfs', 'True')")
            
            # 4. Force AIBES as the absolute default template
            cursor.execute("INSERT OR IGNORE INTO system_config (key, value) VALUES ('receipt_template', 'aibes')")
            
            # 5. Auto-upgrade any old databases that might still say 'melivo'
            cursor.execute("UPDATE system_config SET value = 'aibes' WHERE key = 'receipt_template' AND value = 'melivo'")
            
            # 6. Create receipt_items table
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
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )''')
            
            # 7. Check if receipt_currency column exists, add if missing (for legacy DBs)
            cursor.execute("PRAGMA table_info(receipt_items)")
            columns = [col[1] for col in cursor.fetchall()]
            if 'receipt_currency' not in columns:
                cursor.execute("ALTER TABLE receipt_items ADD COLUMN receipt_currency TEXT DEFAULT 'USD'")
            
            # 8. Commit all changes
            conn.commit()

ensure_scanner_tables()

scanner_state = {'is_running': False, 'thread': None, 'folder': '', 'log': []}

def log_to_db(message, status="INFO"):
    try:
        with db_lock:
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("INSERT INTO scanner_logs (message, status) VALUES (?, ?)", (message, status))
    except Exception as e:
        print(f"DB Log Error: {e}")
    scanner_state['log'].append(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")
    if len(scanner_state['log']) > 100:
        scanner_state['log'] = scanner_state['log'][-100:]

def get_scanner_settings():
    with db_lock:
        with sqlite3.connect(DB_PATH) as conn:
            folder = conn.execute("SELECT value FROM system_config WHERE key = 'scanner_folder'").fetchone()
            fmt = conn.execute("SELECT value FROM system_config WHERE key = 'scanner_print_format'").fetchone()
            tpl = conn.execute("SELECT value FROM system_config WHERE key = 'receipt_template'").fetchone()
            pdfs = conn.execute("SELECT value FROM system_config WHERE key = 'process_pdfs'").fetchone()
    return {
        "folder_path": folder[0] if folder else r'C:\Receipt',
        "print_format": fmt[0] if fmt else 'InvoiceA4',
        "template": tpl[0] if tpl else 'aibes',
        "process_pdfs": pdfs[0] == 'True' if pdfs else True
    }

def process_single_file(file_path, folder_path):
    filename = os.path.basename(file_path)
    full_payload = None
    is_pdf = filename.lower().endswith('.pdf')
    
    try:
        settings = get_scanner_settings()
        
        # 1. Parse the file based on extension and template
        if is_pdf:
            template = settings['template']
            if template.lower() == 'aibes':
                from core.receipt_parser import parse_aibes_receipt
                parsed_data = parse_aibes_receipt(file_path)
            else:
                # Feedmix or other PDF templates
                from core.receipt_parser import parse_pdf_receipt
                parsed_data = parse_pdf_receipt(file_path)
        else:
            # TXT files (Feedmix)
            parsed_data = parse_receipt_file(file_path, template=settings['template'])
            
        state = zimra.get_state()
        
        receipt_payload = build_zimra_payload(
            parsed_data, 
            device_id=zimra.device_id,
            receipt_counter=state['receipt_counter'], 
            receipt_global_no=state['receipt_global_no'],
            fiscal_day_no=state['fiscal_day_no']
        )
        
        # ============================================================
        # VALIDATION 1: Check Buyer Name (Optional)
        # ============================================================
        buyer_name = str(parsed_data.get('buyer_name', '')).strip()

        # ============================================================
        # VALIDATION 2: Duplicate Invoice Number
        # ============================================================
        invoice_no = str(parsed_data.get('invoice_no', '')).strip()
        if invoice_no:
            with db_lock:
                with sqlite3.connect(DB_PATH) as conn:
                    cursor = conn.execute("SELECT id FROM receipt_audit WHERE invoice_no = ? AND status = 'SUCCESS'", (invoice_no,))
                    if cursor.fetchone():
                        send_os_notification("❌ Validation Failed", f"Duplicate Invoice Number: {invoice_no}")
                        log_to_db(f"[VALIDATION FAILED] {filename} -> Duplicate Invoice Number {invoice_no}", "FAILED")
                        move_to = os.path.join(folder_path, 'Failed')
                        os.makedirs(move_to, exist_ok=True)
                        shutil.move(file_path, os.path.join(move_to, filename))
                        return f"[VALIDATION FAILED] {filename}"
        # ============================================================

        full_payload = {"deviceID": int(zimra.device_id), "receipt": receipt_payload}
        full_payload['receipt']['receiptPrintForm'] = settings['print_format']
        
        validation_errors = validate_zimra_payload(full_payload)
        if validation_errors:
            audit_data = {
                'zimra_receipt_id': None, 'device_id': zimra.device_id, 'fiscal_day_no': state['fiscal_day_no'],
                'receipt_counter': state['receipt_counter'], 'receipt_global_no': state['receipt_global_no'],
                'receipt_type': full_payload['receipt']['receiptType'], 'invoice_no': full_payload['receipt']['invoiceNo'],
                'receipt_date': full_payload['receipt']['receiptDate'], 'total_amount': full_payload['receipt']['receiptTotal'],
                'receipt_currency': full_payload['receipt']['receiptCurrency'],
                'hash_b64': '', 'verification_code': '', 'qr_code': '',
                'zimra_response': json.dumps({"validation_errors": validation_errors}), 'status': 'FAILED'
            }
            zimra.log_receipt_audit(audit_data)
            send_os_notification("️ Validation Failed", f"{filename}\n{', '.join(validation_errors)[:100]}")
            payload_str = json.dumps(full_payload, indent=2)
            log_msg = f"[VALIDATION FAILED] {filename} -> {', '.join(validation_errors)}\n\n--- GENERATED PAYLOAD ---\n{payload_str}\n-------------------------"
            log_to_db(log_msg, "FAILED")
            move_to = os.path.join(folder_path, 'Failed'); os.makedirs(move_to, exist_ok=True); shutil.move(file_path, os.path.join(move_to, filename))
            return f"[VALIDATION FAILED] {filename}"
            
        status_code, zimra_response, ver_code, qr_code, hash_b64, receipt_audit_id = zimra.submit_receipt(full_payload)
        
        if status_code == 200:
            try:
                zimra.log_receipt_items(
                    receipt_audit_id=receipt_audit_id,
                    invoice_no=parsed_data.get('invoice_no', ''),
                    receipt_date=parsed_data.get('date', ''),
                    receipt_currency=parsed_data.get('currency', 'USD'),
                    items=parsed_data.get('items', [])
                )
            except Exception as items_err:
                print(f"Error storing items: {items_err}")
                
            try:
                config_status, config_resp = zimra.get_config()
                seller_data = {
                    'name': config_resp.get('deviceBranchName', 'FISCALINK'),
                    'address': f"{config_resp.get('deviceBranchAddress', {}).get('houseNo', '')} {config_resp.get('deviceBranchAddress', {}).get('street', '')}, {config_resp.get('deviceBranchAddress', {}).get('city', '')}",
                    'tin': config_resp.get('taxPayerTIN', ''), 'vat': config_resp.get('vatNumber', ''),
                    'phone': config_resp.get('deviceBranchContacts', {}).get('phoneNo', ''), 'email': config_resp.get('deviceBranchContacts', {}).get('email', '')
                }
                
                # ============================================================
                # OUTPUT GENERATION: PDF vs TXT
                # ============================================================
                if is_pdf:
                    # --- PDF: Stamp QR Code ---
                    from core.pdf_stamper import stamp_qr_on_pdf
                    stamped_filename = filename.replace('.pdf', '_stamped.pdf')
                    stamped_path = os.path.join(folder_path, stamped_filename)
                    fiscal_day_no = state.get('fiscal_day_no', 'N/A')
                    device_id = zimra.device_id
                    receipt_global_no = state.get('receipt_global_no', 'N/A')
                    
                    if stamp_qr_on_pdf(file_path, qr_code, stamped_path, fiscal_day_no, device_id, receipt_global_no, ver_code):
                        move_to = os.path.join(folder_path, 'Processed')
                        os.makedirs(move_to, exist_ok=True)
                        shutil.move(stamped_path, os.path.join(move_to, stamped_filename))
                        if os.path.exists(file_path): os.remove(file_path)
                        send_os_notification("✅ PDF Successfully Stamped", f"{filename}\nVerification Code: {ver_code}")
                        log_to_db(f"[SUCCESS] {filename} | Code: {ver_code} | QR Stamped & Moved to Processed", "SUCCESS")
                    else:
                        move_to = os.path.join(folder_path, 'Processed')
                        os.makedirs(move_to, exist_ok=True)
                        shutil.move(file_path, os.path.join(move_to, filename))
                        send_os_notification("⚠️ Stamp Failed", f"{filename} was fiscalized but stamping failed.")
                        log_to_db(f"[WARNING] {filename} | Code: {ver_code} | Moved (Stamp Failed)", "WARNING")
                else:
                    # --- TXT: Generate 80mm Receipt PDF ---
                    from core.pdf_generator import generate_80mm_thermal_receipt
                    pdf_payload = {"receipt": full_payload['receipt'], "company_name": seller_data['name'], "seller_data": seller_data}
                    serial_number = Config.DEVICE_SERIAL_NUMBER
                    
                    # Use the new 80mm thermal receipt generator
                    pdf_buffer = generate_80mm_thermal_receipt(
                        pdf_payload, ver_code, qr_code, 
                        zimra.device_id, state['fiscal_day_no'], 
                        state['receipt_global_no'], seller_data, serial_number
                    )
                    
                    # Save the 80mm PDF in the Processed folder
                    move_to = os.path.join(folder_path, 'Processed')
                    os.makedirs(move_to, exist_ok=True)
                    
                    pdf_filename = f"Receipt_{filename.replace('.txt', '.pdf')}"
                    pdf_path = os.path.join(move_to, pdf_filename)
                    with open(pdf_path, 'wb') as f: 
                        f.write(pdf_buffer.getvalue())
                    
                    # Move the original TXT to Processed as well
                    shutil.move(file_path, os.path.join(move_to, filename))
                    
                    send_os_notification("✅ 80mm Receipt Generated", f"{filename}\nCode: {ver_code}")
                    log_to_db(f"[SUCCESS] {filename} | Code: {ver_code} | 80mm PDF Generated & Saved", "SUCCESS")
                    
            except Exception as pdf_err:
                log_to_db(f"[SUCCESS] {filename} | Code: {ver_code} | PDF Error: {str(pdf_err)}", "WARNING")
            return f"[SUCCESS] {filename} | Code: {ver_code}"
        else:
            error_msg = zimra_response if isinstance(zimra_response, str) else json.dumps(zimra_response, indent=2)
            send_os_notification("❌ ZIMRA Submission Failed", f"{filename}\nStatus {status_code}")
            payload_str = json.dumps(full_payload, indent=2) if full_payload else "Payload not available"
            log_msg = f"[ZIMRA ERROR] {filename} -> Status {status_code}: {error_msg}\n\n--- GENERATED PAYLOAD ---\n{payload_str}\n-------------------------"
            log_to_db(log_msg, "FAILED")
            move_to = os.path.join(folder_path, 'Failed'); os.makedirs(move_to, exist_ok=True); shutil.move(file_path, os.path.join(move_to, filename))
            return f"[FAILED] {filename} -> ZIMRA Error {status_code}"
    except Exception as e:
        send_os_notification("⚠️ System Error", f"Failed to process {filename}\n{str(e)[:100]}")
        payload_str = json.dumps(full_payload, indent=2) if full_payload else "Payload not available (error occurred before payload generation)"
        log_msg = f"[ERROR] {filename} -> {str(e)}\n\n--- GENERATED PAYLOAD ---\n{payload_str}\n-------------------------"
        log_to_db(log_msg, "ERROR")
        move_to = os.path.join(folder_path, 'Errors'); os.makedirs(move_to, exist_ok=True); shutil.move(file_path, os.path.join(move_to, filename))
        return f"[ERROR] {filename}"

def scanner_loop(folder_path):
    while scanner_state['is_running']:
        if not os.path.exists(folder_path): 
            log_to_db(f"Folder {folder_path} not found. Stopping.", "ERROR")
            scanner_state['is_running'] = False
            break
        settings = get_scanner_settings()
        process_pdfs = settings.get('process_pdfs', True)
        files = [f for f in os.listdir(folder_path) if f.endswith('.txt') or (f.endswith('.pdf') and process_pdfs)]
        if files:
            log_to_db(f"Scanning {len(files)} file(s)...", "INFO")
            for filename in files:
                if not scanner_state['is_running']: break
                file_path = os.path.join(folder_path, filename)
                is_ready = False
                for _ in range(3):
                    try:
                        with open(file_path, 'rb') as f: is_ready = True; break
                    except IOError: time.sleep(1)
                if is_ready:
                    process_single_file(file_path, folder_path)
        time.sleep(5)

@app.route('/api/start_scanning', methods=['POST'])
def api_start_scanning():
    data = request.json
    folder_path = data.get('folder_path', r'C:\Receipt')
    process_pdfs = data.get('process_pdfs', True)
    with db_lock:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("INSERT OR REPLACE INTO system_config (key, value) VALUES ('scanner_folder', ?)", (folder_path,))
            conn.execute("INSERT OR REPLACE INTO system_config (key, value) VALUES ('process_pdfs', ?)", (str(process_pdfs),))
            if 'receipt_print_format' in data:
                conn.execute("INSERT OR REPLACE INTO system_config (key, value) VALUES ('scanner_print_format', ?)", (data['receipt_print_format'],))
            if 'receipt_template' in data:
                conn.execute("INSERT OR REPLACE INTO system_config (key, value) VALUES ('receipt_template', ?)", (data['receipt_template'],))
    if scanner_state['is_running']: return jsonify({"status": "already_running"})
    scanner_state['folder'] = folder_path; scanner_state['is_running'] = True; scanner_state['log'] = []
    log_to_db(f"Scanner started for {folder_path}", "INFO")
    scanner_state['thread'] = threading.Thread(target=scanner_loop, args=(folder_path,), daemon=True); scanner_state['thread'].start()
    return jsonify({"status": "started"})

@app.route('/api/stop_scanning', methods=['POST'])
def api_stop_scanning():
    scanner_state['is_running'] = False
    log_to_db("Scanner stopped by user.", "INFO")
    return jsonify({"status": "stopped"})

@app.route('/api/scanner_status', methods=['GET'])
def api_scanner_status():
    return jsonify({"is_running": scanner_state['is_running'], "log": scanner_state['log'][-50:]})

@app.route('/api/scanner_settings', methods=['GET'])
def api_scanner_settings():
    settings = get_scanner_settings()
    settings["is_running"] = scanner_state['is_running']
    return jsonify(settings)

@app.route('/api/scanner_history', methods=['GET'])
def api_scanner_history():
    ensure_scanner_tables()
    limit = request.args.get('limit', 200)
    with db_lock:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM scanner_logs ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
    return jsonify([{"id": r['id'], "timestamp": r['timestamp'], "message": r['message'], "status": r['status']} for r in rows])

@app.route('/api/clear_scanner_history', methods=['POST'])
def api_clear_scanner_history():
    with db_lock:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("DELETE FROM scanner_logs")
    return jsonify({"status": "cleared"})

@app.route('/api/status', methods=['POST'])
def api_status():
    status_code, response = zimra.get_status()
    return jsonify({"http_status": status_code, "zimra_response": response})

@app.route('/api/open_day', methods=['POST'])
def api_open_day():
    data = request.json or {}; fiscal_day_no = data.get('fiscalDayNo')
    status_code, response = zimra.open_day(fiscal_day_no)
    if status_code == 200:
        actual_day_no = response.get('fiscalDayNo', fiscal_day_no) if isinstance(response, dict) else fiscal_day_no
        zimra.reset_daily_counter(actual_day_no, datetime.now().strftime("%Y-%m-%d"))
    return jsonify({"http_status": status_code, "zimra_response": response})

@app.route('/api/device_details', methods=['GET'])
def api_device_details():
    try:
        state = zimra.get_state()
        details = {
            "company_name": "Vantoss Enterprises",
            "device_id": zimra.device_id,
            "serial_number": Config.DEVICE_SERIAL_NUMBER,
            "vat_number": "220028226",
            "taxpayer_tin": "2000446071",
            "fiscal_day_no": state.get('fiscal_day_no', 'N/A'),
            "receipt_global_no": state.get('receipt_global_no', 'N/A'),
            "status": "Active"
        }
        try:
            status_code, config_resp = zimra.get_config()
            if status_code == 200:
                details["company_name"] = config_resp.get('deviceBranchName', details["company_name"])
                details["serial_number"] = config_resp.get('deviceSerialNo', Config.DEVICE_SERIAL_NUMBER)
                details["vat_number"] = config_resp.get('vatNumber', details["vat_number"])
                details["taxpayer_tin"] = config_resp.get('taxPayerTIN', details["taxpayer_tin"])
        except: pass
        return jsonify(details)
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/api/get_device_config', methods=['GET'])
def api_get_device_config():
    try:
        status_code, response = zimra.get_config()
        return jsonify({"http_status": status_code, "config": response})
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/api/submit_receipt', methods=['POST'])
def api_submit_receipt():
    try:
        data = request.json
        if not data: return jsonify({"Code": "0", "Message": "Invalid or missing JSON payload"}), 400
        receipt_type = data.get('receiptType', 'FiscalInvoice')
        currency = data.get('currency', 'USD')
        total = float(data.get('receiptTotal', 0))
        tax_percent = float(data.get('taxPercent', 15.5))
        quantity = float(data.get('quantity', 2))
        state = zimra.get_state()
        counter = state['receipt_counter']; global_no = state['receipt_global_no']; fiscal_day = state['fiscal_day_no']
        amt1 = round(total * 0.60, 2); amt2 = round(total * 0.20, 2); amt3 = round(total - amt1 - amt2, 2)
        tax1 = round(amt1 * (tax_percent / (100 + tax_percent)), 2)
        if receipt_type.lower() == 'creditnote':
            amt1, amt2, amt3 = -abs(amt1), -abs(amt2), -abs(amt3); tax1 = -abs(tax1); total = -abs(total)
        item_name = data.get('itemName', 'Item')
        receipt_lines = [
            {"receiptLineType": "Sale", "receiptLineNo": 1, "receiptLineHSCode": "10000000", "receiptLineName": f"{item_name} (Standard)", "receiptLinePrice": round(amt1 / quantity, 2), "receiptLineQuantity": quantity, "receiptLineTotal": amt1, "taxCode": "A", "taxPercent": tax_percent, "taxID": 515},
            {"receiptLineType": "Sale", "receiptLineNo": 2, "receiptLineHSCode": "20000000", "receiptLineName": f"{item_name} (Exempt)", "receiptLinePrice": round(amt2 / quantity, 2), "receiptLineQuantity": quantity, "receiptLineTotal": amt2, "taxCode": "B", "taxPercent": 0.0, "taxID": 2},
            {"receiptLineType": "Sale", "receiptLineNo": 3, "receiptLineHSCode": "20000000", "receiptLineName": f"{item_name} (Zero Rated)", "receiptLinePrice": round(amt3 / quantity, 2), "receiptLineQuantity": quantity, "receiptLineTotal": amt3, "taxCode": "B", "taxPercent": 0.0, "taxID": 2}
        ]
        receipt_taxes = [
            {"taxCode": "A", "taxPercent": tax_percent, "taxID": 515, "taxAmount": tax1, "salesAmountWithTax": amt1},
            {"taxCode": "B", "taxPercent": 0.0, "taxID": 2, "taxAmount": 0.00, "salesAmountWithTax": round(amt2 + amt3, 2)}
        ]
        payload = {
            "deviceID": int(zimra.device_id), "receipt": {
                "receiptType": receipt_type.upper().replace(" ", ""), "receiptCurrency": currency, "receiptCounter": counter, "receiptGlobalNo": global_no, 
                "invoiceNo": data.get('invoiceNo', f"INV-{counter}"),
                "buyerData": {"buyerRegisterName": data.get('buyerName', 'Test Buyer'), "buyerTradeName": data.get('buyerTradeName', data.get('buyerName', '')),
                              "buyerTIN": data.get('buyerTIN', '2000457810'), "vatNumber": data.get('buyerVATNumber', '220006789'),
                              "buyerContacts": {"email": data.get('buyerEmail', 'test@gmail.com'), "phoneNo": data.get('buyerPhone', '0798567859')},
                              "buyerAddress": {"province": data.get('buyerProvince', 'Harare'), "street": data.get('buyerStreet', '1at Street'), "houseNo": data.get('buyerHouseNo', '787'), "city": data.get('buyerCity', 'Harare')}},
                "receiptNotes": data.get('receiptNotes', 'Invoice is issued after purchasing goods'), "receiptDate": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), "receiptLinesTaxInclusive": True,
                "receiptLines": receipt_lines, "receiptTaxes": receipt_taxes,
                "receiptPayments": [{"moneyTypeCode": data.get('moneyTypeCode', 'Cash'), "paymentAmount": total}],
                "receiptTotal": total, "receiptPrintForm": data.get('printFormat', 'InvoiceA4')
            }
        }
        if receipt_type.lower() == 'creditnote' and data.get('originalInvoiceNo'):
            payload['receipt']['receiptNotes'] = f"Credit Note for {data['originalInvoiceNo']}"
            payload['receipt']['creditDebitNote'] = {
                "deviceID": int(zimra.device_id), 
                "receiptGlobalNo": data.get('originalGlobalNo', global_no - 1), 
                "fiscalDayNo": fiscal_day,
                "receiptDate": data.get('originalDate', datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))
            }
        
        validation_errors = validate_zimra_payload(payload)
        if validation_errors: return jsonify({"Code": "0", "Message": "Payload failed ZIMRA validation.", "ValidationErrors": validation_errors, "DeviceId": str(zimra.device_id)}), 400
            
        status_code, zimra_response, ver_code, qr_code, hash_b64, receipt_audit_id = zimra.submit_receipt(payload)
        if status_code == 200:
            try:
                items_data = [{"name": l['receiptLineName'], "qty": l['receiptLineQuantity'], "price": l['receiptLinePrice'], "total": l['receiptLineTotal'], "tax_code": l['taxCode'], "tax_pct": l['taxPercent']} for l in receipt_lines]
                zimra.log_receipt_items(receipt_audit_id, payload['receipt']['invoiceNo'], payload['receipt']['receiptDate'], currency, items_data)
            except Exception as e:
                print(f"Error logging items: {e}")
        api_response = {"Code": "1" if status_code == 200 else "0", "Message": "Success" if status_code == 200 else f"ZIMRA Error: {zimra_response}",
                        "DeviceId": str(zimra.device_id), "QRcode": qr_code, "VerificationCode": ver_code, "VerificationLink": qr_code,
                        "FiscalDay": fiscal_day, "ZimraRawResponse": zimra_response, "Data": {"Receipt": payload['receipt']}}
        return jsonify(api_response), 200 if status_code == 200 else 400
    except Exception as e:
        import traceback; error_trace = traceback.format_exc(); print(f"CRITICAL ERROR IN /api/submit_receipt:\n{error_trace}")
        return jsonify({"Code": "0", "Message": f"Internal Server Error: {str(e)}", "Trace": error_trace}), 500

@app.route('/api/close_day', methods=['POST'])
def api_close_day():
    try:
        data = request.json or {}; fiscal_day_no = data.get('fiscalDayNo')
        state = zimra.get_state()
        if not fiscal_day_no: fiscal_day_no = state['fiscal_day_no']
        last_receipt_counter = max(0, state['receipt_counter'] - 1)
        with db_lock:
            with sqlite3.connect(DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute("SELECT id, receipt_type, receipt_currency, total_amount FROM receipt_audit WHERE fiscal_day_no = ? AND status = 'SUCCESS'", (fiscal_day_no,)).fetchall()
                receipt_ids = [row['id'] for row in rows]
                if receipt_ids:
                    placeholders = ','.join('?' * len(receipt_ids))
                    items = conn.execute(f"SELECT ra.receipt_currency, ra.receipt_type, ri.tax_percent, ri.total FROM receipt_items ri JOIN receipt_audit ra ON ri.receipt_audit_id = ra.id WHERE ra.id IN ({placeholders})", receipt_ids).fetchall()
                else:
                    items = []
        currencies = defaultdict(lambda: {'total_sales': 0.0, 'total_tax': 0.0, 'count': 0})
        sale_by_tax = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
        sale_tax_by_tax = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
        balance_by_money = defaultdict(float)
        for row in rows:
            curr = row['receipt_currency'] or 'USD'
            total = float(row['total_amount'] or 0)
            r_type = row['receipt_type'].upper().replace(" ", "")
            currencies[curr]['total_sales'] += total; currencies[curr]['count'] += 1; balance_by_money[(curr, 'Cash')] += total
        if items:
            for item in items:
                curr = item['receipt_currency'] or 'USD'; r_type = item['receipt_type'].upper().replace(" ", "")
                tax_pct = float(item['tax_percent'] or 0); total = float(item['total'] or 0)
                if tax_pct > 0:
                    tax_amt = round(total - (total / (1 + (tax_pct / 100.0))), 2)
                else:
                    tax_amt = 0.0
                currencies[curr]['total_tax'] += tax_amt
                if r_type == 'FISCALINVOICE': counter_type = 'SaleByTax'; tax_counter_type = 'SaleTaxByTax'
                elif r_type == 'CREDITNOTE': counter_type = 'CreditNoteByTax'; tax_counter_type = 'CreditNoteTaxByTax'
                else: continue
                sale_by_tax[curr][counter_type][tax_pct] += total; sale_tax_by_tax[curr][tax_counter_type][tax_pct] += tax_amt
        fiscal_counters = []
        for curr, r_types in sale_by_tax.items():
            for r_type, taxes in r_types.items():
                for tax_pct, val in taxes.items():
                    if val != 0:
                        tax_id = 515 if tax_pct == 15.5 else (2 if tax_pct == 0.0 else 515)
                        fiscal_counters.append({"fiscalCounterType": r_type, "fiscalCounterCurrency": curr, "fiscalCounterTaxPercent": float(f"{float(tax_pct):.2f}"), "fiscalCounterTaxID": int(tax_id), "fiscalCounterValue": float(f"{float(val):.2f}")})
        for curr, r_types in sale_tax_by_tax.items():
            for r_type, taxes in r_types.items():
                for tax_pct, val in taxes.items():
                    if val != 0:
                        tax_id = 515 if tax_pct == 15.5 else (2 if tax_pct == 0.0 else 515)
                        fiscal_counters.append({"fiscalCounterType": r_type, "fiscalCounterCurrency": curr, "fiscalCounterTaxPercent": float(f"{float(tax_pct):.2f}"), "fiscalCounterTaxID": int(tax_id), "fiscalCounterValue": float(f"{float(val):.2f}")})
        for (curr, mtype), val in balance_by_money.items():
            if val != 0: fiscal_counters.append({"fiscalCounterType": "BalanceByMoneyType", "fiscalCounterCurrency": curr, "fiscalCounterMoneyType": mtype, "fiscalCounterValue": float(f"{float(val):.2f}")})
        status_code, response = zimra.close_day(fiscal_day_no, last_receipt_counter, fiscal_counters)
        z_report = {"fiscal_day_no": fiscal_day_no, "device_id": zimra.device_id, "close_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "total_receipts": len(rows), "currencies": dict(currencies)}
        with db_lock:
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("INSERT INTO z_reports (fiscal_day_no, device_id, close_date, total_receipts, currencies_json, total_sales, total_tax, zimra_response_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (fiscal_day_no, zimra.device_id, z_report['close_date'], z_report['total_receipts'], json.dumps(z_report['currencies']), sum(c['total_sales'] for c in currencies.values()), sum(c['total_tax'] for c in currencies.values()), json.dumps(response)))
        return jsonify({"http_status": status_code, "zimra_response": response, "z_report": z_report})
    except Exception as e:
        import traceback; traceback.print_exc(); return jsonify({"http_status": 500, "error": str(e)}), 500

@app.route('/api/receipt_stats', methods=['GET'])
def api_receipt_stats():
    try:
        with db_lock:
            with sqlite3.connect(DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                total_success = conn.execute("SELECT COUNT(*) as count FROM receipt_audit WHERE status = 'SUCCESS'").fetchone()['count']
                total_failed = conn.execute("SELECT COUNT(*) as count FROM receipt_audit WHERE status != 'SUCCESS'").fetchone()['count']
                recent_success = conn.execute("SELECT * FROM receipt_audit WHERE status = 'SUCCESS' ORDER BY created_at DESC LIMIT 10").fetchall()
                recent_failed = conn.execute("SELECT * FROM receipt_audit WHERE status != 'SUCCESS' ORDER BY created_at DESC LIMIT 10").fetchall()
        def to_dict(row):
            resp = row['zimra_response'] or ''
            return {"invoice_no": row['invoice_no'], "total_amount": row['total_amount'], "verification_code": row['verification_code'], "status": row['status'], "created_at": row['created_at'], "zimra_response": (resp[:100] + "...") if len(resp) > 100 else resp}
        return jsonify({"total_success": total_success, "total_failed": total_failed, "recent_success": [to_dict(r) for r in recent_success], "recent_failed": [to_dict(r) for r in recent_failed]})
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/api/z_reports', methods=['GET'])
def api_get_z_reports():
    try:
        with db_lock:
            with sqlite3.connect(DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute("SELECT * FROM z_reports ORDER BY created_at DESC").fetchall()
        reports = []
        for row in rows:
            reports.append({"id": row['id'], "fiscal_day_no": row['fiscal_day_no'], "close_date": row['close_date'], "total_receipts": row['total_receipts'], "total_sales": row['total_sales'], "total_tax": row['total_tax'], "currencies": json.loads(row['currencies_json'])})
        return jsonify(reports)
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/api/z_report/<int:report_id>', methods=['GET'])
def api_download_z_report(report_id):
    try:
        with db_lock:
            with sqlite3.connect(DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute("SELECT * FROM z_reports WHERE id = ?", (report_id,)).fetchone()
        if not row: return jsonify({"error": "Report not found"}), 404
        report_data = {"id": row['id'], "fiscal_day_no": row['fiscal_day_no'], "device_id": row['device_id'], "close_date": row['close_date'], "total_receipts": row['total_receipts'], "currencies": json.loads(row['currencies_json']), "zimra_response": json.loads(row['zimra_response_json'])}
        return Response(json.dumps(report_data, indent=2), mimetype='application/json', headers={'Content-Disposition': f'attachment; filename="ZReport_Day{row["fiscal_day_no"]}.json"'})
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/api/z_report_pdf/<int:report_id>', methods=['GET'])
def api_z_report_pdf(report_id):
    try:
        with db_lock:
            with sqlite3.connect(DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute("SELECT * FROM z_reports WHERE id = ?", (report_id,)).fetchone()
        if not row: return jsonify({"error": "Report not found"}), 404
        report_data = {"fiscal_day_no": row['fiscal_day_no'], "device_id": row['device_id'], "close_date": row['close_date'], "total_receipts": row['total_receipts'], "currencies": json.loads(row['currencies_json'])}
        pdf_buffer = generate_z_report_pdf(report_data); pdf_content = pdf_buffer.getvalue()
        return Response(pdf_content, mimetype='application/pdf', headers={'Content-Disposition': f'attachment; filename="ZReport_Day{row["fiscal_day_no"]}.pdf"'})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route('/api/print_pdf', methods=['POST'])
def api_print_pdf():
    try:
        data = request.json; receipt_data = data.get('receipt_data'); ver_code = data.get('verification_code'); qr_url = data.get('qr_code'); print_format = data.get('print_format', 'InvoiceA4')
        if not receipt_data: return jsonify({"error": "No receipt data provided"}), 400
        device_id = zimra.device_id; fiscal_day_no = 1
        with db_lock:
            with sqlite3.connect(DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute("SELECT fiscal_day_no FROM fiscal_state WHERE device_id = ?", (str(device_id),)).fetchone()
                if row and row['fiscal_day_no']: fiscal_day_no = row['fiscal_day_no']
        config_status, config_resp = zimra.get_config()
        seller_data = {
            'name': config_resp.get('deviceBranchName', 'FISCALINK'),
            'address': f"{config_resp.get('deviceBranchAddress', {}).get('houseNo', '')} {config_resp.get('deviceBranchAddress', {}).get('street', '')}, {config_resp.get('deviceBranchAddress', {}).get('city', '')}",
            'tin': config_resp.get('taxPayerTIN', ''), 'vat': config_resp.get('vatNumber', ''),
            'phone': config_resp.get('deviceBranchContacts', {}).get('phoneNo', ''), 'email': config_resp.get('deviceBranchContacts', {}).get('email', '')
        }
        receipt_data['company_name'] = seller_data['name']
        serial_number = Config.DEVICE_SERIAL_NUMBER
        pdf_buffer = generate_zimra_a4_pdf(receipt_data, ver_code, qr_url, device_id, fiscal_day_no, print_format, seller_data, serial_number=serial_number)
        pdf_content = pdf_buffer.getvalue()
        if len(pdf_content) == 0: return jsonify({"error": "Generated PDF is empty"}), 500
        receipt_obj = receipt_data.get('receipt', receipt_data.get('Receipt', {})); inv_no = receipt_obj.get('invoiceNo', 'unknown')
        return Response(pdf_content, mimetype='application/pdf', headers={'Content-Disposition': f'attachment; filename="ZIMRA_{inv_no}.pdf"', 'Content-Length': str(len(pdf_content))})
    except Exception as e: return jsonify({"error": f"PDF generation failed: {str(e)}"}), 500

@app.route('/api/download_successful_receipts', methods=['GET'])
def api_download_successful_receipts():
    """Download all successful receipts as CSV."""
    try:
        with db_lock:
            with sqlite3.connect(DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute("SELECT invoice_no, receipt_date, receipt_currency, total_amount, verification_code, created_at FROM receipt_audit WHERE status = 'SUCCESS' ORDER BY created_at DESC").fetchall()
        
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Invoice No', 'Date', 'Currency', 'Total Amount', 'Verification Code', 'Created At'])
        for row in rows:
            writer.writerow([row['invoice_no'], row['receipt_date'], row['receipt_currency'], row['total_amount'], row['verification_code'], row['created_at']])
        
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment; filename=successful_receipts.csv'}
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/print_test_80mm', methods=['GET'])
def api_print_test_80mm():
    try:
        config_status, config_resp = zimra.get_config()
        seller_data = {
            'name': config_resp.get('deviceBranchName', 'FISCALINK'),
            'address': f"{config_resp.get('deviceBranchAddress', {}).get('houseNo', '')} {config_resp.get('deviceBranchAddress', {}).get('street', '')}, {config_resp.get('deviceBranchAddress', {}).get('city', '')}",
            'tin': config_resp.get('taxPayerTIN', ''), 'vat': config_resp.get('vatNumber', ''),
            'phone': config_resp.get('deviceBranchContacts', {}).get('phoneNo', ''), 'email': config_resp.get('deviceBranchContacts', {}).get('email', '')
        }
        serial_no = Config.DEVICE_SERIAL_NUMBER
        mock_receipt = {
            "receiptType": "FiscalInvoice", "receiptCurrency": "USD", "receiptCounter": 1, "receiptGlobalNo": 1,
            "invoiceNo": "TEST-WT-SWAN", "receiptTotal": 3.89, "receiptDate": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "buyerData": {
                "buyerRegisterName": "W T SWAN (PVT) LTD", "buyerTIN": "2000223510", "vatNumber": "220187853",
                "buyerContacts": {"email": "gemma@koalapark.co.zw", "phoneNo": "+263 77 945 6376"},
                "buyerAddress": {"street": "Koala Farm, Borrowdale Road", "city": "Harare", "province": "Harare", "houseNo": "123"}
            },
            "receiptLines": [
                {"receiptLineName": "RATION BEEF/ KG", "receiptLineQuantity": 0.258, "receiptLinePrice": 5.00, "receiptLineTotal": 1.29, "taxPercent": 15.5, "receiptLineHSCode": "02013000"},
                {"receiptLineName": "EGGS LOOSE #B", "receiptLineQuantity": 3.0, "receiptLinePrice": 0.20, "receiptLineTotal": 0.60, "taxPercent": 0.0, "receiptLineHSCode": "04072100"},
                {"receiptLineName": "LOBELS BREAD #B", "receiptLineQuantity": 1.0, "receiptLinePrice": 1.00, "receiptLineTotal": 1.00, "taxPercent": 0.0, "receiptLineHSCode": "19059010"},
                {"receiptLineName": "STERI MILK 500ML #B", "receiptLineQuantity": 1.0, "receiptLinePrice": 1.00, "receiptLineTotal": 1.00, "taxPercent": 0.0, "receiptLineHSCode": "04011000"}
            ],
            "receiptTaxes": [
                {"taxCode": "A", "taxPercent": 15.5, "taxAmount": 0.20, "salesAmountWithTax": 1.29},
                {"taxCode": "B", "taxPercent": 0.0, "taxAmount": 0.00, "salesAmountWithTax": 2.60}
            ]
        }
        pdf_payload = {"receipt": mock_receipt, "company_name": seller_data['name'], "seller_data": seller_data}
        pdf_buffer = generate_zimra_a4_pdf(pdf_payload, "TEST-1234-ABCD", "https://fdmstest.zimra.co.zw/...", zimra.device_id, 1, "InvoiceA4", seller_data, serial_number=serial_no)
        return Response(pdf_buffer.getvalue(), mimetype='application/pdf', headers={'Content-Disposition': 'inline; filename="Test_WT_Swan_Layout.pdf"'})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route('/api/analytics', methods=['GET'])
def api_analytics():
    try:
        range_type = request.args.get('range', 'month')
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')
        now = datetime.now()
        cutoff = None; end_dt = None; group_format = "%d %b"
        if start_date_str and end_date_str:
            try:
                cutoff = datetime.strptime(start_date_str, "%Y-%m-%d")
                end_dt = datetime.strptime(end_date_str, "%Y-%m-%d") + timedelta(days=1)
                group_format = "%Y-%m-%d"
            except ValueError: pass
        if cutoff is None:
            if range_type == 'day': cutoff = now - timedelta(days=1); group_format = "%H:00"
            elif range_type == 'week': cutoff = now - timedelta(weeks=1); group_format = "%a %d"
            elif range_type == 'month': cutoff = now - timedelta(days=30); group_format = "%d %b"
            else: cutoff = now - timedelta(days=365); group_format = "%b %Y"
        with db_lock:
            with sqlite3.connect(DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                if end_dt:
                    rows = conn.execute("SELECT id, total_amount, receipt_currency, receipt_date, created_at FROM receipt_audit WHERE status = 'SUCCESS' AND datetime(created_at) >= datetime(?) AND datetime(created_at) < datetime(?) ORDER BY created_at ASC", (cutoff.strftime("%Y-%m-%d %H:%M:%S"), end_dt.strftime("%Y-%m-%d %H:%M:%S"))).fetchall()
                else:
                    rows = conn.execute("SELECT id, total_amount, receipt_currency, receipt_date, created_at FROM receipt_audit WHERE status = 'SUCCESS' AND datetime(created_at) >= datetime(?) ORDER BY created_at ASC", (cutoff.strftime("%Y-%m-%d %H:%M:%S"),)).fetchall()
                if end_dt:
                    item_rows = conn.execute("SELECT ri.receipt_currency, ri.item_name, SUM(ri.quantity) as total_qty, SUM(ri.total) as total_amount FROM receipt_items ri JOIN receipt_audit ra ON ri.receipt_audit_id = ra.id WHERE ra.status = 'SUCCESS' AND datetime(ri.created_at) >= datetime(?) AND datetime(ri.created_at) < datetime(?) GROUP BY ri.receipt_currency, ri.item_name", (cutoff.strftime("%Y-%m-%d %H:%M:%S"), end_dt.strftime("%Y-%m-%d %H:%M:%S"))).fetchall()
                else:
                    item_rows = conn.execute("SELECT ri.receipt_currency, ri.item_name, SUM(ri.quantity) as total_qty, SUM(ri.total) as total_amount FROM receipt_items ri JOIN receipt_audit ra ON ri.receipt_audit_id = ra.id WHERE ra.status = 'SUCCESS' AND datetime(ri.created_at) >= datetime(?) GROUP BY ri.receipt_currency, ri.item_name", (cutoff.strftime("%Y-%m-%d %H:%M:%S"),)).fetchall()
        time_series = defaultdict(lambda: {'USD_sales': 0, 'USD_tax': 0, 'ZWG_sales': 0, 'ZWG_tax': 0})
        busy_hours = defaultdict(int)
        for row in rows:
            created_at = row['created_at']
            if not created_at: continue
            try:
                if ' ' in created_at: ca_dt = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
                else: ca_dt = datetime.fromisoformat(created_at)
            except: continue
            time_key = ca_dt.strftime(group_format)
            curr = (row['receipt_currency'] or 'USD').upper()
            total = float(row['total_amount'] or 0)
            tax = round(total * (15.5 / 115.5), 2)
            if curr == 'USD': time_series[time_key]['USD_sales'] += total; time_series[time_key]['USD_tax'] += tax
            else: time_series[time_key]['ZWG_sales'] += total; time_series[time_key]['ZWG_tax'] += tax
            busy_hours[ca_dt.hour] += 1
        labels = sorted(time_series.keys())
        usd_sales = [round(time_series[l]['USD_sales'], 2) for l in labels]
        usd_tax = [round(time_series[l]['USD_tax'], 2) for l in labels]
        zwg_sales = [round(time_series[l]['ZWG_sales'], 2) for l in labels]
        zwg_tax = [round(time_series[l]['ZWG_tax'], 2) for l in labels]
        products_by_currency = defaultdict(list)
        for item in item_rows:
            curr = (item['receipt_currency'] or 'USD').upper()
            products_by_currency[curr].append({'name': item['item_name'] or 'Unknown', 'qty': float(item['total_qty'] or 0), 'amount': float(item['total_amount'] or 0)})
        top_products = {}
        for curr in ['USD', 'ZWG']:
            prods = products_by_currency.get(curr, [])
            top_products[curr] = {'by_quantity': sorted(prods, key=lambda x: x['qty'], reverse=True)[:10], 'by_amount': sorted(prods, key=lambda x: x['amount'], reverse=True)[:10]}
        busy_data = [{"hour": h, "count": busy_hours.get(h, 0)} for h in range(24)]
        return jsonify({"time_series": {"labels": labels, "usd_sales": usd_sales, "usd_tax": usd_tax, "zwg_sales": zwg_sales, "zwg_tax": zwg_tax}, "top_products": top_products, "busy_hours": busy_data, "range": range_type})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500

def start_auto_scheduler():
    """Start the auto fiscal day scheduler in a background thread."""
    scheduler_thread = threading.Thread(target=auto_fiscal_day_scheduler, daemon=True, name="FiscalDayScheduler")
    scheduler_thread.start()
    print("⏰ Auto Fiscal Day Scheduler started in background.")

if __name__ == '__main__':
    print("\n" + "="*60)
    print("🚀 STARTING FISCALINK SYSTEM...")
    print("="*60)
    
    try:
        print("🔄 Attempting to connect to ZIMRA FDMS...")
        status_code, config_resp = zimra.get_config()
        
        print(f"📡 ZIMRA API Response Status: {status_code}")
        
        if status_code == 200 and isinstance(config_resp, dict):
            company_name = config_resp.get('deviceBranchName', 'Unknown Company')
            device_id = config_resp.get('deviceID', zimra.device_id)
            print(f"✅ Successfully connected to ZIMRA FDMS.")
            print(f"🏢 Company Name: {company_name}")
            print(f" Device ID:      {device_id}")
            
            print("\n" + "="*60)
            print("✅ ACCEPTED TAX IDs FOR THIS DEVICE:")
            print("="*60)
            applicable_taxes = config_resp.get('applicableTaxes', [])
            if applicable_taxes:
                for tax in applicable_taxes:
                    tax_id = tax.get('taxID', 'N/A')
                    tax_pct = tax.get('taxPercent', 0.0)
                    tax_name = tax.get('taxName', 'Unknown')
                    print(f"   Tax ID: {str(tax_id):<4} | Rate: {str(tax_pct):>5}% | Name: {tax_name}")
            else:
                print("  ️ No applicable taxes returned by ZIMRA. Check device registration.")
            print("="*60 + "\n")
        else:
            print("️  Could not fetch company details from ZIMRA.")
    except Exception as e:
        print(f"❌ CRITICAL ERROR fetching ZIMRA config: {e}")
        
    print("="*60)
    print("✅ Server is running on http://0.0.0.0:5000")
    print("="*60 + "\n")

    # Start the scheduler for development testing
    start_auto_scheduler()

    app.run(host='0.0.0.0', port=5000, debug=False)
import sqlite3
import config

def get_db_connection():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS fiscal_days (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id INTEGER,
            fiscal_day_no INTEGER,
            opened_at TEXT,
            closed_at TEXT,
            status TEXT
        );
        CREATE TABLE IF NOT EXISTS receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id INTEGER,
            fiscal_day_no INTEGER,
            receipt_global_no INTEGER,
            receipt_counter INTEGER,
            receipt_type TEXT,
            invoice_no TEXT,
            receipt_date TEXT,
            total_amount REAL,
            tax_amount REAL,
            zimra_receipt_id TEXT,
            status TEXT,
            qr_code_url TEXT,
            verification_code TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
    ''')
    conn.commit()
    conn.close()

def get_current_fiscal_day(device_id):
    conn = get_db_connection()
    day = conn.execute(
        'SELECT * FROM fiscal_days WHERE device_id = ? ORDER BY id DESC LIMIT 1', (device_id,)
    ).fetchone()
    conn.close()
    return day

def save_fiscal_day(device_id, fiscal_day_no, opened_at, status="Opened"):
    conn = get_db_connection()
    conn.execute(
        'INSERT INTO fiscal_days (device_id, fiscal_day_no, opened_at, status) VALUES (?, ?, ?, ?)',
        (device_id, fiscal_day_no, opened_at, status)
    )
    conn.commit()
    conn.close()

def set_manual_fiscal_day(device_id: int, fiscal_day_no: int, opened_at: str, status: str = "Opened"):
    conn = get_db_connection()
    try:
        conn.execute(
            'UPDATE fiscal_days SET status = "Closed", closed_at = CURRENT_TIMESTAMP WHERE device_id = ? AND status = "Opened"',
            (device_id,)
        )
        conn.execute(
            'INSERT INTO fiscal_days (device_id, fiscal_day_no, opened_at, status) VALUES (?, ?, ?, ?)',
            (device_id, fiscal_day_no, opened_at, status)
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

# ==========================================
# NEW: SEQUENTIAL NUMBER GENERATOR
# ==========================================
def get_next_receipt_numbers(device_id, fiscal_day_no):
    """
    Fetches the next sequential numbers.
    - receiptGlobalNo: Strictly sequential across the LIFETIME of the device.
    - receiptCounter: Sequential per FISCAL DAY.
    """
    conn = get_db_connection()
    
    # 1. Get next Global No (Lifetime)
    last_global = conn.execute(
        'SELECT MAX(receipt_global_no) as max_global FROM receipts WHERE device_id = ?',
        (device_id,)
    ).fetchone()['max_global']
    next_global = (last_global or 0) + 1

    # 2. Get next Counter (Daily)
    last_counter = conn.execute(
        'SELECT MAX(receipt_counter) as max_counter FROM receipts WHERE device_id = ? AND fiscal_day_no = ?',
        (device_id, fiscal_day_no)
    ).fetchone()['max_counter']
    next_counter = (last_counter or 0) + 1

    conn.close()
    return next_global, next_counter

def save_receipt(data):
    conn = get_db_connection()
    conn.execute('''
        INSERT INTO receipts (device_id, fiscal_day_no, receipt_global_no, receipt_counter, 
                              receipt_type, invoice_no, receipt_date, total_amount, tax_amount, 
                              zimra_receipt_id, status, qr_code_url, verification_code)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (data['device_id'], data['fiscal_day_no'], data['receipt_global_no'], 
          data['receipt_counter'], data['receipt_type'], data.get('invoice_no', ''),
          data.get('receipt_date', ''), data['total_amount'], data['tax_amount'], 
          data['zimra_receipt_id'], data['status'],
          data.get('qr_code_url', ''), data.get('verification_code', '')))
    conn.commit()
    conn.close()

def get_daily_counters(fiscal_day_no):
    conn = get_db_connection()
    counters = conn.execute('''
        SELECT receipt_type, SUM(total_amount) as total, SUM(tax_amount) as tax
        FROM receipts WHERE fiscal_day_no = ?
        GROUP BY receipt_type
    ''', (fiscal_day_no,)).fetchall()
    conn.close()
    return counters
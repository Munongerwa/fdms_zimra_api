import sqlite3
import os
import threading
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
os.makedirs(DATA_DIR, exist_ok=True)
POS_DB_PATH = os.path.join(DATA_DIR, "pos_accounting.db")
db_lock = threading.Lock()

def init_pos_db():
    with db_lock:
        with sqlite3.connect(POS_DB_PATH) as conn:
            cursor = conn.cursor()
            
            cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT, 
                role TEXT, full_name TEXT, email TEXT, phone TEXT,
                is_active INTEGER DEFAULT 1, created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )''')
            
            cursor.execute('''CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE, name TEXT, 
                price REAL, tax_code TEXT, tax_id INTEGER, stock INTEGER DEFAULT 0, 
                category TEXT, description TEXT, is_active INTEGER DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )''')
            
            cursor.execute('''CREATE TABLE IF NOT EXISTS quotations (
                id INTEGER PRIMARY KEY AUTOINCREMENT, quote_no TEXT UNIQUE, customer_name TEXT, 
                customer_tin TEXT, customer_email TEXT, customer_phone TEXT,
                total_amount REAL, currency TEXT DEFAULT 'USD', items_json TEXT, 
                status TEXT DEFAULT 'Pending', notes TEXT,
                created_by INTEGER, created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                valid_until DATE
            )''')

            cursor.execute('''CREATE TABLE IF NOT EXISTS delivery_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT, dn_no TEXT UNIQUE, quote_id INTEGER,
                customer_name TEXT, customer_address TEXT, customer_phone TEXT,
                total_amount REAL, currency TEXT DEFAULT 'USD', items_json TEXT, 
                status TEXT DEFAULT 'Draft', driver_name TEXT, vehicle_reg TEXT,
                notes TEXT, created_by INTEGER, created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )''')

            cursor.execute('''CREATE TABLE IF NOT EXISTS pos_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, invoice_no TEXT UNIQUE, cashier_id INTEGER, 
                customer_name TEXT, customer_tin TEXT, total_amount REAL, currency TEXT, 
                items_json TEXT, is_fiscalized INTEGER DEFAULT 0, 
                zimra_response TEXT, payment_method TEXT DEFAULT 'Cash',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )''')

            # Seed default admin
            cursor.execute("SELECT COUNT(*) FROM users WHERE username = 'fiscalink_admin'")
            if cursor.fetchone()[0] == 0:
                admin_pass = generate_password_hash("1213Fiscalink#")
                cursor.execute("""INSERT INTO users (username, password, role, full_name, email) 
                                  VALUES (?, ?, ?, ?, ?)""",
                               ("fiscalink_admin", admin_pass, "admin", "System Administrator", "admin@fiscalink.co.zw"))

            # Seed default products if empty
            cursor.execute("SELECT COUNT(*) FROM products")
            if cursor.fetchone()[0] == 0:
                cursor.executemany("""INSERT INTO products (code, name, price, tax_code, tax_id, stock, category, description) 
                                      VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", [
                    ("1001", "Z Book 14inch (Standard)", 100.00, "A", 517, 50, "Electronics", "14 inch laptop"),
                    ("1002", "Eggs Loose (Zero Rated)", 5.00, "B", 2, 200, "Groceries", "Farm fresh eggs"),
                    ("1003", "Milk 1L (Zero Rated)", 2.50, "B", 2, 100, "Groceries", "Fresh milk 1L"),
                    ("1004", "Consulting Fee (Exempt)", 150.00, "C", 1, 999, "Services", "Professional services"),
                    ("1005", "Bread Loaf (Zero Rated)", 1.20, "B", 2, 150, "Groceries", "White bread"),
                    ("1006", "Soft Drink 500ml", 1.50, "A", 517, 300, "Beverages", "Carbonated drink")
                ])
            conn.commit()

# --- AUTH FUNCTIONS ---
def authenticate_user(username, password):
    with db_lock:
        with sqlite3.connect(POS_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            user = conn.execute("SELECT * FROM users WHERE username = ? AND is_active = 1", (username,)).fetchone()
            if user and check_password_hash(user['password'], password):
                return dict(user)
    return None

# --- USER CRUD ---
def get_all_users():
    with db_lock:
        with sqlite3.connect(POS_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute("SELECT id, username, role, full_name, email, phone, is_active, created_at FROM users ORDER BY created_at DESC").fetchall()]

def create_user(username, password, role, full_name, email="", phone=""):
    with db_lock:
        with sqlite3.connect(POS_DB_PATH) as conn:
            try:
                hashed = generate_password_hash(password)
                conn.execute("""INSERT INTO users (username, password, role, full_name, email, phone) 
                                VALUES (?, ?, ?, ?, ?, ?)""", (username, hashed, role, full_name, email, phone))
                conn.commit()
                return {"success": True, "message": "User created"}
            except sqlite3.IntegrityError:
                return {"success": False, "message": "Username already exists"}

def update_user(user_id, password=None, role=None, full_name=None, email=None, phone=None, is_active=None):
    with db_lock:
        with sqlite3.connect(POS_DB_PATH) as conn:
            updates = []
            params = []
            if password:
                updates.append("password = ?"); params.append(generate_password_hash(password))
            if role: updates.append("role = ?"); params.append(role)
            if full_name: updates.append("full_name = ?"); params.append(full_name)
            if email is not None: updates.append("email = ?"); params.append(email)
            if phone is not None: updates.append("phone = ?"); params.append(phone)
            if is_active is not None: updates.append("is_active = ?"); params.append(int(is_active))
            
            if updates:
                params.append(user_id)
                conn.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", params)
                conn.commit()
            return {"success": True}

def delete_user(user_id):
    with db_lock:
        with sqlite3.connect(POS_DB_PATH) as conn:
            conn.execute("UPDATE users SET is_active = 0 WHERE id = ?", (user_id,))
            conn.commit()
            return {"success": True}

# --- PRODUCT CRUD ---
def get_all_products(active_only=True):
    with db_lock:
        with sqlite3.connect(POS_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            query = "SELECT * FROM products" + (" WHERE is_active = 1" if active_only else "") + " ORDER BY name"
            return [dict(row) for row in conn.execute(query).fetchall()]

def create_product(code, name, price, tax_code, tax_id, stock=0, category="", description=""):
    with db_lock:
        with sqlite3.connect(POS_DB_PATH) as conn:
            try:
                conn.execute("""INSERT INTO products (code, name, price, tax_code, tax_id, stock, category, description) 
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", (code, name, price, tax_code, tax_id, stock, category, description))
                conn.commit()
                return {"success": True, "message": "Product created"}
            except sqlite3.IntegrityError:
                return {"success": False, "message": "Product code already exists"}

def update_product(product_id, **kwargs):
    with db_lock:
        with sqlite3.connect(POS_DB_PATH) as conn:
            updates = []
            params = []
            for key, val in kwargs.items():
                if key in ['name', 'price', 'tax_code', 'tax_id', 'stock', 'category', 'description', 'is_active']:
                    updates.append(f"{key} = ?"); params.append(val)
            if updates:
                params.append(product_id)
                conn.execute(f"UPDATE products SET {', '.join(updates)} WHERE id = ?", params)
                conn.commit()
            return {"success": True}

def delete_product(product_id):
    with db_lock:
        with sqlite3.connect(POS_DB_PATH) as conn:
            conn.execute("UPDATE products SET is_active = 0 WHERE id = ?", (product_id,))
            conn.commit()
            return {"success": True}

# --- QUOTATION CRUD ---
def get_all_quotations():
    with db_lock:
        with sqlite3.connect(POS_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute("SELECT * FROM quotations ORDER BY created_at DESC").fetchall()]

def create_quotation(quote_no, customer_name, customer_tin, customer_email, customer_phone, total_amount, currency, items_json, notes, created_by, valid_until):
    with db_lock:
        with sqlite3.connect(POS_DB_PATH) as conn:
            try:
                conn.execute("""INSERT INTO quotations (quote_no, customer_name, customer_tin, customer_email, customer_phone, total_amount, currency, items_json, notes, created_by, valid_until) 
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                             (quote_no, customer_name, customer_tin, customer_email, customer_phone, total_amount, currency, items_json, notes, created_by, valid_until))
                conn.commit()
                return {"success": True, "message": "Quotation created"}
            except sqlite3.IntegrityError:
                return {"success": False, "message": "Quote number already exists"}

def update_quotation_status(quote_id, status):
    with db_lock:
        with sqlite3.connect(POS_DB_PATH) as conn:
            conn.execute("UPDATE quotations SET status = ? WHERE id = ?", (status, quote_id))
            conn.commit()
            return {"success": True}

def delete_quotation(quote_id):
    with db_lock:
        with sqlite3.connect(POS_DB_PATH) as conn:
            conn.execute("DELETE FROM quotations WHERE id = ?", (quote_id,))
            conn.commit()
            return {"success": True}

# --- DELIVERY NOTE CRUD ---
def get_all_delivery_notes():
    with db_lock:
        with sqlite3.connect(POS_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute("SELECT * FROM delivery_notes ORDER BY created_at DESC").fetchall()]

def create_delivery_note(dn_no, quote_id, customer_name, customer_address, customer_phone, total_amount, currency, items_json, driver_name, vehicle_reg, notes, created_by):
    with db_lock:
        with sqlite3.connect(POS_DB_PATH) as conn:
            try:
                conn.execute("""INSERT INTO delivery_notes (dn_no, quote_id, customer_name, customer_address, customer_phone, total_amount, currency, items_json, driver_name, vehicle_reg, notes, created_by) 
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                             (dn_no, quote_id, customer_name, customer_address, customer_phone, total_amount, currency, items_json, driver_name, vehicle_reg, notes, created_by))
                conn.commit()
                return {"success": True, "message": "Delivery note created"}
            except sqlite3.IntegrityError:
                return {"success": False, "message": "DN number already exists"}

def update_delivery_note_status(dn_id, status):
    with db_lock:
        with sqlite3.connect(POS_DB_PATH) as conn:
            conn.execute("UPDATE delivery_notes SET status = ? WHERE id = ?", (status, dn_id))
            conn.commit()
            return {"success": True}

# --- POS TRANSACTION ---
def save_pos_transaction(invoice_no, cashier_id, customer_name, customer_tin, total, currency, items_json, is_fiscalized, zimra_response="", payment_method="Cash"):
    with db_lock:
        with sqlite3.connect(POS_DB_PATH) as conn:
            conn.execute("""INSERT INTO pos_transactions (invoice_no, cashier_id, customer_name, customer_tin, total_amount, currency, items_json, is_fiscalized, zimra_response, payment_method) 
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                         (invoice_no, cashier_id, customer_name, customer_tin, total, currency, items_json, int(is_fiscalized), zimra_response, payment_method))
            conn.commit()

def get_all_pos_transactions():
    with db_lock:
        with sqlite3.connect(POS_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute("SELECT * FROM pos_transactions ORDER BY created_at DESC").fetchall()]

# --- REPORTS ---
def get_sales_report(date_from=None, date_to=None):
    with db_lock:
        with sqlite3.connect(POS_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            query = "SELECT * FROM pos_transactions WHERE 1=1"
            params = []
            if date_from:
                query += " AND created_at >= ?"; params.append(date_from)
            if date_to:
                query += " AND created_at <= ?"; params.append(date_to + " 23:59:59")
            query += " ORDER BY created_at DESC"
            return [dict(row) for row in conn.execute(query, params).fetchall()]

def get_inventory_report():
    with db_lock:
        with sqlite3.connect(POS_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute("SELECT * FROM products WHERE is_active = 1 ORDER BY stock ASC").fetchall()]

def get_dashboard_stats():
    with db_lock:
        with sqlite3.connect(POS_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            today = datetime.now().strftime("%Y-%m-%d")
            total_sales = conn.execute("SELECT COALESCE(SUM(total_amount), 0) as total FROM pos_transactions WHERE DATE(created_at) = ?", (today,)).fetchone()['total']
            total_transactions = conn.execute("SELECT COUNT(*) as count FROM pos_transactions WHERE DATE(created_at) = ?", (today,)).fetchone()['count']
            total_products = conn.execute("SELECT COUNT(*) as count FROM products WHERE is_active = 1").fetchone()['count']
            low_stock = conn.execute("SELECT COUNT(*) as count FROM products WHERE stock < 10 AND is_active = 1").fetchone()['count']
            pending_quotes = conn.execute("SELECT COUNT(*) as count FROM quotations WHERE status = 'Pending'").fetchone()['count']
            return {
                "today_sales": total_sales,
                "today_transactions": total_transactions,
                "total_products": total_products,
                "low_stock_items": low_stock,
                "pending_quotations": pending_quotes
            }
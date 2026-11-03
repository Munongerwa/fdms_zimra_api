import hashlib
import hmac
import json
import math
import os
import secrets
import sqlite3
import tempfile
import threading
from datetime import datetime, timedelta
from functools import wraps

from flask import Blueprint, current_app, jsonify, make_response, render_template, request, send_file

from config import Config
from core.zimra_client import DB_PATH, db_lock
from core.zimra_validator import validate_zimra_payload


_fiscalization_lock = threading.Lock()
_PAYMENT_TYPES = {"Cash", "Card", "MobileWallet", "BankTransfer", "Other"}
_CURRENCIES = (("USD", "US Dollar"), ("ZAR", "South African Rand"), ("ZWL", "Zimbabwean Dollar"))


class _ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def _connect():
    connection = sqlite3.connect(DB_PATH, timeout=30, factory=_ClosingConnection)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _initialize_pos_db():
    with db_lock:
        with _connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS pos_cashiers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    display_name TEXT NOT NULL,
                    pin_salt TEXT NOT NULL,
                    pin_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'cashier' CHECK (role IN ('manager', 'cashier')),
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS pos_sessions (
                    token_hash TEXT PRIMARY KEY,
                    cashier_id INTEGER NOT NULL REFERENCES pos_cashiers(id),
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS pos_products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sku TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    name TEXT NOT NULL,
                    hs_code TEXT NOT NULL DEFAULT '10000000',
                    price REAL NOT NULL CHECK (price > 0),
                    currency TEXT NOT NULL DEFAULT 'USD',
                    tax_code TEXT NOT NULL DEFAULT 'A',
                    tax_percent REAL NOT NULL DEFAULT 15.5 CHECK (tax_percent >= 0),
                    tax_id INTEGER NOT NULL DEFAULT 515,
                    stock_qty REAL NOT NULL DEFAULT 0,
                    low_stock_threshold REAL NOT NULL DEFAULT 5,
                    track_stock INTEGER NOT NULL DEFAULT 1,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS pos_invoices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    invoice_no TEXT NOT NULL UNIQUE,
                    cashier_id INTEGER NOT NULL REFERENCES pos_cashiers(id),
                    customer_name TEXT NOT NULL DEFAULT '',
                    currency TEXT NOT NULL,
                    subtotal REAL NOT NULL,
                    tax_total REAL NOT NULL,
                    total REAL NOT NULL,
                    payments_json TEXT NOT NULL,
                    fiscal_status TEXT NOT NULL DEFAULT 'pending'
                        CHECK (fiscal_status IN ('pending', 'processing', 'failed', 'fiscalized')),
                    fiscal_error TEXT NOT NULL DEFAULT '',
                    payload_json TEXT,
                    response_json TEXT,
                    verification_code TEXT,
                    qr_code TEXT,
                    fiscal_day_no INTEGER,
                    receipt_audit_id INTEGER,
                    exchange_rate REAL NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    fiscalized_at TEXT
                );
                CREATE TABLE IF NOT EXISTS pos_invoice_lines (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    invoice_id INTEGER NOT NULL REFERENCES pos_invoices(id),
                    product_id INTEGER REFERENCES pos_products(id),
                    sku TEXT NOT NULL,
                    name TEXT NOT NULL,
                    hs_code TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    unit_price REAL NOT NULL,
                    line_total REAL NOT NULL,
                    tax_code TEXT NOT NULL,
                    tax_percent REAL NOT NULL,
                    tax_id INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS pos_stock_movements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id INTEGER NOT NULL REFERENCES pos_products(id),
                    cashier_id INTEGER NOT NULL REFERENCES pos_cashiers(id),
                    invoice_id INTEGER REFERENCES pos_invoices(id),
                    movement_type TEXT NOT NULL,
                    quantity_delta REAL NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS pos_cash_movements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cashier_id INTEGER NOT NULL REFERENCES pos_cashiers(id),
                    invoice_id INTEGER REFERENCES pos_invoices(id),
                    movement_type TEXT NOT NULL,
                    amount REAL NOT NULL,
                    currency TEXT NOT NULL,
                    exchange_rate REAL NOT NULL DEFAULT 1,
                    note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS pos_currencies (
                    code TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    rate_to_base REAL NOT NULL DEFAULT 1 CHECK (rate_to_base > 0),
                    active INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS pos_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS pos_customers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    tin TEXT NOT NULL DEFAULT '',
                    vat_number TEXT NOT NULL DEFAULT '',
                    address TEXT NOT NULL DEFAULT '',
                    phone TEXT NOT NULL DEFAULT '',
                    email TEXT NOT NULL DEFAULT '',
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS pos_held_sales (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cashier_id INTEGER NOT NULL REFERENCES pos_cashiers(id),
                    sale_data_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS pos_audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cashier_id INTEGER REFERENCES pos_cashiers(id) ON DELETE SET NULL,
                    actor_name TEXT NOT NULL,
                    actor_username TEXT NOT NULL DEFAULT '',
                    action TEXT NOT NULL,
                    method TEXT NOT NULL,
                    path TEXT NOT NULL,
                    status_code INTEGER NOT NULL,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_pos_invoice_created ON pos_invoices(created_at);
                CREATE INDEX IF NOT EXISTS idx_pos_stock_product ON pos_stock_movements(product_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_pos_cash_created ON pos_cash_movements(created_at);
                CREATE INDEX IF NOT EXISTS idx_pos_held_sales_cashier ON pos_held_sales(cashier_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_pos_audit_created ON pos_audit_log(id DESC);
                CREATE TRIGGER IF NOT EXISTS pos_audit_no_update
                BEFORE UPDATE ON pos_audit_log
                BEGIN
                    SELECT RAISE(ABORT, 'POS audit entries are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS pos_audit_no_delete
                BEFORE DELETE ON pos_audit_log
                BEGIN
                    SELECT RAISE(ABORT, 'POS audit entries are immutable');
                END;
            """)
            for code, name in _CURRENCIES:
                connection.execute(
                    "INSERT OR IGNORE INTO pos_currencies (code, name, rate_to_base) VALUES (?, ?, ?)",
                    (code, name, 1.0),
                )
            connection.execute(
                "INSERT OR IGNORE INTO pos_settings (key, value) VALUES ('base_currency', 'USD')"
            )
            migrations = {
                "pos_invoices": {
                    "customer_id": "INTEGER REFERENCES pos_customers(id)",
                    "buyer_data_json": "TEXT NOT NULL DEFAULT '{}'",
                    "invoice_format": "TEXT NOT NULL DEFAULT 'InvoiceA4'",
                    "document_type": "TEXT NOT NULL DEFAULT 'invoice'",
                    "original_invoice_id": "INTEGER REFERENCES pos_invoices(id)",
                    "original_global_no": "INTEGER",
                    "original_receipt_date": "TEXT",
                    "original_fiscal_day_no": "INTEGER",
                    "amount_received": "REAL NOT NULL DEFAULT 0",
                    "change_due": "REAL NOT NULL DEFAULT 0",
                },
            }
            for table, columns in migrations.items():
                existing = {
                    row["name"] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
                }
                for column, definition in columns.items():
                    if column not in existing:
                        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_pos_customer_tin ON pos_customers(tin) WHERE tin != ''"
            )
            base = connection.execute(
                "SELECT value FROM pos_settings WHERE key = 'base_currency'"
            ).fetchone()["value"]
            base_rate = connection.execute(
                "SELECT rate_to_base FROM pos_currencies WHERE code = ?", (base,)
            ).fetchone()
            if base_rate and base_rate["rate_to_base"] > 0:
                for row in connection.execute(
                    "SELECT id, currency, price FROM pos_products WHERE currency != ?", (base,)
                ).fetchall():
                    old_rate = connection.execute(
                        "SELECT rate_to_base FROM pos_currencies WHERE code = ?", (row["currency"],)
                    ).fetchone()
                    if old_rate:
                        connection.execute(
                            """UPDATE pos_products SET price = ?, currency = ?, updated_at = CURRENT_TIMESTAMP
                               WHERE id = ?""",
                            (round(row["price"] * old_rate["rate_to_base"] / base_rate["rate_to_base"], 6),
                             base, row["id"]),
                        )
            connection.execute(
                "UPDATE pos_invoices SET fiscal_status = 'failed', fiscal_error = "
                "'Previous fiscalisation attempt was interrupted. Verify with ZIMRA before retrying.' "
                "WHERE fiscal_status = 'processing'"
            )


def _json_error(message, status=400, **extra):
    return jsonify({"error": message, **extra}), status


def _parse_json():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError("A JSON object is required.")
    return data


def _cashier_from_request(connection):
    token = request.headers.get("X-POS-Session", "")
    if not token:
        return None
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    row = connection.execute(
        """SELECT c.id, c.username, c.display_name, c.role
           FROM pos_sessions s JOIN pos_cashiers c ON c.id = s.cashier_id
           WHERE s.token_hash = ? AND s.expires_at > ? AND c.active = 1""",
        (token_hash, datetime.now().isoformat(timespec="seconds")),
    ).fetchone()
    return dict(row) if row else None


_POS_AUDIT_ACTIONS = {
    "pos_catalog": "Viewed product catalog",
    "pos_customers": "Viewed customer directory",
    "pos_add_customer": "Added customer",
    "pos_update_customer": "Updated customer",
    "pos_held_sales": "Viewed held sales",
    "pos_hold_sale": "Held sale",
    "pos_get_held_sale": "Viewed/resumed held sale",
    "pos_discard_held_sale": "Discarded held sale",
    "pos_add_product": "Added product",
    "pos_update_product": "Updated product",
    "pos_deactivate_product": "Archived product",
    "pos_stock_movement": "Adjusted stock",
    "pos_add_currency": "Added currency",
    "pos_sell": "Completed sale",
    "pos_invoices": "Viewed invoice history",
    "pos_invoice": "Viewed invoice",
    "pos_analysis": "Viewed sales analysis",
    "pos_create_credit_note": "Created credit note",
    "pos_late_fiscalize": "Fiscalised invoice",
    "pos_print_invoice": "Opened invoice PDF",
    "pos_send_invoice_to_printer": "Printed invoice",
    "pos_stock_history": "Viewed stock movement history",
    "pos_cashbook": "Viewed cash book",
    "pos_cashbook_entry": "Recorded cash book movement",
    "pos_settings": "Viewed POS settings",
    "pos_update_settings": "Updated POS settings",
    "pos_cashiers": "Viewed cashier accounts",
    "pos_add_cashier": "Created cashier account",
    "pos_summary": "Viewed POS summary",
    "pos_logout": "Signed out of POS",
}


def _record_pos_audit(
    cashier,
    action,
    status_code,
    actor_username="",
    actor_name="Unknown user",
):
    cashier = dict(cashier) if cashier is not None else {}
    actor_id = cashier.get("id")
    username = cashier.get("username", actor_username)
    name = cashier.get("display_name", actor_name)
    details = {
        "endpoint": request.endpoint or "",
        "route_parameters": request.view_args or {},
    }
    with db_lock:
        with _connect() as connection:
            connection.execute(
                """INSERT INTO pos_audit_log
                   (cashier_id, actor_name, actor_username, action, method, path,
                    status_code, details_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    actor_id,
                    name,
                    username,
                    action,
                    request.method,
                    request.path,
                    int(status_code),
                    json.dumps(details, sort_keys=True),
                ),
            )


def _require_pos(manager=False):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            with db_lock:
                with _connect() as connection:
                    cashier = _cashier_from_request(connection)
            if cashier is None:
                _record_pos_audit(
                    None,
                    _POS_AUDIT_ACTIONS.get(function.__name__, function.__name__),
                    401,
                )
                return _json_error("Please log in to the POS.", 401)
            if manager and cashier["role"] != "manager":
                _record_pos_audit(
                    cashier,
                    _POS_AUDIT_ACTIONS.get(function.__name__, function.__name__),
                    403,
                )
                return _json_error("Manager access is required for this action.", 403)
            request.pos_cashier = cashier
            status_code = 500
            try:
                response = function(*args, **kwargs)
                if isinstance(response, tuple) and len(response) > 1:
                    status_code = int(response[1])
                else:
                    status_code = int(getattr(response, "status_code", 200))
                return response
            finally:
                try:
                    _record_pos_audit(
                        cashier,
                        _POS_AUDIT_ACTIONS.get(function.__name__, function.__name__),
                        status_code,
                    )
                except sqlite3.Error:
                    current_app.logger.exception(
                        "Could not append POS audit entry for %s", function.__name__
                    )
        return wrapped
    return decorate


def _money(value, label):
    try:
        amount = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a number.")
    if not math.isfinite(amount):
        raise ValueError(f"{label} must be a finite number.")
    amount = round(amount, 2)
    if amount < 0:
        raise ValueError(f"{label} cannot be negative.")
    return amount


def _invoice_details(connection, invoice_id):
    invoice = connection.execute(
        """SELECT i.*, c.display_name AS cashier_name
           FROM pos_invoices i JOIN pos_cashiers c ON c.id = i.cashier_id WHERE i.id = ?""",
        (invoice_id,),
    ).fetchone()
    if not invoice:
        return None
    result = dict(invoice)
    result["payments"] = json.loads(result.pop("payments_json"))
    result["buyer_data"] = json.loads(result.pop("buyer_data_json") or "{}")
    if result.get("original_invoice_id"):
        original = connection.execute(
            "SELECT invoice_no FROM pos_invoices WHERE id = ?", (result["original_invoice_id"],)
        ).fetchone()
        result["original_invoice_no"] = original["invoice_no"] if original else ""
    result["lines"] = [
        dict(row) for row in connection.execute(
            """SELECT l.*,
                      CASE WHEN i.document_type = 'invoice' THEN
                          COALESCE((SELECT SUM(credit_line.quantity)
                                    FROM pos_invoice_lines credit_line
                                    JOIN pos_invoices credit_invoice ON credit_invoice.id = credit_line.invoice_id
                                    WHERE credit_invoice.original_invoice_id = i.id
                                      AND credit_invoice.document_type = 'credit_note'
                                      AND credit_line.product_id IS l.product_id
                                      AND credit_line.name = l.name), 0)
                          ELSE 0 END AS credited_quantity
               FROM pos_invoice_lines l JOIN pos_invoices i ON i.id = l.invoice_id
               WHERE l.invoice_id = ? ORDER BY l.id""",
            (invoice_id,)
        ).fetchall()
    ]
    for line in result["lines"]:
        line["remaining_quantity"] = max(
            0, float(line["quantity"]) - float(line["credited_quantity"])
        )
    return result


def _create_fiscal_payload(invoice, lines, payments, zimra):
    state = zimra.get_state()
    grouped_taxes = {}
    receipt_lines = []
    for index, line in enumerate(lines, start=1):
        total = round(float(line["line_total"]), 2)
        quantity = float(line["quantity"])
        key = (line["tax_code"], float(line["tax_percent"]), int(line["tax_id"]))
        grouped_taxes.setdefault(key, {"total": 0.0, "tax": 0.0})
        grouped_taxes[key]["total"] += total
        grouped_taxes[key]["tax"] += (
            round(total * key[1] / (100 + key[1]), 2) if key[1] else 0
        )
        receipt_lines.append({
            "receiptLineType": "Sale",
            "receiptLineNo": index,
            "receiptLineHSCode": line["hs_code"],
            "receiptLineName": line["name"][:200],
            "receiptLinePrice": round(total / quantity, 2),
            "receiptLineQuantity": quantity,
            "receiptLineTotal": total,
            "taxCode": key[0],
            "taxPercent": key[1],
            "taxID": key[2],
        })

    receipt_taxes = [
        {
            "taxCode": code,
            "taxPercent": percent,
            "taxID": tax_id,
            "taxAmount": round(values["tax"], 2),
            "salesAmountWithTax": round(values["total"], 2),
        }
        for (code, percent, tax_id), values in sorted(grouped_taxes.items())
    ]
    is_credit_note = invoice.get("document_type") == "credit_note"
    receipt = {
        "receiptType": "CREDITNOTE" if is_credit_note else "FISCALINVOICE",
        "receiptCurrency": invoice["currency"],
        "receiptCounter": state["receipt_counter"],
        "receiptGlobalNo": state["receipt_global_no"],
        "invoiceNo": invoice["invoice_no"],
        "receiptNotes": (
            f"Credit note for {invoice['invoice_no']}"
            if is_credit_note else "Point of sale invoice"
        ),
        "receiptDate": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "receiptLinesTaxInclusive": True,
        "receiptLines": receipt_lines,
        "receiptTaxes": receipt_taxes,
        "receiptPayments": payments,
        "receiptTotal": round(float(invoice["total"]), 2),
        "receiptPrintForm": invoice.get("invoice_format", "InvoiceA4"),
    }
    if is_credit_note:
        receipt["creditDebitNote"] = {
            "deviceID": int(zimra.device_id),
            "receiptGlobalNo": int(invoice["original_global_no"]),
            "fiscalDayNo": int(invoice["original_fiscal_day_no"]),
            "receiptDate": invoice["original_receipt_date"],
        }
        receipt["originalInvoiceNo"] = invoice.get("original_invoice_no", "")
    buyer_data = json.loads(invoice.get("buyer_data_json") or "{}")
    if buyer_data.get("name"):
        receipt["buyerData"] = {
            "buyerRegisterName": buyer_data["name"][:200],
            "buyerAddress": {
                "street": buyer_data.get("address", "")[:100],
                "city": "", "province": "", "houseNo": "",
            },
            "buyerContacts": {
                "email": buyer_data.get("email", "")[:100],
                "phoneNo": buyer_data.get("phone", "")[:20],
            },
        }
        if buyer_data.get("tin"):
            receipt["buyerData"]["buyerTIN"] = buyer_data["tin"][:30]
        if buyer_data.get("vat_number"):
            receipt["buyerData"]["vatNumber"] = buyer_data["vat_number"][:30]
    return {"deviceID": int(zimra.device_id), "receipt": receipt}, state["fiscal_day_no"]


def _buyer_data_from_customer(data):
    return {
        "name": str(data.get("name", "")).strip()[:200],
        "tin": str(data.get("tin", "")).strip()[:30],
        "vat_number": str(data.get("vat_number", "")).strip()[:30],
        "address": str(data.get("address", "")).strip()[:250],
        "phone": str(data.get("phone", "")).strip()[:30],
        "email": str(data.get("email", "")).strip()[:100],
    }


def _receipt_for_print(invoice, zimra):
    payload = json.loads(invoice.get("payload_json") or "{}")
    receipt = payload.get("receipt")
    if not isinstance(receipt, dict):
        state = zimra.get_state()
        buyer = invoice.get("buyer_data") or {}
        receipt_lines = []
        grouped_taxes = {}
        for index, line in enumerate(invoice["lines"], start=1):
            quantity = float(line["quantity"])
            line_total = float(line["line_total"])
            rate = float(line["tax_percent"])
            price = round(line_total / quantity, 2)
            receipt_lines.append({
                "receiptLineType": "Sale",
                "receiptLineNo": index,
                "receiptLineHSCode": line["hs_code"],
                "receiptLineName": line["name"][:200],
                "receiptLinePrice": price,
                "receiptLineQuantity": quantity,
                "receiptLineTotal": line_total,
                "taxCode": line["tax_code"],
                "taxPercent": rate,
                "taxID": line["tax_id"],
            })
            tax_key = (line["tax_code"], rate, line["tax_id"])
            grouped_taxes.setdefault(tax_key, {"total": 0.0, "tax": 0.0})
            grouped_taxes[tax_key]["total"] += line_total
            grouped_taxes[tax_key]["tax"] += (
                round(line_total * rate / (100 + rate), 2) if rate else 0
            )
        receipt_taxes = [
            {"taxCode": key[0], "taxPercent": key[1], "taxID": key[2],
             "taxAmount": round(value["tax"], 2), "salesAmountWithTax": round(value["total"], 2)}
            for key, value in grouped_taxes.items()
        ]
        receipt = {
            "receiptType": "CREDITNOTE" if invoice["document_type"] == "credit_note" else "FISCALINVOICE",
            "receiptCurrency": invoice["currency"],
            "receiptCounter": 0,
            "receiptGlobalNo": 0,
            "invoiceNo": invoice["invoice_no"],
            "receiptDate": invoice["created_at"].replace(" ", "T"),
            "receiptLinesTaxInclusive": True,
            "receiptLines": receipt_lines,
            "receiptTaxes": receipt_taxes,
            "receiptPayments": invoice["payments"],
            "receiptTotal": invoice["total"],
            "receiptPrintForm": invoice["invoice_format"],
        }
        if buyer.get("name"):
            receipt["buyerData"] = {
                "buyerRegisterName": buyer["name"],
                "buyerTIN": buyer.get("tin", ""),
                "vatNumber": buyer.get("vat_number", ""),
                "buyerAddress": {"street": buyer.get("address", ""), "city": "", "province": "", "houseNo": ""},
                "buyerContacts": {"phoneNo": buyer.get("phone", ""), "email": buyer.get("email", "")},
            }
        if invoice["document_type"] == "credit_note":
            receipt["receiptNotes"] = f"Credit note for {invoice['invoice_no']}"
            receipt["originalInvoiceNo"] = invoice.get("original_invoice_no", "")
            receipt["creditDebitNote"] = {
                "deviceID": int(zimra.device_id),
                "receiptGlobalNo": int(invoice["original_global_no"]),
                "fiscalDayNo": int(invoice["original_fiscal_day_no"]),
                "receiptDate": invoice["original_receipt_date"],
            }
        payload = {"deviceID": int(zimra.device_id), "receipt": receipt}
    elif invoice["document_type"] == "credit_note":
        receipt["receiptType"] = "CREDITNOTE"
    receipt["posAmountReceived"] = invoice.get("amount_received", 0)
    receipt["posChangeDue"] = invoice.get("change_due", 0)
    payload["cashier_name"] = invoice.get("cashier_name", "")
    return payload


def _render_invoice_pdf(invoice, zimra):
    from core.pdf_generator import generate_80mm_thermal_receipt, generate_zimra_a4_pdf

    payload = _receipt_for_print(invoice, zimra)
    receipt = payload["receipt"]
    is_fiscalized = invoice["fiscal_status"] == "fiscalized"
    qr_url = invoice.get("qr_code", "") if is_fiscalized else ""
    verification_code = invoice.get("verification_code", "") if is_fiscalized else ""
    try:
        _, response = zimra.get_config()
        response = response if isinstance(response, dict) else {}
        branch_address = response.get("deviceBranchAddress") or {}
        contacts = response.get("deviceBranchContacts") or {}
        seller = {
            "name": response.get("deviceBranchName", "AIBES FISCALISATION"),
            "address": " ".join(
                str(branch_address.get(key, "")).strip()
                for key in ("houseNo", "street", "city")
                if branch_address.get(key)
            ),
            "tin": response.get("taxPayerTIN", ""),
            "vat": response.get("vatNumber", ""),
            "phone": contacts.get("phoneNo", ""),
            "email": contacts.get("email", ""),
        }
    except Exception as error:
        current_app.logger.warning("Could not retrieve seller details for POS invoice: %s", error)
        seller = {"name": "AIBES FISCALISATION", "address": "", "tin": "", "vat": "", "phone": "", "email": ""}
    serial_number = getattr(Config, "DEVICE_SERIAL_NUMBER", "N/A")
    if invoice["invoice_format"] == "Receipt48":
        return generate_80mm_thermal_receipt(
            payload, verification_code, qr_url, zimra.device_id,
            invoice.get("fiscal_day_no") or 0, seller, serial_number,
        )
    return generate_zimra_a4_pdf(
        payload, verification_code, qr_url, zimra.device_id,
        invoice.get("fiscal_day_no") or 0, invoice["invoice_format"],
        seller, serial_number=serial_number,
    )


def _fiscalize_invoice(invoice_id, zimra):
    with _fiscalization_lock:
        with db_lock:
            with _connect() as connection:
                invoice = connection.execute(
                    "SELECT * FROM pos_invoices WHERE id = ?", (invoice_id,)
                ).fetchone()
                if invoice is None:
                    return None, 404
                if invoice["fiscal_status"] == "fiscalized":
                    return _invoice_details(connection, invoice_id), 200
                if invoice["fiscal_status"] == "processing":
                    return {"error": "Fiscalisation is already in progress."}, 409
                connection.execute(
                    "UPDATE pos_invoices SET fiscal_status = 'processing', fiscal_error = '' WHERE id = ?",
                    (invoice_id,),
                )
                invoice = dict(invoice)
                lines = [
                    dict(row) for row in connection.execute(
                        "SELECT * FROM pos_invoice_lines WHERE invoice_id = ? ORDER BY id", (invoice_id,)
                    ).fetchall()
                ]
                payments = json.loads(invoice["payments_json"])
        payload_text = None
        submission_attempted = False
        try:
            payload, fiscal_day_no = _create_fiscal_payload(invoice, lines, payments, zimra)
            payload_text = json.dumps(payload, default=str)
            with db_lock:
                with _connect() as connection:
                    connection.execute(
                        "UPDATE pos_invoices SET payload_json = ? WHERE id = ?",
                        (payload_text, invoice_id),
                    )
            validation_errors = validate_zimra_payload(payload)
            if validation_errors:
                raise ValueError("ZIMRA payload validation failed: " + "; ".join(validation_errors))
            submission_attempted = True
            status, response, verification_code, qr_code, hash_b64, audit_id = zimra.submit_receipt(payload)
            accepted = status == 200
            if accepted:
                zimra.log_receipt_items(
                    audit_id,
                    invoice["invoice_no"],
                    payload["receipt"]["receiptDate"],
                    invoice["currency"],
                    [
                        {
                            "name": line["name"],
                            "qty": line["quantity"],
                            "price": line["unit_price"],
                            "total": line["line_total"],
                            "tax_code": line["tax_code"],
                            "tax_pct": line["tax_percent"],
                        }
                        for line in lines
                    ],
                )
            response_text = json.dumps(response, default=str)
            payload_text = json.dumps(payload, default=str)
            error = "" if accepted else str(response)
            with db_lock:
                with _connect() as connection:
                    connection.execute(
                        """UPDATE pos_invoices SET fiscal_status = ?, fiscal_error = ?,
                           payload_json = ?, response_json = ?, verification_code = ?, qr_code = ?,
                           fiscal_day_no = ?, receipt_audit_id = ?, fiscalized_at = ?
                           WHERE id = ?""",
                        (
                            "fiscalized" if accepted else "failed",
                            error[:2000],
                            payload_text,
                            response_text,
                            verification_code if accepted else "",
                            qr_code if accepted else "",
                            fiscal_day_no,
                            audit_id,
                            datetime.now().isoformat(timespec="seconds") if accepted else None,
                            invoice_id,
                        ),
                    )
                    return _invoice_details(connection, invoice_id), (200 if accepted else 502)
        except Exception as error:
            error_message = str(error)
            if submission_attempted:
                error_message = (
                    "Submission failed. Verify the receipt with ZIMRA before retrying. "
                    + error_message
                )
            with db_lock:
                with _connect() as connection:
                    connection.execute(
                        """UPDATE pos_invoices SET fiscal_status = 'failed', fiscal_error = ?,
                           payload_json = COALESCE(?, payload_json)
                           WHERE id = ?""",
                        (error_message[:2000], payload_text, invoice_id),
                    )
                    return _invoice_details(connection, invoice_id), 422


def create_pos_blueprint(zimra):
    _initialize_pos_db()
    blueprint = Blueprint("pos", __name__)

    @blueprint.get("/api/pos/ui")
    def pos_ui():
        return render_template("pos.html")

    @blueprint.get("/api/pos/bootstrap")
    def pos_bootstrap():
        with db_lock:
            with _connect() as connection:
                count = connection.execute("SELECT COUNT(*) FROM pos_cashiers").fetchone()[0]
                currencies = [
                    dict(row) for row in connection.execute(
                        "SELECT code, name, rate_to_base FROM pos_currencies WHERE active = 1 ORDER BY code"
                    ).fetchall()
                ]
                base = connection.execute(
                    "SELECT value FROM pos_settings WHERE key = 'base_currency'"
                ).fetchone()["value"]
        return jsonify({"setup_required": count == 0, "currencies": currencies, "base_currency": base})

    @blueprint.post("/api/pos/setup")
    def pos_setup():
        username = ""
        try:
            data = _parse_json()
            username = str(data.get("username", "")).strip()
            name = str(data.get("display_name", "")).strip()
            pin = str(data.get("pin", ""))
            if not username or not name or not pin.isdigit() or not 4 <= len(pin) <= 12:
                raise ValueError("Enter a username, display name, and a 4–12 digit PIN.")
            salt = secrets.token_hex(16)
            pin_hash = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), 200000).hex()
            with db_lock:
                with _connect() as connection:
                    if connection.execute("SELECT 1 FROM pos_cashiers LIMIT 1").fetchone():
                        return _json_error("POS setup has already been completed.", 409)
                    cursor = connection.execute(
                        """INSERT INTO pos_cashiers
                           (username, display_name, pin_salt, pin_hash, role)
                           VALUES (?, ?, ?, ?, 'manager')""",
                        (username, name, salt, pin_hash),
                    )
                    cashier_id = cursor.lastrowid
            response = _issue_session(cashier_id)
            _record_pos_audit(
                {"id": cashier_id, "username": username, "display_name": name},
                "Completed initial POS setup",
                200,
            )
            return response
        except ValueError as error:
            _record_pos_audit(None, "Attempted initial POS setup", 400, actor_username=username)
            return _json_error(str(error))
        except sqlite3.IntegrityError:
            _record_pos_audit(None, "Attempted initial POS setup", 409, actor_username=username)
            return _json_error("That username is already in use.", 409)

    @blueprint.post("/api/pos/login")
    def pos_login():
        username = ""
        try:
            data = _parse_json()
            username = str(data.get("username", "")).strip()
            pin = str(data.get("pin", ""))
            with db_lock:
                with _connect() as connection:
                    cashier = connection.execute(
                        "SELECT * FROM pos_cashiers WHERE username = ? COLLATE NOCASE AND active = 1",
                        (username,),
                    ).fetchone()
            valid = cashier is not None
            if valid:
                actual = hashlib.pbkdf2_hmac(
                    "sha256", pin.encode(), bytes.fromhex(cashier["pin_salt"]), 200000
                ).hex()
                valid = hmac.compare_digest(actual, cashier["pin_hash"])
            if not valid:
                _record_pos_audit(
                    None,
                    "Failed POS sign-in",
                    401,
                    actor_username=username,
                )
                return _json_error("Incorrect username or PIN.", 401)
            response = _issue_session(cashier["id"])
            _record_pos_audit(cashier, "Signed in to POS", 200)
            return response
        except ValueError as error:
            _record_pos_audit(None, "Invalid POS sign-in request", 400, actor_username=username)
            return _json_error(str(error))

    @blueprint.get("/api/pos/audit-log")
    @_require_pos(manager=True)
    def pos_audit_log():
        try:
            limit = max(1, min(int(request.args.get("limit", 200)), 500))
            before_id = request.args.get("before_id")
            before_id = int(before_id) if before_id not in (None, "") else None
            if before_id is not None and before_id <= 0:
                raise ValueError
        except ValueError:
            return _json_error("Limit and before_id must be positive integers.")
        with db_lock:
            with _connect() as connection:
                if before_id is None:
                    rows = connection.execute(
                        """SELECT id, cashier_id, actor_name, actor_username, action,
                                  method, path, status_code, details_json, created_at
                           FROM pos_audit_log ORDER BY id DESC LIMIT ?""",
                        (limit + 1,),
                    ).fetchall()
                else:
                    rows = connection.execute(
                        """SELECT id, cashier_id, actor_name, actor_username, action,
                                  method, path, status_code, details_json, created_at
                           FROM pos_audit_log WHERE id < ? ORDER BY id DESC LIMIT ?""",
                        (before_id, limit + 1),
                    ).fetchall()
        has_more = len(rows) > limit
        rows = rows[:limit]
        entries = []
        for row in rows:
            entry = dict(row)
            entry["details"] = json.loads(entry.pop("details_json") or "{}")
            entries.append(entry)
        return jsonify({"entries": entries, "has_more": has_more})

    @blueprint.post("/api/pos/logout")
    @_require_pos()
    def pos_logout():
        token = request.headers.get("X-POS-Session", "")
        with db_lock:
            with _connect() as connection:
                connection.execute(
                    "DELETE FROM pos_sessions WHERE token_hash = ?",
                    (hashlib.sha256(token.encode("utf-8")).hexdigest(),),
                )
        return jsonify({"ok": True})

    @blueprint.get("/api/pos/catalog")
    @_require_pos()
    def pos_catalog():
        with db_lock:
            with _connect() as connection:
                products = [
                    dict(row) for row in connection.execute(
                        """SELECT * FROM pos_products WHERE active = 1
                           ORDER BY name COLLATE NOCASE"""
                    ).fetchall()
                ]
                currencies = [
                    dict(row) for row in connection.execute(
                        "SELECT code, name, rate_to_base FROM pos_currencies WHERE active = 1 ORDER BY code"
                    ).fetchall()
                ]
                base = connection.execute(
                    "SELECT value FROM pos_settings WHERE key = 'base_currency'"
                ).fetchone()["value"]
                cashier = _cashier_from_request(connection)
        return jsonify({"products": products, "currencies": currencies, "base_currency": base, "cashier": cashier})

    @blueprint.get("/api/pos/customers")
    @_require_pos()
    def pos_customers():
        query = str(request.args.get("q", "")).strip()
        with db_lock:
            with _connect() as connection:
                rows = connection.execute(
                    """SELECT id, name, tin, vat_number, address, phone, email
                       FROM pos_customers WHERE active = 1 AND
                       (? = '' OR name LIKE ? OR tin LIKE ? OR phone LIKE ?)
                       ORDER BY name COLLATE NOCASE LIMIT 500""",
                    (query, f"%{query}%", f"%{query}%", f"%{query}%"),
                ).fetchall()
        return jsonify([dict(row) for row in rows])

    @blueprint.get("/api/pos/held-sales")
    @_require_pos()
    def pos_held_sales():
        cashier = request.pos_cashier
        with db_lock:
            with _connect() as connection:
                if cashier["role"] == "manager":
                    rows = connection.execute(
                        """SELECT h.id, h.cashier_id, h.sale_data_json, h.created_at,
                                  c.display_name AS cashier_name
                           FROM pos_held_sales h JOIN pos_cashiers c ON c.id = h.cashier_id
                           ORDER BY h.id DESC LIMIT 100"""
                    ).fetchall()
                else:
                    rows = connection.execute(
                        """SELECT h.id, h.cashier_id, h.sale_data_json, h.created_at,
                                  c.display_name AS cashier_name
                           FROM pos_held_sales h JOIN pos_cashiers c ON c.id = h.cashier_id
                           WHERE h.cashier_id = ? ORDER BY h.id DESC LIMIT 100""",
                        (cashier["id"],),
                    ).fetchall()
                products = {
                    row["id"]: row["name"] for row in connection.execute(
                        "SELECT id, name FROM pos_products"
                    ).fetchall()
                }
                result = []
                for row in rows:
                    sale = json.loads(row["sale_data_json"])
                    customer = connection.execute(
                        "SELECT name FROM pos_customers WHERE id = ?",
                        (sale.get("customer_id"),),
                    ).fetchone() if sale.get("customer_id") else None
                    result.append({
                        "id": row["id"],
                        "cashier_id": row["cashier_id"],
                        "cashier_name": row["cashier_name"],
                        "created_at": row["created_at"],
                        "currency": sale["currency"],
                        "customer_name": customer["name"] if customer else "",
                        "line_count": len(sale["lines"]),
                        "items": [
                            products.get(line["product_id"], "Archived product")
                            for line in sale["lines"]
                        ],
                    })
        return jsonify(result)

    @blueprint.post("/api/pos/held-sales")
    @_require_pos()
    def pos_hold_sale():
        try:
            data = _parse_json()
            lines = data.get("lines")
            if not isinstance(lines, list) or not lines:
                raise ValueError("Add at least one product before holding a sale.")
            currency = str(data.get("currency", "")).upper()
            invoice_format = str(data.get("invoice_format", "InvoiceA4"))
            payment_type = str(data.get("payment_type", "Cash"))
            if invoice_format not in ("InvoiceA4", "Receipt48"):
                raise ValueError("Choose A4 invoice or 80mm thermal receipt format.")
            if payment_type not in _PAYMENT_TYPES:
                raise ValueError("Select a valid payment method.")
            customer_id = data.get("customer_id")
            if customer_id not in (None, ""):
                customer_id = int(customer_id)
            else:
                customer_id = None
            received_value = data.get("amount_received")
            amount_received = (
                _money(received_value, "Amount received")
                if received_value not in (None, "") else 0
            )
            held_lines = []
            seen = set()
            with db_lock:
                with _connect() as connection:
                    if not connection.execute(
                        "SELECT 1 FROM pos_currencies WHERE code = ? AND active = 1", (currency,)
                    ).fetchone():
                        raise ValueError("Choose an enabled currency.")
                    if customer_id is not None and not connection.execute(
                        "SELECT 1 FROM pos_customers WHERE id = ? AND active = 1", (customer_id,)
                    ).fetchone():
                        raise ValueError("Selected customer is no longer available.")
                    for line in lines:
                        if not isinstance(line, dict):
                            raise ValueError("Each sale line must be an object.")
                        product_id = int(line.get("product_id"))
                        quantity = round(_finite_number(line.get("quantity"), "Quantity"), 3)
                        if quantity <= 0:
                            raise ValueError("Product quantities must be greater than zero.")
                        if product_id in seen:
                            raise ValueError("A product can only appear once in the held sale.")
                        seen.add(product_id)
                        if not connection.execute(
                            "SELECT 1 FROM pos_products WHERE id = ? AND active = 1", (product_id,)
                        ).fetchone():
                            raise ValueError("A selected product is no longer available.")
                        held_lines.append({"product_id": product_id, "quantity": quantity})
                    sale = {
                        "lines": held_lines,
                        "currency": currency,
                        "customer_id": customer_id,
                        "invoice_format": invoice_format,
                        "payment_type": payment_type,
                        "amount_received": amount_received,
                        "fiscalize": bool(data.get("fiscalize", False)),
                    }
                    cursor = connection.execute(
                        "INSERT INTO pos_held_sales (cashier_id, sale_data_json) VALUES (?, ?)",
                        (request.pos_cashier["id"], json.dumps(sale)),
                    )
            return jsonify({"id": cursor.lastrowid, "created_at": datetime.now().isoformat(timespec="seconds")}), 201
        except (ValueError, TypeError) as error:
            return _json_error(str(error))

    @blueprint.get("/api/pos/held-sales/<int:held_sale_id>")
    @_require_pos()
    def pos_get_held_sale(held_sale_id):
        cashier = request.pos_cashier
        with db_lock:
            with _connect() as connection:
                if cashier["role"] == "manager":
                    row = connection.execute(
                        "SELECT * FROM pos_held_sales WHERE id = ?", (held_sale_id,)
                    ).fetchone()
                else:
                    row = connection.execute(
                        "SELECT * FROM pos_held_sales WHERE id = ? AND cashier_id = ?",
                        (held_sale_id, cashier["id"]),
                    ).fetchone()
        if not row:
            return _json_error("Held sale not found.", 404)
        sale = json.loads(row["sale_data_json"])
        sale["id"] = row["id"]
        return jsonify(sale)

    @blueprint.delete("/api/pos/held-sales/<int:held_sale_id>")
    @_require_pos()
    def pos_discard_held_sale(held_sale_id):
        cashier = request.pos_cashier
        with db_lock:
            with _connect() as connection:
                if cashier["role"] == "manager":
                    cursor = connection.execute(
                        "DELETE FROM pos_held_sales WHERE id = ?", (held_sale_id,)
                    )
                else:
                    cursor = connection.execute(
                        "DELETE FROM pos_held_sales WHERE id = ? AND cashier_id = ?",
                        (held_sale_id, cashier["id"]),
                    )
        if not cursor.rowcount:
            return _json_error("Held sale not found.", 404)
        return jsonify({"ok": True})

    @blueprint.post("/api/pos/customers")
    @_require_pos()
    def pos_add_customer():
        try:
            data = _parse_json()
            customer = _buyer_data_from_customer(data)
            if not customer["name"]:
                raise ValueError("Customer name is required.")
            with db_lock:
                with _connect() as connection:
                    cursor = connection.execute(
                        """INSERT INTO pos_customers (name, tin, vat_number, address, phone, email)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (customer["name"], customer["tin"], customer["vat_number"],
                         customer["address"], customer["phone"], customer["email"]),
                    )
                    customer["id"] = cursor.lastrowid
            return jsonify(customer), 201
        except ValueError as error:
            return _json_error(str(error))
        except sqlite3.IntegrityError:
            return _json_error("A customer with that TIN already exists.", 409)

    @blueprint.put("/api/pos/customers/<int:customer_id>")
    @_require_pos()
    def pos_update_customer(customer_id):
        try:
            data = _parse_json()
            customer = _buyer_data_from_customer(data)
            if not customer["name"]:
                raise ValueError("Customer name is required.")
            with db_lock:
                with _connect() as connection:
                    cursor = connection.execute(
                        """UPDATE pos_customers SET name = ?, tin = ?, vat_number = ?, address = ?,
                           phone = ?, email = ?, updated_at = CURRENT_TIMESTAMP
                           WHERE id = ? AND active = 1""",
                        (customer["name"], customer["tin"], customer["vat_number"], customer["address"],
                         customer["phone"], customer["email"], customer_id),
                    )
            if not cursor.rowcount:
                return _json_error("Customer not found.", 404)
            return jsonify({"id": customer_id, **customer})
        except ValueError as error:
            return _json_error(str(error))
        except sqlite3.IntegrityError:
            return _json_error("A customer with that TIN already exists.", 409)

    @blueprint.post("/api/pos/products")
    @_require_pos(manager=True)
    def pos_add_product():
        try:
            data = _parse_json()
            sku = str(data.get("sku", "")).strip()
            name = str(data.get("name", "")).strip()
            price = _money(data.get("price"), "Price")
            if price < 0.01:
                raise ValueError("Price must be at least 0.01.")
            tax_percent = _finite_number(data.get("tax_percent", 0), "Tax rate")
            stock_qty = _finite_number(data.get("stock_qty", 0), "Opening stock")
            low_stock = _finite_number(data.get("low_stock_threshold", 5), "Low-stock threshold")
            currency = str(data.get("currency", "USD")).upper()
            tax_code = str(data.get("tax_code", "A")).strip().upper()
            if tax_percent == 0 and tax_code == "A":
                tax_code = "B"
            if not tax_code:
                raise ValueError("Tax code is required.")
            hs_code = str(data.get("hs_code", "10000000")).strip()
            track_stock = 0 if data.get("track_stock") is False else 1
            if not sku or not name or len(sku) > 80 or len(name) > 200:
                raise ValueError("SKU and product name are required (maximum 80 and 200 characters).")
            if tax_percent < 0 or stock_qty < 0 or low_stock < 0:
                raise ValueError("Tax and stock values cannot be negative.")
            if len(hs_code) not in (4, 8) or not hs_code.isdigit():
                raise ValueError("HS code must contain 4 or 8 digits.")
            with db_lock:
                with _connect() as connection:
                    if not connection.execute(
                        "SELECT 1 FROM pos_currencies WHERE code = ? AND active = 1", (currency,)
                    ).fetchone():
                        raise ValueError("Choose an enabled currency.")
                    base_currency = connection.execute(
                        "SELECT value FROM pos_settings WHERE key = 'base_currency'"
                    ).fetchone()["value"]
                    price_in_base = round(
                        price * connection.execute(
                            "SELECT rate_to_base FROM pos_currencies WHERE code = ?", (currency,)
                        ).fetchone()["rate_to_base"],
                        6,
                    )
                    cursor = connection.execute(
                        """INSERT INTO pos_products
                           (sku, name, hs_code, price, currency, tax_code, tax_percent, tax_id,
                            stock_qty, low_stock_threshold, track_stock)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (sku, name, hs_code, price_in_base, base_currency, tax_code, tax_percent,
                         Config.TAX_ID if tax_percent else 2, stock_qty, low_stock, track_stock),
                    )
                    product_id = cursor.lastrowid
                    if stock_qty:
                        connection.execute(
                            """INSERT INTO pos_stock_movements
                               (product_id, cashier_id, movement_type, quantity_delta, note)
                               VALUES (?, ?, 'OPENING', ?, 'Initial stock')""",
                            (product_id, request.pos_cashier["id"], stock_qty),
                        )
                    product = dict(connection.execute(
                        "SELECT * FROM pos_products WHERE id = ?", (product_id,)
                    ).fetchone())
            return jsonify(product), 201
        except ValueError as error:
            return _json_error(str(error))
        except sqlite3.IntegrityError:
            return _json_error("A product with that SKU already exists.", 409)

    @blueprint.put("/api/pos/products/<int:product_id>")
    @_require_pos(manager=True)
    def pos_update_product(product_id):
        try:
            data = _parse_json()
            allowed = {"sku", "name", "hs_code", "price", "currency", "tax_code",
                       "tax_percent", "low_stock_threshold", "track_stock"}
            with db_lock:
                with _connect() as connection:
                    current = connection.execute(
                        "SELECT * FROM pos_products WHERE id = ? AND active = 1", (product_id,)
                    ).fetchone()
                    if not current:
                        return _json_error("Product not found.", 404)
                    values = dict(current)
                    values.update({key: value for key, value in data.items() if key in allowed})
                    if not str(values["sku"]).strip() or not str(values["name"]).strip():
                        raise ValueError("SKU and product name are required.")
                    values["price"] = _money(values["price"], "Price")
                    if values["price"] < 0.01:
                        raise ValueError("Price must be at least 0.01.")
                    values["tax_percent"] = _finite_number(values["tax_percent"], "Tax rate")
                    values["low_stock_threshold"] = _finite_number(
                        values["low_stock_threshold"], "Low-stock threshold"
                    )
                    values["currency"] = str(values["currency"]).upper()
                    values["hs_code"] = str(values["hs_code"])
                    values["tax_code"] = str(values["tax_code"]).strip().upper()
                    if values["tax_percent"] == 0 and values["tax_code"] == "A":
                        values["tax_code"] = "B"
                    if not values["tax_code"]:
                        raise ValueError("Tax code is required.")
                    if values["tax_percent"] < 0 or values["low_stock_threshold"] < 0:
                        raise ValueError("Tax and low-stock threshold cannot be negative.")
                    if len(values["hs_code"]) not in (4, 8) or not values["hs_code"].isdigit():
                        raise ValueError("HS code must contain 4 or 8 digits.")
                    if not connection.execute(
                        "SELECT 1 FROM pos_currencies WHERE code = ? AND active = 1",
                        (values["currency"],),
                    ).fetchone():
                        raise ValueError("Choose an enabled currency.")
                    base_currency = connection.execute(
                        "SELECT value FROM pos_settings WHERE key = 'base_currency'"
                    ).fetchone()["value"]
                    if "price" in data or "currency" in data:
                        price_currency = str(data.get("currency", base_currency)).upper()
                        if not connection.execute(
                            "SELECT 1 FROM pos_currencies WHERE code = ? AND active = 1",
                            (price_currency,),
                        ).fetchone():
                            raise ValueError("Choose an enabled currency.")
                        price_rate = connection.execute(
                            "SELECT rate_to_base FROM pos_currencies WHERE code = ?", (price_currency,)
                        ).fetchone()["rate_to_base"]
                        values["price"] = round(values["price"] * price_rate, 6)
                    connection.execute(
                        """UPDATE pos_products SET sku = ?, name = ?, hs_code = ?, price = ?,
                           currency = ?, tax_code = ?, tax_percent = ?, tax_id = ?,
                           low_stock_threshold = ?, track_stock = ?, updated_at = CURRENT_TIMESTAMP
                           WHERE id = ?""",
                        (values["sku"], values["name"], values["hs_code"], values["price"],
                         base_currency, values["tax_code"], values["tax_percent"],
                         Config.TAX_ID if values["tax_percent"] else 2,
                         values["low_stock_threshold"], int(bool(values["track_stock"])), product_id),
                    )
                    return jsonify(dict(connection.execute(
                        "SELECT * FROM pos_products WHERE id = ?", (product_id,)
                    ).fetchone()))
        except ValueError as error:
            return _json_error(str(error))
        except sqlite3.IntegrityError:
            return _json_error("A product with that SKU already exists.", 409)

    @blueprint.delete("/api/pos/products/<int:product_id>")
    @_require_pos(manager=True)
    def pos_deactivate_product(product_id):
        with db_lock:
            with _connect() as connection:
                cursor = connection.execute(
                    "UPDATE pos_products SET active = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND active = 1",
                    (product_id,),
                )
        if not cursor.rowcount:
            return _json_error("Product not found.", 404)
        return jsonify({"ok": True})

    @blueprint.post("/api/pos/stock")
    @_require_pos(manager=True)
    def pos_stock_movement():
        try:
            data = _parse_json()
            product_id = int(data.get("product_id"))
            delta = _finite_number(data.get("quantity_delta"), "Stock adjustment")
            note = str(data.get("note", "")).strip()[:250]
            if delta == 0:
                raise ValueError("Stock adjustment cannot be zero.")
            with db_lock:
                with _connect() as connection:
                    product = connection.execute(
                        "SELECT stock_qty FROM pos_products WHERE id = ? AND active = 1", (product_id,)
                    ).fetchone()
                    if not product:
                        return _json_error("Product not found.", 404)
                    if product["stock_qty"] + delta < 0:
                        raise ValueError("Stock cannot be adjusted below zero.")
                    connection.execute(
                        "UPDATE pos_products SET stock_qty = stock_qty + ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (delta, product_id),
                    )
                    connection.execute(
                        """INSERT INTO pos_stock_movements
                           (product_id, cashier_id, movement_type, quantity_delta, note)
                           VALUES (?, ?, ?, ?, ?)""",
                        (product_id, request.pos_cashier["id"],
                         "RESTOCK" if delta > 0 else "ADJUSTMENT", delta, note),
                    )
                    quantity = connection.execute(
                        "SELECT stock_qty FROM pos_products WHERE id = ?", (product_id,)
                    ).fetchone()["stock_qty"]
            return jsonify({"product_id": product_id, "stock_qty": quantity})
        except (ValueError, TypeError) as error:
            return _json_error(str(error))

    @blueprint.post("/api/pos/currencies")
    @_require_pos(manager=True)
    def pos_add_currency():
        try:
            data = _parse_json()
            code = str(data.get("code", "")).strip().upper()
            name = str(data.get("name", "")).strip()
            rate = _finite_number(data.get("rate_to_base"), "Exchange rate")
            if len(code) != 3 or not code.isalpha() or not name or rate <= 0:
                raise ValueError("Enter a three-letter currency code, name, and positive exchange rate.")
            with db_lock:
                with _connect() as connection:
                    base = connection.execute(
                        "SELECT value FROM pos_settings WHERE key = 'base_currency'"
                    ).fetchone()["value"]
                    connection.execute(
                        "INSERT INTO pos_currencies (code, name, rate_to_base) VALUES (?, ?, ?)",
                        (code, name, 1 if code == base else rate),
                    )
            return jsonify({"code": code, "name": name, "rate_to_base": 1 if code == base else rate}), 201
        except ValueError as error:
            return _json_error(str(error))
        except sqlite3.IntegrityError:
            return _json_error("That currency is already configured.", 409)

    @blueprint.post("/api/pos/sell")
    @_require_pos()
    def pos_sell():
        try:
            data = _parse_json()
            requested_lines = data.get("lines")
            if not isinstance(requested_lines, list) or not requested_lines:
                raise ValueError("Add at least one product to the sale.")
            currency = str(data.get("currency", "USD")).upper()
            invoice_format = str(data.get("invoice_format", "InvoiceA4"))
            if invoice_format not in ("InvoiceA4", "Receipt48"):
                raise ValueError("Choose A4 invoice or 80mm thermal receipt format.")
            payment_type = str(data.get("payment_type", "Cash"))
            if payment_type not in _PAYMENT_TYPES:
                raise ValueError("Select a valid payment method.")
            aggregate = {}
            for line in requested_lines:
                if not isinstance(line, dict):
                    raise ValueError("Each sale line must be an object.")
                product_id = int(line.get("product_id"))
                quantity = round(_finite_number(line.get("quantity"), "Quantity"), 3)
                if quantity <= 0:
                    raise ValueError("Product quantities must be greater than zero.")
                aggregate[product_id] = aggregate.get(product_id, 0) + quantity
            with db_lock:
                with _connect() as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    held_sale_id = data.get("held_sale_id")
                    if held_sale_id not in (None, ""):
                        held_sale_id = int(held_sale_id)
                        held_query = "SELECT cashier_id FROM pos_held_sales WHERE id = ?"
                        held_row = connection.execute(held_query, (held_sale_id,)).fetchone()
                        if not held_row or (
                            held_row["cashier_id"] != request.pos_cashier["id"]
                            and request.pos_cashier["role"] != "manager"
                        ):
                            raise ValueError("Held sale was not found or is no longer available.")
                    currency_row = connection.execute(
                        "SELECT rate_to_base FROM pos_currencies WHERE code = ? AND active = 1",
                        (currency,),
                    ).fetchone()
                    if not currency_row:
                        raise ValueError("Choose an enabled currency.")
                    base_currency = connection.execute(
                        "SELECT value FROM pos_settings WHERE key = 'base_currency'"
                    ).fetchone()["value"]
                    customer_id = data.get("customer_id")
                    buyer_data = {}
                    if customer_id not in (None, ""):
                        customer = connection.execute(
                            """SELECT id, name, tin, vat_number, address, phone, email
                               FROM pos_customers WHERE id = ? AND active = 1""",
                            (int(customer_id),),
                        ).fetchone()
                        if not customer:
                            raise ValueError("Selected customer is no longer available.")
                        buyer_data = {
                            "name": customer["name"], "tin": customer["tin"],
                            "vat_number": customer["vat_number"], "address": customer["address"],
                            "phone": customer["phone"], "email": customer["email"],
                        }
                    elif str(data.get("customer_name", "")).strip():
                        buyer_data = _buyer_data_from_customer({
                            "name": data.get("customer_name"),
                            "tin": data.get("customer_tin"),
                            "vat_number": data.get("customer_vat_number"),
                            "address": data.get("customer_address"),
                            "phone": data.get("customer_phone"),
                            "email": data.get("customer_email"),
                        })
                    products = {}
                    for product_id, quantity in aggregate.items():
                        product = connection.execute(
                            "SELECT * FROM pos_products WHERE id = ? AND active = 1", (product_id,)
                        ).fetchone()
                        if not product:
                            raise ValueError("A selected product is no longer available.")
                        if product["track_stock"] and product["stock_qty"] < quantity:
                            raise ValueError(f"Insufficient stock for {product['name']}.")
                        products[product_id] = (dict(product), quantity)

                    invoice_no = "POS-" + datetime.now().strftime("%Y%m%d") + "-" + secrets.token_hex(3).upper()
                    invoice_lines = []
                    subtotal = tax_total = total = 0.0
                    for product, quantity in products.values():
                        unit_price = round(float(product["price"]) / currency_row["rate_to_base"], 2)
                        line_total = round(unit_price * quantity, 2)
                        if line_total <= 0:
                            raise ValueError(f"Sale total for {product['name']} must be at least 0.01.")
                        tax = round(
                            line_total * product["tax_percent"] / (100 + product["tax_percent"]), 2
                        ) if product["tax_percent"] else 0.0
                        invoice_lines.append((product, quantity, unit_price, line_total, tax))
                        total += line_total
                        tax_total += tax
                        subtotal += line_total - tax
                    total, tax_total, subtotal = round(total, 2), round(tax_total, 2), round(subtotal, 2)
                    amount_received = total
                    change_due = 0.0
                    if payment_type == "Cash":
                        amount_received = _money(data.get("amount_received", total), "Amount received")
                        if amount_received < total:
                            raise ValueError(
                                f"Amount received must be at least {currency} {total:.2f}."
                            )
                        change_due = round(amount_received - total, 2)
                    payments = [{"moneyTypeCode": payment_type, "paymentAmount": total}]
                    cursor = connection.execute(
                        """INSERT INTO pos_invoices
                           (invoice_no, cashier_id, customer_name, currency, subtotal, tax_total, total,
                           payments_json, exchange_rate, customer_id, buyer_data_json, invoice_format,
                           amount_received, change_due)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (invoice_no, request.pos_cashier["id"], buyer_data.get("name", ""), currency,
                         subtotal, tax_total, total, json.dumps(payments), currency_row["rate_to_base"],
                         customer_id, json.dumps(buyer_data), invoice_format, amount_received, change_due),
                    )
                    invoice_id = cursor.lastrowid
                    for product, quantity, unit_price, line_total, tax in invoice_lines:
                        connection.execute(
                            """INSERT INTO pos_invoice_lines
                               (invoice_id, product_id, sku, name, hs_code, quantity, unit_price,
                                line_total, tax_code, tax_percent, tax_id)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (invoice_id, product["id"], product["sku"], product["name"], product["hs_code"],
                             quantity, unit_price, line_total, product["tax_code"],
                             product["tax_percent"], product["tax_id"]),
                        )
                        if product["track_stock"]:
                            connection.execute(
                                "UPDATE pos_products SET stock_qty = stock_qty - ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                                (quantity, product["id"]),
                            )
                            connection.execute(
                                """INSERT INTO pos_stock_movements
                                   (product_id, cashier_id, invoice_id, movement_type, quantity_delta, note)
                                   VALUES (?, ?, ?, 'SALE', ?, ?)""",
                                (product["id"], request.pos_cashier["id"], invoice_id, -quantity, invoice_no),
                            )
                    if payment_type == "Cash":
                        connection.execute(
                            """INSERT INTO pos_cash_movements
                               (cashier_id, invoice_id, movement_type, amount, currency, exchange_rate, note)
                               VALUES (?, ?, 'SALE', ?, ?, ?, ?)""",
                            (request.pos_cashier["id"], invoice_id, total, currency,
                             currency_row["rate_to_base"], invoice_no),
                        )
                    if held_sale_id is not None:
                        connection.execute("DELETE FROM pos_held_sales WHERE id = ?", (held_sale_id,))
                    fiscalize = bool(data.get("fiscalize", False))
                    result = _invoice_details(connection, invoice_id)
            if fiscalize:
                result, fiscal_status = _fiscalize_invoice(invoice_id, zimra)
                if result and fiscal_status >= 400:
                    result["fiscal_http_status"] = fiscal_status
            else:
                fiscal_status = 200
            result["amount_received"] = amount_received
            result["change_due"] = change_due
            return jsonify(result), 201
        except (ValueError, TypeError, KeyError) as error:
            return _json_error(str(error))
        except sqlite3.IntegrityError as error:
            return _json_error(f"Could not save the sale: {error}", 409)

    @blueprint.get("/api/pos/invoices")
    @_require_pos()
    def pos_invoices():
        try:
            limit = max(1, min(int(request.args.get("limit", 100)), 500))
        except ValueError:
            return _json_error("Limit must be a number.")
        with db_lock:
            with _connect() as connection:
                rows = connection.execute(
                    """SELECT i.id, i.invoice_no, i.customer_name, i.currency, i.total, i.fiscal_status,
                              i.fiscal_error, i.verification_code, i.created_at, i.document_type,
                              i.original_invoice_id, c.display_name AS cashier_name
                       FROM pos_invoices i JOIN pos_cashiers c ON c.id = i.cashier_id
                       ORDER BY i.id DESC LIMIT ?""",
                    (limit,),
                ).fetchall()
        return jsonify([dict(row) for row in rows])

    @blueprint.get("/api/pos/analysis")
    @_require_pos()
    def pos_analysis():
        today = datetime.now().date()
        default_start = (today - timedelta(days=29)).isoformat()
        start = request.args.get("start", default_start)
        end = request.args.get("end", today.isoformat())
        try:
            start_date = datetime.strptime(start, "%Y-%m-%d").date()
            end_date = datetime.strptime(end, "%Y-%m-%d").date()
            if start_date > end_date:
                raise ValueError
        except ValueError:
            return _json_error("Use valid start/end dates (YYYY-MM-DD) with start before end.")
        with db_lock:
            with _connect() as connection:
                base = connection.execute(
                    "SELECT value FROM pos_settings WHERE key = 'base_currency'"
                ).fetchone()["value"]
                invoices = [
                    dict(row) for row in connection.execute(
                        """SELECT id, currency, total, tax_total, exchange_rate, document_type, payments_json
                           FROM pos_invoices
                           WHERE substr(created_at, 1, 10) BETWEEN ? AND ?""",
                        (start, end),
                    ).fetchall()
                ]
                product_rows = connection.execute(
                    """SELECT l.sku, l.name, i.currency, i.document_type,
                              SUM(l.quantity * CASE WHEN i.document_type = 'credit_note' THEN -1 ELSE 1 END) AS net_quantity,
                              SUM(l.line_total) AS net_sales
                       FROM pos_invoice_lines l JOIN pos_invoices i ON i.id = l.invoice_id
                       WHERE substr(i.created_at, 1, 10) BETWEEN ? AND ?
                       GROUP BY l.sku, l.name, i.currency
                       ORDER BY ABS(SUM(l.line_total)) DESC LIMIT 20""",
                    (start, end),
                ).fetchall()
                daily_rows = connection.execute(
                    """SELECT substr(created_at, 1, 10) AS day, currency,
                              SUM(CASE WHEN document_type = 'credit_note' THEN 0 ELSE total END) AS gross_sales,
                              SUM(CASE WHEN document_type = 'credit_note' THEN total ELSE 0 END) AS credits,
                              SUM(total) AS net_sales, SUM(tax_total) AS net_tax,
                              SUM(total * exchange_rate) AS base_net_sales
                       FROM pos_invoices
                       WHERE substr(created_at, 1, 10) BETWEEN ? AND ?
                       GROUP BY day, currency ORDER BY day""",
                    (start, end),
                ).fetchall()
        totals = {
            "gross_sales": 0.0, "credits": 0.0, "net_sales": 0.0, "net_tax": 0.0,
            "invoice_count": 0, "credit_note_count": 0, "base_gross_sales": 0.0,
            "base_credits": 0.0, "base_net_sales": 0.0, "base_net_tax": 0.0,
        }
        by_currency = {}
        payments_by_type = {}
        for invoice in invoices:
            currency = invoice["currency"]
            values = by_currency.setdefault(
                currency, {"gross_sales": 0.0, "credits": 0.0, "net_sales": 0.0, "net_tax": 0.0}
            )
            total = float(invoice["total"])
            tax = float(invoice["tax_total"])
            totals["invoice_count"] += invoice["document_type"] != "credit_note"
            totals["credit_note_count"] += invoice["document_type"] == "credit_note"
            if invoice["document_type"] == "credit_note":
                totals["credits"] += abs(total)
                values["credits"] += abs(total)
            else:
                totals["gross_sales"] += total
                values["gross_sales"] += total
            totals["net_sales"] += total
            totals["net_tax"] += tax
            values["net_sales"] += total
            values["net_tax"] += tax
            rate_to_base = float(invoice["exchange_rate"])
            totals["base_net_sales"] += total * rate_to_base
            totals["base_net_tax"] += tax * rate_to_base
            if invoice["document_type"] == "credit_note":
                totals["base_credits"] += abs(total) * rate_to_base
            else:
                totals["base_gross_sales"] += total * rate_to_base
            for payment in json.loads(invoice["payments_json"]):
                payment_type = payment.get("moneyTypeCode", "Other")
                payment_total = float(payment.get("paymentAmount", 0))
                payments_by_currency = payments_by_type.setdefault(payment_type, {})
                payments_by_currency[currency] = payments_by_currency.get(currency, 0) + payment_total
        daily = [dict(row) for row in daily_rows]
        return jsonify({
            "start": start, "end": end, "base_currency": base,
            "totals": {key: round(value, 2) if isinstance(value, float) else value
                       for key, value in totals.items()},
            "average_sale": round(
                totals["base_gross_sales"] / totals["invoice_count"], 2
            ) if totals["invoice_count"] else 0,
            "by_currency": by_currency,
            "sales_by_day": daily,
            "top_products": [dict(row) for row in product_rows],
            "payments_by_type": payments_by_type,
        })

    @blueprint.get("/api/pos/invoices/<int:invoice_id>")
    @_require_pos()
    def pos_invoice(invoice_id):
        with db_lock:
            with _connect() as connection:
                invoice = _invoice_details(connection, invoice_id)
        return jsonify(invoice) if invoice else _json_error("Invoice not found.", 404)

    @blueprint.post("/api/pos/invoices/<int:invoice_id>/credit-note")
    @_require_pos(manager=True)
    def pos_create_credit_note(invoice_id):
        try:
            data = _parse_json()
            requested_lines = data.get("lines")
            if not isinstance(requested_lines, list) or not requested_lines:
                raise ValueError("Select at least one invoice line to credit.")
            quantities = {}
            for entry in requested_lines:
                if not isinstance(entry, dict):
                    raise ValueError("Each credit-note line must be an object.")
                line_id = int(entry.get("line_id"))
                quantity = round(_finite_number(entry.get("quantity"), "Credit quantity"), 3)
                if quantity <= 0:
                    raise ValueError("Credit quantities must be greater than zero.")
                quantities[line_id] = quantities.get(line_id, 0) + quantity
            with db_lock:
                with _connect() as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    original = connection.execute(
                        "SELECT * FROM pos_invoices WHERE id = ?", (invoice_id,)
                    ).fetchone()
                    if not original:
                        return _json_error("Original invoice not found.", 404)
                    if original["document_type"] != "invoice" or original["fiscal_status"] != "fiscalized":
                        raise ValueError("A credit note requires an original fiscalised sales invoice.")
                    original = dict(original)
                    original_payload = json.loads(original["payload_json"] or "{}")
                    original_receipt = original_payload.get("receipt") or {}
                    global_no = original_receipt.get("receiptGlobalNo")
                    if not global_no or not original.get("fiscal_day_no") or not original_receipt.get("receiptDate"):
                        raise ValueError("Original fiscal receipt reference is incomplete; credit note cannot be submitted.")
                    selected = {}
                    amount = 0.0
                    tax_total = 0.0
                    for line_id, quantity in quantities.items():
                        source = connection.execute(
                            "SELECT * FROM pos_invoice_lines WHERE id = ? AND invoice_id = ?",
                            (line_id, invoice_id),
                        ).fetchone()
                        if not source:
                            raise ValueError("A selected line does not belong to the original invoice.")
                        credited = connection.execute(
                            """SELECT COALESCE(SUM(quantity), 0) FROM pos_invoice_lines
                               WHERE product_id IS ? AND name = ? AND invoice_id IN
                                 (SELECT id FROM pos_invoices WHERE original_invoice_id = ?
                                  AND document_type = 'credit_note')""",
                            (source["product_id"], source["name"], invoice_id),
                        ).fetchone()[0]
                        remaining = float(source["quantity"]) - float(credited)
                        if quantity > remaining + 0.0001:
                            raise ValueError(
                                f"Credit quantity for {source['name']} exceeds the unreturned quantity ({remaining:g})."
                            )
                        line_total = round(float(source["unit_price"]) * quantity, 2)
                        line_tax = round(
                            line_total * source["tax_percent"] / (100 + source["tax_percent"]), 2
                        ) if source["tax_percent"] else 0
                        selected[line_id] = (dict(source), quantity, line_total, line_tax)
                        amount += line_total
                        tax_total += line_tax
                    amount, tax_total = round(amount, 2), round(tax_total, 2)
                    if amount <= 0:
                        raise ValueError("Credit note total must be greater than zero.")
                    invoice_no = "POS-CN-" + datetime.now().strftime("%Y%m%d") + "-" + secrets.token_hex(3).upper()
                    customer_data = json.loads(original.get("buyer_data_json") or "{}")
                    payments = [
                        {"moneyTypeCode": payment.get("moneyTypeCode", "Cash"), "paymentAmount": -amount}
                        for payment in json.loads(original["payments_json"])
                    ]
                    cursor = connection.execute(
                        """INSERT INTO pos_invoices
                           (invoice_no, cashier_id, customer_name, currency, subtotal, tax_total, total,
                            payments_json, exchange_rate, customer_id, buyer_data_json, invoice_format,
                            document_type, original_invoice_id, original_global_no,
                            original_receipt_date, original_fiscal_day_no)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'credit_note', ?, ?, ?, ?)""",
                        (invoice_no, request.pos_cashier["id"], customer_data.get("name", ""),
                         original["currency"], round(-(amount - tax_total), 2), -tax_total, -amount,
                         json.dumps(payments), original["exchange_rate"], original.get("customer_id"),
                         json.dumps(customer_data), original["invoice_format"], invoice_id, int(global_no),
                         original_receipt["receiptDate"], original["fiscal_day_no"]),
                    )
                    credit_id = cursor.lastrowid
                    for source, quantity, line_total, line_tax in selected.values():
                        connection.execute(
                            """INSERT INTO pos_invoice_lines
                               (invoice_id, product_id, sku, name, hs_code, quantity, unit_price,
                                line_total, tax_code, tax_percent, tax_id)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (credit_id, source["product_id"], source["sku"], source["name"],
                             source["hs_code"], quantity, -abs(source["unit_price"]),
                             -abs(line_total), source["tax_code"], source["tax_percent"], source["tax_id"]),
                        )
                        if source["product_id"]:
                            product = connection.execute(
                                "SELECT track_stock FROM pos_products WHERE id = ?",
                                (source["product_id"],),
                            ).fetchone()
                        else:
                            product = None
                        if product and product["track_stock"]:
                            connection.execute(
                                "UPDATE pos_products SET stock_qty = stock_qty + ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                                (quantity, source["product_id"]),
                            )
                            connection.execute(
                                """INSERT INTO pos_stock_movements
                                   (product_id, cashier_id, invoice_id, movement_type, quantity_delta, note)
                                   VALUES (?, ?, ?, 'RETURN', ?, ?)""",
                                (source["product_id"], request.pos_cashier["id"], credit_id,
                                 quantity, invoice_no),
                            )
                    if any(payment["moneyTypeCode"] == "Cash" for payment in payments):
                        connection.execute(
                            """INSERT INTO pos_cash_movements
                               (cashier_id, invoice_id, movement_type, amount, currency, exchange_rate, note)
                               VALUES (?, ?, 'OUT', ?, ?, ?, ?)""",
                            (request.pos_cashier["id"], credit_id, amount, original["currency"],
                             original["exchange_rate"], invoice_no),
                        )
                    result = _invoice_details(connection, credit_id)
            if data.get("fiscalize", False):
                result, status = _fiscalize_invoice(credit_id, zimra)
                if status >= 400:
                    return jsonify({"error": result.get("fiscal_error", "Credit-note fiscalisation failed."),
                                    "invoice": result}), status
            return jsonify(result), 201
        except (ValueError, TypeError, KeyError) as error:
            return _json_error(str(error))
        except sqlite3.IntegrityError as error:
            return _json_error(f"Could not save the credit note: {error}", 409)

    @blueprint.post("/api/pos/invoices/<int:invoice_id>/fiscalize")
    @_require_pos(manager=True)
    def pos_late_fiscalize(invoice_id):
        invoice, status = _fiscalize_invoice(invoice_id, zimra)
        if invoice is None:
            return _json_error("Invoice not found.", status)
        if status >= 400:
            return jsonify({"error": invoice.get("fiscal_error", invoice.get("error", "Fiscalisation failed.")),
                            "invoice": invoice}), status
        return jsonify(invoice)

    @blueprint.get("/api/pos/invoices/<int:invoice_id>/print")
    @_require_pos()
    def pos_print_invoice(invoice_id):
        with db_lock:
            with _connect() as connection:
                invoice = _invoice_details(connection, invoice_id)
        if not invoice:
            return _json_error("Invoice not found.", 404)
        try:
            pdf = _render_invoice_pdf(invoice, zimra)
        except Exception as error:
            current_app.logger.exception("Could not create POS invoice PDF %s", invoice["invoice_no"])
            return _json_error(f"Could not generate invoice PDF: {error}", 500)
        response = make_response(send_file(
            pdf,
            mimetype="application/pdf",
            as_attachment=False,
            download_name=f"{invoice['invoice_no']}.pdf",
        ))
        response.headers["Cache-Control"] = "no-store"
        return response

    @blueprint.post("/api/pos/invoices/<int:invoice_id>/print")
    @_require_pos()
    def pos_send_invoice_to_printer(invoice_id):
        with db_lock:
            with _connect() as connection:
                invoice = _invoice_details(connection, invoice_id)
        if not invoice:
            return _json_error("Invoice not found.", 404)
        pdf_path = None
        try:
            pdf = _render_invoice_pdf(invoice, zimra)
            with tempfile.NamedTemporaryFile(
                prefix=f"{invoice['invoice_no']}-", suffix=".pdf", delete=False
            ) as pdf_file:
                pdf_path = pdf_file.name
                pdf_file.write(pdf.getvalue())
            from core.printer_manager import send_pdf_to_printer
            logger = current_app.logger
            printer_name, job_id = send_pdf_to_printer(
                pdf_path,
                Config.PRINTER_NAME,
                lambda title, message: logger.info("%s: %s", title, message),
            )
            return jsonify({"printed": True, "printer": printer_name, "job_id": job_id})
        except Exception as error:
            current_app.logger.exception("Could not print POS invoice %s", invoice["invoice_no"])
            return _json_error(f"Could not print invoice: {error}", 500)
        finally:
            if pdf_path and os.path.exists(pdf_path):
                os.remove(pdf_path)

    @blueprint.get("/api/pos/stock-movements")
    @_require_pos()
    def pos_stock_history():
        with db_lock:
            with _connect() as connection:
                rows = connection.execute(
                    """SELECT m.id, m.movement_type, m.quantity_delta, m.note, m.created_at,
                              p.sku, p.name AS product_name, c.display_name AS cashier_name
                       FROM pos_stock_movements m
                       JOIN pos_products p ON p.id = m.product_id
                       JOIN pos_cashiers c ON c.id = m.cashier_id
                       ORDER BY m.id DESC LIMIT 300"""
                ).fetchall()
        return jsonify([dict(row) for row in rows])

    @blueprint.get("/api/pos/cashbook")
    @_require_pos()
    def pos_cashbook():
        with db_lock:
            with _connect() as connection:
                rows = connection.execute(
                    """SELECT m.*, c.display_name AS cashier_name, i.invoice_no
                       FROM pos_cash_movements m JOIN pos_cashiers c ON c.id = m.cashier_id
                       LEFT JOIN pos_invoices i ON i.id = m.invoice_id
                       ORDER BY m.id DESC LIMIT 500"""
                ).fetchall()
                base = connection.execute(
                    "SELECT value FROM pos_settings WHERE key = 'base_currency'"
                ).fetchone()["value"]
                summary = connection.execute(
                    """SELECT currency, SUM(CASE WHEN movement_type IN ('SALE', 'IN') THEN amount
                                ELSE -amount END) AS balance,
                              SUM(CASE WHEN movement_type IN ('SALE', 'IN') THEN amount ELSE 0 END) AS cash_in,
                              SUM(CASE WHEN movement_type = 'OUT' THEN amount ELSE 0 END) AS cash_out
                       FROM pos_cash_movements GROUP BY currency ORDER BY currency"""
                ).fetchall()
                base_summary = connection.execute(
                """SELECT SUM(CASE WHEN movement_type IN ('SALE', 'IN') THEN amount * exchange_rate
                                    ELSE -amount * exchange_rate END) AS balance,
                          SUM(CASE WHEN movement_type IN ('SALE', 'IN') THEN amount * exchange_rate ELSE 0 END) AS cash_in,
                          SUM(CASE WHEN movement_type = 'OUT' THEN amount * exchange_rate ELSE 0 END) AS cash_out
                   FROM pos_cash_movements"""
                ).fetchone()
        return jsonify({"entries": [dict(row) for row in rows],
                    "balances": [dict(row) for row in summary],
                    "base_balance": dict(base_summary), "base_currency": base})

    @blueprint.post("/api/pos/cashbook")
    @_require_pos(manager=True)
    def pos_cashbook_entry():
        try:
            data = _parse_json()
            movement_type = str(data.get("movement_type", "")).upper()
            amount = _money(data.get("amount"), "Amount")
            currency = str(data.get("currency", "USD")).upper()
            note = str(data.get("note", "")).strip()[:250]
            if movement_type not in ("IN", "OUT") or amount <= 0 or not note:
                raise ValueError("Choose cash in/out and enter a positive amount and note.")
            with db_lock:
                with _connect() as connection:
                    currency_row = connection.execute(
                        "SELECT rate_to_base FROM pos_currencies WHERE code = ? AND active = 1", (currency,)
                    ).fetchone()
                    if not currency_row:
                        raise ValueError("Choose an enabled currency.")
                    connection.execute(
                        """INSERT INTO pos_cash_movements
                           (cashier_id, movement_type, amount, currency, exchange_rate, note)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (request.pos_cashier["id"], movement_type, amount, currency,
                         currency_row["rate_to_base"], note),
                    )
            return jsonify({"ok": True}), 201
        except ValueError as error:
            return _json_error(str(error))

    @blueprint.get("/api/pos/settings")
    @_require_pos()
    def pos_settings():
        with db_lock:
            with _connect() as connection:
                base = connection.execute(
                    "SELECT value FROM pos_settings WHERE key = 'base_currency'"
                ).fetchone()["value"]
                currencies = [
                    dict(row) for row in connection.execute(
                        "SELECT code, name, rate_to_base, active FROM pos_currencies ORDER BY code"
                    ).fetchall()
                ]
                cashier = _cashier_from_request(connection)
        return jsonify({"base_currency": base, "currencies": currencies,
                        "role": cashier["role"]})

    @blueprint.put("/api/pos/settings")
    @_require_pos(manager=True)
    def pos_update_settings():
        try:
            data = _parse_json()
            base = str(data.get("base_currency", "")).upper()
            rates = data.get("rates", {})
            if not isinstance(rates, dict):
                raise ValueError("Currency rates must be an object.")
            with db_lock:
                with _connect() as connection:
                    codes = {
                        row["code"] for row in connection.execute(
                            "SELECT code FROM pos_currencies WHERE active = 1"
                        ).fetchall()
                    }
                    if base not in codes:
                        raise ValueError("Choose an enabled base currency.")
                    if set(str(code).upper() for code in rates) != codes:
                        raise ValueError("Provide an exchange rate for every enabled currency.")
                    old_base = connection.execute(
                        "SELECT value FROM pos_settings WHERE key = 'base_currency'"
                    ).fetchone()["value"]
                    converted_rates = {}
                    for code, value in rates.items():
                        code = str(code).upper()
                        rate = _finite_number(value, f"Exchange rate for {code}")
                        if code not in codes or rate <= 0:
                            raise ValueError(f"Invalid exchange rate for {code}.")
                        converted_rates[code] = rate
                    if old_base != base:
                        old_base_rate = converted_rates[old_base]
                        connection.execute(
                            """UPDATE pos_products SET price = price * ?, currency = ?,
                               updated_at = CURRENT_TIMESTAMP""",
                            (old_base_rate, base),
                        )
                        connection.execute(
                            "UPDATE pos_invoices SET exchange_rate = exchange_rate * ?",
                            (old_base_rate,),
                        )
                        connection.execute(
                            "UPDATE pos_cash_movements SET exchange_rate = exchange_rate * ?",
                            (old_base_rate,),
                        )
                    for code, rate in converted_rates.items():
                        connection.execute(
                            "UPDATE pos_currencies SET rate_to_base = ? WHERE code = ?",
                            (1 if code == base else rate, code),
                        )
                    connection.execute(
                        "UPDATE pos_settings SET value = ? WHERE key = 'base_currency'", (base,)
                    )
            return jsonify({"ok": True})
        except (ValueError, TypeError) as error:
            return _json_error(str(error))

    @blueprint.get("/api/pos/cashiers")
    @_require_pos(manager=True)
    def pos_cashiers():
        with db_lock:
            with _connect() as connection:
                rows = connection.execute(
                    "SELECT id, username, display_name, role, active, created_at FROM pos_cashiers ORDER BY id"
                ).fetchall()
        return jsonify([dict(row) for row in rows])

    @blueprint.post("/api/pos/cashiers")
    @_require_pos(manager=True)
    def pos_add_cashier():
        try:
            data = _parse_json()
            username = str(data.get("username", "")).strip()
            name = str(data.get("display_name", "")).strip()
            pin = str(data.get("pin", ""))
            role = str(data.get("role", "cashier")).lower()
            if not username or not name or not pin.isdigit() or not 4 <= len(pin) <= 12:
                raise ValueError("Enter a username, display name, and a 4–12 digit PIN.")
            if role not in ("manager", "cashier"):
                raise ValueError("Role must be manager or cashier.")
            salt = secrets.token_hex(16)
            pin_hash = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), 200000).hex()
            with db_lock:
                with _connect() as connection:
                    cursor = connection.execute(
                        """INSERT INTO pos_cashiers
                           (username, display_name, pin_salt, pin_hash, role)
                           VALUES (?, ?, ?, ?, ?)""",
                        (username, name, salt, pin_hash, role),
                    )
                    result = dict(connection.execute(
                        """SELECT id, username, display_name, role, active, created_at
                           FROM pos_cashiers WHERE id = ?""", (cursor.lastrowid,)
                    ).fetchone())
            return jsonify(result), 201
        except ValueError as error:
            return _json_error(str(error))
        except sqlite3.IntegrityError:
            return _json_error("That username is already in use.", 409)

    @blueprint.get("/api/pos/summary")
    @_require_pos()
    def pos_summary():
        with db_lock:
            with _connect() as connection:
                products = connection.execute(
                    "SELECT COUNT(*) AS count, SUM(CASE WHEN stock_qty <= low_stock_threshold AND track_stock = 1 THEN 1 ELSE 0 END) AS low_stock FROM pos_products WHERE active = 1"
                ).fetchone()
                today = datetime.now().strftime("%Y-%m-%d")
                sales = connection.execute(
                    """SELECT currency, SUM(total) AS total, COUNT(*) AS count
                       FROM pos_invoices WHERE substr(created_at, 1, 10) = ?
                       GROUP BY currency ORDER BY currency""", (today,)
                ).fetchall()
                pending = connection.execute(
                    "SELECT COUNT(*) FROM pos_invoices WHERE fiscal_status IN ('pending', 'failed')"
                ).fetchone()[0]
        return jsonify({"product_count": products["count"], "low_stock_count": products["low_stock"] or 0,
                        "today_sales": [dict(row) for row in sales], "pending_fiscalization": pending})

    return blueprint


def _issue_session(cashier_id):
    token = secrets.token_urlsafe(32)
    expires = (datetime.now() + timedelta(hours=12)).isoformat(timespec="seconds")
    with db_lock:
        with _connect() as connection:
            connection.execute("DELETE FROM pos_sessions WHERE expires_at <= ?", (datetime.now().isoformat(),))
            connection.execute(
                "INSERT INTO pos_sessions (token_hash, cashier_id, expires_at) VALUES (?, ?, ?)",
                (hashlib.sha256(token.encode("utf-8")).hexdigest(), cashier_id, expires),
            )
            cashier = connection.execute(
                "SELECT id, username, display_name, role FROM pos_cashiers WHERE id = ?", (cashier_id,)
            ).fetchone()
    return jsonify({"token": token, "expires_at": expires, "cashier": dict(cashier)})


def _finite_number(value, label):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a number.")
    if not math.isfinite(number):
        raise ValueError(f"{label} must be a finite number.")
    return number

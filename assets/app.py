"""
ZIMRA FDMS ANALYTICS TOOL
Main application — Threaded Progress + Verification Link + System Tray + Persistent DB Path Cache
"""

import os
import re
import sys
import json
import sqlite3
import logging
import concurrent.futures
import webbrowser
import threading
import time
import pandas as pd
import requests
import diskcache
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from datetime import datetime
import plotly.express as px
import plotly.graph_objects as go

import dash
from dash import dcc, html, dash_table, Input, Output, State, callback, no_update, ctx
from dash.exceptions import PreventUpdate
import config

# Must exist before startup cache loading can report errors.
logger = logging.getLogger(__name__)

# Try importing system tray libraries
try:
    import pystray
    from PIL import Image, ImageDraw
    TRAY_AVAILABLE = True
except ImportError:
    TRAY_AVAILABLE = False
    print("Warning: pystray and Pillow not installed. System tray will be disabled.")

# ==========================================
# EXE DETECTION & CONFIGURATION
# ==========================================
IS_EXE = getattr(sys, 'frozen', False)
_BROWSER_OPENED = False

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

if sys.stdout is not None and sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

if IS_EXE:
    APP_DIR = os.path.dirname(sys.executable)
    CACHE_DIR = os.path.join(os.environ.get('APPDATA', APP_DIR), 'ZIMRA_FDMS_Cache')
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    CACHE_DIR = os.path.join(APP_DIR, 'dash_cache')

os.makedirs(CACHE_DIR, exist_ok=True)

# ==========================================
# PERSISTENT DB PATH CACHE
# ==========================================
APP_SETTINGS_FILE = os.path.join(CACHE_DIR, 'app_settings.json')

def load_cached_db_path():
    """Load the last used database path from settings file."""
    try:
        if os.path.exists(APP_SETTINGS_FILE):
            with open(APP_SETTINGS_FILE, 'r', encoding='utf-8') as f:
                settings = json.load(f)
                cached_path = settings.get('db_path', '')
                # Verify the cached path still exists
                if cached_path and os.path.exists(cached_path):
                    return cached_path
    except Exception as e:
        logger.warning(f"Could not load cached settings: {e}")
    # Fallback to default from config
    return config.DB_PATH

def save_db_path(db_path):
    """Save the database path to settings file for next startup."""
    try:
        settings = {}
        if os.path.exists(APP_SETTINGS_FILE):
            with open(APP_SETTINGS_FILE, 'r', encoding='utf-8') as f:
                settings = json.load(f)
        
        settings['db_path'] = db_path
        settings['last_updated'] = datetime.now().isoformat()
        
        with open(APP_SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=2)
        
        logger.info(f"Database path saved to cache: {db_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to save database path: {e}")
        return False

# Load cached path on startup
CACHED_DB_PATH = load_cached_db_path()
logger.info(f"Loaded database path: {CACHED_DB_PATH}")

# ==========================================
# SYSTEM TRAY SETUP
# ==========================================
def get_tray_icon_image():
    """Loads the favicon for the tray icon, or creates a fallback."""
    icon_path = os.path.join(APP_DIR, 'assets', 'favicon.ico')
    if os.path.exists(icon_path):
        try:
            img = Image.open(icon_path)
            return img.resize((32, 32), Image.Resampling.LANCZOS)
        except Exception:
            pass
            
    # Fallback: Create a simple green square with a white 'Z'
    img = Image.new('RGB', (32, 32), color=(46, 204, 113))
    draw = ImageDraw.Draw(img)
    draw.text((8, 4), "Z", fill=(255, 255, 255))
    return img

def open_dashboard_action(icon, item):
    webbrowser.open(f"http://{config.APP_HOST}:{config.APP_PORT}")

def exit_action(icon, item):
    icon.stop()
    logger.info("Exiting application from system tray...")
    os._exit(0)

def run_system_tray():
    if not TRAY_AVAILABLE: return
    
    image = get_tray_icon_image()
    menu = pystray.Menu(
        pystray.MenuItem("Open Dashboard", open_dashboard_action, default=True),
        pystray.MenuItem("Status: Running", None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Exit", exit_action)
    )
    
    icon = pystray.Icon("ZIMRA_FDMS", image, "ZIMRA FDMS Analytics Tool - Running", menu)
    icon.run()

# ==========================================
# LOGGING & REQUESTS
# ==========================================
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[logging.StreamHandler(sys.stderr)]
)
logger = logging.getLogger(__name__)

retry_strategy = Retry(total=3, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET"])
adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=50, pool_maxsize=50)
session = requests.Session()
session.mount("http://", adapter)
session.mount("https://", adapter)
session.headers.update({'User-Agent': config.USER_AGENT})

# ==========================================
# DATABASE & HELPERS
# ==========================================
def check_db_connection(db_path):
    try:
        if not db_path or not os.path.exists(db_path): return False, "File not found."
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{config.DB_TABLE}'")
        if not cursor.fetchone():
            conn.close()
            return False, f"Table '{config.DB_TABLE}' not found"
        cursor.execute(f"SELECT COUNT(*) FROM {config.DB_TABLE}")
        row_count = cursor.fetchone()[0]
        conn.close()
        return True, f"Connected — {row_count} records"
    except Exception as e:
        return False, f"Error: {str(e)}"

def get_db_connection(db_path):
    if not os.path.exists(db_path): raise FileNotFoundError(f"Database not found: {db_path}")
    return sqlite3.connect(db_path)

def parse_transaction_date(date_value):
    if pd.isna(date_value): return None
    if isinstance(date_value, (datetime, pd.Timestamp)): return date_value.date() if hasattr(date_value, 'date') else date_value
    date_str = str(date_value).strip()
    for fmt in ['%d/%m/%Y %H:%M:%S', '%d/%m/%Y %H:%M', '%d/%m/%Y', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d']:
        try: return datetime.strptime(date_str, fmt).date()
        except ValueError: continue
    return None

# ==========================================
# WEB SCRAPING & WORKER
# ==========================================
def check_invoice_validity(first_url):
    try:
        response = session.get(first_url, timeout=15, verify=False)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        text = soup.get_text(separator=' ')
        
        is_invoice_valid = "Invoice is valid" in text
        is_credit_note_valid = "Credit note is valid" in text
        has_check_circle = "check-circle" in text
        
        if is_invoice_valid or is_credit_note_valid or has_check_circle:
            web_doc_type = "Credit Note" if is_credit_note_valid else "Invoice"
            form = soup.find('form', action=lambda a: a and '/Receipt/Print' in a)
            if form:
                vid = form.find('input', attrs={'name': 'validationId'})
                vsc = form.find('input', attrs={'name': 'validationSecurityCode'})
                if vid and vsc:
                    print_url = urljoin(first_url, f"/Receipt/Print?validationId={vid.get('value')}&validationSecurityCode={vsc.get('value')}")
                    return "Valid", print_url, "", web_doc_type
            return "Valid", None, "", web_doc_type
        else:
            error_text = "Unknown validation error"
            error_block = soup.find(class_='val-errors-block')
            if error_block:
                errors = [div.get_text(strip=True) for div in error_block.find_all('div', class_='col')]
                error_text = " | ".join(errors) if errors else error_block.get_text(strip=True)
            return "Invalid", None, error_text, "Invoice"
    except requests.exceptions.RequestException as e:
        return "Network Error", None, f"Connection failed: {str(e)}", "Invoice"

def extract_buyer_details_from_page(print_url):
    try:
        response = session.get(print_url, timeout=15, verify=False)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        text = soup.get_text(separator='\n')

        buyer_name, buyer_tin, buyer_vat = 'N/A', 'N/A', 'N/A'
        buyer_match = re.search(r'BUYER\s*\n(.+?)(?=Invoice No:|Fiscal day no:|Device Serial|Code\s+Description)', text, re.DOTALL | re.IGNORECASE)

        if buyer_match:
            block = buyer_match.group(1)
            lines = [line.strip() for line in block.split('\n') if line.strip()]
            if lines: buyer_name = lines[0]
            tin_match = re.search(r'Tin:\s*(\d+)', block, re.IGNORECASE)
            if tin_match: buyer_tin = tin_match.group(1)
            vat_match = re.search(r'VAT No:\s*(\d+)', block, re.IGNORECASE)
            if vat_match: buyer_vat = vat_match.group(1)
        else:
            tin_match = re.search(r'Tin:\s*(\d+)', text, re.IGNORECASE)
            if tin_match: buyer_tin = tin_match.group(1)
            vat_match = re.search(r'VAT No:\s*(\d+)', text, re.IGNORECASE)
            if vat_match: buyer_vat = vat_match.group(1)

        return {'Buyer Name': buyer_name, 'Buyer VAT': buyer_vat, 'Buyer TIN': buyer_tin}
    except Exception:
        return None

def process_single_receipt(row, index):
    first_link = row[config.DB_QRCODE_COLUMN]
    invoice_no = str(row.get('ReceiptGlobalNumber', 'N/A')) if pd.notna(row.get('ReceiptGlobalNumber')) else 'N/A'
    fiscal_day = str(row.get('FiscalDayNumber', 'N/A')) if pd.notna(row.get('FiscalDayNumber')) else 'N/A'
    cust_ref = str(row.get('InvoiceNumber', 'N/A')) if pd.notna(row.get('InvoiceNumber')) else 'N/A'
    
    raw_date = row.get(config.DB_FISCAL_DATE_COLUMN)
    parsed_date = parse_transaction_date(raw_date)
    trans_date_str = parsed_date.isoformat() if parsed_date else str(raw_date)
    
    verification_link = str(first_link)

    if not first_link or not str(first_link).startswith('http'):
        return {'type': 'invalid', 'Invoice No': invoice_no, 'Fiscal Day No': fiscal_day, 
                'Transaction Date': trans_date_str, 'Customer Ref No': cust_ref, 
                'Validation Error': 'Invalid or missing link', 'Link': verification_link}, False

    status, print_link, error_msg, web_doc_type = check_invoice_validity(str(first_link))
    
    if status in ["Invalid", "Network Error"]:
        return {'type': 'invalid', 'Invoice No': invoice_no, 'Fiscal Day No': fiscal_day, 
                'Transaction Date': trans_date_str, 'Customer Ref No': cust_ref, 
                'Validation Error': error_msg, 'Link': verification_link}, False

    db_status = str(row.get('InvoiceStatus', 1)).strip()
    db_doc_type = 'Credit Note' if db_status in ['2', '02'] else 'Invoice'
    final_doc_type = web_doc_type if web_doc_type else db_doc_type

    record = {
        'type': 'valid',
        'Document Type': final_doc_type,
        'Transaction Date': trans_date_str,
        'Fiscal Day No': fiscal_day,
        'Customer Ref No': cust_ref,
        'Invoice No': invoice_no,
        'Buyer Name': 'N/A', 'Buyer VAT': 'N/A', 'Buyer TIN': 'N/A',
        'Total Tax': float(row.get('InvoiceTaxAmount', 0.0)) if pd.notna(row.get('InvoiceTaxAmount')) else 0.0,
        'Currency': str(row.get('Currency', 'USD')) if pd.notna(row.get('Currency')) else 'USD',
        'Total Amount': float(row.get('InvoiceAmount', 0.0)) if pd.notna(row.get('InvoiceAmount')) else 0.0,
        'Verification Link': verification_link 
    }
    
    if final_doc_type == 'Credit Note':
        if record['Total Amount'] > 0: record['Total Amount'] = -abs(record['Total Amount'])
        if record['Total Tax'] > 0: record['Total Tax'] = -abs(record['Total Tax'])

    try:
        if print_link:
            buyer_info = extract_buyer_details_from_page(print_link)
            if buyer_info:
                record['Buyer Name'] = buyer_info.get('Buyer Name', 'N/A')
                record['Buyer VAT'] = buyer_info.get('Buyer VAT', 'N/A')
                record['Buyer TIN'] = buyer_info.get('Buyer TIN', 'N/A')
        return record, True
    except Exception as e:
        logger.error(f"Row {index} failed: {e}")
        return record, True

# ==========================================
# THREADING PROGRESS SYSTEM
# ==========================================
FETCH_STATE = {'running': False, 'percent': 0, 'message': '', 'data': None}

def run_fetch_task(start_date, end_date, db_path):
    global FETCH_STATE
    try:
        FETCH_STATE = {'running': True, 'percent': 0, 'message': 'Connecting to database...', 'data': None}
        db_ok, db_msg = check_db_connection(db_path)
        if not db_ok:
            FETCH_STATE['message'] = f"DB Error: {db_msg}"; FETCH_STATE['running'] = False; return

        conn = get_db_connection(db_path)
        query = f"""SELECT {config.DB_QRCODE_COLUMN}, {config.DB_FISCAL_DATE_COLUMN}, FiscalDayNumber, ReceiptGlobalNumber, InvoiceNumber, InvoiceStatus, InvoiceTaxAmount, InvoiceAmount, Currency
                    FROM {config.DB_TABLE} WHERE {config.DB_FISCAL_DATE_COLUMN} BETWEEN ? AND ?"""
        df_db = pd.read_sql_query(query, conn, params=(start_date, end_date))
        conn.close()

        if df_db.empty:
            FETCH_STATE['message'] = "No transactions found."; FETCH_STATE['running'] = False; return

        total_receipts = len(df_db)
        valid_records, invalid_records = [], []
        FETCH_STATE['message'] = f"Processing 0/{total_receipts}..."
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
            future_to_index = {executor.submit(process_single_receipt, row, index): index for index, row in df_db.iterrows()}
            for future in concurrent.futures.as_completed(future_to_index):
                index = future_to_index[future]
                try:
                    record, _ = future.result()
                    if record.get('type') == 'invalid': invalid_records.append(record)
                    else: valid_records.append(record)
                    
                    completed = len(valid_records) + len(invalid_records)
                    if completed % 5 == 0 or completed == total_receipts:
                        pct = int((completed / total_receipts) * 100)
                        FETCH_STATE['percent'] = pct
                        FETCH_STATE['message'] = f"Processed {completed}/{total_receipts} ({pct}%)"
                except Exception as exc: logger.error(f"Row {index}: {exc}")

        FETCH_STATE['data'] = {'valid': pd.DataFrame(valid_records).to_dict('records'), 'invalid': pd.DataFrame(invalid_records).to_dict('records')}
        FETCH_STATE['message'] = "Complete!"; FETCH_STATE['percent'] = 100
    except Exception as e:
        logger.error(f"Fetch task failed: {e}"); FETCH_STATE['message'] = f"Error: {str(e)}"
    finally:
        FETCH_STATE['running'] = False

# ==========================================
# VISUALIZATION
# ==========================================
def format_currency_totals(df, column_name):
    if df.empty: return "0.00"
    grouped = df.groupby('Currency')[column_name].sum()
    parts = [f"{cur}: {val:,.2f}" for cur, val in grouped.items() if pd.notna(val)]
    return " | ".join(parts) if parts else "0.00"

def create_kpi_cards(df, invalid_count=0):
    if df.empty and invalid_count == 0: return [html.P("No data.", style={'textAlign': 'center', 'fontSize': '13px'})]
    total_docs = len(df)
    credit_notes = len(df[df['Document Type'] == 'Credit Note']) if not df.empty else 0
    total_revenue_str = format_currency_totals(df, 'Total Amount')
    total_tax_str = format_currency_totals(df, 'Total Tax')

    card = {'padding': '10px 12px', 'borderRadius': '8px', 'textAlign': 'center'}
    icon = {'fontSize': '20px', 'marginBottom': '4px'}
    val = {'margin': '4px 0', 'fontSize': '18px', 'fontWeight': 'bold'}
    lbl = {'margin': '0', 'fontSize': '10px', 'opacity': '0.9'}

    cards = [
        html.Div(style={**card, 'backgroundColor': config.COLORS['primary'], 'color': 'white'}, children=[html.I(className="fas fa-file-invoice", style=icon), html.H3(f"{total_docs:,}", style=val), html.P("Valid Docs", style=lbl)]),
        html.Div(style={**card, 'backgroundColor': config.COLORS['success'], 'color': 'white'}, children=[html.I(className="fas fa-dollar-sign", style=icon), html.H3(total_revenue_str, style={**val, 'fontSize': '14px'}), html.P("Total Amount", style=lbl)]),
        html.Div(style={**card, 'backgroundColor': config.COLORS['warning'], 'color': 'white'}, children=[html.I(className="fas fa-percentage", style=icon), html.H3(total_tax_str, style={**val, 'fontSize': '14px'}), html.P("Total Tax", style=lbl)])
    ]
    if invalid_count > 0:
        cards.append(html.Div(style={**card, 'backgroundColor': config.COLORS['danger'], 'color': 'white'}, children=[html.I(className="fas fa-exclamation-triangle", style=icon), html.H3(f"{invalid_count}", style=val), html.P("Invalid/Errors", style=lbl)]))
    else:
        cards.append(html.Div(style={**card, 'backgroundColor': config.COLORS['danger'], 'color': 'white'}, children=[html.I(className="fas fa-undo", style=icon), html.H3(f"{credit_notes}", style=val), html.P("Credit Notes", style=lbl)]))
    return cards

def create_revenue_trend_chart(df):
    if df.empty or 'Transaction Date' not in df.columns: return go.Figure()
    df_copy = df.copy()
    df_copy['Date Only'] = pd.to_datetime(df_copy['Transaction Date'], errors='coerce')
    df_copy = df_copy.dropna(subset=['Date Only'])
    if df_copy.empty: return go.Figure()
    
    has_multi = 'Currency' in df_copy.columns and df_copy['Currency'].nunique() > 1
    if has_multi:
        daily = df_copy.groupby(['Date Only', 'Currency'])['Total Amount'].sum().reset_index()
        fig = px.area(daily, x='Date Only', y='Total Amount', color='Currency', title='Daily Revenue by Currency')
    else:
        daily = df_copy.groupby('Date Only')['Total Amount'].sum().reset_index()
        fig = px.area(daily, x='Date Only', y='Total Amount', title='Daily Revenue', color_discrete_sequence=[config.COLORS['primary']])
        
    fig.update_traces(line=dict(shape='spline', width=2), hovertemplate="Date: %{x}<br>Amount: %{y:.2f}<extra></extra>")
    fig.update_xaxes(type='date', tickformat='%d/%m/%Y', tickangle=-45, tickmode='auto', nticks=10)
    fig.update_layout(hovermode='x unified', plot_bgcolor=config.CHART_BG_COLOR, margin=dict(t=40, b=60, l=40, r=40))
    return fig

def create_document_type_pie(df):
    if df.empty or 'Document Type' not in df.columns: return go.Figure()
    type_counts = df['Document Type'].value_counts().reset_index()
    type_counts.columns = ['Document Type', 'Count']
    max_idx = type_counts['Count'].idxmax()
    pull = [0.05 if i == max_idx else 0 for i in range(len(type_counts))]
    fig = px.pie(type_counts, values='Count', names='Document Type', title='Document Type Distribution',
                 color='Document Type', color_discrete_map={'Invoice': config.COLORS['primary'], 'Credit Note': config.COLORS['danger']}, hole=0.5)
    fig.update_traces(pull=pull, textposition='inside', textinfo='percent+label', hovertemplate="%{label}: %{value} (%{percent})<extra></extra>")
    fig.update_layout(margin=dict(t=40, b=40, l=40, r=40))
    return fig

def create_top_buyers_chart(df, metric="amount"):
    if df.empty or 'Buyer Name' not in df.columns: return go.Figure()
    df_valid = df[df['Buyer Name'] != 'N/A']
    if df_valid.empty: return go.Figure()
    
    if metric == "frequency":
        buyer_stats = df_valid.groupby('Buyer Name').size().reset_index(name='Count')
        buyer_stats = buyer_stats.sort_values('Count', ascending=False).head(config.TOP_N_ITEMS)
        fig = px.bar(buyer_stats, x='Buyer Name', y='Count', title=f'Top {config.TOP_N_ITEMS} Buyers by Frequency', color='Count', color_continuous_scale='Blues')
        y_title = "Number of Invoices"
        hover = "Buyer: %{x}<br>Invoices: %{y}<extra></extra>"
    else:
        buyer_stats = df_valid.groupby('Buyer Name')['Total Amount'].sum().reset_index()
        buyer_stats = buyer_stats.sort_values('Total Amount', ascending=False).head(config.TOP_N_ITEMS)
        fig = px.bar(buyer_stats, x='Buyer Name', y='Total Amount', title=f'Top {config.TOP_N_ITEMS} Buyers by Amount', color='Total Amount', color_continuous_scale='Blues')
        y_title = "Total Amount"
        hover = "Buyer: %{x}<br>Amount: $%{y:,.2f}<extra></extra>"
        
    fig.update_traces(hovertemplate=hover)
    fig.update_layout(
        showlegend=False, xaxis_tickangle=-45, 
        plot_bgcolor='#FFFDD0', paper_bgcolor='#FFFDD0',
        margin=dict(t=40, b=80, l=40, r=40), yaxis_title=y_title,
        xaxis=dict(tickfont=dict(size=10))
    )
    return fig

def create_daily_tax_bar_chart(df):
    if df.empty or 'Transaction Date' not in df.columns: return go.Figure()
    df_copy = df.copy()
    df_copy['Date Only'] = pd.to_datetime(df_copy['Transaction Date'], errors='coerce')
    df_copy = df_copy.dropna(subset=['Date Only'])
    if df_copy.empty: return go.Figure()
    
    has_multi = 'Currency' in df_copy.columns and df_copy['Currency'].nunique() > 1
    if has_multi:
        daily = df_copy.groupby(['Date Only', 'Currency'])['Total Tax'].sum().reset_index()
        fig = px.bar(daily, x='Date Only', y='Total Tax', color='Currency', title='Daily Tax by Currency', barmode='group')
    else:
        daily = df_copy.groupby('Date Only')['Total Tax'].sum().reset_index()
        fig = px.bar(daily, x='Date Only', y='Total Tax', title='Daily Tax Collected', color_discrete_sequence=[config.COLORS['warning']])
        
    fig.update_traces(hovertemplate="Date: %{x}<br>Tax: %{y:.2f}<extra></extra>")
    fig.update_xaxes(type='date', tickformat='%d/%m/%Y', tickangle=-45, tickmode='auto', nticks=10)
    fig.update_layout(plot_bgcolor=config.CHART_BG_COLOR, margin=dict(t=40, b=60, l=40, r=40))
    return fig

# ==========================================
# DASH APP LAYOUT
# ==========================================
app = dash.Dash(__name__, suppress_callback_exceptions=True, external_stylesheets=['https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css'])
app.title = config.APP_TITLE

db_connected, db_message = check_db_connection(CACHED_DB_PATH)
if db_connected: logger.info(f"Database: {db_message}")
else: logger.error(f"Database: {db_message}")

PROGRESS_BAR_BASE_STYLE = {"backgroundColor": config.COLORS['primary'], "height": "100%", "borderRadius": "10px", "transition": "width 0.3s ease"}
CARD_STYLE = {'backgroundColor': 'white', 'padding': '12px 14px', 'borderRadius': '8px', 'boxShadow': '0 2px 4px rgba(0,0,0,0.08)', 'height': '100%', 'boxSizing': 'border-box'}
CARD_HEADER = {'marginTop': '0', 'marginBottom': '8px', 'fontSize': '13px', 'fontWeight': '600', 'color': config.COLORS['dark'], 'display': 'flex', 'alignItems': 'center', 'gap': '8px'}
INPUT_STYLE = {'padding': '6px 8px', 'border': '1px solid #ccc', 'borderRadius': '4px', 'fontSize': '12px', 'width': '100%', 'boxSizing': 'border-box'}
BTN_STYLE = {'padding': '6px 12px', 'border': 'none', 'borderRadius': '4px', 'cursor': 'pointer', 'fontSize': '12px', 'fontWeight': '600', 'color': 'white'}

app.layout = html.Div(style={'fontFamily': 'Arial, sans-serif', 'backgroundColor': config.COLORS['light'], 'padding': '20px', 'minHeight': '100vh'}, children=[

    # LIGHT SPLASH SCREEN
    html.Div(id="splash-screen", style={"position": "fixed", "top": 0, "left": 0, "width": "100%", "height": "100%", "backgroundColor": config.COLORS['light'], "zIndex": 9999, "display": "flex", "flexDirection": "column", "justifyContent": "center", "alignItems": "center", "transition": "opacity 0.5s ease"}, children=[
        html.Img(src="assets/company_logo.png", className="splash-logo", style={"height": "120px", "width": "auto", "objectFit": "contain", "marginBottom": "20px"}),
        html.H2("ZIMRA FDMS ANALYTICS TOOL", style={"color": config.COLORS['dark'], "margin": "0", "fontSize": "24px", "fontWeight": "600"}),
        html.P("Initializing Dashboard...", style={"color": "#666", "marginTop": "10px", "fontSize": "14px"})
    ]),
    dcc.Interval(id="splash-interval", interval=2500, max_intervals=1),

    html.Div(style={'backgroundColor': config.COLORS['dark'], 'color': 'white', 'padding': '12px 25px', 'borderRadius': '8px', 'marginBottom': '20px', 'display': 'flex', 'alignItems': 'center', 'justifyContent': 'space-between', 'boxShadow': '0 2px 8px rgba(0,0,0,0.15)'}, children=[
        html.Div(style={'display': 'flex', 'alignItems': 'center', 'gap': '15px'}, children=[
            html.Img(src='assets/company_logo.png', style={'height': '35px', 'width': 'auto', 'objectFit': 'contain'}),
            html.H1("ZIMRA FDMS ANALYTICS TOOL", style={'margin': '0', 'fontSize': '18px', 'fontWeight': '600', 'letterSpacing': '0.5px'}),
        ]),
        html.Div(style={'fontSize': '11px', 'opacity': '0.8', 'textAlign': 'right', 'lineHeight': '1.4'}, children=[
            html.Div("Fiscal Device Management System", style={'fontWeight': 'bold'}),
            html.Div("Invoice & Receipt Analytics")
        ])
    ]),

    html.Div(style={'display': 'grid', 'gridTemplateColumns': 'repeat(4, 1fr)', 'gap': '15px', 'marginBottom': '20px'}, children=[
        html.Div(style={**CARD_STYLE, 'borderTop': f"4px solid {config.COLORS['primary']}"}, children=[
            html.H4(children=[html.I(className="fas fa-info-circle", style={'color': config.COLORS['primary']}), " App Details"], style=CARD_HEADER),
            html.Div(style={'fontSize': '11px', 'color': '#555', 'lineHeight': '1.6'}, children=[
                html.Div([html.Strong("Version: "), "2.8.0 (Cached DB)"]),
                html.Div([html.Strong("Status: "), html.Span("Running in System Tray", style={'color': config.COLORS['success'], 'fontWeight': 'bold'})]),
            ])
        ]),
        html.Div(style={**CARD_STYLE, 'borderTop': f"4px solid {config.COLORS['success']}"}, children=[
            html.H4(children=[html.I(className="fas fa-database", style={'color': config.COLORS['success']}), " Database"], style=CARD_HEADER),
            html.Div(style={'fontSize': '10px', 'color': '#666', 'marginBottom': '6px', 'lineHeight': '1.4'}, children=["📌 ", html.I("Right-click RevDB.db → 'Copy as path' → Paste below. Path is saved for next time.")]),
            dcc.Input(id='db-path-input', type='text', value=CACHED_DB_PATH, style={**INPUT_STYLE, 'fontFamily': 'monospace', 'fontSize': '11px'}, placeholder='e.g., C:\\ProgramData\\...\\RevDB.db'),
            html.Button('Connect & Verify', id='connect-db-btn', n_clicks=0, style={**BTN_STYLE, 'backgroundColor': config.COLORS['success'], 'width': '100%', 'marginTop': '8px'}),
            html.Div(id='db-status-msg', children=db_message, style={'marginTop': '6px', 'fontSize': '11px', 'color': '#155724' if db_connected else '#721c24', 'fontWeight': 'bold'})
        ]),
        html.Div(style={**CARD_STYLE, 'borderTop': f"4px solid {config.COLORS['warning']}"}, children=[
            html.H4(children=[html.I(className="fas fa-calendar-alt", style={'color': config.COLORS['warning']}), " Date Range"], style=CARD_HEADER),
            dcc.DatePickerRange(id='date-picker-range', start_date_placeholder_text='Start', end_date_placeholder_text='End', display_format='YYYY-MM-DD', style={'fontSize': '12px'}),
            html.Button(children=[html.I(className="fas fa-search", style={'marginRight': '6px'}), "Fetch Data"], id='fetch-button', n_clicks=0, style={**BTN_STYLE, 'backgroundColor': config.COLORS['warning'], 'width': '100%', 'marginTop': '8px'})
        ]),
        html.Div(id="dashboard-controls", style={**CARD_STYLE, 'borderTop': f"4px solid {config.COLORS['info']}"}, children=[
            html.H4(children=[html.I(className="fas fa-sliders-h", style={'color': config.COLORS['info']}), " Filters & Export"], style=CARD_HEADER),
            html.Label("Currency:", style={'fontSize': '11px', 'fontWeight': 'bold', 'marginBottom': '4px', 'display': 'block'}),
            dcc.Dropdown(id="currency-filter", options=[{"label": "ALL", "value": "ALL"}], value="ALL", style={'fontSize': '12px'}),
            html.Div(style={'display': 'flex', 'gap': '6px', 'marginTop': '8px'}, children=[
                html.Button(id="btn-download-valid", children=[html.I(className="fas fa-download", style={'marginRight': '4px'}), "Valid CSV"], style={**BTN_STYLE, 'backgroundColor': config.COLORS['success'], 'flex': '1'}),
                html.Button(id="btn-download-invalid", children=[html.I(className="fas fa-exclamation-triangle", style={'marginRight': '4px'}), "Invalid CSV"], style={**BTN_STYLE, 'backgroundColor': config.COLORS['danger'], 'flex': '1'}),
            ]),
            dcc.Download(id="download-valid-csv"), dcc.Download(id="download-invalid-csv")
        ]),
    ]),

    html.Div(id="progress-container", style={"display": "none", "marginBottom": "15px"}, children=[
        html.Div(style={"backgroundColor": "white", "padding": "10px 14px", "borderRadius": "8px", "boxShadow": "0 2px 4px rgba(0,0,0,0.08)"}, children=[
            html.Div(id="progress-text", children="Initializing...", style={"marginBottom": "4px", "fontSize": "12px", "fontWeight": "bold"}),
            html.Div(style={"backgroundColor": "#e9ecef", "borderRadius": "10px", "height": "12px", "overflow": "hidden"}, children=[
                html.Div(id="progress-bar", style={**PROGRESS_BAR_BASE_STYLE, "width": "0%"})
            ])
        ])
    ]),
    dcc.Interval(id="progress-poller", interval=500, n_intervals=0),

    html.Div(id="kpi-cards-area", style={'marginBottom': '20px'}),

    html.Div(id="charts-area", style={"display": "none", "marginBottom": "20px"}, children=[
        html.Div(style={'display': 'grid', 'gridTemplateColumns': 'repeat(auto-fit, minmax(500px, 1fr))', 'gap': '15px', 'marginBottom': '15px'}, children=[
            html.Div(style={'backgroundColor': 'white', 'padding': '15px', 'borderRadius': '8px', 'boxShadow': '0 2px 4px rgba(0,0,0,0.08)'}, children=[
                html.H5("Revenue Trend", style={'color': config.COLORS['dark'], 'marginTop': '0', 'fontSize': '14px'}),
                dcc.Graph(id="revenue-trend-graph", figure=go.Figure(), style={'height': '350px'})
            ]),
            html.Div(style={'backgroundColor': 'white', 'padding': '15px', 'borderRadius': '8px', 'boxShadow': '0 2px 4px rgba(0,0,0,0.08)'}, children=[
                html.H5("Document Types", style={'color': config.COLORS['dark'], 'marginTop': '0', 'fontSize': '14px'}),
                dcc.Graph(id="doc-type-pie-graph", figure=go.Figure(), style={'height': '350px'})
            ]),
        ]),
        html.Div(style={'display': 'grid', 'gridTemplateColumns': 'repeat(auto-fit, minmax(500px, 1fr))', 'gap': '15px', 'marginBottom': '15px'}, children=[
            html.Div(style={'backgroundColor': 'white', 'padding': '15px', 'borderRadius': '8px', 'boxShadow': '0 2px 4px rgba(0,0,0,0.08)'}, children=[
                html.Div(style={'display': 'flex', 'justifyContent': 'space-between', 'alignItems': 'center', 'marginBottom': '10px'}, children=[
                    html.H5("Top Buyers", style={'color': config.COLORS['dark'], 'margin': '0', 'fontSize': '14px'}),
                    dcc.RadioItems(id="top-buyers-metric", options=[{"label": " By Amount", "value": "amount"}, {"label": " By Frequency", "value": "frequency"}], value="amount", labelStyle={"display": "inline-block", "marginRight": "15px", "fontSize": "12px", "cursor": "pointer", "color": "#555"}, inputStyle={"marginRight": "5px", "cursor": "pointer"})
                ]),
                dcc.Graph(id="top-buyers-graph", figure=go.Figure(), style={'height': '500px'})
            ]),
            html.Div(style={'backgroundColor': 'white', 'padding': '15px', 'borderRadius': '8px', 'boxShadow': '0 2px 4px rgba(0,0,0,0.08)'}, children=[
                html.H5("Daily Tax", style={'color': config.COLORS['dark'], 'marginTop': '0', 'fontSize': '14px'}),
                dcc.Graph(id="daily-tax-graph", figure=go.Figure(), style={'height': '350px'})
            ]),
        ]),
    ]),

    html.Div(id="tables-area", style={'marginBottom': '20px'}),
    dcc.Store(id="store-raw-data"), dcc.Store(id="filtered-store"), dcc.Store(id="active-db-path", data=CACHED_DB_PATH),
    html.Div(style={'textAlign': 'center', 'padding': '15px', 'color': '#7f8c8d', 'fontSize': '11px'}, children=[html.P("© 2026 ZIMRA FDMS Analytics Tool — Dapsoft Solutions")])
])

# ==========================================
# CALLBACKS
# ==========================================
@callback(Output("splash-screen", "style"), Input("splash-interval", "n_intervals"))
def hide_splash(n_intervals):
    if n_intervals == 1: return {"display": "none"}
    return {"position": "fixed", "top": 0, "left": 0, "width": "100%", "height": "100%", "backgroundColor": config.COLORS['light'], "zIndex": 9999, "display": "flex", "flexDirection": "column", "justifyContent": "center", "alignItems": "center"}

@callback(Output('db-status-msg', 'children'), Output('db-status-msg', 'style'), Output('active-db-path', 'data'), Input('connect-db-btn', 'n_clicks'), State('db-path-input', 'value'), prevent_initial_call=True)
def connect_database(n_clicks, db_path):
    if not db_path: return "Enter a path.", {'color': '#721c24', 'marginTop': '6px', 'fontSize': '11px'}, no_update
    connected, message = check_db_connection(db_path)
    style = {'marginTop': '6px', 'fontSize': '11px', 'color': '#155724' if connected else '#721c24', 'fontWeight': 'bold'}
    
    # Save the path to cache if connection is successful
    if connected:
        save_db_path(db_path)
        logger.info(f"Database path cached successfully: {db_path}")
    
    return message, style, db_path if connected else no_update

@callback(Output('progress-container', 'style'), Output('progress-bar', 'style'), Output('progress-text', 'children'), Output('store-raw-data', 'data'),
          Input('fetch-button', 'n_clicks'), Input('progress-poller', 'n_intervals'), State('date-picker-range', 'start_date'), State('date-picker-range', 'end_date'), State('active-db-path', 'data'), prevent_initial_call=True)
def handle_fetch_and_progress(n_clicks, n_intervals, start_date, end_date, db_path):
    triggered_id = ctx.triggered_id
    if triggered_id == 'fetch-button':
        if not start_date or not end_date: return {"display": "block"}, {**PROGRESS_BAR_BASE_STYLE, "width": "0%"}, "Please select a date range.", no_update
        if not db_path: return {"display": "block"}, {**PROGRESS_BAR_BASE_STYLE, "width": "0%"}, "Please connect to a database first.", no_update
        if FETCH_STATE['running']: raise PreventUpdate
        threading.Thread(target=run_fetch_task, args=(start_date, end_date, db_path), daemon=True).start()
        return {"display": "block"}, {**PROGRESS_BAR_BASE_STYLE, "width": "0%"}, "Starting thread...", no_update

    if triggered_id == 'progress-poller':
        if FETCH_STATE['running']: return {"display": "block"}, {**PROGRESS_BAR_BASE_STYLE, "width": f"{FETCH_STATE['percent']}%"}, FETCH_STATE['message'], no_update
        elif FETCH_STATE['data'] is not None:
            data = FETCH_STATE['data']; FETCH_STATE['data'] = None
            return {"display": "none"}, {**PROGRESS_BAR_BASE_STYLE, "width": "100%"}, "Complete!", data
        else: raise PreventUpdate
    raise PreventUpdate

@callback(Output("currency-filter", "options"), Input("store-raw-data", "data"), prevent_initial_call=True)
def update_currency_options(raw_data):
    if not raw_data: return [{"label": "ALL", "value": "ALL"}]
    df_valid = pd.DataFrame(raw_data.get('valid', []))
    if df_valid.empty: return [{"label": "ALL", "value": "ALL"}]
    currencies = sorted(df_valid['Currency'].dropna().unique().tolist())
    options = [{"label": c, "value": c} for c in currencies]
    options.insert(0, {"label": "ALL", "value": "ALL"})
    return options

@callback(Output("filtered-store", "data"), Input("store-raw-data", "data"), Input("currency-filter", "value"), prevent_initial_call=True)
def update_filtered_store(raw_data, selected_currency):
    if not raw_data: raise PreventUpdate
    df_valid = pd.DataFrame(raw_data.get('valid', []))
    df_invalid = pd.DataFrame(raw_data.get('invalid', []))
    if selected_currency and selected_currency != "ALL": df_valid = df_valid[df_valid['Currency'] == selected_currency].copy()
    return {'valid': df_valid.to_dict('records'), 'invalid': df_invalid.to_dict('records')}

@callback(Output("kpi-cards-area", "children"), Input("filtered-store", "data"), prevent_initial_call=True)
def update_kpi_cards(filtered_data):
    if not filtered_data: return html.Div(style={'textAlign': 'center', 'padding': '40px', 'color': '#7f8c8d'}, children=[html.I(className="fas fa-hand-pointer", style={'fontSize': '48px', 'marginBottom': '15px', 'color': config.COLORS['primary']}), html.H2("Welcome"), html.P("Select a date range and click Fetch Data.")])
    df_valid = pd.DataFrame(filtered_data.get('valid', []))
    df_invalid = pd.DataFrame(filtered_data.get('invalid', []))
    return html.Div(style={'display': 'grid', 'gridTemplateColumns': 'repeat(auto-fit, minmax(180px, 1fr))', 'gap': '10px'}, children=create_kpi_cards(df_valid, len(df_invalid)))

@callback(Output("charts-area", "style"), Output("revenue-trend-graph", "figure"), Output("doc-type-pie-graph", "figure"), Output("top-buyers-graph", "figure"), Output("daily-tax-graph", "figure"),
          Input("filtered-store", "data"), Input("top-buyers-metric", "value"), prevent_initial_call=True)
def update_all_charts(filtered_data, top_buyers_metric):
    if not filtered_data: return {"display": "none"}, go.Figure(), go.Figure(), go.Figure(), go.Figure()
    df_valid = pd.DataFrame(filtered_data.get('valid', []))
    return ({"display": "block", "marginBottom": "20px"}, create_revenue_trend_chart(df_valid), create_document_type_pie(df_valid), create_top_buyers_chart(df_valid, metric=top_buyers_metric if top_buyers_metric else "amount"), create_daily_tax_bar_chart(df_valid))

@callback(Output("tables-area", "children"), Input("filtered-store", "data"), prevent_initial_call=True)
def update_tables(filtered_data):
    if not filtered_data: return ""
    df_valid = pd.DataFrame(filtered_data.get('valid', []))
    df_invalid = pd.DataFrame(filtered_data.get('invalid', []))
    content = []

    if not df_valid.empty:
        total_tax = df_valid['Total Tax'].sum()
        total_amount = df_valid['Total Amount'].sum()
        total_count = len(df_valid)
        totals_row = {'Document Type': 'TOTALS', 'Invoice No': f"{total_count} Records", 'Total Tax': round(total_tax, 2), 'Total Amount': round(total_amount, 2)}
        df_table = pd.concat([df_valid, pd.DataFrame([totals_row])], ignore_index=True)
        
        table_columns = ['Document Type', 'Transaction Date', 'Fiscal Day No', 'Customer Ref No', 'Invoice No', 'Buyer Name', 'Buyer VAT', 'Buyer TIN', 'Total Tax', 'Currency', 'Total Amount', 'Verification Link']
        
        content.append(html.Div(style={'backgroundColor': 'white', 'padding': '15px', 'borderRadius': '8px', 'boxShadow': '0 2px 4px rgba(0,0,0,0.08)', 'marginBottom': '20px'}, children=[
            html.H5(f"✅ Valid Invoice Data ({total_count} records)", style={'color': config.COLORS['success'], 'marginTop': '0', 'fontSize': '14px'}),
            dash_table.DataTable(id='results-table', 
                                 columns=[{"name": i, "id": i, "presentation": "markdown" if i == 'Verification Link' else "input"} for i in table_columns if i in df_table.columns], 
                                 data=df_table[table_columns].to_dict('records'), 
                                 page_size=15, filter_action="native", sort_action="native", 
                                 style_table={'overflowX': 'auto'}, 
                                 style_cell={'fontSize': '12px', 'padding': '8px'}, 
                                 style_header={'backgroundColor': config.COLORS['success'], 'color': 'white', 'fontWeight': 'bold'})
        ]))
        
    if not df_invalid.empty:
        invalid_count = len(df_invalid)
        content.append(html.Div(style={'backgroundColor': 'white', 'padding': '15px', 'borderRadius': '8px', 'boxShadow': '0 2px 4px rgba(0,0,0,0.08)', 'border': '1px solid #f5c6cb'}, children=[
            html.H5(f"⚠️ Invalid / Network Error Invoices ({invalid_count} records)", style={'color': config.COLORS['danger'], 'marginTop': '0', 'fontSize': '14px'}),
            html.P("These invoices failed validation or experienced connection errors.", style={'fontSize': '12px', 'color': '#721c24', 'marginBottom': '10px'}),
            dash_table.DataTable(id='invalid-results-table', columns=[{"name": "Invoice No", "id": "Invoice No"}, {"name": "Fiscal Day", "id": "Fiscal Day No"}, {"name": "Trans. Date", "id": "Transaction Date"}, {"name": "Cust. Ref", "id": "Customer Ref No"}, {"name": "Validation Error", "id": "Validation Error"}, {"name": "Link", "id": "Link"}], data=df_invalid[['Invoice No', 'Fiscal Day No', 'Transaction Date', 'Customer Ref No', 'Validation Error', 'Link']].to_dict('records'), page_size=10, filter_action="native", sort_action="native", style_table={'overflowX': 'auto'}, style_cell={'fontSize': '12px', 'padding': '8px', 'whiteSpace': 'normal'}, style_header={'backgroundColor': config.COLORS['danger'], 'color': 'white', 'fontWeight': 'bold'})
        ]))
    return html.Div(content) if content else ""

@callback(Output("download-valid-csv", "data"), Input("btn-download-valid", "n_clicks"), State("filtered-store", "data"), prevent_initial_call=True)
def download_valid_csv(n_clicks, filtered_data):
    if not filtered_data: raise PreventUpdate
    df = pd.DataFrame(filtered_data['valid'])
    if df.empty: raise PreventUpdate
    
    totals_row = {'Document Type': 'TOTALS', 'Total Tax': round(df['Total Tax'].sum(), 2), 'Total Amount': round(df['Total Amount'].sum(), 2)}
    df_csv = pd.concat([df, pd.DataFrame([totals_row])], ignore_index=True)
    
    if 'Verification Link' not in df_csv.columns and 'Link' in df_csv.columns:
        df_csv['Verification Link'] = df_csv['Link']
        
    return dcc.send_data_frame(df_csv.to_csv, "valid_invoices.csv", index=False)

@callback(Output("download-invalid-csv", "data"), Input("btn-download-invalid", "n_clicks"), State("filtered-store", "data"), prevent_initial_call=True)
def download_invalid_csv(n_clicks, filtered_data):
    if not filtered_data: raise PreventUpdate
    df_invalid = pd.DataFrame(filtered_data.get('invalid', []))
    if df_invalid.empty: raise PreventUpdate
    cols = ['Invoice No', 'Fiscal Day No', 'Transaction Date', 'Customer Ref No', 'Validation Error', 'Link']
    cols = [c for c in cols if c in df_invalid.columns]
    return dcc.send_data_frame(df_invalid[cols].to_csv, "invalid_invoices.csv", index=False)

# ==========================================
# RUN APPLICATION WITH SYSTEM TRAY
# ==========================================
if __name__ == '__main__':
    logger.info(f"Starting {config.APP_TITLE}...")
    logger.info(f"Dashboard: http://{config.APP_HOST}:{config.APP_PORT}")
    logger.info(f"Settings file: {APP_SETTINGS_FILE}")
    
    if TRAY_AVAILABLE:
        tray_thread = threading.Thread(target=run_system_tray, daemon=True)
        tray_thread.start()
        logger.info("System tray icon initialized.")
    else:
        logger.warning("System tray disabled (install pystray and Pillow to enable).")
        if not IS_EXE:
            threading.Timer(1.5, lambda: webbrowser.open(f"http://{config.APP_HOST}:{config.APP_PORT}")).start()

    app.run(host=config.APP_HOST, port=config.APP_PORT, debug=False)
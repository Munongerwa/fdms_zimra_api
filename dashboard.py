import dash
from dash import html, dcc, Input, Output, State, callback, ctx
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import requests
import json
from collections import defaultdict
from datetime import datetime, timedelta

API_BASE = "http://localhost:5000"

app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP, dbc.icons.FONT_AWESOME],
    suppress_callback_exceptions=True,
    assets_folder='assets'
)
app.title = "FISCALINK"

COLORS = {
    "primary": "#0d6efd", "info": "#0dcaf0", "dark": "#1a1a2e", "darker": "#16213e",
    "sidebar": "#0f0f1e", "sidebar_hover": "#1e1e3f", "light": "#f8f9fa",
    "success": "#198754", "danger": "#dc3545", "warning": "#ffc107",
    "text_muted": "#6c757d", "border": "#2a2a4a"
}

SIDEBAR_WIDTH_EXPANDED = "250px"
SIDEBAR_WIDTH_COLLAPSED = "70px"

app.layout = html.Div([
    html.Div(
        id="splash-screen",
        children=[
            html.Div(children=[
                html.Img(src="assets/logo.png", style={"width": "200px", "height": "200px", "objectFit": "contain", "marginBottom": "30px", "animation": "pulse 2s infinite"}),
                html.H2("FISCALINK", style={"color": COLORS["primary"], "fontWeight": "bold", "fontSize": "36px", "marginBottom": "20px"}),
                html.P("Initializing System...", style={"color": "#888", "fontSize": "16px", "marginBottom": "30px"}),
                html.Div(dbc.Spinner(size="lg", color="primary"), style={"display": "flex", "justifyContent": "center", "alignItems": "center"})
            ], style={"display": "flex", "flexDirection": "column", "justifyContent": "center", "alignItems": "center", "textAlign": "center", "width": "100%", "height": "100%"})
        ],
        style={"position": "fixed", "top": 0, "left": 0, "width": "100vw", "height": "100vh", "backgroundColor": "#0a0a15", "zIndex": 9999, "display": "flex", "justifyContent": "center", "alignItems": "center"}
    ),
    dcc.Interval(id="splash-interval", interval=4000, max_intervals=1),
    dcc.Store(id="splash-shown", data=False, storage_type='session'),

    html.Div(
        id="main-app",
        children=[
            html.Div(id="appbar", children=[
                html.Div([
                    html.I(id="menu-icon", className="fas fa-bars", style={"fontSize": "22px", "cursor": "pointer", "color": "white", "marginRight": "15px", "padding": "8px", "borderRadius": "4px"}),
                    html.Img(src="assets/logo.png", style={"height": "35px", "marginRight": "10px"}),
                    html.H4("FISCALINK", style={"color": "white", "margin": 0, "fontSize": "20px", "fontWeight": "600"})
                ], style={"display": "flex", "alignItems": "center"}),
                html.Div(id="appbar-status-display", children=[dbc.Spinner(size="sm", color="light"), " Connecting..."], style={"color": "white", "display": "flex", "alignItems": "center", "gap": "10px", "fontSize": "14px", "backgroundColor": "rgba(255,255,255,0.1)", "padding": "8px 16px", "borderRadius": "20px"})
            ], style={"position": "fixed", "top": 0, "left": 0, "width": "100%", "height": "60px", "backgroundColor": COLORS["dark"], "display": "flex", "justifyContent": "space-between", "alignItems": "center", "padding": "0 20px", "zIndex": 1000, "boxShadow": "0 2px 10px rgba(0,0,0,0.3)", "borderBottom": f"1px solid {COLORS['border']}"},),

            html.Div(id="sidebar", children=[html.Div(id="sidebar-nav-items", children=[], style={"width": "100%"})], style={"position": "fixed", "top": "60px", "left": 0, "bottom": 0, "width": SIDEBAR_WIDTH_COLLAPSED, "backgroundColor": COLORS["sidebar"], "padding": "10px 0", "transition": "width 0.3s ease", "overflow": "hidden", "zIndex": 900, "borderRight": f"1px solid {COLORS['border']}"}),
            html.Div(id="page-content", style={"marginLeft": SIDEBAR_WIDTH_COLLAPSED, "marginTop": "60px", "padding": "20px", "transition": "margin-left 0.3s ease", "minHeight": "calc(100vh - 60px)", "backgroundColor": "#f0f2f5"}),

            dcc.Location(id="url", refresh=False),
            dcc.Store(id="sidebar-state", data="collapsed"),
            dcc.Interval(id="status-refresh", interval=60000),
            dcc.Interval(id="scanner-refresh", interval=3000, n_intervals=0),
            
            # Download Components
            dcc.Download(id="download-pdf"),
            dcc.Download(id="download-zreport"),
            dcc.Download(id="download-zreport-pdf"),
            dcc.Download(id="download-success-csv"),
            
            # MOVED HERE: Toast Notifications & Polling Components (Must be in main layout)
            html.Div([
                dbc.Toast(id="toast-success", header="✅ Successfully Processed", is_open=False, duration=5000),
                dbc.Toast(id="toast-warning", header="⚠️ Processing Failed", is_open=False, duration=7000),
                dbc.Toast(id="toast-error", header="❌ System Error", is_open=False, duration=7000),
            ], style={
                "position": "fixed", 
                "top": "80px", 
                "right": "20px", 
                "zIndex": 9999, 
                "display": "flex", 
                "flexDirection": "column", 
                "gap": "10px", 
                "width": "350px"
            }),
            
            dcc.Interval(id="notification-interval", interval=3000, n_intervals=0),
            dcc.Store(id="last-seen-log-id", data=0),
            
            dcc.Store(id="pdf-payload-store-inv"),
            dcc.Store(id="pdf-payload-store-cn"),
            dcc.Store(id="download-trigger-inv"),
            dcc.Store(id="download-trigger-cn"),
            dcc.Store(id="print-command-store"),
            html.Div(id="dummy-print", style={"display": "none"})
        ],
        style={"display": "none"}
    )
])

app.index_string = '''
<!DOCTYPE html>
<html>
    <head>
        {%metas%}<title>{%title%}</title>
        <link rel="icon" href="/assets/favicon.ico">
        {%favicon%}{%css%}
        <style>
            @keyframes pulse { 0% { transform: scale(1); opacity: 1; } 50% { transform: scale(1.05); opacity: 0.8; } 100% { transform: scale(1); opacity: 1; } }
            .sidebar-nav-link { display: flex; align-items: center; padding: 12px 20px; color: #b0b0c0; text-decoration: none; transition: all 0.2s; border-left: 3px solid transparent; margin: 4px 0; }
            .sidebar-nav-link:hover { background-color: ''' + COLORS["sidebar_hover"] + '''; color: white; border-left-color: ''' + COLORS["primary"] + '''; }
            .sidebar-nav-link.active { background-color: ''' + COLORS["sidebar_hover"] + '''; color: ''' + COLORS["primary"] + '''; border-left-color: ''' + COLORS["primary"] + '''; }
            .sidebar-nav-link i { font-size: 20px; min-width: 30px; text-align: center; }
            .sidebar-nav-link span { margin-left: 12px; font-size: 14px; white-space: nowrap; }
        </style>
    </head>
    <body>{%app_entry%}<footer>{%config%}{%scripts%}{%renderer%}</footer></body>
</html>
'''

@callback([Output("splash-screen", "style"), Output("main-app", "style"), Output("splash-shown", "data")], Input("splash-interval", "n_intervals"), State("splash-shown", "data"))
def hide_splash(n, already_shown):
    if already_shown: return {"display": "none"}, {"display": "block"}, True
    if n is not None and n > 0: return {"display": "none"}, {"display": "block"}, True
    return {"display": "flex"}, {"display": "none"}, False

def build_sidebar_items(state, current_path):
    items = [
        {"path": "/", "icon": "fa-home", "label": "Home"}, 
        {"path": "/transactions", "icon": "fa-file-invoice", "label": "Transactions"}, 
        {"path": "/fiscal-day", "icon": "fa-calendar-day", "label": "Fiscal Day"}, 
        {"path": "/scanner", "icon": "fa-folder-open", "label": "Folder Scanner"},
        {"path": "/analytics", "icon": "fa-chart-line", "label": "Analytics"},
        {"path": "/pos", "icon": "fa-cash-register", "label": "POS"}, 
        {"path": "/audit", "icon": "fa-clipboard-list", "label": "Audit & Z-Reports"}
    ]
    nav_items = []
    for item in items:
        is_active = current_path == item["path"]
        active_class = "sidebar-nav-link active" if is_active else "sidebar-nav-link"
        if state == "collapsed":
            nav_items.append(html.A([html.I(className=f"fas {item['icon']}")], href=item["path"], className=active_class, style={"justifyContent": "center", "padding": "15px 0"}, title=item["label"]))
        else:
            nav_items.append(html.A([html.I(className=f"fas {item['icon']}"), html.Span(item["label"])], href=item["path"], className=active_class))
    return nav_items

@callback([Output("sidebar", "style"), Output("page-content", "style"), Output("sidebar-state", "data"), Output("sidebar-nav-items", "children")], [Input("menu-icon", "n_clicks"), Input("url", "pathname")], [State("sidebar-state", "data")])
def toggle_sidebar(n_clicks, pathname, current_state):
    if pathname is None: pathname = "/"
    new_state = "expanded" if (n_clicks is not None and n_clicks > 0 and current_state == "collapsed") else "collapsed" if (n_clicks is not None and n_clicks > 0) else current_state
    sidebar_style = {"position": "fixed", "top": "60px", "left": 0, "bottom": 0, "width": SIDEBAR_WIDTH_EXPANDED if new_state == "expanded" else SIDEBAR_WIDTH_COLLAPSED, "backgroundColor": COLORS["sidebar"], "padding": "10px 0", "transition": "width 0.3s ease", "overflow": "hidden", "zIndex": 900, "borderRight": f"1px solid {COLORS['border']}", "display": "flex", "flexDirection": "column"}
    content_style = {"marginLeft": SIDEBAR_WIDTH_EXPANDED if new_state == "expanded" else SIDEBAR_WIDTH_COLLAPSED, "marginTop": "60px", "padding": "20px", "transition": "margin-left 0.3s ease", "minHeight": "calc(100vh - 60px)", "backgroundColor": "#f0f2f5"}
    return sidebar_style, content_style, new_state, build_sidebar_items(new_state, pathname)

@callback(Output("appbar-status-display", "children"), Input("status-refresh", "n_intervals"))
def update_appbar_status(n):
    try:
        res = requests.post(f"{API_BASE}/api/status", json={}, timeout=5)
        data = res.json().get("zimra_response", {})
        status = data.get("fiscalDayStatus", "Unknown")
        color = COLORS["success"] if "Opened" in status else COLORS["text_muted"] if "Closed" in status else COLORS["warning"]
        icon = "fa-check-circle" if "Opened" in status else "fa-lock" if "Closed" in status else "fa-exclamation-triangle"
        return [html.I(className=f"fas {icon}", style={"color": color}), html.Span(f"Device: {status}", style={"fontWeight": "bold"})]
    except Exception: return [html.I(className="fas fa-wifi", style={"color": COLORS["danger"]}), html.Span("Offline", style={"color": COLORS["danger"]})]

@callback(Output("page-content", "children"), Input("url", "pathname"))
def render_page(pathname):
    if pathname == "/transactions": return get_transactions_page()
    elif pathname == "/fiscal-day": return get_fiscal_day_page()
    elif pathname == "/scanner": return get_scanner_page()
    elif pathname == "/analytics": return get_analytics_page()
    elif pathname == "/pos": return get_pos_page()
    elif pathname == "/audit": return get_audit_page()
    else: return get_home_page()

def get_home_page():
    try:
        res = requests.get(f"{API_BASE}/api/device_details", timeout=5)
        details = res.json()
    except: 
        details = {"company_name": "Unknown", "device_id": "N/A", "serial_number": "N/A", "vat_number": "N/A", "taxpayer_tin": "N/A", "fiscal_day_no": "N/A", "receipt_global_no": "N/A", "status": "Offline"}
    
    status_color = COLORS["success"] if "Active" in details.get("status", "") else COLORS["danger"]
    
    def make_card(title, value, icon, color=COLORS["primary"]):
        return dbc.Col(dbc.Card([dbc.CardBody([html.Div([html.I(className=f"fas {icon}", style={"fontSize": "28px", "color": color, "marginRight": "15px"}), html.Div([html.H6(title, className="text-muted mb-1", style={"fontSize": "12px", "textTransform": "uppercase"}), html.H4(str(value), className="mb-0", style={"fontWeight": "bold"})])], style={"display": "flex", "alignItems": "center"})])], className="mb-3", style={"border": "none", "boxShadow": "0 2px 8px rgba(0,0,0,0.08)", "borderRadius": "10px"}), md=6, lg=4)

    return html.Div([
        html.H2("Dashboard Overview", className="mb-4", style={"fontWeight": "600"}),
        dbc.Card([dbc.CardBody([html.Div([html.I(className="fas fa-circle", style={"color": status_color, "marginRight": "10px", "fontSize": "14px"}), html.H4(f"Device Status: {details.get('status', 'Unknown')}", style={"display": "inline-block", "margin": 0})])])], className="mb-4", style={"borderLeft": f"4px solid {status_color}", "borderRadius": "10px"}),
        dbc.Row([make_card("Company Name", details.get("company_name", "N/A"), "fa-building", COLORS["primary"]), make_card("Device ID", details.get("device_id", "N/A"), "fa-microchip", COLORS["success"]), make_card("Serial Number", details.get("serial_number", "N/A"), "fa-barcode", COLORS["warning"])]),
        dbc.Row([make_card("VAT Number", details.get("vat_number", "N/A"), "fa-file-invoice", "#6f42c1"), make_card("TaxPayer TIN", details.get("taxpayer_tin", "N/A"), "fa-id-card", COLORS["danger"])]),
        dbc.Row([make_card("Current Fiscal Day", details.get("fiscal_day_no", "N/A"), "fa-calendar-day", COLORS["info"]), make_card("Receipt Global No", details.get("receipt_global_no", "N/A"), "fa-receipt", COLORS["primary"])]),
        html.H4("Quick Actions", className="mt-4 mb-3", style={"fontWeight": "600"}),
        dbc.Row([
            dbc.Col(dbc.Card([dbc.CardBody([html.I(className="fas fa-file-invoice", style={"fontSize": "32px", "color": COLORS["primary"], "marginBottom": "10px"}), html.H5("New Invoice"), html.P("Create a new fiscal invoice", className="text-muted"), dbc.Button("Go to Transactions", href="/transactions", color="primary", className="w-100")])], className="text-center", style={"cursor": "pointer", "borderRadius": "10px"}), md=4),
            dbc.Col(dbc.Card([dbc.CardBody([html.I(className="fas fa-folder-open", style={"fontSize": "32px", "color": COLORS["success"], "marginBottom": "10px"}), html.H5("Folder Scanner"), html.P("Auto-process receipts", className="text-muted"), dbc.Button("Open Scanner", href="/scanner", color="success", className="w-100")])], className="text-center", style={"cursor": "pointer", "borderRadius": "10px"}), md=4),
            dbc.Col(dbc.Card([dbc.CardBody([html.I(className="fas fa-chart-line", style={"fontSize": "32px", "color": COLORS["info"], "marginBottom": "10px"}), html.H5("Analytics"), html.P("View sales insights", className="text-muted"), dbc.Button("Open Analytics", href="/analytics", color="info", className="w-100")])], className="text-center", style={"cursor": "pointer", "borderRadius": "10px"}), md=4),
        ])
    ])

def get_scanner_page():
    return html.Div([
        # (Toasts and Interval were moved to the main layout)
        
        html.H2("Folder Scanner", className="mb-4", style={"fontWeight": "600"}),
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader(html.H5("Scanner Control & Settings", className="mb-0")),
                    dbc.CardBody([
                        html.Label("Folder Path:", className="fw-bold mb-1"),
                        dbc.Input(id="scanner-folder-path", value=r"C:\Receipt", placeholder="Folder Path", className="mb-3"),
                        
                        html.Label("Receipt Template:", className="fw-bold mb-1"),
                        dbc.Select(id="scanner-template", options=[
                            {"label": "Melivo POS (Default)", "value": "melivo"},
                            {"label": "FEEDMIX POS", "value": "feedmix"},
                            {"label": "QuickBooks POS", "value": "quickbooks"},
                            {"label": "AIBES (PDF Only)", "value": "aibes"}
                        ], value="feedmix", className="mb-3"),
                        html.Label("Default Print Format:", className="fw-bold mb-1"),
                        dbc.Select(id="scanner-print-format", options=[
                            {"label": "A4 Invoice (InvoiceA4)", "value": "InvoiceA4"},
                            {"label": "80mm Thermal Receipt (Receipt48)", "value": "Receipt48"}
                        ], value="Receipt48", className="mb-3"),
                        
                        dbc.Checklist(
                            options=[{"label": " Process PDF Files (Extract, Fiscalize & Stamp QR)", "value": "pdfs"}],
                            value=[],
                            id="scanner-process-pdfs",
                            switch=True,
                            className="mb-3"
                        ),
                        
                        dbc.Row([
                            dbc.Col(dbc.Button("Start Scanning", id="btn-start-scanner", color="success", className="w-100", size="lg"), md=6),
                            dbc.Col(dbc.Button("Stop Scanning", id="btn-stop-scanner", color="danger", className="w-100", size="lg"), md=6),
                        ], className="mb-3"),
                        
                        dbc.Row([
                            dbc.Col(html.A(dbc.Button([html.I(className="fas fa-print me-2"), "Print Test 80mm Receipt"], color="info", className="w-100"), href="/api/print_test_80mm", target="_blank"), md=12)
                        ], className="mb-3"),
                        
                        html.A(
                            dbc.Button([html.I(className="fas fa-external-link-alt me-2"), "Verify Receipt on ZIMRA Portal"], color="secondary", className="w-100 mb-3"),
                            href="https://fdms.zimra.co.zw/Receipt/Find", target="_blank"
                        ),
                        html.Div(id="scanner-status-display", className="mt-3")
                    ])
                ], style={"borderRadius": "10px"})
            ], md=6),
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader(html.Div([
                        html.H5("Scanner History Log", className="mb-0 d-inline-block"),
                        dbc.Button("Clear History", id="btn-clear-history", color="warning", size="sm", className="float-end")
                    ])),
                    dbc.CardBody([
                        html.Div(id="scanner-log-display", style={"maxHeight": "600px", "overflow": "auto", "backgroundColor": "#f8f9fa", "padding": "15px", "borderRadius": "5px", "fontSize": "12px"})
                    ])
                ], style={"borderRadius": "10px"})
            ], md=6),
        ])
    ])

@callback([Output("scanner-folder-path", "value"), Output("scanner-template", "value"), Output("scanner-print-format", "value"), Output("scanner-process-pdfs", "value")], Input("url", "pathname"))
def load_scanner_settings(pathname):
    if pathname == "/scanner":
        try:
            res = requests.get(f"{API_BASE}/api/scanner_settings", timeout=2)
            data = res.json()
            pdf_val = ["pdfs"] if data.get("process_pdfs", False) else []
            # Updated fallbacks to default to Feedmix and Receipt48
            return data.get("folder_path", r"C:\Receipt"), data.get("template", "feedmix"), data.get("print_format", "Receipt48"), pdf_val
        except:
            return r"C:\Receipt", "feedmix", "Receipt48", []
    return dash.no_update, dash.no_update, dash.no_update, dash.no_update

@callback(Output("scanner-status-display", "children"), [Input("btn-start-scanner", "n_clicks"), Input("btn-stop-scanner", "n_clicks")], [State("scanner-folder-path", "value"), State("scanner-template", "value"), State("scanner-print-format", "value"), State("scanner-process-pdfs", "value")], prevent_initial_call=True)
def control_scanner(start_clicks, stop_clicks, folder_path, template, print_format, process_pdfs):
    triggered = ctx.triggered_id
    
    if triggered == "btn-start-scanner":
        try:
            res = requests.post(f"{API_BASE}/api/start_scanning", json={
                "folder_path": folder_path, 
                "receipt_template": template,
                "receipt_print_format": print_format,
                "process_pdfs": "pdfs" in process_pdfs if process_pdfs else False
            })
            data = res.json()
            if data.get("status") == "started":
                return dbc.Alert(f"Scanner started! Monitoring folder. Template: {template.upper()} POS", color="success")
            elif data.get("status") == "already_running":
                return dbc.Alert("Scanner is already running.", color="warning")
            return dbc.Alert(f"Error: {data}", color="danger")
        except Exception as e:
            return dbc.Alert(f"Error: {str(e)}", color="danger")
    
    elif triggered == "btn-stop-scanner":
        try:
            res = requests.post(f"{API_BASE}/api/stop_scanning", json={})
            data = res.json()
            if data.get("status") == "stopped":
                return dbc.Alert("Scanner stopped.", color="info")
            return dbc.Alert(f"Error: {data}", color="danger")
        except Exception as e:
            return dbc.Alert(f"Error: {str(e)}", color="danger")
    
    return ""

@callback(
    [Output("toast-success", "is_open"), Output("toast-success", "header"), Output("toast-success", "children"),
     Output("toast-warning", "is_open"), Output("toast-warning", "header"), Output("toast-warning", "children"),
     Output("toast-error", "is_open"), Output("toast-error", "header"), Output("toast-error", "children"),
     Output("last-seen-log-id", "data")],
    Input("notification-interval", "n_intervals"),
    State("last-seen-log-id", "data")
)
def update_scanner_notifications(n, last_id):
    """Polls the backend for new logs and triggers toast popups."""
    try:
        res = requests.get(f"{API_BASE}/api/scanner_history", params={"limit": 1}, timeout=2)
        logs = res.json()
        if logs and isinstance(logs, list):
            latest = logs[0]
            current_id = latest.get('id', 0)
            
            if current_id > last_id:
                status = latest.get('status', 'INFO')
                msg = latest.get('message', '')
                short_msg = msg.split('\n')[0] if '\n' in msg else (msg[:120] + "..." if len(msg) > 120 else msg)
                
                if status == 'SUCCESS':
                    return True, f"✅ Successfully Processed: {latest.get('timestamp', '')}", short_msg, False, "", "", False, "", "", current_id
                elif status in ['FAILED', 'ERROR'] or 'VALIDATION FAILED' in msg or 'ZIMRA ERROR' in msg:
                    header = "⚠️ Processing Failed" if status == 'FAILED' else "❌ System Error"
                    return False, "", "", True, header, short_msg, False, "", "", current_id
                else:
                    return False, "", "", False, "", "", False, "", "", current_id
                    
        return False, "", "", False, "", "", False, "", "", last_id
    except Exception:
        return False, "", "", False, "", "", False, "", "", last_id

@callback(Output("scanner-log-display", "children"), [Input("scanner-refresh", "n_intervals"), Input("btn-clear-history", "n_clicks")])
def update_scanner_log(n, clear_clicks):
    if clear_clicks:
        try:
            requests.post(f"{API_BASE}/api/clear_scanner_history", json={})
        except: pass

    try:
        res = requests.get(f"{API_BASE}/api/scanner_history", timeout=2)
        logs = res.json()
        
        if not isinstance(logs, list):
            return f"Error fetching logs: {logs}"
            
        if not logs:
            return "No history yet..."
        
        logs_by_date = defaultdict(list)
        for entry in logs:
            ts = entry.get('timestamp', '')
            date_part = ts.split(' ')[0] if ' ' in ts else ts
            time_part = ts.split(' ')[1] if ' ' in ts else ''
            logs_by_date[date_part].append({
                'time': time_part,
                'message': entry.get('message', ''),
                'status': entry.get('status', 'INFO')
            })

        formatted_logs = []
        for date, entries in sorted(logs_by_date.items(), reverse=True):
            formatted_logs.append(html.H6(date, className="mt-3 mb-2 text-primary fw-bold border-bottom pb-1"))
            
            for entry in entries:
                msg = entry['message']
                status = entry['status']
                time_str = entry['time']
                
                border_color = COLORS["success"] if status == "SUCCESS" else COLORS["warning"] if status == "WARNING" else COLORS["danger"]
                
                log_content = []
                verify_btn = None
                
                if "URL: https://" in msg:
                    parts = msg.split("URL: ")
                    text_part = parts[0]
                    url_part = parts[1].split(" | ")[0].strip()
                    
                    log_content.append(html.Span(text_part, style={"color": "#333", "whiteSpace": "pre-wrap", "fontFamily": "monospace"}))
                    verify_btn = html.A(
                        dbc.Button([html.I(className="fas fa-shield-alt me-1"), "Verify on ZIMRA"], color="primary", size="sm", className="ms-2"),
                        href=url_part, target="_blank", style={"textDecoration": "none"}
                    )
                else:
                    log_content.append(html.Span(msg, style={"color": "#333", "whiteSpace": "pre-wrap", "fontFamily": "monospace"}))

                row_content = [
                    html.Span(f"[{time_str}] ", style={"color": "#888", "marginRight": "8px", "fontFamily": "monospace"}),
                    *log_content
                ]
                if verify_btn:
                    row_content.append(verify_btn)

                formatted_logs.append(html.Div(
                    row_content,
                    style={"marginBottom": "8px", "padding": "10px", "backgroundColor": "#fff", "borderRadius": "4px", "fontSize": "13px", "borderLeft": f"4px solid {border_color}", "boxShadow": "0 1px 2px rgba(0,0,0,0.05)", "display": "flex", "alignItems": "center", "flexWrap": "wrap"}
                ))
        
        return html.Div(formatted_logs)
    except Exception as e:
        return f"Unable to connect to scanner: {str(e)}"

def get_analytics_page():
    return html.Div([
        html.H2("Sales Analytics", className="mb-4", style={"fontWeight": "600"}),
        
        dbc.Card([
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        html.Label("Time Range:", className="fw-bold mb-1"),
                        dbc.Select(id="analytics-range", options=[
                            {"label": "Last 24 Hours", "value": "day"},
                            {"label": "Last 7 Days", "value": "week"},
                            {"label": "Last 30 Days", "value": "month"},
                            {"label": "Last Year", "value": "year"}
                        ], value="month", className="mb-2")
                    ], md=3),
                    dbc.Col([
                        html.Label("Custom Date Range:", className="fw-bold mb-1"),
                        dcc.DatePickerRange(
                            id='analytics-date-range',
                            min_date_allowed=datetime(2020, 1, 1),
                            max_date_allowed=datetime.now(),
                            initial_visible_month=datetime.now(),
                            start_date=(datetime.now() - timedelta(days=30)).date(),
                            end_date=datetime.now().date(),
                            display_format='YYYY-MM-DD',
                            className="mb-2",
                            style={"width": "100%"}
                        ),
                        dbc.Button("Apply Custom Date Range", id="btn-apply-date-range-visible", 
                                  color="primary", size="sm", className="mt-2")
                    ], md=5),
                    dbc.Col([
                        html.Label("Chart Type:", className="fw-bold mb-1"),
                        dbc.Select(id="analytics-chart-type", options=[
                            {"label": "Bar Chart", "value": "bar"},
                            {"label": "Line Chart", "value": "line"}
                        ], value="bar", className="mb-2")
                    ], md=2),
                    dbc.Col([
                        html.Label("Metric:", className="fw-bold mb-1"),
                        dbc.Select(id="analytics-metric", options=[
                            {"label": "Sales Total", "value": "sales"},
                            {"label": "Tax Total", "value": "tax"}
                        ], value="sales", className="mb-2")
                    ], md=2)
                ])
            ])
        ], className="mb-4", style={"borderRadius": "10px"}),
        
        dbc.Card([
            dbc.CardHeader(html.H5("USD vs ZWG Performance", className="mb-0")),
            dbc.CardBody([
                dcc.Graph(id="analytics-main-chart", style={"height": "400px"})
            ])
        ], className="mb-4", style={"borderRadius": "10px"}),
        
        dbc.Card([
            dbc.CardHeader(html.H5("Top 10 Products by Currency", className="mb-0")),
            dbc.CardBody([
                dbc.Tabs([
                    dbc.Tab(
                        label="USD", 
                        tab_id="tab-usd",
                        label_style={"fontWeight": "bold", "color": COLORS["primary"]},
                        children=html.Div([
                            dbc.Row([
                                dbc.Col([
                                    html.H6("Top 10 by Quantity", className="mt-3 mb-2 text-primary fw-bold"),
                                    html.Div(id="top-products-usd-qty")
                                ], md=6),
                                dbc.Col([
                                    html.H6("Top 10 by Sales Amount", className="mt-3 mb-2 text-primary fw-bold"),
                                    html.Div(id="top-products-usd-amt")
                                ], md=6),
                            ])
                        ])
                    ),
                    dbc.Tab(
                        label="ZWG", 
                        tab_id="tab-zwg",
                        label_style={"fontWeight": "bold", "color": COLORS["success"]},
                        children=html.Div([
                            dbc.Row([
                                dbc.Col([
                                    html.H6("Top 10 by Quantity", className="mt-3 mb-2 text-success fw-bold"),
                                    html.Div(id="top-products-zwg-qty")
                                ], md=6),
                                dbc.Col([
                                    html.H6("Top 10 by Sales Amount", className="mt-3 mb-2 text-success fw-bold"),
                                    html.Div(id="top-products-zwg-amt")
                                ], md=6),
                            ])
                        ])
                    ),
                ], id="analytics-currency-tabs", active_tab="tab-usd")
            ])
        ], className="mb-4", style={"borderRadius": "10px"}),
        
        dbc.Card([
            dbc.CardHeader(html.H5("Peak Business Hours (24h)", className="mb-0")),
            dbc.CardBody([
                dcc.Graph(id="busy-hours-chart", style={"height": "300px"})
            ])
        ], style={"borderRadius": "10px"}),
        
        dcc.Interval(id="analytics-refresh", interval=10000, n_intervals=0)
    ])

@callback(
    [Output("analytics-main-chart", "figure"),
     Output("top-products-usd-qty", "children"),
     Output("top-products-usd-amt", "children"),
     Output("top-products-zwg-qty", "children"),
     Output("top-products-zwg-amt", "children"),
     Output("busy-hours-chart", "figure")],
    [Input("analytics-range", "value"),
     Input("analytics-chart-type", "value"),
     Input("analytics-metric", "value"),
     Input("btn-apply-date-range-visible", "n_clicks"),
     Input("analytics-refresh", "n_intervals")],
    [State("analytics-date-range", "start_date"),
     State("analytics-date-range", "end_date")]
)
def update_analytics(range_type, chart_type, metric, apply_clicks, n, start_date, end_date):
    try:
        params = {"range": range_type}
        if start_date and end_date and apply_clicks:
            params["start_date"] = start_date
            params["end_date"] = end_date
            
        res = requests.get(f"{API_BASE}/api/analytics", params=params, timeout=5)
        data = res.json()
        
        if "error" in data:
            empty_fig = go.Figure().update_layout(title="No data available", height=400)
            no_data = html.P("No data", className="text-muted text-center p-3")
            return empty_fig, no_data, no_data, no_data, no_data, empty_fig
        
        ts = data.get('time_series', {})
        labels = ts.get('labels', [])
        
        if metric == 'sales':
            usd_data = ts.get('usd_sales', [])
            zwg_data = ts.get('zwg_sales', [])
            y_title = "Sales Total"
        else:
            usd_data = ts.get('usd_tax', [])
            zwg_data = ts.get('zwg_tax', [])
            y_title = "Tax Total"
        
        if chart_type == 'bar':
            fig = go.Figure()
            fig.add_trace(go.Bar(name='USD', x=labels, y=usd_data, marker_color=COLORS["primary"]))
            fig.add_trace(go.Bar(name='ZWG', x=labels, y=zwg_data, marker_color=COLORS["success"]))
        else:
            fig = go.Figure()
            fig.add_trace(go.Scatter(name='USD', x=labels, y=usd_data, mode='lines+markers', line=dict(color=COLORS["primary"], width=3)))
            fig.add_trace(go.Scatter(name='ZWG', x=labels, y=zwg_data, mode='lines+markers', line=dict(color=COLORS["success"], width=3)))
        
        fig.update_layout(
            title=f"{y_title} by {range_type.title()}",
            xaxis_title="Period",
            yaxis_title=y_title,
            barmode='group' if chart_type == 'bar' else None,
            template='plotly_white',
            height=400,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        
        def build_product_table(products, rank_by, currency_color):
            if not products:
                return html.P("No product data for this currency in the selected range.", 
                             className="text-muted text-center p-3")
            
            rows = []
            for i, p in enumerate(products, 1):
                rows.append(html.Tr([
                    html.Td(html.Span(f"#{i}", className="badge me-2", 
                                     style={"backgroundColor": currency_color, "color": "white"})),
                    html.Td(p.get('name', 'Unknown'), style={"maxWidth": "250px", "overflow": "hidden", "textOverflow": "ellipsis", "whiteSpace": "nowrap"}),
                    html.Td(f"{p.get('qty', 0):,.2f}", className="text-end"),
                    html.Td(f"${p.get('amount', 0):,.2f}", className="text-end fw-bold")
                ]))
            
            return dbc.Table([
                html.Thead(html.Tr([
                    html.Th("Rank"), html.Th("Product"), 
                    html.Th("Qty", className="text-end"), 
                    html.Th("Amount", className="text-end")
                ])),
                html.Tbody(rows)
            ], bordered=True, hover=True, responsive=True, size="sm", className="mb-0")
        
        top_products = data.get('top_products', {})
        
        usd_data = top_products.get('USD', {})
        usd_qty_table = build_product_table(usd_data.get('by_quantity', []), 'qty', COLORS["primary"])
        usd_amt_table = build_product_table(usd_data.get('by_amount', []), 'amount', COLORS["primary"])
        
        zwg_data = top_products.get('ZWG', {})
        zwg_qty_table = build_product_table(zwg_data.get('by_quantity', []), 'qty', COLORS["success"])
        zwg_amt_table = build_product_table(zwg_data.get('by_amount', []), 'amount', COLORS["success"])
        
        busy = data.get('busy_hours', [])
        hours = [f"{h:02d}:00" for h in range(24)]
        counts = [b.get('count', 0) for b in busy]
        
        busy_fig = go.Figure()
        busy_fig.add_trace(go.Scatter(
            x=hours, y=counts,
            fill='tozeroy',
            mode='lines+markers',
            line=dict(color=COLORS["warning"], width=2),
            marker=dict(size=6),
            name="Transactions"
        ))
        busy_fig.update_layout(
            title="Transaction Volume by Hour of Day",
            xaxis_title="Hour",
            yaxis_title="Number of Transactions",
            template='plotly_white',
            height=300
        )
        
        return fig, usd_qty_table, usd_amt_table, zwg_qty_table, zwg_amt_table, busy_fig
    except Exception as e:
        empty_fig = go.Figure().update_layout(title=f"Error: {str(e)}", height=400)
        error_msg = html.P(f"Error: {str(e)}", className="text-danger text-center p-3")
        return empty_fig, error_msg, error_msg, error_msg, error_msg, empty_fig

def get_fiscal_day_page():
    return html.Div([
        html.H2("Fiscal Day Management", className="mb-4", style={"fontWeight": "600"}),
        dbc.Row([
            dbc.Col(dbc.Card([dbc.CardHeader(html.H5("Open New Fiscal Day", className="mb-0")), dbc.CardBody([html.P("Start a new fiscal day to begin issuing receipts.", className="text-muted"), dbc.Input(id="open-day-no", type="number", placeholder="Fiscal Day No (Optional)", className="mb-3"), dbc.Button("Open Fiscal Day", id="btn-open-day", color="success", className="w-100", size="lg"), html.Div(id="open-day-output", className="mt-3")])], style={"borderRadius": "10px"}), md=6),
            dbc.Col(dbc.Card([dbc.CardHeader(html.H5("Close Current Fiscal Day", className="mb-0")), dbc.CardBody([html.P("Close the current fiscal day automatically and generate Z-Report.", className="text-muted"), dbc.Button("Close Fiscal Day (Auto)", id="btn-close-day", color="danger", className="w-100", size="lg"), html.Div(id="close-day-output", className="mt-3")])], style={"borderRadius": "10px"}), md=6),
        ])
    ])

@callback(Output("open-day-output", "children"), Input("btn-open-day", "n_clicks"), State("open-day-no", "value"), prevent_initial_call=True)
def open_fiscal_day(n, day_no):
    if not n: return ""
    try:
        res = requests.post(f"{API_BASE}/api/open_day", json={"fiscalDayNo": day_no})
        try: data = res.json()
        except: return dbc.Alert(f"Invalid JSON response: {res.text[:100]}", color="danger")
        if data.get("http_status") == 200: return dbc.Alert("Fiscal Day Opened Successfully!", color="success")
        return dbc.Alert(f"Error: {data.get('zimra_response')}", color="danger")
    except Exception as e: return dbc.Alert(str(e), color="danger")

@callback(Output("close-day-output", "children"), Input("btn-close-day", "n_clicks"), prevent_initial_call=True)
def close_fiscal_day(n):
    if not n: return ""
    try:
        res = requests.post(f"{API_BASE}/api/close_day", json={})
        try: data = res.json()
        except ValueError: return dbc.Alert(f"Server returned invalid JSON: {res.text[:100]}", color="danger")
        
        if data.get("http_status") == 200: 
            z_report = data.get('z_report', {})
            currencies = z_report.get('currencies', {})
            usd_sales = currencies.get('USD', {}).get('total_sales', 0)
            zwg_sales = currencies.get('ZWG', {}).get('total_sales', 0)
            report_text = f"Z-Report Generated! USD Sales: ${usd_sales:,.2f} | ZWG Sales: ${zwg_sales:,.2f}"
            return dbc.Alert(report_text, color="success")
        return dbc.Alert(f"Error: {data.get('zimra_response')}", color="danger")
    except Exception as e: return dbc.Alert(str(e), color="danger")

def get_transactions_page():
    return html.Div([
        html.H2("Test Transactions", className="mb-4", style={"fontWeight": "600"}),
        dbc.Tabs([dbc.Tab(label="Submit Invoice", tab_id="tab-invoice", labelClassName="text-primary fw-bold"), dbc.Tab(label="Credit Note", tab_id="tab-credit", labelClassName="text-warning fw-bold")], id="trans-tabs", active_tab="tab-invoice", className="mb-3"),
        html.Div(id="trans-tab-content")
    ])

@callback(Output("trans-tab-content", "children"), Input("trans-tabs", "active_tab"))
def render_trans_tab(tab):
    print_options = [{"label": "A4 Invoice", "value": "InvoiceA4"}, {"label": "Receipt 48mm", "value": "Receipt48"}]
    if tab == "tab-credit":
        return dbc.Card([dbc.CardHeader(html.H5("Credit Note", className="mb-0")), dbc.CardBody([
            dbc.Row([dbc.Col(dbc.Input(id="cn-no", placeholder="CN No", value="CN-001"), md=4), dbc.Col(dbc.Input(id="cn-orig", placeholder="Original Inv No", value="INV-001"), md=4), dbc.Col(dbc.Input(id="cn-total", type="number", value=115.50, placeholder="Total"), md=4)], className="mb-3"),
            dbc.Row([dbc.Col(dbc.Input(id="cn-qty", type="number", value=2, placeholder="Quantity"), md=4), dbc.Col(dbc.Select(id="cn-print-format", options=print_options, value="InvoiceA4"), md=4)], className="mb-3"),
            dbc.Button("Submit Credit Note", id="btn-cn", color="warning", className="w-100", size="lg"),
            html.Div(id="cn-out", className="mt-3")
        ])], style={"borderRadius": "10px"})
    else:
        return dbc.Card([dbc.CardHeader(html.H5("Fiscal Invoice", className="mb-0")), dbc.CardBody([
            dbc.Row([dbc.Col(dbc.Input(id="inv-no", placeholder="Invoice No", value="INV-001"), md=4), dbc.Col(dbc.Select(id="inv-curr", options=[{"label": "USD", "value": "USD"}, {"label": "ZWG", "value": "ZWG"}], value="USD"), md=4), dbc.Col(dbc.Input(id="inv-total", type="number", value=115.50, placeholder="Total"), md=4)], className="mb-3"),
            dbc.Row([dbc.Col(dbc.Input(id="inv-qty", type="number", value=2, placeholder="Quantity"), md=4), dbc.Col(dbc.Select(id="inv-print-format", options=print_options, value="InvoiceA4"), md=4)], className="mb-3"),
            dbc.Button("Submit Invoice", id="btn-inv", color="primary", className="w-100", size="lg"),
            html.Div(id="inv-out", className="mt-3")
        ])], style={"borderRadius": "10px"})

@callback([Output("inv-out", "children"), Output("pdf-payload-store-inv", "data"), Output("download-trigger-inv", "data"), Output("print-command-store", "data", allow_duplicate=True)], 
          Input("btn-inv", "n_clicks"), 
          [State("inv-no", "value"), State("inv-curr", "value"), State("inv-total", "value"), State("inv-qty", "value"), State("inv-print-format", "value")], 
          prevent_initial_call=True)
def submit_inv(n, no, curr, total, qty, print_format):
    if not n: return "", dash.no_update, dash.no_update, dash.no_update
    quantity = float(qty) if qty else 2.0
    payload = {"receiptType": "FiscalInvoice", "currency": curr, "invoiceNo": no, "receiptTotal": float(total), "taxPercent": 15.5, "buyerName": "Test Buyer", "buyerTIN": "2000457810", "itemName": "Item 1", "quantity": quantity, "printFormat": print_format}
    try:
        res = requests.post(f"{API_BASE}/api/submit_receipt", json=payload)
        data = res.json()
        if data.get("Code") == "1":
            qr_url = data.get('QRcode', 'https://fdms.zimra.co.zw/Receipt/Find')
            pdf_store_data = {"receipt_data": data.get("Data"), "verification_code": data.get("VerificationCode"), "qr_code": qr_url, "print_format": print_format}
            success_ui = html.Div([
                dbc.Alert([html.I(className="fas fa-check-circle me-2"), f"Success! Verification Code: {data.get('VerificationCode')}"], color="success"),
                dbc.Row([dbc.Col(html.A(dbc.Button([html.I(className="fas fa-external-link-alt me-2"), "Verify on ZIMRA"], color="success", className="w-100"), href=qr_url, target="_blank"), width=4), 
                         dbc.Col(dbc.Button([html.I(className="fas fa-file-pdf me-2"), "Download PDF"], id="btn-trigger-download-inv", color="primary", className="w-100", n_clicks=0), width=4),
                         dbc.Col(dbc.Button([html.I(className="fas fa-print me-2"), "Print Receipt"], id="btn-print-inv-ui", color="info", className="w-100"), width=4)], className="mt-3")
            ])
            return success_ui, pdf_store_data, pdf_store_data, {"type": "invoice"}
        return dbc.Alert(f"Error: {data.get('Message')}", color="danger"), dash.no_update, dash.no_update, dash.no_update
    except Exception as e: return dbc.Alert(str(e), color="danger"), dash.no_update, dash.no_update, dash.no_update

@callback([Output("cn-out", "children"), Output("pdf-payload-store-cn", "data"), Output("download-trigger-cn", "data"), Output("print-command-store", "data", allow_duplicate=True)], 
          Input("btn-cn", "n_clicks"), 
          [State("cn-no", "value"), State("cn-orig", "value"), State("cn-total", "value"), State("cn-qty", "value"), State("cn-print-format", "value")], 
          prevent_initial_call=True)
def submit_cn(n, no, orig, total, qty, print_format):
    if not n: return "", dash.no_update, dash.no_update, dash.no_update
    quantity = float(qty) if qty else 2.0
    payload = {"receiptType": "CreditNote", "invoiceNo": no, "originalInvoiceNo": orig, "receiptTotal": float(total), "taxPercent": 15.5, "buyerName": "Test Buyer", "buyerTIN": "2000457810", "itemName": "Item 1", "quantity": quantity, "printFormat": print_format}
    try:
        res = requests.post(f"{API_BASE}/api/submit_receipt", json=payload)
        data = res.json()
        if data.get("Code") == "1":
            qr_url = data.get('QRcode', 'https://fdms.zimra.co.zw/Receipt/Find')
            pdf_store_data = {"receipt_data": data.get("Data"), "verification_code": data.get("VerificationCode"), "qr_code": qr_url, "print_format": print_format}
            success_ui = html.Div([
                dbc.Alert([html.I(className="fas fa-check-circle me-2"), f"Success! Verification Code: {data.get('VerificationCode')}"], color="success"),
                dbc.Row([dbc.Col(html.A(dbc.Button([html.I(className="fas fa-external-link-alt me-2"), "Verify on ZIMRA"], color="success", className="w-100"), href=qr_url, target="_blank"), width=4), 
                         dbc.Col(dbc.Button([html.I(className="fas fa-file-pdf me-2"), "Download PDF"], id="btn-trigger-download-cn", color="primary", className="w-100", n_clicks=0), width=4),
                         dbc.Col(dbc.Button([html.I(className="fas fa-print me-2"), "Print Receipt"], id="btn-print-cn-ui", color="info", className="w-100"), width=4)], className="mt-3")
            ])
            return success_ui, pdf_store_data, pdf_store_data, {"type": "creditnote"}
        return dbc.Alert(f"Error: {data.get('Message')}", color="danger"), dash.no_update, dash.no_update, dash.no_update
    except Exception as e: return dbc.Alert(str(e), color="danger"), dash.no_update, dash.no_update, dash.no_update

@callback(Output("download-pdf", "data"), [Input("download-trigger-inv", "data"), Input("download-trigger-cn", "data")], prevent_initial_call=True)
def download_pdf(inv_data, cn_data):
    triggered = ctx.triggered_id
    payload = inv_data if triggered == "download-trigger-inv" else cn_data
    if payload:
        try:
            res = requests.post(f"{API_BASE}/api/print_pdf", json=payload)
            if res.status_code == 200:
                inv_no = payload.get('receipt_data', {}).get('receipt', {}).get('invoiceNo', 'Receipt')
                prefix = "ZIMRA_CN_" if triggered == "download-trigger-cn" else "ZIMRA_"
                return dcc.send_bytes(res.content, f"{prefix}{inv_no}.pdf")
        except Exception: pass
    return dash.no_update

@callback(Output("dummy-print", "children"), Input("print-command-store", "data"), prevent_initial_call=True)
def execute_print(data):
    if data:
        return dcc.Markdown("<script>window.print();</script>", dangerously_allow_html=True)
    return ""

def get_audit_page():
    try:
        res_stats = requests.get(f"{API_BASE}/api/receipt_stats", timeout=5)
        stats = res_stats.json()
        res_reports = requests.get(f"{API_BASE}/api/z_reports", timeout=5)
        z_reports = res_reports.json()
    except: 
        stats = {"total_success": 0, "total_failed": 0, "recent_success": [], "recent_failed": []}
        z_reports = []

    def build_table(data):
        if not data: return html.P("No records found.", className="text-muted text-center p-3")
        rows = [html.Tr([html.Td(r.get('invoice_no', 'N/A')), html.Td(f"${r.get('total_amount', 0):.2f}"), html.Td(r.get('verification_code', 'N/A') or 'N/A'), html.Td(r.get('created_at', 'N/A')), html.Td(html.Small(r.get('zimra_response', ''), className="text-muted"))]) for r in data]
        return dbc.Table([html.Thead(html.Tr([html.Th("Invoice No"), html.Th("Amount"), html.Th("Verification Code"), html.Th("Date"), html.Th("ZIMRA Response")])), html.Tbody(rows)], bordered=True, hover=True, responsive=True, size="sm")

    def build_z_report_table(reports):
        if not reports: return html.P("No Z-Reports generated yet.", className="text-muted text-center p-3")
        rows = []
        for r in reports:
            currencies = r.get('currencies', {})
            usd_sales = currencies.get('USD', {}).get('total_sales', 0)
            usd_vat = currencies.get('USD', {}).get('total_tax', 0)
            zwg_sales = currencies.get('ZWG', {}).get('total_sales', 0)
            zwg_vat = currencies.get('ZWG', {}).get('total_tax', 0)
            rows.append(html.Tr([
                html.Td(f"Day {r.get('fiscal_day_no')}"), html.Td(r.get('close_date', 'N/A')), 
                html.Td(f"${usd_sales:,.2f} / ${usd_vat:,.2f}"), html.Td(f"${zwg_sales:,.2f} / ${zwg_vat:,.2f}"), 
                html.Td(str(r.get('total_receipts', 0))),
                html.Td(html.Div([
                    dbc.Button("JSON", color="secondary", size="sm", className="me-1", id={'type': 'btn-dl-zreport', 'index': r['id']}),
                    dbc.Button("PDF", color="primary", size="sm", id={'type': 'btn-dl-zreport-pdf', 'index': r['id']})
                ]))
            ]))
        return dbc.Table([html.Thead(html.Tr([html.Th("Fiscal Day"), html.Th("Closed Date"), html.Th("USD (Sales/VAT)"), html.Th("ZWG (Sales/VAT)"), html.Th("Receipts"), html.Th("Download")])), html.Tbody(rows)], bordered=True, hover=True, responsive=True, size="sm")

    return html.Div([
        html.H2("Audit Log & Z-Reports", className="mb-4", style={"fontWeight": "600"}),
        html.H4("Z-Report History", className="mb-3"),
        dbc.Card([dbc.CardBody(build_z_report_table(z_reports))], className="mb-4", style={"borderRadius": "10px"}),
        dbc.Row([dbc.Col(dbc.Card([dbc.CardBody([html.Div([html.I(className="fas fa-check-circle", style={"fontSize": "32px", "color": COLORS["success"], "marginRight": "15px"}), html.Div([html.H6("Total Successful", className="text-muted mb-1"), html.H3(str(stats.get('total_success', 0)), className="mb-0 text-success")])], style={"display": "flex", "alignItems": "center"})])], style={"borderRadius": "10px"}), md=6), dbc.Col(dbc.Card([dbc.CardBody([html.Div([html.I(className="fas fa-times-circle", style={"fontSize": "32px", "color": COLORS["danger"], "marginRight": "15px"}), html.Div([html.H6("Total Failed", className="text-muted mb-1"), html.H3(str(stats.get('total_failed', 0)), className="mb-0 text-danger")])], style={"display": "flex", "alignItems": "center"})])], style={"borderRadius": "10px"}), md=6)], className="mb-4"),
        
        # NEW: Download CSV Button for Successful Receipts
        html.Div([
            html.H4("Recent Successful Receipts", className="mb-3 d-inline-block"),
            dbc.Button([html.I(className="fas fa-file-csv me-2"), "Download CSV"], id="btn-download-success", color="success", size="sm", className="ms-3")
        ], className="d-flex align-items-center mb-3"), 
        dbc.Card([dbc.CardBody(build_table(stats.get('recent_success', [])))], className="mb-4", style={"borderRadius": "10px"}),
        
        html.H4("Recent Failed Receipts", className="mb-3"), dbc.Card([dbc.CardBody(build_table(stats.get('recent_failed', [])))], className="mb-4", style={"borderRadius": "10px"}),
    ])

@callback(Output("download-success-csv", "data"), Input("btn-download-success", "n_clicks"), prevent_initial_call=True)
def download_success_csv(n):
    if n:
        try:
            res = requests.get(f"{API_BASE}/api/download_successful_receipts", timeout=10)
            if res.status_code == 200:
                return dcc.send_bytes(res.content, "successful_receipts.csv")
        except Exception as e:
            print(f"Error downloading CSV: {e}")
    return dash.no_update

def get_pos_page():
    return html.Div([html.H2("Point of Sale", className="mb-4", style={"fontWeight": "600"}), dbc.Card([dbc.CardBody([html.Div([html.I(className="fas fa-cash-register", style={"fontSize": "64px", "color": COLORS["text_muted"], "marginBottom": "20px"}), html.H4("POS Module Coming Soon", className="text-center text-muted"), html.P("This module will integrate directly with your barcode scanner and cart system.", className="text-center")], style={"textAlign": "center", "padding": "40px"})])], style={"borderRadius": "10px"})])

@callback(Output("download-zreport", "data"), Input({'type': 'btn-dl-zreport', 'index': dash.ALL}, "n_clicks"), prevent_initial_call=True)
def download_z_report(n_clicks_list):
    if not any(n_clicks_list): return dash.no_update
    triggered_id = ctx.triggered_id
    if triggered_id and isinstance(triggered_id, dict):
        report_id = triggered_id.get('index')
        try:
            res = requests.get(f"{API_BASE}/api/z_report/{report_id}")
            if res.status_code == 200:
                return dcc.send_string(res.text, f"ZReport_Day{report_id}.json")
        except Exception as e:
            print(f"Error downloading Z-Report JSON: {e}")
    return dash.no_update

@callback(Output("download-zreport-pdf", "data"), Input({'type': 'btn-dl-zreport-pdf', 'index': dash.ALL}, "n_clicks"), prevent_initial_call=True)
def download_z_report_pdf(n_clicks_list):
    if not any(n_clicks_list): return dash.no_update
    triggered_id = ctx.triggered_id
    if triggered_id and isinstance(triggered_id, dict):
        report_id = triggered_id.get('index')
        try:
            res = requests.get(f"{API_BASE}/api/z_report_pdf/{report_id}")
            if res.status_code == 200:
                return dcc.send_bytes(res.content, f"ZReport_Day{report_id}.pdf")
        except Exception as e:
            print(f"Error downloading Z-Report PDF: {e}")
    return dash.no_update

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8050, debug=False)
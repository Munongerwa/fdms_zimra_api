import dash
from dash import html, dcc, Input, Output, State, callback, ctx
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import requests
import json
from collections import defaultdict
from datetime import datetime, timedelta

API_BASE = "http://localhost:5000"

# ============================================================
# CUSTOM CSS (Turquoise Theme & Animations)
# ============================================================
CUSTOM_CSS = """
body { background-color: #0e0e14; color: #e2e8f0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 0; padding: 0; }
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: rgba(255,255,255,.1); border-radius: 3px; }

/* Splash Animations */
.impulsive-logo { animation: impulsive-pulse 1.4s cubic-bezier(.4,0,.2,1) infinite; }
@keyframes impulsive-pulse { 
    0% { transform: scale(1); box-shadow: 0 0 0 0 rgba(64, 224, 208, .7); } 
    50% { transform: scale(1.15); box-shadow: 0 0 30px 15px rgba(64, 224, 208, .3); } 
    100% { transform: scale(1); box-shadow: 0 0 0 0 rgba(64, 224, 208, .7); } 
}
@keyframes fadeSlideUp { from{opacity:0;transform:translateY(30px);} to{opacity:1;transform:translateY(0);} }
.fade-slide-up { animation: fadeSlideUp .9s ease-out forwards; opacity: 0; }
.fade-delay-1 { animation-delay: .4s; } .fade-delay-2 { animation-delay: .8s; } .fade-delay-3 { animation-delay: 1.2s; }
@keyframes dotBlink { 0%,80%,100%{opacity:.2;} 40%{opacity:1;} }
.dot { animation: dotBlink 1.4s infinite; font-size: 28px; color: #40E0D0; }
.dot:nth-child(2){animation-delay:.2s;} .dot:nth-child(3){animation-delay:.4s;}
@keyframes progressFill { from{width:0%;} to{width:100%;} }
.splash-progress-bar { height: 3px; background: linear-gradient(90deg, #40E0D0, #00CED1, #40E0D0); border-radius: 3px; animation: progressFill 6s ease-in-out forwards; }

/* General UI */
.btn-fiscal { background: linear-gradient(135deg, #40E0D0, #00CED1) !important; border: none !important; color: #0a0a0a !important; font-weight: 700 !important; border-radius: 12px !important; padding: 10px 20px !important; transition: transform .15s; }
.btn-fiscal:hover { transform: translateY(-2px); box-shadow: 0 6px 24px rgba(64, 224, 208, .35); color:#0a0a0a !important; }
.fiscal-input { background: rgba(255,255,255,.06) !important; border: 1px solid rgba(255,255,255,.1) !important; border-radius: 12px !important; color: #e2e8f0 !important; padding: 10px 14px !important; }
.fiscal-input:focus { border-color: #40E0D0 !important; box-shadow: 0 0 0 3px rgba(64, 224, 208, .15) !important; color: #e2e8f0 !important; }
.module-card:hover .module-arrow { transform: translateX(4px); color: #40E0D0; }
.nav-tabs .nav-link.active { color: #40E0D0 !important; border-bottom: 2px solid #40E0D0 !important; background: transparent !important; }
.dashboard-card { background: #151821 !important; border: 1px solid rgba(255,255,255,.07) !important; color: #e2e8f0 !important; transition: transform .18s ease, border-color .18s ease, box-shadow .18s ease; }
.dashboard-card:hover { transform: translateY(-3px); border-color: rgba(64,224,208,.3) !important; box-shadow: 0 12px 28px rgba(0,0,0,.2) !important; }
.card { background-color: #151821; border-color: rgba(255,255,255,.07); color: #e2e8f0; }
.card-header { background-color: rgba(255,255,255,.025); border-bottom-color: rgba(255,255,255,.07); color: #edf2f7; }
.form-label, label { color: #cbd5e1; }
.form-control, .form-select { background-color: #10131b; border-color: rgba(255,255,255,.12); color: #e2e8f0; }
.form-control:focus, .form-select:focus { background-color: #10131b; border-color: #40e0d0; color: #e2e8f0; box-shadow: 0 0 0 3px rgba(64,224,208,.15); }
.form-control::placeholder { color: #748094; }
.form-select option { background-color: #151821; color: #e2e8f0; }
.text-muted { color: #929bad !important; }
.text-primary { color: #54a8ff !important; }
.table { --bs-table-color: #dce3ed; --bs-table-bg: transparent; --bs-table-border-color: rgba(255,255,255,.08); --bs-table-hover-color: #f1f5f9; --bs-table-hover-bg: rgba(255,255,255,.04); }
.table > :not(caption) > * > * { background-color: transparent; }
.table thead th { color: #98a4b7; font-size: 11px; letter-spacing: .06em; text-transform: uppercase; }
.DateInput, .DateInput_input, .DateRangePickerInput, .DateRangePickerInput_arrow { background: #10131b !important; color: #e2e8f0 !important; }
.DateInput_input { border-color: rgba(255,255,255,.12) !important; }
.DateRangePickerInput { border: 1px solid rgba(255,255,255,.12) !important; border-radius: 10px; }
.DateRangePickerInput_arrow { color: #929bad !important; }

/* Scanner notification toasts */
.notification-toast {
    width: 100%;
    max-height: min(45vh, 360px);
    overflow: hidden;
    border: 1px solid rgba(255,255,255,.12) !important;
    border-radius: 14px !important;
    background: rgba(21,24,33,.96) !important;
    color: #e2e8f0 !important;
    box-shadow: 0 16px 40px rgba(0,0,0,.38);
    backdrop-filter: blur(14px);
}
.notification-toast .toast-header {
    gap: 8px;
    align-items: flex-start;
    border-bottom: 1px solid rgba(255,255,255,.08);
    background: rgba(255,255,255,.04);
    color: #f1f5f9;
    font-size: 13px;
    font-weight: 700;
    line-height: 1.4;
}
.notification-toast .toast-header strong {
    flex: 1 1 auto;
    min-width: 0;
    white-space: normal;
    overflow-wrap: anywhere;
}
.notification-toast .toast-header .btn-close {
    flex: 0 0 auto;
    filter: invert(1) grayscale(100%) brightness(180%);
}
.notification-toast .toast-body {
    max-height: calc(min(45vh, 360px) - 56px);
    overflow-y: auto;
    overflow-wrap: anywhere;
    white-space: pre-wrap;
    color: #cbd5e1;
    font-size: 13px;
    line-height: 1.55;
}
.notification-toast-success { border-left: 3px solid #40e0a0 !important; }
.notification-toast-warning { border-left: 3px solid #ffc857 !important; }
.notification-toast-error { border-left: 3px solid #ff6b6b !important; }
@media (max-width: 575.98px) {
    .notification-toast .toast-header,
    .notification-toast .toast-body { font-size: 12px; }
}
"""

app = dash.Dash(
    __name__,
    external_stylesheets=[
        dbc.themes.BOOTSTRAP,
        "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css",
    ],
    suppress_callback_exceptions=True,
    assets_folder='assets'
)
app.title = "AIBES FISCALISATION"

# Inject Custom CSS into the HTML head
app.index_string = f"""
<!DOCTYPE html>
<html>
<head>
    {{%metas%}}
    <title>AIBES FISCALISATION</title>
    {{%favicon%}}
    {{%css%}}
    <style>{CUSTOM_CSS}</style>
</head>
<body>
    {{%app_entry%}}
    <footer>
        {{%config%}}
        {{%scripts%}}
        {{%renderer%}}
    </footer>
</body>
</html>
"""

COLORS = {
    "primary": "#0d6efd", "info": "#0dcaf0", "dark": "#1a1a2e", "darker": "#16213e",
    "sidebar": "#0f0f1e", "sidebar_hover": "#1e1e3f", "light": "#f8f9fa",
    "success": "#198754", "danger": "#dc3545", "warning": "#ffc107",
    "text_muted": "#6c757d", "border": "#2a2a4a",
    "turquoise": "#40E0D0" 
}

SIDEBAR_WIDTH_EXPANDED = "250px"
SIDEBAR_WIDTH_COLLAPSED = "0px"

app.layout = html.Div([
    # ============================================================
    # SPLASH SCREEN (Fixed Overlay, 6 Seconds, "A" Logo)
    # ============================================================
    html.Div(
        id="splash-screen",
        children=[
            dcc.Interval(id="splash-timer", interval=6000, max_intervals=1),
            html.Div([
                html.Div("A", className="fw-bold impulsive-logo", style={
                    "background": "#40E0D0", "color": "#0a0a0a", 
                    "width": "80px", "height": "80px", "lineHeight": "80px", 
                    "textAlign": "center", "borderRadius": "16px", 
                    "fontSize": "40px", "marginBottom": "24px",
                    "margin": "0 auto"
                }),
                html.H1("AIBES FISCALISATION", className="fade-slide-up fade-delay-1", style={
                    "color": "#f1f5f9", "fontWeight": "800", "fontSize": "42px", "marginBottom": "4px"
                }),
                html.P("Fiscal Management System", className="fade-slide-up fade-delay-2", style={
                    "color": "rgba(255,255,255,.45)", "fontSize": "16px", "letterSpacing": "3px", 
                    "textTransform": "uppercase", "marginBottom": "48px"
                }),
                html.Div([html.Span(".", className="dot") for _ in range(3)], className="fade-slide-up fade-delay-3", style={"textAlign": "center"}),
                html.Div(className="splash-progress-bar", style={
                    "position": "fixed", "bottom": "40px", "left": "50%", 
                    "transform": "translateX(-50%)", "width": "200px"
                }),
            ], style={
                "display": "flex", "flexDirection": "column", "justifyContent": "center", 
                "alignItems": "center", "height": "100vh", "width": "100%"
            })
        ],
        style={
            "position": "fixed", "top": "0", "left": "0", 
            "width": "100vw", "height": "100vh", 
            "backgroundColor": "#0b0b10", # Solid background to hide everything behind
            "zIndex": 9999, "display": "flex",
            "overflow": "hidden"
        }
    ),
    # Session storage ensures this persists across page reloads/navigations in the same tab
    dcc.Store(id="splash-shown", data=False, storage_type='session'),

    html.Div(
        id="main-app", 
        children=[
            html.Div(id="appbar", children=[
                html.Div([
                    html.I(id="menu-icon", className="bi bi-list", style={"fontSize": "22px", "cursor": "pointer", "color": "white", "marginRight": "15px", "padding": "8px", "borderRadius": "4px"}),
                    # Updated Appbar Logo to match Splash Screen
                    html.Div("A", style={
                        "background": "#40E0D0", "color": "#0a0a0a",
                        "width": "32px", "height": "32px", "lineHeight": "32px",
                        "textAlign": "center", "borderRadius": "8px",
                        "fontSize": "18px", "fontWeight": "bold", "marginRight": "10px"
                    }),
                    html.H4("AIBES FISCALISATION", style={"color": "white", "margin": 0, "fontSize": "20px", "fontWeight": "600"})
                ], style={"display": "flex", "alignItems": "center"}),
                html.Div(id="appbar-status-display", children=[dbc.Spinner(size="sm", color="light"), " Connecting..."], style={"color": "white", "display": "flex", "alignItems": "center", "gap": "10px", "fontSize": "14px", "backgroundColor": "rgba(255,255,255,0.1)", "padding": "8px 16px", "borderRadius": "20px"})
            ], style={"position": "fixed", "top": 0, "left": 0, "width": "100%", "height": "60px", "backgroundColor": COLORS["dark"], "display": "flex", "justifyContent": "space-between", "alignItems": "center", "padding": "0 20px", "zIndex": 1000, "boxShadow": "0 2px 10px rgba(0,0,0,0.3)", "borderBottom": f"1px solid {COLORS['border']}"}),

            html.Div(id="sidebar", children=[html.Div(id="sidebar-nav-items", children=[], style={"width": "100%"})], style={"position": "fixed", "top": "60px", "left": 0, "bottom": 0, "width": SIDEBAR_WIDTH_COLLAPSED, "backgroundColor": COLORS["sidebar"], "padding": "10px 0", "transition": "width 0.3s ease", "overflow": "hidden", "zIndex": 900, "borderRight": f"1px solid {COLORS['border']}"}),
            html.Div(id="page-content", style={"marginLeft": SIDEBAR_WIDTH_COLLAPSED, "marginTop": "60px", "padding": "20px", "transition": "margin-left 0.3s ease", "minHeight": "calc(100vh - 60px)", "backgroundColor": "#0e0e14"}),

            dcc.Location(id="url", refresh=False),
            dcc.Store(id="sidebar-state", data="collapsed"),
            dcc.Interval(id="status-refresh", interval=60000),
            dcc.Interval(id="scanner-refresh", interval=3000, n_intervals=0),
            
            # Download Components
            dcc.Download(id="download-pdf"),
            dcc.Download(id="download-zreport"),
            dcc.Download(id="download-zreport-pdf"),
            dcc.Download(id="download-success-csv"),
            
            # Toast Notifications & Polling Components
            html.Div([
                dbc.Toast(id="toast-success", header="✅ Successfully Processed", is_open=False, duration=5000, class_name="notification-toast notification-toast-success"),
                dbc.Toast(id="toast-warning", header="⚠️ Processing Failed", is_open=False, duration=7000, class_name="notification-toast notification-toast-warning"),
                dbc.Toast(id="toast-error", header="❌ System Error", is_open=False, duration=7000, class_name="notification-toast notification-toast-error"),
            ], style={
                "position": "fixed", 
                "top": "clamp(16px, 8vh, 80px)", 
                "right": "clamp(12px, 2vw, 20px)", 
                "zIndex": 9999, 
                "display": "flex", 
                "flexDirection": "column", 
                "gap": "10px", 
                "width": "min(420px, calc(100vw - 24px))"
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
        style={"display": "none"} # Hidden until splash finishes
    )
])

# ============================================================
# SPLASH SCREEN CALLBACK
# ============================================================
@callback(
    [Output("splash-screen", "style"), Output("main-app", "style"), Output("splash-shown", "data")], 
    Input("splash-timer", "n_intervals"), 
    State("splash-shown", "data")
)
def hide_splash(n, already_shown):
    """
    If already_shown is True (from session store), keep splash hidden immediately.
    If not shown yet, wait for timer (n > 0) then hide.
    """
    if already_shown:
        return {"display": "none"}, {"display": "block"}, True
    
    if n is not None and n > 0:
        return {"display": "none"}, {"display": "block"}, True
        
    return {"display": "flex"}, {"display": "none"}, False

# ============================================================
# SIDEBAR & NAVIGATION LOGIC
# ============================================================
def build_sidebar_items(state, current_path):
    items = [
        {"path": "/", "icon": "bi-house-door", "label": "Home"},
        {"path": "/transactions", "icon": "bi-receipt", "label": "Transactions"},
        {"path": "/fiscal-day", "icon": "bi-calendar3", "label": "Fiscal Day"},
        {"path": "/scanner", "icon": "bi-folder2-open", "label": "Folder Scanner"},
        {"path": "/analytics", "icon": "bi-graph-up-arrow", "label": "Analytics"},
        {"path": "/pos", "icon": "bi-shop", "label": "POS"},
        {"path": "/audit", "icon": "bi-clipboard-data", "label": "Audit & Z-Reports"}
    ]
    
    # Define Theme Colors
    default_color = "#ffffff"  # White for inactive options
    active_color = "#40E0D0"   # Turquoise Blue for the selected option
    
    nav_items = []
    for item in items:
        is_active = current_path == item["path"]
        active_class = "sidebar-nav-link active" if is_active else "sidebar-nav-link"
        
        # Determine colors and font weight based on active state
        icon_color = active_color if is_active else default_color
        text_color = active_color if is_active else default_color
        text_weight = "bold" if is_active else "normal"
        
        if state == "collapsed":
            nav_items.append(html.A(
                [html.I(className=f"bi {item['icon']}", style={"color": icon_color})],
                href=item["path"], 
                className=active_class, 
                style={"display": "block", "padding": "15px 0", "textAlign": "center", "textDecoration": "none"}, 
                title=item["label"]
            ))
        else:
            nav_items.append(html.A(
                [
                    html.I(className=f"bi {item['icon']}", style={"color": icon_color, "width": "20px"}),
                    html.Span(item["label"], style={"marginLeft": "10px", "color": text_color, "fontWeight": text_weight})
                ], 
                href=item["path"], 
                className=active_class,
                style={"display": "flex", "alignItems": "center", "padding": "12px 20px", "textDecoration": "none"}
            ))
            
    return html.Div(nav_items, style={"display": "flex", "flexDirection": "column", "width": "100%"})

@callback([Output("sidebar", "style"), Output("page-content", "style"), Output("sidebar-state", "data"),  Output("sidebar-nav-items", "children")], [Input("menu-icon", "n_clicks"), Input("url", "pathname")], [State("sidebar-state", "data")])
def toggle_sidebar(n_clicks, pathname, current_state):
    if pathname is None: pathname = "/"
    new_state = "expanded" if (n_clicks is not None and n_clicks > 0 and current_state == "collapsed") else "collapsed" if (n_clicks is not None and n_clicks > 0) else current_state
    sidebar_style = {
        "position": "fixed", 
        "top": "60px", 
        "left": 0, 
        "bottom": 0, 
        "width": SIDEBAR_WIDTH_EXPANDED if new_state == "expanded" else SIDEBAR_WIDTH_COLLAPSED, 
        "backgroundColor": COLORS["sidebar"], 
        "padding": "10px 0", 
        "transition": "width 0.3s ease", 
        "overflow": "hidden", 
        "zIndex": 900, 
        "borderRight": f"1px solid {COLORS['border']}", 
        "display": "flex", 
        "flexDirection": "column",
        "overflowY": "auto"
    }
    content_style = {"marginLeft": SIDEBAR_WIDTH_EXPANDED if new_state == "expanded" else SIDEBAR_WIDTH_COLLAPSED, "marginTop": "60px", "padding": "20px", "transition": "margin-left 0.3s ease", "minHeight": "calc(100vh - 60px)", "backgroundColor": "#0e0e14"}
    return sidebar_style, content_style, new_state, build_sidebar_items(new_state, pathname)

@callback(Output("appbar-status-display", "children"), Input("status-refresh", "n_intervals"))
def update_appbar_status(n):
    try:
        res = requests.post(f"{API_BASE}/api/status", json={}, timeout=5)
        data = res.json().get("zimra_response", {})
        status = data.get("fiscalDayStatus", "Unknown")
        color = COLORS["success"] if "Opened" in status else COLORS["text_muted"] if "Closed" in status else COLORS["warning"]
        icon = "bi-check-circle" if "Opened" in status else "bi-lock" if "Closed" in status else "bi-exclamation-triangle"
        return [html.I(className=f"bi {icon}", style={"color": color}), html.Span(f"Device: {status}", style={"fontWeight": "bold"})]
    except Exception: return [html.I(className="bi bi-wifi-off", style={"color": COLORS["danger"]}), html.Span("Offline", style={"color": COLORS["danger"]})]

@callback(Output("page-content", "children"), Input("url", "pathname"))
def render_page(pathname):
    if pathname == "/transactions": return get_transactions_page()
    elif pathname == "/fiscal-day": return get_fiscal_day_page()
    elif pathname == "/scanner": return get_scanner_page()
    elif pathname == "/analytics": return get_analytics_page()
    elif pathname == "/pos": return get_pos_page()
    elif pathname == "/audit": return get_audit_page()
    else: return get_home_page()

# ============================================================
# PAGE CONTENT FUNCTIONS
# ============================================================
def page_layout(title, description, icon, children):
    return html.Div([
        html.Div([
            html.Div(
                html.I(className=f"bi {icon}", style={"fontSize": "23px", "color": "#40e0a0"}),
                style={
                    "width": "52px", "height": "52px", "display": "flex",
                    "alignItems": "center", "justifyContent": "center",
                    "borderRadius": "15px", "backgroundColor": "rgba(64,224,160,.11)",
                    "flexShrink": 0,
                },
            ),
            html.Div([
                html.H1(title, style={
                    "fontSize": "clamp(23px, 2.5vw, 30px)", "fontWeight": "750",
                    "letterSpacing": "-.025em", "color": "#f1f5f9", "margin": "0 0 5px",
                }),
                html.P(description, style={"fontSize": "13px", "color": "#929bad", "margin": 0}),
            ]),
        ], style={
            "display": "flex", "alignItems": "center", "gap": "16px",
            "marginBottom": "28px",
        }),
        *children,
    ], style={
        "backgroundColor": "#0e0e14", "color": "#e2e8f0",
        "margin": "-20px", "padding": "28px", "minHeight": "calc(100vh - 60px)",
    })

def get_home_page():
    try:
        res = requests.get(f"{API_BASE}/api/device_details", timeout=5)
        details = res.json()
    except: 
        details = {"company_name": "Unknown", "device_id": "N/A", "serial_number": "N/A", "vat_number": "N/A", "taxpayer_tin": "N/A", "fiscal_day_no": "N/A", "receipt_global_no": "N/A", "status": "Offline"}
    
    try:
        res_license = requests.get(f"{API_BASE}/api/license_status", timeout=2)
        license_data = res_license.json()
    except:
        license_data = {"status": "ERROR", "message": "Could not fetch license status.", "is_valid": False, "days_left": 0}
    
    try:
        res_machine = requests.get(f"{API_BASE}/api/machine_id", timeout=2)
        machine_data = res_machine.json()
        machine_id = machine_data.get("machine_id", "N/A")
    except:
        machine_id = "N/A"

    status_color = COLORS["success"] if "Active" in details.get("status", "") else COLORS["danger"]
    license_status_color = COLORS["success"] if license_data.get("status") == "VALID" else COLORS["danger"]
    
    days_left = license_data.get('days_left', 0)
    if license_data.get('status') == 'VALID':
        days_text = f" {days_left} Days Left"
        days_color = COLORS["success"] if days_left > 7 else (COLORS["warning"] if days_left > 0 else COLORS["danger"])
    else:
        days_text = "⏳ Expired"
        days_color = COLORS["danger"]

    company_name = details.get("company_name") or "Your company"
    hour = datetime.now().hour
    greeting = "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"
    today = datetime.now().strftime("%A, %B %d, %Y")

    def make_card(title, value, icon, color):
        return dbc.Col(
            dbc.Card(
                dbc.CardBody([
                    html.Div(
                        html.I(className=f"bi {icon}", style={"fontSize": "17px", "color": color}),
                        style={
                            "width": "36px", "height": "36px", "display": "flex",
                            "alignItems": "center", "justifyContent": "center",
                            "borderRadius": "11px", "backgroundColor": f"{color}20",
                            "flexShrink": 0,
                        },
                    ),
                    html.Div([
                        html.Div(title, style={
                            "fontSize": "9px", "fontWeight": "700", "letterSpacing": ".07em",
                            "textTransform": "uppercase", "color": "#8993a5", "marginBottom": "4px",
                        }),
                        html.Div(str(value), style={
                            "fontSize": "14px", "fontWeight": "650", "color": "#f1f5f9",
                            "overflowWrap": "anywhere",
                        }),
                    ], style={"minWidth": 0}),
                ], style={"display": "flex", "alignItems": "center", "gap": "11px", "padding": "12px 14px"}),
                className="dashboard-card h-100",
                style={"borderRadius": "13px"},
            ),
            xs=12, sm=6, xl=3, className="mb-2",
        )

    def section_heading(title, description):
        return html.Div([
            html.H4(title, style={"fontSize": "16px", "fontWeight": "700", "color": "#edf2f7", "margin": 0}),
            html.P(description, style={"fontSize": "11px", "color": "#8791a3", "margin": "3px 0 0"}),
        ], className="mb-2")

    return html.Div([
        html.Div([
            html.Div([
                html.Div(greeting, style={
                    "fontSize": "9px", "fontWeight": "800", "letterSpacing": ".14em",
                    "textTransform": "uppercase", "color": "#e0f0ea", "marginBottom": "5px",
                }),
                html.H1(f"Welcome back, {company_name}", style={
                    "fontSize": "clamp(20px, 2.2vw, 27px)", "fontWeight": "750",
                    "letterSpacing": "-.03em", "color": "#f1f5f9", "margin": "0 0 4px",
                }),
                html.P(today, style={"fontSize": "11px", "color": "#d1d8e2", "margin": 0}),
            ]),
            html.Div(
                html.I(className="bi bi-hand-wave-fill", style={"fontSize": "28px", "color": "#40e0a0"}),
                style={
                    "width": "52px", "height": "52px", "display": "flex", "alignItems": "center",
                    "justifyContent": "center", "borderRadius": "16px",
                    "backgroundColor": "rgba(255,200,87,.10)", "flexShrink": 0,
                },
            ),
        ], style={
            "display": "flex", "alignItems": "center", "justifyContent": "space-between",
            "gap": "16px", "padding": "16px 20px", "marginBottom": "16px",
            "border": "1px solid rgba(64,224,160,.16)", "borderRadius": "20px",
            "background": "linear-gradient(115deg, rgba(22,43,39,.96), rgba(17,21,31,.98) 68%)",
        }),
        html.Div([
            html.Div([
                html.Div([
                    html.Span(className="bi bi-circle-fill", style={
                        "fontSize": "9px", "color": status_color,
                    }),
                    html.Span("DEVICE", style={
                        "fontSize": "9px", "fontWeight": "800", "letterSpacing": ".1em",
                        "color": "#8993a5",
                    }),
                ], style={"display": "flex", "alignItems": "center", "gap": "7px", "marginBottom": "5px"}),
                html.Div(details.get("status", "Unknown"), style={
                    "fontSize": "16px", "fontWeight": "700", "color": "#f1f5f9",
                }),
            ]),
            html.Span(details.get("status", "Unknown"), style={
                "padding": "5px 9px", "borderRadius": "999px",
                "color": status_color, "backgroundColor": f"{status_color}18",
                "fontSize": "10px", "fontWeight": "700",
            }),
        ], className="dashboard-card mb-2", style={
            "display": "flex", "alignItems": "center", "justifyContent": "space-between",
            "gap": "12px", "padding": "11px 16px", "borderRadius": "13px",
        }),

        section_heading("Device overview", "Your registered fiscal device and company details"),
        dbc.Row([
            make_card("Company name", company_name, "bi-building", "#40e0a0"),
            make_card("Device ID", details.get("device_id", "N/A"), "bi-cpu", "#54a8ff"),
            make_card("Serial number", details.get("serial_number", "N/A"), "bi-upc-scan", "#ffc857"),
            make_card("VAT number", details.get("vat_number", "N/A"), "bi-receipt", "#b38cff"),
            make_card("Taxpayer TIN", details.get("taxpayer_tin", "N/A"), "bi-person-vcard", "#ff719a"),
            make_card("Machine ID", machine_id, "bi-pc-display", "#36c9d5"),
            make_card("Current fiscal day", details.get("fiscal_day_no", "N/A"), "bi-calendar3", "#54a8ff"),
            make_card("Receipt global no.", details.get("receipt_global_no", "N/A"), "bi-123", "#40e0a0"),
        ], className="mb-2"),

        section_heading("License", "Manage your fiscalisation license"),
        dbc.Row([
            dbc.Col(dbc.Card([
                dbc.CardBody([
                    html.Div([
                        html.Div(
                            html.I(className="bi bi-shield-check", style={"fontSize": "17px", "color": license_status_color}),
                            style={
                                "width": "36px", "height": "36px", "display": "flex",
                                "alignItems": "center", "justifyContent": "center",
                                "borderRadius": "11px", "backgroundColor": f"{license_status_color}20",
                                "flexShrink": 0,
                            },
                        ),
                        html.Div([
                            html.H6("License status", style={
                                "fontSize": "9px", "fontWeight": "700", "letterSpacing": ".08em",
                                "textTransform": "uppercase", "color": "#8993a5", "marginBottom": "3px",
                            }),
                            html.Div(license_data.get("status", "UNKNOWN"), style={
                                "fontSize": "14px", "fontWeight": "700", "color": license_status_color,
                            }),
                            html.Small(license_data.get("message", ""), style={"color": "#929bad", "display": "block", "fontSize": "10px"}),
                            html.Small(days_text, style={
                                "color": days_color, "fontWeight": "700", "fontSize": "10px",
                                "display": "block", "marginTop": "2px",
                            }),
                        ], style={"minWidth": 0}),
                    ], style={"display": "flex", "alignItems": "center", "gap": "11px"})
                ])
            ], className="dashboard-card h-100", style={"borderRadius": "13px"}), md=6, xl=4, className="mb-2"),

            dbc.Col(dbc.Card([
                dbc.CardBody([
                    html.H6("Activate license", style={
                        "fontSize": "13px", "fontWeight": "700", "color": "#edf2f7", "marginBottom": "7px",
                    }),
                    dbc.InputGroup([
                        dbc.Input(id="input-license-key", placeholder="Paste license key here...", type="text", className="fiscal-input"),
                        dbc.Button("Activate", id="btn-activate-license", className="btn-fiscal")
                    ]),
                    html.Div(id="activation-output", className="mt-1", style={"color": "#cbd5e1"}),
                ], style={"padding": "12px 14px"})
            ], className="dashboard-card h-100", style={"borderRadius": "13px"}), md=6, xl=8, className="mb-2")
        ]),

        section_heading("Quick actions", "Jump straight into the tools you use most"),
        dbc.Row([
            dbc.Col(dbc.Card(dbc.CardBody([
                html.Div(html.I(className="bi bi-file-earmark-plus", style={"fontSize": "17px", "color": "#54a8ff"}), style={
                    "width": "34px", "height": "34px", "display": "flex", "alignItems": "center",
                    "justifyContent": "center", "borderRadius": "10px", "backgroundColor": "rgba(84,168,255,.12)",
                    "marginBottom": "8px",
                }),
                html.H5("New invoice", style={"fontSize": "13px", "fontWeight": "700", "color": "#edf2f7", "marginBottom": "3px"}),
                html.P("Create a new fiscal invoice", style={"fontSize": "11px", "color": "#929bad", "marginBottom": "9px"}),
                dbc.Button("Go to transactions", href="/transactions", className="btn-fiscal w-100", size="sm"),
            ], style={"padding": "11px 13px"}), className="dashboard-card h-100", style={"borderRadius": "13px"}), md=4, className="mb-2"),
            dbc.Col(dbc.Card(dbc.CardBody([
                html.Div(html.I(className="bi bi-folder2-open", style={"fontSize": "17px", "color": "#40e0a0"}), style={
                    "width": "34px", "height": "34px", "display": "flex", "alignItems": "center",
                    "justifyContent": "center", "borderRadius": "10px", "backgroundColor": "rgba(64,224,160,.12)",
                    "marginBottom": "8px",
                }),
                html.H5("Folder scanner", style={"fontSize": "13px", "fontWeight": "700", "color": "#edf2f7", "marginBottom": "3px"}),
                html.P("Automatically process receipts", style={"fontSize": "11px", "color": "#929bad", "marginBottom": "9px"}),
                dbc.Button("Open scanner", href="/scanner", className="btn-fiscal w-100", size="sm"),
            ], style={"padding": "11px 13px"}), className="dashboard-card h-100", style={"borderRadius": "13px"}), md=4, className="mb-2"),
            dbc.Col(dbc.Card(dbc.CardBody([
                html.Div(html.I(className="bi bi-graph-up-arrow", style={"fontSize": "17px", "color": "#b38cff"}), style={
                    "width": "34px", "height": "34px", "display": "flex", "alignItems": "center",
                    "justifyContent": "center", "borderRadius": "10px", "backgroundColor": "rgba(179,140,255,.12)",
                    "marginBottom": "8px",
                }),
                html.H5("Analytics", style={"fontSize": "13px", "fontWeight": "700", "color": "#edf2f7", "marginBottom": "3px"}),
                html.P("Explore your fiscal insights", style={"fontSize": "11px", "color": "#929bad", "marginBottom": "9px"}),
                dbc.Button("Open analytics", href="/analytics", className="btn-fiscal w-100", size="sm"),
            ], style={"padding": "11px 13px"}), className="dashboard-card h-100", style={"borderRadius": "13px"}), md=4, className="mb-2"),
        ])
    ], style={
        "backgroundColor": "#0e0e14", "color": "#e2e8f0",
        "margin": "-20px", "padding": "16px", "minHeight": "calc(100vh - 60px)",
    })

def get_scanner_page():
    return page_layout("Folder scanner", "Configure receipt processing and review scanner activity.", "bi-folder2-open", [
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader(html.H5("Scanner control & settings", className="mb-0")),
                    dbc.CardBody([
                        html.Label("Folder Path:", className="fw-bold mb-1"),
                        dbc.Input(id="scanner-folder-path", value=r"C:\Receipt", placeholder="Folder Path", className="mb-3"),
                        
                        html.Label("Receipt Template:", className="fw-bold mb-1"),
                        dbc.Select(id="scanner-template", options=[
                            {"label": "Melivo POS (Default)", "value": "melivo"},
                            {"label": "FEEDMIX POS", "value": "feedmix"},
                            {"label": "QuickBooks POS", "value": "quickbooks"},
                            {"label": "AIBES EXCL", "value": "aibes"},
                            {"label": "AIBES INCL", "value": "aibes_incl"}
                        ], value="aibes_incl", className="mb-3"),
                        html.Label("Default Print Format:", className="fw-bold mb-1"),
                        dbc.Select(id="scanner-print-format", options=[
                            {"label": "A4 Invoice (InvoiceA4)", "value": "InvoiceA4"},
                            {"label": "80mm Thermal Receipt (Receipt48)", "value": "Receipt48"}
                        ], value="InvoiceA4", className="mb-3"),
                        
                        dbc.Checklist(
                            options=[{"label": "Process PDF Files (Extract, Fiscalize & Stamp QR)", "value": "pdfs"}],
                            value=[],
                            id="scanner-process-pdfs",
                            switch=True,
                            className="mb-3"
                        ),
                        
                        dbc.Row([
                            dbc.Col(dbc.Button([html.I(className="bi bi-play-fill me-2"), "Start scanning"], id="btn-start-scanner", className="btn-fiscal w-100", size="lg"), md=6),
                            dbc.Col(dbc.Button([html.I(className="bi bi-stop-fill me-2"), "Stop scanning"], id="btn-stop-scanner", color="danger", className="w-100", size="lg"), md=6),
                        ], className="mb-3"),
                        
                        dbc.Row([
                            dbc.Col(html.A(dbc.Button([html.I(className="bi bi-printer me-2"), "Print test 80mm receipt"], color="info", className="w-100"), href="/api/print_test_80mm", target="_blank"), md=12)
                        ], className="mb-3"),
                        
                        html.A(
                            dbc.Button([html.I(className="bi bi-box-arrow-up-right me-2"), "Verify receipt on ZIMRA portal"], color="secondary", className="w-100 mb-3"),
                            href="https://fdms.zimra.co.zw/Receipt/Find", target="_blank"  
                        ),
                        html.Div(id="scanner-status-display", className="mt-3")
                    ])
                ], className="dashboard-card", style={"borderRadius": "16px"})
            ], md=6),
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader(html.Div([
                        html.H5("Scanner history log", className="mb-0 d-inline-block"),
                        dbc.Button([html.I(className="bi bi-trash3 me-1"), "Clear history"], id="btn-clear-history", color="warning", size="sm", className="float-end")
                    ])), 
                    dbc.CardBody([
                        html.Div(id="scanner-log-display", style={"maxHeight": "600px", "overflow": "auto", "backgroundColor": "#10131b", "padding": "15px", "borderRadius": "12px", "fontSize": "12px"})
                    ])
                ], className="dashboard-card", style={"borderRadius": "16px"})
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
            return data.get("folder_path", r"C:\Receipt"), data.get("template", "aibes_incl"), data.get("print_format", "InvoiceA4"), pdf_val
        except:
            return r"C:\Receipt", "aibes_incl", "InvoiceA4", []
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
    try:
        res = requests.get(f"{API_BASE}/api/scanner_history", params={"limit": 1}, timeout=2)
        logs = res.json()
        if logs and isinstance(logs, list):
            latest = logs[0]
            current_id = latest.get('id', 0)
            
            if current_id > last_id:
                status = latest.get('status', 'INFO')
                msg = str(latest.get('message') or '')
                
                if status == 'SUCCESS':
                    return True, f"✅ Successfully Processed: {latest.get('timestamp', '')}", msg, False, "", "", False, "", "", current_id
                elif status in ['FAILED', 'ERROR'] or 'VALIDATION FAILED' in msg or 'ZIMRA ERROR' in msg:
                    header = "⚠️ Processing Failed" if status == 'FAILED' else " System Error"
                    return False, "", "", True, header, msg, False, "", "", current_id
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
                    
                    log_content.append(html.Span(text_part, style={"color": "#dce3ed", "whiteSpace": "pre-wrap", "fontFamily": "monospace"}))
                    verify_btn = html.A(
                        dbc.Button([html.I(className="bi bi-shield-check me-1"), "Verify on ZIMRA"], color="primary", size="sm", className="ms-2"),
                        href=url_part, target="_blank", style={"textDecoration": "none"}
                    )
                else:
                    log_content.append(html.Span(msg, style={"color": "#dce3ed", "whiteSpace": "pre-wrap", "fontFamily": "monospace"}))

                row_content = [
                    html.Span(f"[{time_str}] ", style={"color": "#929bad", "marginRight": "8px", "fontFamily": "monospace"}),
                    *log_content
                ]
                if verify_btn:
                    row_content.append(verify_btn)

                formatted_logs.append(html.Div(
                    row_content,
                    style={"marginBottom": "8px", "padding": "12px", "backgroundColor": "#151821", "border": "1px solid rgba(255,255,255,.06)", "borderRadius": "10px", "fontSize": "13px", "borderLeft": f"3px solid {border_color}", "display": "flex", "alignItems": "center", "flexWrap": "wrap"}
                ))
        
        return html.Div(formatted_logs)
    except Exception as e:
        return f"Unable to connect to scanner: {str(e)}"

def get_analytics_page():
    return page_layout("Sales analytics", "Track sales, tax, product performance, and peak business hours.", "bi-graph-up-arrow", [
        
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
        ], className="mb-4 dashboard-card", style={"borderRadius": "16px"}),
        
        dbc.Card([
            dbc.CardHeader(html.H5("USD vs ZWG Performance", className="mb-0")),
            dbc.CardBody([
                dcc.Graph(id="analytics-main-chart", style={"height": "400px"})
            ])
        ], className="mb-4 dashboard-card", style={"borderRadius": "16px"}),
        
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
        ], className="mb-4 dashboard-card", style={"borderRadius": "16px"}),
        
        dbc.Card([
            dbc.CardHeader(html.H5("Peak Business Hours (24h)", className="mb-0")),
            dbc.CardBody([
                dcc.Graph(id="busy-hours-chart", style={"height": "300px"})
            ])
        ], className="dashboard-card", style={"borderRadius": "16px"}),
        
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
            template='plotly_dark',
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#dce3ed"),
            xaxis=dict(gridcolor="rgba(255,255,255,.08)"),
            yaxis=dict(gridcolor="rgba(255,255,255,.08)"),
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
            template='plotly_dark',
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#dce3ed"),
            xaxis=dict(gridcolor="rgba(255,255,255,.08)"),
            yaxis=dict(gridcolor="rgba(255,255,255,.08)"),
            height=300
        )
        
        return fig, usd_qty_table, usd_amt_table, zwg_qty_table, zwg_amt_table, busy_fig
    except Exception as e:
        empty_fig = go.Figure().update_layout(title=f"Error: {str(e)}", height=400)
        error_msg = html.P(f"Error: {str(e)}", className="text-danger text-center p-3")
        return empty_fig, error_msg, error_msg, error_msg, error_msg, empty_fig

def get_fiscal_day_page():
    return page_layout("Fiscal day management", "Open and close fiscal days and generate the daily Z-Report.", "bi-calendar3", [
        dbc.Row([
            dbc.Col(dbc.Card([dbc.CardHeader(html.H5([html.I(className="bi bi-unlock me-2"), "Open new fiscal day"], className="mb-0")), dbc.CardBody([html.P("Start a new fiscal day to begin issuing receipts.", className="text-muted"), dbc.Input(id="open-day-no", type="number", placeholder="Fiscal day no. (optional)", className="mb-3"), dbc.Button([html.I(className="bi bi-play-fill me-2"), "Open fiscal day"], id="btn-open-day", className="btn-fiscal w-100", size="lg"), html.Div(id="open-day-output", className="mt-3")])], className="dashboard-card h-100", style={"borderRadius": "16px"}), md=6, className="mb-3"),
            dbc.Col(dbc.Card([dbc.CardHeader(html.H5([html.I(className="bi bi-lock me-2"), "Close current fiscal day"], className="mb-0")), dbc.CardBody([html.P("Close the current fiscal day automatically and generate a Z-Report.", className="text-muted"), dbc.Button([html.I(className="bi bi-check2-circle me-2"), "Close fiscal day"], id="btn-close-day", color="danger", className="w-100", size="lg"), html.Div(id="close-day-output", className="mt-3")])], className="dashboard-card h-100", style={"borderRadius": "16px"}), md=6, className="mb-3"),
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
    return page_layout("Transactions", "Submit fiscal invoices and credit notes to the fiscal device.", "bi-receipt", [
        dbc.Tabs([dbc.Tab(label="Submit invoice", tab_id="tab-invoice", labelClassName="fw-bold"), dbc.Tab(label="Credit note", tab_id="tab-credit", labelClassName="fw-bold")], id="trans-tabs", active_tab="tab-invoice", className="mb-3"),
        html.Div(id="trans-tab-content")
    ])

@callback(Output("trans-tab-content", "children"), Input("trans-tabs", "active_tab"))
def render_trans_tab(tab):
    print_options = [{"label": "A4 Invoice", "value": "InvoiceA4"}, {"label": "Receipt 48mm", "value": "Receipt48"}]
    if tab == "tab-credit":
        return dbc.Card([dbc.CardHeader(html.H5([html.I(className="bi bi-arrow-counterclockwise me-2"), "Credit note"], className="mb-0")), dbc.CardBody([
            dbc.Row([dbc.Col(dbc.Input(id="cn-no", placeholder="CN No", value="CN-001"), md=4), dbc.Col(dbc.Input(id="cn-orig", placeholder="Original Inv No", value="INV-001"), md=4), dbc.Col(dbc.Input(id="cn-total", type="number", value=115.50, placeholder="Total"), md=4)], className="mb-3"),
            dbc.Row([dbc.Col(dbc.Input(id="cn-qty", type="number", value=2, placeholder="Quantity"), md=4), dbc.Col(dbc.Select(id="cn-print-format", options=print_options, value="InvoiceA4"), md=4)], className="mb-3"),
            dbc.Button([html.I(className="bi bi-send me-2"), "Submit credit note"], id="btn-cn", color="warning", className="w-100", size="lg"),
            html.Div(id="cn-out", className="mt-3")
        ])], className="dashboard-card", style={"borderRadius": "16px"})
    else:
        return dbc.Card([dbc.CardHeader(html.H5([html.I(className="bi bi-receipt me-2"), "Fiscal invoice"], className="mb-0")), dbc.CardBody([
            dbc.Row([dbc.Col(dbc.Input(id="inv-no", placeholder="Invoice No", value="INV-001"), md=4), dbc.Col(dbc.Select(id="inv-curr", options=[{"label": "USD", "value": "USD"}, {"label": "ZWG", "value": "ZWG"}], value="USD"), md=4), dbc.Col(dbc.Input(id="inv-total", type="number", value=115.50, placeholder="Total"), md=4)], className="mb-3"),
            dbc.Row([dbc.Col(dbc.Input(id="inv-qty", type="number", value=2, placeholder="Quantity"), md=4), dbc.Col(dbc.Select(id="inv-print-format", options=print_options, value="InvoiceA4"), md=4)], className="mb-3"),
            dbc.Button([html.I(className="bi bi-send me-2"), "Submit invoice"], id="btn-inv", className="btn-fiscal w-100", size="lg"),
            html.Div(id="inv-out", className="mt-3")
        ])], className="dashboard-card", style={"borderRadius": "16px"})

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
                dbc.Alert([html.I(className="bi bi-check-circle me-2"), f"Success! Verification Code: {data.get('VerificationCode')}"], color="success"),
                dbc.Row([dbc.Col(html.A(dbc.Button([html.I(className="bi bi-box-arrow-up-right me-2"), "Verify on ZIMRA"], color="success", className="w-100"), href=qr_url, target="_blank"), width=4),
                         dbc.Col(dbc.Button([html.I(className="bi bi-file-earmark-pdf me-2"), "Download PDF"], id="btn-trigger-download-inv", color="primary", className="w-100", n_clicks=0), width=4),
                         dbc.Col(dbc.Button([html.I(className="bi bi-printer me-2"), "Print receipt"], id="btn-print-inv-ui", color="info", className="w-100"), width=4)], className="mt-3")
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
                dbc.Alert([html.I(className="bi bi-check-circle me-2"), f"Success! Verification Code: {data.get('VerificationCode')}"], color="success"),
                dbc.Row([dbc.Col(html.A(dbc.Button([html.I(className="bi bi-box-arrow-up-right me-2"), "Verify on ZIMRA"], color="success", className="w-100"), href=qr_url, target="_blank"), width=4),
                         dbc.Col(dbc.Button([html.I(className="bi bi-file-earmark-pdf me-2"), "Download PDF"], id="btn-trigger-download-cn", color="primary", className="w-100", n_clicks=0), width=4),
                         dbc.Col(dbc.Button([html.I(className="bi bi-printer me-2"), "Print receipt"], id="btn-print-cn-ui", color="info", className="w-100"), width=4)], className="mt-3")
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
        return dcc.Markdown(" ", dangerously_allow_html=True)
    return ""

def build_zimra_receipt_table(receipts):
    rows = []
    totals_by_currency = {}
    for receipt in receipts:
        status = receipt.get("zimra_status", "Unverified")
        badge_color = "success" if status == "Valid" else "danger" if status == "Invalid" else "warning"
        currency = receipt.get("receipt_currency") or "USD"
        try:
            amount = float(receipt.get("total_amount") or 0)
        except (TypeError, ValueError):
            amount = 0.0
        totals_by_currency[currency] = totals_by_currency.get(currency, 0.0) + amount
        amount_text = f"{currency} {amount:,.2f}"
        qr_url = receipt.get("qr_code")
        rows.append(html.Tr([
            html.Td(receipt.get("fiscal_day_no") or "N/A"),
            html.Td(receipt.get("invoice_no") or "N/A"),
            html.Td(receipt.get("customer_name") or "N/A"),
            html.Td(receipt.get("customer_vat") or "N/A"),
            html.Td(receipt.get("customer_tin") or "N/A"),
            html.Td(amount_text),
            html.Td(receipt.get("created_at") or "N/A"),
            html.Td(receipt.get("verification_code") or "N/A"),
            html.Td(dbc.Badge(status, color=badge_color, className="px-2 py-1")),
            html.Td(html.Small(receipt.get("zimra_detail") or "", className="text-muted")),
            html.Td(html.A(
                [html.I(className="bi bi-box-arrow-up-right me-1"), "Open QR"],
                href=qr_url, target="_blank", rel="noopener noreferrer",
            ) if qr_url else "N/A"),
        ]))

    if not rows:
        rows.append(html.Tr([
            html.Td("No receipts match the selected filters.", colSpan=11,
                    className="text-muted text-center py-4"),
        ]))

    total_text = " | ".join(
        f"{currency} {amount:,.2f}"
        for currency, amount in sorted(totals_by_currency.items())
    ) or "—"
    return dbc.Table([
        html.Thead(html.Tr([
            html.Th("Fiscal day"), html.Th("Invoice no."), html.Th("Customer name"),
            html.Th("Customer VAT"), html.Th("Customer TIN"), html.Th("Amount"),
            html.Th("Submitted"), html.Th("Verification code"), html.Th("ZIMRA status"),
            html.Th("ZIMRA response"), html.Th("QR link"),
        ])),
        html.Tbody(rows),
        html.Tfoot(html.Tr([
            html.Th(f"TOTAL · {len(receipts)} receipt(s)", colSpan=5),
            html.Th(total_text),
            html.Th(colSpan=5),
        ], style={"borderTop": "2px solid rgba(64,224,208,.35)", "fontWeight": "700"})),
    ], bordered=True, hover=True, responsive=True, size="sm", className="mb-0")

def filter_zimra_receipts(receipts, fiscal_day, customer_name, invoice_no, start_date, end_date):
    filtered = []
    fiscal_day_filter = str(fiscal_day or "").strip().casefold()
    customer_filter = str(customer_name or "").strip().casefold()
    invoice_filter = str(invoice_no or "").strip().casefold()

    for receipt in receipts:
        submitted_date = str(receipt.get("created_at") or "")[:10]
        if fiscal_day_filter and fiscal_day_filter not in str(receipt.get("fiscal_day_no") or "").casefold():
            continue
        if customer_filter and customer_filter not in str(receipt.get("customer_name") or "").casefold():
            continue
        if invoice_filter and invoice_filter not in str(receipt.get("invoice_no") or "").casefold():
            continue
        if start_date and (not submitted_date or submitted_date < start_date[:10]):
            continue
        if end_date and (not submitted_date or submitted_date > end_date[:10]):
            continue
        filtered.append(receipt)
    return filtered

def get_audit_page():
    z_report_error = None
    try:
        res_reports = requests.get(f"{API_BASE}/api/z_reports", timeout=5)
        res_reports.raise_for_status()
        z_reports = res_reports.json()
        if not isinstance(z_reports, list):
            raise ValueError("The Z-Reports endpoint returned an invalid response.")
    except (requests.RequestException, ValueError) as error:
        z_report_error = str(error)
        z_reports = []

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
        return dbc.Table([html.Thead(html.Tr([html.Th("Fiscal Day"), html.Th("Closed Date"), html.Th("USD (Sales/VAT)"), html.Th("ZWG (Sales/VAT)"), html.Th("Receipts"), html.Th("Download")])), html.Tbody(rows)], bordered=True, hover=True, responsive=True, size="sm", className="mb-0")

    return page_layout("Audit log & Z-Reports", "Review receipt outcomes verified directly against ZIMRA, plus fiscal-day summaries.", "bi-clipboard-data", [
        html.Div([
            html.Div([
                html.H4("Receipt verification", className="mb-1"),
                html.P("Verify recent QR links with ZIMRA, then filter receipt records.", className="text-muted mb-0"),
            ]),
            dbc.Button(
                [html.I(className="bi bi-arrow-clockwise me-2"), "Verify recent receipts"],
                id="btn-refresh-zimra-audit", n_clicks=0, className="btn-fiscal",
            ),
        ], className="d-flex align-items-center justify-content-between flex-wrap gap-3 mb-3"),
        dcc.Store(id="zimra-audit-store", storage_type="memory"),
        dbc.Card([
            dbc.CardBody([
                dbc.Row([
                    dbc.Col(dbc.Input(
                        id="audit-filter-fiscal-day", placeholder="Filter fiscal day",
                        type="text", className="fiscal-input",
                    ), md=2, className="mb-2"),
                    dbc.Col(dbc.Input(
                        id="audit-filter-customer", placeholder="Filter customer name",
                        type="text", className="fiscal-input",
                    ), md=3, className="mb-2"),
                    dbc.Col(dbc.Input(
                        id="audit-filter-invoice", placeholder="Filter invoice number",
                        type="text", className="fiscal-input",
                    ), md=3, className="mb-2"),
                    dbc.Col(dcc.DatePickerRange(
                        id="audit-filter-submitted-date",
                        start_date_placeholder_text="Submitted from",
                        end_date_placeholder_text="Submitted to",
                        display_format="YYYY-MM-DD",
                        minimum_nights=0,
                        className="mb-2",
                    ), md=4, className="mb-2"),
                ]),
                dbc.Button(
                    [html.I(className="bi bi-x-circle me-2"), "Clear filters"],
                    id="btn-clear-audit-filters", color="secondary", size="sm",
                ),
            ]),
        ], className="dashboard-card mb-3", style={"borderRadius": "16px"}),
        dbc.Tabs([
            dbc.Tab(label="Successful", tab_id="success"),
            dbc.Tab(label="Failed", tab_id="failed"),
            dbc.Tab(label="Receipts not verified", tab_id="unverified"),
        ], id="audit-receipt-tabs", active_tab="success", className="mb-3"),
        dcc.Loading(
            html.Div("Select Verify recent receipts to check ZIMRA.", id="zimra-audit-results"),
            type="circle",
            color="#40E0D0",
        ),
        html.Div(id="zimra-audit-refresh-status", className="mb-3"),
        html.H4("Z-Report history", className="mb-3 mt-4"),
        dbc.Alert(
            f"Unable to load Z-Reports: {z_report_error}", color="danger",
        ) if z_report_error else None,
        dbc.Card([dbc.CardBody(build_z_report_table(z_reports))], className="mb-4 dashboard-card", style={"borderRadius": "16px"}),
        html.Div([
            html.H5("Local audit export", className="mb-0"),
            dbc.Button(
                [html.I(className="bi bi-filetype-csv me-2"), "Export locally accepted receipts"],
                id="btn-download-success", color="secondary", size="sm",
            ),
        ], className="d-flex align-items-center justify-content-between flex-wrap gap-3 mb-3"),
    ])

@callback(
    [Output("zimra-audit-store", "data"), Output("zimra-audit-refresh-status", "children")],
    [Input("url", "pathname"), Input("btn-refresh-zimra-audit", "n_clicks")],
)
def refresh_zimra_audit(pathname, n_clicks):
    if pathname != "/audit":
        return dash.no_update, dash.no_update
    try:
        response = requests.get(f"{API_BASE}/api/receipt_verification", timeout=45)
        response.raise_for_status()
        data = response.json()
        if "error" in data:
            raise ValueError(data["error"])
        return data, ""
    except (requests.RequestException, ValueError) as error:
        return None, dbc.Alert(f"Unable to verify receipts with ZIMRA: {error}", color="danger")

@callback(
    Output("zimra-audit-results", "children"),
    [
        Input("zimra-audit-store", "data"),
        Input("audit-receipt-tabs", "active_tab"),
        Input("audit-filter-fiscal-day", "value"),
        Input("audit-filter-customer", "value"),
        Input("audit-filter-invoice", "value"),
        Input("audit-filter-submitted-date", "start_date"),
        Input("audit-filter-submitted-date", "end_date"),
    ],
)
def render_zimra_receipt_tab(data, active_tab, fiscal_day, customer_name, invoice_no, start_date, end_date):
    if not data:
        return html.P("Select Verify recent receipts to check ZIMRA.", className="text-muted text-center p-3")

    status_data = {
        "success": data.get("recent_success", []),
        "failed": data.get("recent_failed", []),
        "unverified": data.get("recent_unverified", []),
    }
    receipts = filter_zimra_receipts(
        status_data.get(active_tab, []),
        fiscal_day,
        customer_name,
        invoice_no,
        start_date,
        end_date,
    )
    return dbc.Card(
        dbc.CardBody(build_zimra_receipt_table(receipts)),
        className="dashboard-card mb-4",
        style={"borderRadius": "16px"},
    )

@callback(
    [
        Output("audit-filter-fiscal-day", "value"),
        Output("audit-filter-customer", "value"),
        Output("audit-filter-invoice", "value"),
        Output("audit-filter-submitted-date", "start_date"),
        Output("audit-filter-submitted-date", "end_date"),
    ],
    Input("btn-clear-audit-filters", "n_clicks"),
    prevent_initial_call=True,
)
def clear_audit_filters(n_clicks):
    return "", "", "", None, None

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
    return page_layout("Point of sale", "A streamlined checkout experience for your fiscal device.", "bi-shop", [
        dbc.Card([dbc.CardBody([html.Div([html.I(className="bi bi-basket2", style={"fontSize": "48px", "color": "#40e0a0", "marginBottom": "18px"}), html.H4("POS module coming soon", className="text-center", style={"color": "#edf2f7"}), html.P("This module will integrate directly with your barcode scanner and cart system.", className="text-center text-muted", style={"maxWidth": "480px", "margin": "0 auto"})], style={"textAlign": "center", "padding": "48px 24px"})])], className="dashboard-card", style={"borderRadius": "16px"})
    ])

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

@callback(
    Output("activation-output", "children"),
    Input("btn-activate-license", "n_clicks"),
    State("input-license-key", "value"),
    prevent_initial_call=True
)
def activate_license(n, key):
    if not n:
        return ""
    try:
        res = requests.post(f"{API_BASE}/api/activate_license", json={"license_key": key})
        data = res.json()
        if data.get("status") == "success":
            return dbc.Alert(f"✅ {data.get('message')} (Expires: {data.get('expiry')})", color="success")
        return dbc.Alert(f"❌ {data.get('message')}", color="danger")
    except Exception as e:
        return dbc.Alert(f"Error: {str(e)}", color="danger")

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8050, debug=False)
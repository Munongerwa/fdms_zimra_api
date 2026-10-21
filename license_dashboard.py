import dash
from dash import html, dcc, Input, Output, State, callback, dash_table
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import sqlite3
import os
import sys
from datetime import datetime, timedelta

# ============================================================
# FIX: Set License Secret Key for Dashboard
# This MUST be here so the dashboard can generate keys.
# ============================================================
LICENSE_SECRET = "AIBES_FISCALISATION_SUPER_SECRET_KEY_2026_CHANGE_ME!"
if len(LICENSE_SECRET) < 32:
    raise ValueError("LICENSE_SECRET must be at least 32 characters long.")
os.environ.setdefault("FISCALINK_LICENSE_SECRET", LICENSE_SECRET)
# ============================================================

# Ensure the core module is accessible
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.license_manager import generate_license_key, get_machine_id


DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "developer_licenses.db")

# --- STYLING ---
COLORS = {
    "bg": "#0e0e14",
    "card": "#151821",
    "primary": "#40E0D0",
    "info": "#54a8ff",
    "success": "#40e0a0",
    "warning": "#ffc857",
    "danger": "#ff6b6b",
    "text": "#e2e8f0",
    "muted": "#929bad",
    "border": "rgba(255,255,255,.07)",
}

CUSTOM_CSS = """
body {
    background-color: #0e0e14;
    color: #e2e8f0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    margin: 0;
}
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: rgba(255,255,255,.1); border-radius: 3px; }
.dashboard-card {
    background: #151821 !important;
    border: 1px solid rgba(255,255,255,.07) !important;
    border-radius: 16px !important;
    color: #e2e8f0 !important;
    transition: transform .18s ease, border-color .18s ease, box-shadow .18s ease;
}
.dashboard-card:hover {
    transform: translateY(-2px);
    border-color: rgba(64,224,208,.3) !important;
    box-shadow: 0 12px 28px rgba(0,0,0,.2) !important;
}
.card-header {
    background-color: rgba(255,255,255,.025);
    border-bottom-color: rgba(255,255,255,.07);
    color: #edf2f7;
}
.form-label, label { color: #cbd5e1; }
.form-control, .form-select, textarea.form-control {
    background-color: #10131b;
    border-color: rgba(255,255,255,.12);
    color: #e2e8f0;
}
.form-control:focus, .form-select:focus, textarea.form-control:focus {
    background-color: #10131b;
    border-color: #40e0d0;
    color: #e2e8f0;
    box-shadow: 0 0 0 3px rgba(64,224,208,.15);
}
.form-control::placeholder { color: #748094; }
.input-group-text {
    background: #10131b;
    border-color: rgba(255,255,255,.12);
    color: #929bad;
}
.text-muted { color: #929bad !important; }
.text-primary { color: #54a8ff !important; }
.license-tabs.nav-tabs {
    gap: 8px;
    border-bottom: 1px solid rgba(255,255,255,.12);
}
.license-tabs .nav-link {
    padding: 10px 16px;
    border: 1px solid rgba(255,255,255,.14) !important;
    border-radius: 10px 10px 0 0 !important;
    background: #151821 !important;
    color: #e2e8f0 !important;
    font-size: 14px;
    font-weight: 700;
    opacity: 1;
}
.license-tabs .nav-link:hover {
    border-color: rgba(64,224,208,.5) !important;
    background: #1b202b !important;
    color: #ffffff !important;
}
.license-tabs .nav-link.active {
    border-color: #40e0d0 !important;
    border-bottom-color: #0e0e14 !important;
    background: #0e0e14 !important;
    color: #40e0d0 !important;
}
.license-tabs .nav-link:focus-visible {
    outline: 2px solid #40e0d0;
    outline-offset: 2px;
}
.btn-fiscal {
    background: linear-gradient(135deg, #40e0d0, #00ced1) !important;
    border: none !important;
    border-radius: 12px !important;
    color: #0a0a0a !important;
    font-weight: 700 !important;
    transition: transform .15s, box-shadow .15s;
}
.btn-fiscal:hover {
    transform: translateY(-2px);
    box-shadow: 0 6px 24px rgba(64,224,208,.35);
    color: #0a0a0a !important;
}
.fiscal-input {
    background: rgba(255,255,255,.06) !important;
    border: 1px solid rgba(255,255,255,.1) !important;
    border-radius: 12px !important;
    color: #e2e8f0 !important;
}
.fiscal-input:focus {
    border-color: #40e0d0 !important;
    box-shadow: 0 0 0 3px rgba(64,224,208,.15) !important;
}
.license-key {
    background: #10131b !important;
    border: 1px solid rgba(255,255,255,.12) !important;
    border-radius: 12px !important;
    color: #e2e8f0 !important;
    font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
}
.alert {
    border-radius: 12px;
}
.alert-success {
    background: rgba(64,224,160,.1);
    border-color: rgba(64,224,160,.28);
    color: #9be8cc;
}
.alert-danger {
    background: rgba(255,107,107,.1);
    border-color: rgba(255,107,107,.28);
    color: #ffaaaa;
}
@media (max-width: 575.98px) {
    .license-page-header { align-items: flex-start !important; }
}
"""

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS licenses 
                        (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                         machine_id TEXT NOT NULL, 
                         company_name TEXT,
                         device_id TEXT,
                         duration_days INTEGER,
                         expiry_date TEXT, 
                         license_key TEXT, 
                         created_at TEXT, 
                         status TEXT)''')
        conn.commit()

# FIX: suppress_callback_exceptions=True is critical for dynamic tabs
app = dash.Dash(
    __name__, 
    external_stylesheets=[
        dbc.themes.BOOTSTRAP,
        "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css",
    ],
    suppress_callback_exceptions=True
)
app.title = "FISCALINK License Manager"
app.index_string = """
<!DOCTYPE html>
<html>
<head>
    {%metas%}
    <title>FISCALINK License Manager</title>
    {%favicon%}
    {%css%}
    <style>__CUSTOM_CSS__</style>
</head>
<body>
    {%app_entry%}
    <footer>
        {%config%}
        {%scripts%}
        {%renderer%}
    </footer>
</body>
</html>
""".replace("__CUSTOM_CSS__", CUSTOM_CSS)

app.layout = dbc.Container([
    html.Div([
        html.Div(
            html.I(className="bi bi-shield-lock-fill", style={"fontSize": "24px", "color": COLORS["success"]}),
            style={
                "width": "52px", "height": "52px", "display": "flex",
                "alignItems": "center", "justifyContent": "center",
                "borderRadius": "15px", "backgroundColor": "rgba(64,224,160,.11)",
                "flexShrink": 0,
            },
        ),
        html.Div([
            html.H1("FISCALINK License Manager", style={
                "fontSize": "clamp(23px, 2.5vw, 30px)", "fontWeight": "750",
                "letterSpacing": "-.025em", "color": "#f1f5f9", "margin": "0 0 5px",
            }),
            html.P("Manage, generate, and track client licenses", className="text-muted mb-0"),
        ]),
    ], className="license-page-header d-flex align-items-center gap-3 mb-4 py-3"),

    dbc.Tabs([
        dbc.Tab("Overview & Stats", tab_id="tab-overview", labelClassName="fw-semibold"),
        dbc.Tab("Generate License", tab_id="tab-generator", labelClassName="fw-semibold"),
        dbc.Tab("Track Licenses", tab_id="tab-tracker", labelClassName="fw-semibold"),
    ], id="main-tabs", active_tab="tab-overview", className="license-tabs mb-4"),

    html.Div(id="tab-content"),
    dcc.Interval(id="refresh-interval", interval=10000, n_intervals=0)

], fluid=True, className="px-3 px-md-4 px-xl-5", style={
    "backgroundColor": COLORS["bg"], "color": COLORS["text"],
    "minHeight": "100vh", "paddingTop": "20px", "paddingBottom": "50px",
})

# ==========================================
# TAB RENDERING CALLBACK
# ==========================================
@callback(Output("tab-content", "children"), Input("main-tabs", "active_tab"))
def render_tab(active_tab):
    if active_tab == "tab-overview":
        return html.Div([
            html.H4([html.I(className="bi bi-pie-chart-fill me-2"), "Dashboard Overview"], className="mb-3 text-primary"),
            
            # Metric Cards
            dbc.Row([
                dbc.Col(dbc.Card([dbc.CardBody([
                    html.H6("Total Issued", className="text-muted text-uppercase small"),
                    html.Div([
                        html.I(className="bi bi-key-fill", style={"color": COLORS["info"], "fontSize": "20px"}),
                        html.H3(id="stat-total", className="mb-0 fw-bold", style={"color": COLORS["info"]}),
                    ], className="d-flex align-items-center justify-content-between")
                ])], className="dashboard-card h-100"), md=3),
                dbc.Col(dbc.Card([dbc.CardBody([
                    html.H6("Active", className="text-muted text-uppercase small"),
                    html.Div([
                        html.I(className="bi bi-shield-check", style={"color": COLORS["success"], "fontSize": "20px"}),
                        html.H3(id="stat-active", className="mb-0 fw-bold", style={"color": COLORS["success"]}),
                    ], className="d-flex align-items-center justify-content-between")
                ])], className="dashboard-card h-100"), md=3),
                dbc.Col(dbc.Card([dbc.CardBody([
                    html.H6("Expiring Soon (<7 Days)", className="text-muted text-uppercase small"),
                    html.Div([
                        html.I(className="bi bi-clock-history", style={"color": COLORS["warning"], "fontSize": "20px"}),
                        html.H3(id="stat-expiring", className="mb-0 fw-bold", style={"color": COLORS["warning"]}),
                    ], className="d-flex align-items-center justify-content-between")
                ])], className="dashboard-card h-100"), md=3),
                dbc.Col(dbc.Card([dbc.CardBody([
                    html.H6("Expired", className="text-muted text-uppercase small"),
                    html.Div([
                        html.I(className="bi bi-shield-x", style={"color": COLORS["danger"], "fontSize": "20px"}),
                        html.H3(id="stat-expired", className="mb-0 fw-bold", style={"color": COLORS["danger"]}),
                    ], className="d-flex align-items-center justify-content-between")
                ])], className="dashboard-card h-100"), md=3),
            ], className="mb-4"),

            # Charts
            dbc.Row([
                dbc.Col(dbc.Card([
                    dbc.CardHeader(html.H5("License Status Distribution", className="mb-0")),
                    dbc.CardBody([dcc.Graph(id="chart-pie", style={"height": "350px"})])
                ], className="dashboard-card h-100"), md=5),
                dbc.Col(dbc.Card([
                    dbc.CardHeader(html.H5("Licenses Issued (Last 30 Days)", className="mb-0")),
                    dbc.CardBody([dcc.Graph(id="chart-bar", style={"height": "350px"})])
                ], className="dashboard-card h-100"), md=7),
            ])
        ])
    
    elif active_tab == "tab-generator":
        return html.Div([
            html.H4([html.I(className="bi bi-key-fill me-2"), "Generate New License"], className="mb-3 text-primary"),
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardBody([
                            dbc.Label("Company Name", className="fw-bold"),
                            dbc.InputGroup([
                                dbc.InputGroupText(html.I(className="bi bi-building")),
                                dbc.Input(id="gen-company", placeholder="e.g., Feedmix Pvt Ltd", className="form-control-lg fiscal-input")
                            ], className="mb-3"),

                            dbc.Label("Device ID", className="fw-bold"),
                            dbc.InputGroup([
                                dbc.InputGroupText(html.I(className="bi bi-cpu")),
                                dbc.Input(id="gen-device-id", placeholder="e.g., 37619", className="form-control-lg fiscal-input")
                            ], className="mb-3"),
                            
                            dbc.Label("Machine ID", className="fw-bold"),
                            dbc.InputGroup([
                                dbc.InputGroupText(html.I(className="bi bi-pc-display")),
                                dbc.Input(id="gen-mid", placeholder="e.g., MID-1A2B3C4D", className="form-control-lg fiscal-input")
                            ], className="mb-3"),
                            
                            dbc.Label("Duration (Custom Days)", className="fw-bold"),
                            dbc.Input(id="gen-days", type="number", value=30, min=1, placeholder="Enter number of days", className="mb-4 form-control-lg fiscal-input"),

                            dbc.Button([html.I(className="bi bi-lightning-charge-fill me-2"), "Generate License"],
                                       id="btn-generate", className="btn-fiscal w-100 btn-lg"),
                            
                            html.Hr(className="my-4"),
                            
                            dbc.Label("Generated License Key", className="fw-bold"),
                            dcc.Textarea(id="gen-output-key", readOnly=True,
                                         className="license-key w-100",
                                         style={"height": "120px", "fontSize": "14px", "padding": "12px"}),
                            html.Div(id="gen-alert", className="mt-3")
                        ])
                    ], className="dashboard-card")
                ], md=8, lg=6, className="mx-auto")
            ])
        ])

    elif active_tab == "tab-tracker":
        return html.Div([
            html.H4([html.I(className="bi bi-search me-2"), "License Tracker"], className="mb-3 text-primary"),
            dbc.Card([
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            dbc.InputGroup([
                                dbc.InputGroupText(html.I(className="bi bi-search")),
                                dbc.Input(id="track-search", placeholder="Search by Machine ID, Company, or Device ID...", className="form-control-lg fiscal-input")
                            ])
                        ], md=8),
                        dbc.Col(dbc.Button([html.I(className="bi bi-search me-2"), "Search"], id="btn-search", className="btn-fiscal btn-lg w-100"), md=4)
                    ], className="mb-4"),
                    
                    dash_table.DataTable(
                        id='track-table',
                        columns=[
                            {"name": "Company Name", "id": "company_name"},
                            {"name": "Device ID", "id": "device_id"},
                            {"name": "Machine ID", "id": "machine_id"},
                            {"name": "Duration (Days)", "id": "duration_days"},
                            {"name": "Created At", "id": "created_at"},
                            {"name": "Expiry Date", "id": "expiry_date"},
                            {"name": "Status", "id": "status"},
                            {"name": "License Key", "id": "license_key"}
                        ],
                        style_table={'overflowX': 'auto', 'borderRadius': '12px'},
                        style_cell={
                            'textAlign': 'left', 'padding': '12px', 'fontSize': '13px',
                            'backgroundColor': 'transparent', 'color': COLORS["text"],
                            'border': f'1px solid {COLORS["border"]}',
                            'minWidth': '100px', 'maxWidth': '280px', 'whiteSpace': 'normal',
                        },
                        style_header={
                            'backgroundColor': '#10131b', 'color': COLORS["muted"],
                            'fontWeight': 'bold', 'fontSize': '11px',
                            'letterSpacing': '.06em', 'textTransform': 'uppercase',
                            'border': f'1px solid {COLORS["border"]}',
                        },
                        style_data={'backgroundColor': 'transparent', 'color': COLORS["text"]},
                        style_data_conditional=[
                            {'if': {'filter_query': '{status} = Active', 'column_id': 'status'}, 'backgroundColor': '#123a31', 'color': '#8ee0c4', 'fontWeight': '700'},
                            {'if': {'filter_query': '{status} = Expired', 'column_id': 'status'}, 'backgroundColor': '#3a2025', 'color': '#ff9a9a', 'fontWeight': '700'},
                            {'if': {'filter_query': '{status} = Expiring Soon', 'column_id': 'status'}, 'backgroundColor': '#3a3020', 'color': '#ffd27a', 'fontWeight': '700'},
                            {'if': {'state': 'selected'}, 'backgroundColor': 'rgba(64,224,208,.12)', 'border': '1px solid #40e0d0'},
                        ],
                        page_size=10,
                        sort_action="native",
                        filter_action="native"
                    )
                ])
            ], className="dashboard-card")
        ])
    return html.Div()

# ==========================================
# CALLBACKS: OVERVIEW & STATS
# ==========================================
@callback(
    [Output("stat-total", "children"), Output("stat-active", "children"), 
     Output("stat-expiring", "children"), Output("stat-expired", "children"),
     Output("chart-pie", "figure"), Output("chart-bar", "figure")],
    [Input("main-tabs", "active_tab"), Input("refresh-interval", "n_intervals")]
)
def update_stats(active_tab, n):
    if active_tab != "tab-overview":
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update

    today = datetime.now().strftime("%Y-%m-%d")
    soon = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
    
    with sqlite3.connect(DB_PATH) as conn:
        total = conn.execute("SELECT COUNT(*) FROM licenses").fetchone()[0]
        active = conn.execute("SELECT COUNT(*) FROM licenses WHERE expiry_date >= ? AND status != 'Revoked'", (today,)).fetchone()[0]
        expiring = conn.execute("SELECT COUNT(*) FROM licenses WHERE expiry_date BETWEEN ? AND ? AND status != 'Revoked'", (today, soon)).fetchone()[0]
        expired = conn.execute("SELECT COUNT(*) FROM licenses WHERE expiry_date < ? AND status != 'Revoked'", (today,)).fetchone()[0]

        pie_fig = go.Figure(data=[go.Pie(
            labels=['Active', 'Expiring Soon', 'Expired'],
            values=[active, expiring, expired],
            marker_colors=[COLORS["success"], COLORS["warning"], COLORS["danger"]],
            hole=0.4, textinfo='label+percent'
        )])
        pie_fig.update_layout(
            margin=dict(t=0, b=0, l=0, r=0),
            showlegend=True,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color=COLORS["text"]),
            legend=dict(
                orientation="h", yanchor="bottom", y=1.02,
                font=dict(color=COLORS["muted"]),
            ),
        )

        thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        rows = conn.execute("SELECT DATE(created_at) as day, COUNT(*) as count FROM licenses WHERE created_at >= ? GROUP BY day ORDER BY day", (thirty_days_ago,)).fetchall()
        days = [r[0] for r in rows]
        counts = [r[1] for r in rows]
        
        bar_fig = go.Figure(data=[go.Bar(x=days, y=counts, marker_color=COLORS["primary"])])
        bar_fig.update_layout(
            margin=dict(t=20, b=40, l=40, r=20),
            xaxis_title="Date",
            yaxis_title="Licenses Issued",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color=COLORS["text"]),
            xaxis=dict(gridcolor="rgba(255,255,255,.07)", zerolinecolor="rgba(255,255,255,.07)"),
            yaxis=dict(gridcolor="rgba(255,255,255,.07)", zerolinecolor="rgba(255,255,255,.07)"),
        )

    return total, active, expiring, expired, pie_fig, bar_fig

# ==========================================
# CALLBACKS: GENERATOR
# ==========================================
@callback(
    [Output("gen-output-key", "value"), Output("gen-alert", "children")],
    Input("btn-generate", "n_clicks"),
    [State("gen-company", "value"), State("gen-device-id", "value"), State("gen-mid", "value"), State("gen-days", "value")],
    prevent_initial_call=True
)
def generate_and_save(n, company, device_id, mid, days):
    if not n: return "", ""
    
    mid = (mid or "").upper().strip()
    if not mid.startswith("MID-"):
        return "", dbc.Alert([html.I(className="bi bi-exclamation-triangle-fill me-2"), "Invalid Machine ID format. Must start with 'MID-'."], color="danger")
    
    days = int(days) if days else 30
    key = generate_license_key(mid, days_valid=days)
    expiry_date = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
    
    status = "Expiring Soon" if days <= 7 else "Active"
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT INTO licenses (machine_id, company_name, device_id, duration_days, expiry_date, license_key, created_at, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (mid, company, device_id, days, expiry_date, key, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), status))
        conn.commit()
    
    return key, dbc.Alert([html.I(className="bi bi-check-circle-fill me-2"), f"License generated successfully for {company} ({mid})! Expires on {expiry_date}."], color="success", className="mt-3")

# ==========================================
# CALLBACKS: TRACKER
# ==========================================
@callback(
    Output("track-table", "data"),
    [Input("btn-search", "n_clicks"), Input("main-tabs", "active_tab")],
    State("track-search", "value")
)
def update_tracker(n_clicks, active_tab, search_val):
    if active_tab != "tab-tracker": return dash.no_update
    
    query = "SELECT company_name, device_id, machine_id, duration_days, created_at, expiry_date, status, license_key FROM licenses"
    params = []
    
    if search_val and search_val.strip():
        search_term = f"%{search_val.strip()}%"
        query += " WHERE company_name LIKE ? OR device_id LIKE ? OR machine_id LIKE ?"
        params.extend([search_term, search_term, search_term])
        
    query += " ORDER BY id DESC"
    
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(query, params).fetchall()
        
    data = []
    for row in rows:
        key_display = f"{row[7][:20]}...{row[7][-10:]}" if row[7] and len(row[7]) > 30 else row[7]
        data.append({
            "company_name": row[0] or "N/A",
            "device_id": row[1] or "N/A",
            "machine_id": row[2],
            "duration_days": row[3],
            "created_at": row[4],
            "expiry_date": row[5],
            "status": row[6],
            "license_key": key_display
        })
    return data

if __name__ == "__main__":
    init_db()
    app.run(host='0.0.0.0', port=8051, debug=False)
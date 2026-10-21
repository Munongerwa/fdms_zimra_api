import dash
from dash import html, dcc, Input, Output, State, callback, dash_table
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import sqlite3
import os
import sys
from datetime import datetime, timedelta

# Ensure the core module is accessible
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.license_manager import generate_license_key, get_machine_id

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "developer_licenses.db")

# --- STYLING ---
COLORS = {
    "bg": "#f4f7f6",
    "card": "#ffffff",
    "primary": "#4361ee",
    "success": "#2ec4b6",
    "warning": "#ff9f1c",
    "danger": "#e71d36",
    "text": "#2b2d42",
    "muted": "#8d99ae"
}

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
    external_stylesheets=[dbc.themes.BOOTSTRAP, dbc.icons.FONT_AWESOME],
    suppress_callback_exceptions=True
)
app.title = "FISCALINK License Manager"

app.layout = dbc.Container([
    # Header
    html.Div([
        html.H2([html.I(className="fas fa-shield-alt me-2"), "FISCALINK License Manager"], 
                style={"color": COLORS["primary"], "fontWeight": "700"}),
        html.P("Manage, Generate, and Track Client Licenses", className="text-muted")
    ], className="d-flex justify-content-between align-items-center mb-4 py-3 border-bottom"),

    # FIX: Use simple string labels for DBC v2 compatibility. Added fs-5 to make them large and visible.
    dbc.Tabs([
        dbc.Tab("Overview & Stats", tab_id="tab-overview", labelClassName="fw-bold fs-5"),
        dbc.Tab("Generate License", tab_id="tab-generator", labelClassName="fw-bold fs-5"),
        dbc.Tab("Track Licenses", tab_id="tab-tracker", labelClassName="fw-bold fs-5"),
    ], id="main-tabs", active_tab="tab-overview", className="mb-4"),

    # Tab Content Container
    html.Div(id="tab-content"),
    
    # Hidden Interval for auto-refreshing stats
    dcc.Interval(id="refresh-interval", interval=10000, n_intervals=0)

], fluid=True, style={"backgroundColor": COLORS["bg"], "minHeight": "100vh", "paddingBottom": "50px"})

# ==========================================
# TAB RENDERING CALLBACK
# ==========================================
@callback(Output("tab-content", "children"), Input("main-tabs", "active_tab"))
def render_tab(active_tab):
    if active_tab == "tab-overview":
        return html.Div([
            # Icon Header
            html.H4([html.I(className="fas fa-chart-pie me-2"), "Dashboard Overview"], className="mb-3 text-primary"),
            
            # Metric Cards
            dbc.Row([
                dbc.Col(dbc.Card([dbc.CardBody([
                    html.H6("Total Issued", className="text-muted text-uppercase small"),
                    html.H3(id="stat-total", className="mb-0 fw-bold", style={"color": COLORS["primary"]})
                ])], className="shadow-sm border-0 h-100"), md=3),
                dbc.Col(dbc.Card([dbc.CardBody([
                    html.H6("Active", className="text-muted text-uppercase small"),
                    html.H3(id="stat-active", className="mb-0 fw-bold", style={"color": COLORS["success"]})
                ])], className="shadow-sm border-0 h-100"), md=3),
                dbc.Col(dbc.Card([dbc.CardBody([
                    html.H6("Expiring Soon (<7 Days)", className="text-muted text-uppercase small"),
                    html.H3(id="stat-expiring", className="mb-0 fw-bold", style={"color": COLORS["warning"]})
                ])], className="shadow-sm border-0 h-100"), md=3),
                dbc.Col(dbc.Card([dbc.CardBody([
                    html.H6("Expired", className="text-muted text-uppercase small"),
                    html.H3(id="stat-expired", className="mb-0 fw-bold", style={"color": COLORS["danger"]})
                ])], className="shadow-sm border-0 h-100"), md=3),
            ], className="mb-4"),

            # Charts
            dbc.Row([
                dbc.Col(dbc.Card([
                    dbc.CardHeader(html.H5("License Status Distribution", className="mb-0")),
                    dbc.CardBody([dcc.Graph(id="chart-pie", style={"height": "350px"})])
                ], className="shadow-sm border-0 h-100"), md=5),
                dbc.Col(dbc.Card([
                    dbc.CardHeader(html.H5("Licenses Issued (Last 30 Days)", className="mb-0")),
                    dbc.CardBody([dcc.Graph(id="chart-bar", style={"height": "350px"})])
                ], className="shadow-sm border-0 h-100"), md=7),
            ])
        ])
    
    elif active_tab == "tab-generator":
        return html.Div([
            html.H4([html.I(className="fas fa-key me-2"), "Generate New License"], className="mb-3 text-primary"),
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardBody([
                            dbc.Label("Company Name", className="fw-bold"),
                            dbc.InputGroup([
                                dbc.InputGroupText(html.I(className="fas fa-building")),
                                dbc.Input(id="gen-company", placeholder="e.g., Feedmix Pvt Ltd", className="form-control-lg")
                            ], className="mb-3"),

                            dbc.Label("Device ID", className="fw-bold"),
                            dbc.InputGroup([
                                dbc.InputGroupText(html.I(className="fas fa-microchip")),
                                dbc.Input(id="gen-device-id", placeholder="e.g., 37619", className="form-control-lg")
                            ], className="mb-3"),
                            
                            dbc.Label("Machine ID", className="fw-bold"),
                            dbc.InputGroup([
                                dbc.InputGroupText(html.I(className="fas fa-laptop")),
                                dbc.Input(id="gen-mid", placeholder="e.g., MID-1A2B3C4D", className="form-control-lg")
                            ], className="mb-3"),
                            
                            dbc.Label("Duration (Custom Days)", className="fw-bold"),
                            dbc.Input(id="gen-days", type="number", value=30, min=1, placeholder="Enter number of days", className="mb-4 form-control-lg"),

                            dbc.Button([html.I(className="fas fa-bolt me-2"), "Generate License"], 
                                       id="btn-generate", color="primary", className="w-100 btn-lg shadow"),
                            
                            html.Hr(className="my-4"),
                            
                            dbc.Label("Generated License Key", className="fw-bold"),
                            dcc.Textarea(id="gen-output-key", readOnly=True, 
                                         style={"height": "120px", "fontSize": "14px", "fontFamily": "monospace", "backgroundColor": "#f8f9fa"}),
                            html.Div(id="gen-alert", className="mt-3")
                        ])
                    ], className="shadow-sm border-0")
                ], md=8, lg=6, className="mx-auto")
            ])
        ])

    elif active_tab == "tab-tracker":
        return html.Div([
            html.H4([html.I(className="fas fa-search me-2"), "License Tracker"], className="mb-3 text-primary"),
            dbc.Card([
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            dbc.InputGroup([
                                dbc.InputGroupText(html.I(className="fas fa-search")),
                                dbc.Input(id="track-search", placeholder="Search by Machine ID, Company, or Device ID...", className="form-control-lg")
                            ])
                        ], md=8),
                        dbc.Col(dbc.Button("Search", id="btn-search", color="secondary", className="btn-lg"), md=4)
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
                        style_table={'overflowX': 'auto'},
                        style_cell={'textAlign': 'left', 'padding': '12px', 'fontSize': '13px'},
                        style_header={'backgroundColor': COLORS["primary"], 'color': 'white', 'fontWeight': 'bold'},
                        style_data_conditional=[
                            {'if': {'filter_query': '{status} = Active'}, 'backgroundColor': '#d1e7dd', 'color': '#0f5132'},
                            {'if': {'filter_query': '{status} = Expired'}, 'backgroundColor': '#f8d7da', 'color': '#842029'},
                            {'if': {'filter_query': '{status} = Expiring Soon'}, 'backgroundColor': '#fff3cd', 'color': '#664d03'},
                        ],
                        page_size=10,
                        sort_action="native",
                        filter_action="native"
                    )
                ])
            ], className="shadow-sm border-0")
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
        pie_fig.update_layout(margin=dict(t=0, b=0, l=0, r=0), showlegend=True, legend=dict(orientation="h", yanchor="bottom", y=1.02))

        thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        rows = conn.execute("SELECT DATE(created_at) as day, COUNT(*) as count FROM licenses WHERE created_at >= ? GROUP BY day ORDER BY day", (thirty_days_ago,)).fetchall()
        days = [r[0] for r in rows]
        counts = [r[1] for r in rows]
        
        bar_fig = go.Figure(data=[go.Bar(x=days, y=counts, marker_color=COLORS["primary"])])
        bar_fig.update_layout(margin=dict(t=20, b=40, l=40, r=20), xaxis_title="Date", yaxis_title="Licenses Issued")

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
        return "", dbc.Alert([html.I(className="fas fa-exclamation-triangle me-2"), "Invalid Machine ID format. Must start with 'MID-'."], color="danger")
    
    days = int(days) if days else 30
    key = generate_license_key(mid, days_valid=days)
    expiry_date = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
    
    status = "Expiring Soon" if days <= 7 else "Active"
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT INTO licenses (machine_id, company_name, device_id, duration_days, expiry_date, license_key, created_at, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (mid, company, device_id, days, expiry_date, key, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), status))
        conn.commit()
    
    return key, dbc.Alert([html.I(className="fas fa-check-circle me-2"), f"License generated successfully for {company} ({mid})! Expires on {expiry_date}."], color="success", className="mt-3")

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
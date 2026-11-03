import os
import sys
import dash
from dash import html, dcc, Input, Output, State, callback
import dash_bootstrap_components as dbc

# ============================================================
# CRITICAL: Set the Secret Key BEFORE importing the manager
# This MUST match the secret in core/license_manager.py exactly!
# ============================================================
LICENSE_SECRET = "AIBES_FISCALISATION_SUPER_SECRET_KEY_2026_V2"
if len(LICENSE_SECRET) < 32:
    raise ValueError("LICENSE_SECRET must be at least 32 characters long.")
os.environ.setdefault("FISCALINK_LICENSE_SECRET", LICENSE_SECRET)

# Ensure the core module is accessible
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.license_manager import generate_license_key, validate_license_key, get_machine_id, save_license_to_db

app = dash.Dash(__name__, external_stylesheets=[dbc.themes.DARKLY])
app.title = "AIBES License Manager"

app.layout = dbc.Container([
    # NOTE: html.* components use className
    # NOTE: dbc.* components use class_name
    html.H1("🔑 AIBES License Manager", className="text-center my-4 text-info"),
    
    dbc.Row([
        # ============================================================
        # SECTION 1: KEY GENERATOR (For Clients)
        # ============================================================
        dbc.Col([
            dbc.Card([
                dbc.CardHeader(html.H4("1. Generate License Key", className="mb-0 text-warning")),
                dbc.CardBody([
                    html.P("Enter the client's Machine ID to generate a license key.", className="text-muted"),
                    
                    html.Label("Client Machine ID:", className="fw-bold mt-2"),
                    dbc.Input(id="input-client-machine-id", placeholder="e.g., A1B2C3D4E5F6G7H8", type="text", class_name="mb-3"),
                    
                    html.Label("Days Valid:", className="fw-bold"),
                    dbc.Input(id="input-days-valid", value=365, type="number", class_name="mb-3"),
                    
                    dbc.Button("Generate Key", id="btn-generate", color="warning", class_name="w-100 mb-3 fw-bold"),
                    
                    html.Label("Generated Key:", className="fw-bold"),
                    # dbc.Input uses 'readonly' (lowercase) in v2.0+
                    dbc.Input(id="output-generated-key", type="text", readonly=True, class_name="mb-3 font-monospace text-success fw-bold"),
                ])
            ], class_name="mb-4")
        ], md=6),
        
        # ============================================================
        # SECTION 2: LOCAL TESTER (For Your Machine)
        # ============================================================
        dbc.Col([
            dbc.Card([
                dbc.CardHeader(html.H4("2. Test / Activate Locally", className="mb-0 text-info")),
                dbc.CardBody([
                    html.P("Test a license key on this machine.", className="text-muted"),
                    
                    html.Label("Your Machine ID:", className="fw-bold mt-2"),
                    dbc.Input(id="display-local-machine-id", type="text", readonly=True, class_name="mb-3 font-monospace text-info"),
                    
                    html.Label("License Key to Test:", className="fw-bold"),
                    dbc.Textarea(id="input-test-key", placeholder="Paste full license key here...", class_name="mb-3", style={"height": "100px"}),
                    
                    dbc.Button("Validate & Save Locally", id="btn-activate-local", color="info", class_name="w-100 mb-3 fw-bold"),
                    
                    html.Div(id="output-activation-status", className="mt-3"),
                ])
            ], class_name="mb-4")
        ], md=6),
    ])
], fluid=True, style={"maxWidth": "1200px", "marginTop": "20px"})

# ============================================================
# CALLBACK 1: Show Local Machine ID on Load
# ============================================================
@callback(
    Output("display-local-machine-id", "value"),
    Input("display-local-machine-id", "id") # Dummy trigger to run on load
)
def show_local_machine_id(_):
    mid = get_machine_id()
    print(f"ℹ️  [SYSTEM] Local Machine ID detected: {mid}")
    return mid

# ============================================================
# CALLBACK 2: Generate Key for Client
# ============================================================
@callback(
    Output("output-generated-key", "value"),
    Input("btn-generate", "n_clicks"),
    [State("input-client-machine-id", "value"), State("input-days-valid", "value")],
    prevent_initial_call=True
)
def generate_key_for_client(n_clicks, client_mid, days):
    if not n_clicks:
        return ""
    
    print("\n" + "="*60)
    print("🔄 ATTEMPTING TO GENERATE LICENSE KEY...")
    
    if not client_mid or not days:
        print("❌ [ERROR] Missing Machine ID or Days.")
        return "Error: Missing inputs."
        
    try:
        days = int(days)
        if days <= 0:
            raise ValueError("Days must be positive.")
            
        # Generate the key
        new_key = generate_license_key(client_mid, days_valid=days)
        
        # Terminal Success Message
        print("✅ [SUCCESS] License Key Generated Successfully!")
        print(f"   👤 Client Machine ID : {client_mid.upper()}")
        print(f"   📅 Valid For         : {days} days")
        print(f"   🔑 Generated Key     : {new_key}")
        print("="*60 + "\n")
        
        return new_key
        
    except Exception as e:
        print(f"❌ [ERROR] Failed to generate key: {str(e)}")
        return f"Error: {str(e)}"

# ============================================================
# CALLBACK 3: Test and Activate Key Locally
# ============================================================
@callback(
    Output("output-activation-status", "children"),
    Input("btn-activate-local", "n_clicks"),
    State("input-test-key", "value"),
    prevent_initial_call=True
)
def test_and_activate_local(n_clicks, license_key):
    if not n_clicks:
        return ""
        
    print("\n" + "="*60)
    print("🔄 ATTEMPTING TO ACTIVATE LICENSE LOCALLY...")
    
    if not license_key:
        print("❌ [ERROR] No license key provided.")
        return dbc.Alert("Please enter a license key.", color="warning")
        
    try:
        # Validate the key
        is_valid, message, expiry_date = validate_license_key(license_key)
        
        if is_valid:
            # Save to database
            save_license_to_db(license_key, expiry_date)
            
            # Terminal Success Message
            print("✅ [SUCCESS] License Activated Successfully!")
            print(f"    Expiry Date : {expiry_date}")
            print(f"   💾 Saved to    : fiscal.db")
            print("="*60 + "\n")
            
            return dbc.Alert(f"✅ Success! {message} (Expires: {expiry_date})", color="success")
        else:
            # Terminal Error Message
            print(f"❌ [FAILED] License Activation Failed.")
            print(f"   Reason: {message}")
            print("="*60 + "\n")
            
            return dbc.Alert(f"❌ Failed: {message}", color="danger")
            
    except Exception as e:
        print(f"❌ [CRITICAL ERROR] {str(e)}")
        return dbc.Alert(f"System Error: {str(e)}", color="danger")

if __name__ == "__main__":
    print("\n" + "="*60)
    print("🚀 STARTING AIBES LICENSE MANAGER DASHBOARD...")
    print(f"🔑 Using Secret Key: {LICENSE_SECRET[:10]}...")
    print(f"💻 Local Machine ID: {get_machine_id()}")
    print("="*60 + "\n")
    app.run(debug=True, port=8051) # Port 8051 to avoid conflict with main app
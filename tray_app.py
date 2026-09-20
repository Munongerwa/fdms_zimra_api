"""
FISCALINK System Tray Application - Full Integrated Version
Flask backend (port 5000) - auto-starts
Dash frontend (port 8050) - auto-starts
Receipt Processor (C:\receipt modification → C:\Receipt) - auto-starts
System tray with simplified controls
"""
import os
import sys
import re
import time
import json
import queue
import threading
import webbrowser
import socket
import requests
import logging

# ============================================================
# LOGGING SETUP
# ============================================================
def get_log_path():
    """Get log file path - next to EXE in production, or project dir in dev."""
    if getattr(sys, 'frozen', False):
        return os.path.join(os.path.dirname(sys.executable), "fiscalink_log.txt")
    else:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "fiscalink_log.txt")

logging.basicConfig(
    filename=get_log_path(),
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("FISCALINK")

# ============================================================
# PyInstaller resource path helper
# ============================================================
def resource_path(relative_path):
    """Get absolute path to resource, works for dev and PyInstaller EXE."""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

# Configure paths
BASE_DIR = resource_path('.')
os.chdir(BASE_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

API_BASE = "http://localhost:5000"
DASHBOARD_URL = "http://localhost:8050"

# Global references
tray_icon = None
notification_queue = queue.Queue()
notification_thread = None

# ============================================================
# RECEIPT PROCESSOR (Auto-starts, runs silently in background)
# ============================================================
RECEIPT_INPUT_FOLDER = r'C:\receipt modification'
RECEIPT_OUTPUT_FOLDER = r'C:\Receipt'
processor_thread = None
processor_stop_event = threading.Event()
processor_is_running = False

def modify_receipt_file(file_path):
    """
    Modify a receipt file according to FEEDMIX POS formatting rules.
    """
    with open(file_path, 'r', encoding='utf-8') as file:
        lines = file.readlines()
    
    modified_lines = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith('SubTotal') or line.startswith('SUBTOTAL'):
            modified_lines.append(line + '\n')
            i += 1
            while i < len(lines):
                modified_lines.append(lines[i])
                i += 1
            break
            
        if re.match(r'^\d{7,}', line):
            current_line = line
            j = i + 1
            while j < len(lines):
                next_line = lines[j].strip()
                if re.match(r'^\d{7,}', next_line) or next_line.startswith('SubTotal') or next_line.startswith('SUBTOTAL'):
                    break
                current_line += ' ' + next_line
                j += 1
                
            modified_line = current_line
            modified_line = re.sub(r'(\d{7,})([A-Za-z])', r'\1 \2', modified_line)
            modified_line = re.sub(r'(\.\d{2})(?=\d)', r'\1 ', modified_line)
            modified_line = re.sub(r'(KG)(\d)', r'\1 \2', modified_line)
            modified_line = re.sub(r'(BAG)(\d)', r'\1 \2', modified_line)
            modified_lines.append(modified_line + '\n')
            i = j
        else:
            modified_line = line
            modified_line = re.sub(r'(\.\d{2})(?=\d)', r'\1 ', modified_line)
            modified_line = re.sub(r'(KG)(\d)', r'\1 \2', modified_line)
            modified_line = re.sub(r'(BAG)(\d)', r'\1 \2', modified_line)
            modified_lines.append(modified_line + '\n')
            i += 1
            
    return modified_lines

def run_receipt_processor_loop():
    """
    Main processing loop for the receipt processor.
    """
    global processor_is_running
    input_folder = RECEIPT_INPUT_FOLDER
    output_folder = RECEIPT_OUTPUT_FOLDER
    
    try:
        os.makedirs(output_folder, exist_ok=True)
        os.makedirs(input_folder, exist_ok=True)
    except Exception as e:
        logger.error(f"Receipt Processor: Could not create folders: {e}")
        print(f"❌ Receipt Processor: Could not create folders: {e}")
        return

    logger.info("Receipt Processor: Started automatically. Monitoring for files...")
    print(f"\n📂 Receipt Processor auto-started!")
    print(f"   Input:  {input_folder}")
    print(f"   Output: {output_folder}")
    print(f"   Waiting for .txt files...\n")
    
    processor_is_running = True
    
    while not processor_stop_event.is_set():
        try:
            if os.path.exists(input_folder):
                for filename in os.listdir(input_folder):
                    if filename.endswith('.txt'):
                        input_file_path = os.path.join(input_folder, filename)
                        logger.info(f"Receipt Processor: Processing file: {filename}")
                        print(f"📄 Receipt Processor: Processing {filename}...")
                        try:
                            modified_content = modify_receipt_file(input_file_path)
                            output_file_path = os.path.join(output_folder, filename)
                            with open(output_file_path, 'w', encoding='utf-8') as output_file:
                                output_file.writelines(modified_content)
                            os.remove(input_file_path)
                            print(f"   ✅ Saved to: {output_file_path} (Original deleted)")
                        except Exception as e:
                            logger.error(f"Receipt Processor: Error processing {filename}: {str(e)}")
                            print(f"   ❌ Error: {e}")
            else:
                logger.warning(f"Receipt Processor: Input folder '{input_folder}' does not exist.")
                
            for _ in range(50):
                if processor_stop_event.is_set():
                    break
                time.sleep(0.1)
                
        except Exception as e:
            logger.error(f"Receipt Processor: Error monitoring folder: {str(e)}")
            for _ in range(60):
                if processor_stop_event.is_set():
                    break
                time.sleep(0.1)

    logger.info("Receipt Processor: Processing loop stopped.")
    print("\n⏹️  Receipt Processor stopped.")
    processor_is_running = False

def start_receipt_processor():
    global processor_thread
    if processor_thread is None or not processor_thread.is_alive():
        processor_stop_event.clear()
        processor_thread = threading.Thread(
            target=run_receipt_processor_loop,
            daemon=True,
            name="ReceiptProcessorThread"
        )
        processor_thread.start()
        logger.info("Receipt Processor started automatically.")

def stop_receipt_processor():
    global processor_thread
    if processor_thread and processor_thread.is_alive():
        logger.info("Receipt Processor: Stopping...")
        print("\n⏳ Stopping Receipt Processor...")
        processor_stop_event.set()
        processor_thread.join(timeout=10)

# ============================================================
# UTILITY FUNCTIONS & NOTIFICATION QUEUE
# ============================================================
def is_port_open(port, host='localhost'):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            return s.connect_ex((host, port)) == 0
    except:
        return False

def _process_notification_queue():
    """Process notifications from the queue on a dedicated thread to prevent freezing."""
    while True:
        try:
            title, message = notification_queue.get(timeout=1)
            
            if sys.platform == 'win32':
                try:
                    import ctypes
                    # MB_OK | MB_ICONINFORMATION
                    ctypes.windll.user32.MessageBoxW(0, str(message), str(title), 0x40)
                except Exception as e:
                    logger.error(f"MessageBox failed: {e}")
            
            notification_queue.task_done()
            time.sleep(0.5) # Prevent rapid-fire dialogs
            
        except queue.Empty:
            continue
        except Exception as e:
            logger.error(f"Notification processor error: {e}")
            break

def show_notification(title, message, timeout=5):
    """Show a system notification with proper thread handling."""
    print(f"\n📢 [{title}] {message}\n")
    logger.info(f"Notification: [{title}] {message}")
    
    # Try plyer first (auto-closes)
    try:
        from plyer import notification
        notification.notify(
            title=title,
            message=message,
            app_name="FISCALINK",
            timeout=timeout
        )
        return  # Success, no need for fallback
    except Exception as e:
        logger.warning(f"Plyer notification failed: {e}")
    
    # Fallback: Add to queue for main thread processing
    if sys.platform == 'win32':
        notification_queue.put((title, message))
        
        global notification_thread
        if notification_thread is None or not notification_thread.is_alive():
            notification_thread = threading.Thread(target=_process_notification_queue, daemon=True)
            notification_thread.start()

def run_flask_backend():
    print("=" * 60)
    print(" Starting Flask Backend on port 5000...")
    print("=" * 60)
    logger.info("Starting Flask backend on port 5000")
    try:
        from app import app
        app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False, threaded=True)
    except Exception as e:
        print(f" Flask failed to start: {e}")
        logger.error(f"Flask failed to start: {e}")

def run_dash_frontend():
    print("=" * 60)
    print("🚀 Starting Dash Frontend on port 8050...")
    print("=" * 60)
    logger.info("Starting Dash frontend on port 8050")
    try:
        import dashboard
        dashboard.app.run(host='0.0.0.0', port=8050, debug=False, use_reloader=False, threaded=True)
    except Exception as e:
        print(f"❌ Dash failed to start: {e}")
        logger.error(f"Dash failed to start: {e}")

def start_services():
    """Start Flask, Dash, and Receipt Processor automatically in background threads."""
    print("\n🔧 Initializing FISCALINK services...\n")
    logger.info("Initializing all FISCALINK services")
    
    # ============================================================
    # NEW: Fetch and print ZIMRA Tax IDs to the terminal
    # ============================================================
    try:
        print("🔄 Attempting to connect to ZIMRA FDMS...")
        # Import the zimra client from app.py
        from app import zimra 
        status_code, config_resp = zimra.get_config()
        
        print(f"📡 ZIMRA API Response Status: {status_code}")
        
        if status_code == 200 and isinstance(config_resp, dict):
            company_name = config_resp.get('deviceBranchName', 'Unknown Company')
            device_id = config_resp.get('deviceID', 'N/A')
            print(f"✅ Successfully connected to ZIMRA FDMS.")
            print(f"🏢 Company Name: {company_name}")
            print(f"📟 Device ID:      {device_id}")
            
            print("\n" + "="*60)
            print("✅ ACCEPTED TAX IDs FOR THIS DEVICE:")
            print("="*60)
            applicable_taxes = config_resp.get('applicableTaxes', [])
            if applicable_taxes:
                for tax in applicable_taxes:
                    tax_id = tax.get('taxID', 'N/A')
                    tax_pct = tax.get('taxPercent', 0.0)
                    tax_name = tax.get('taxName', 'Unknown')
                    print(f"  ➔ Tax ID: {str(tax_id):<4} | Rate: {str(tax_pct):>5}% | Name: {tax_name}")
            else:
                print("  ️ No applicable taxes returned by ZIMRA. Check device registration.")
            print("="*60 + "\n")
        else:
            print("️  Could not fetch company details from ZIMRA.")
    except Exception as e:
        print(f"❌ CRITICAL ERROR fetching ZIMRA config: {e}")
    # ============================================================

    # Start Flask
    flask_thread = threading.Thread(target=run_flask_backend, daemon=True, name="FlaskThread")
    flask_thread.start()
    time.sleep(2) # Give Flask a moment to fully initialize
    
    # Start the Auto Fiscal Day Scheduler
    try:
        from app import start_auto_scheduler
        start_auto_scheduler()
    except Exception as e:
        print(f"️ Warning: Could not start auto scheduler: {e}")
    
    # Start Dash
    dash_thread = threading.Thread(target=run_dash_frontend, daemon=True, name="DashThread")
    dash_thread.start()
    
    # ✅ AUTO-START Receipt Processor (no menu entry needed)
    start_receipt_processor()
    
    # Wait for Flask and Dash ports to open (max 60 seconds)
    print(" Waiting for web services to initialize...")
    flask_ready = False
    dash_ready = False
    for i in range(60):
        if not flask_ready and is_port_open(5000):
            print("✅ Flask backend is ready on port 5000!")
            flask_ready = True
        if not dash_ready and is_port_open(8050):
            print("✅ Dash frontend is ready on port 8050!")
            dash_ready = True
        if flask_ready and dash_ready:
            print("\n✨ All services are running successfully!\n")
            return True
        time.sleep(1)
        
    print("\n⚠️  Warning: Services may not have started correctly.")
    print(f"   Flask (5000): {'Ready ✅' if flask_ready else 'Not ready ❌'}")
    print(f"   Dash  (8050): {'Ready ✅' if dash_ready else 'Not ready ❌'}")
    return flask_ready or dash_ready

def api_call(endpoint, method="GET", json_data=None, timeout=15):
    try:
        url = f"{API_BASE}{endpoint}"
        if method == "GET":
            response = requests.get(url, timeout=timeout)
        else:
            response = requests.post(url, json=json_data or {}, timeout=timeout)
        try:
            return response.status_code, response.json()
        except:
            return response.status_code, {"raw": response.text}
    except Exception as e:
        return 500, {"error": str(e)}

# ============================================================
# TRAY MENU ACTIONS
# ============================================================
def on_open_dashboard(icon, item):
    print("\n🌐 Opening dashboard...")
    try: webbrowser.open(DASHBOARD_URL)
    except Exception as e: print(f"   Error: {e}")

def on_check_status(icon, item):
    print("\n🔍 Checking device status...")
    status_code, data = api_call("/api/status", method="POST")
    if status_code == 200:
        zimra_resp = data.get("zimra_response", {})
        status = zimra_resp.get("fiscalDayStatus", "Unknown")
        device_id = zimra_resp.get("deviceID", "N/A")
        show_notification("Device Status", f"Status: {status}\nDevice ID: {device_id}")
    else:
        show_notification("Error", f"Failed to check status: {data.get('error', 'Unknown error')}")

def on_open_fiscal_day(icon, item):
    print("\n📅 Opening fiscal day...")
    status_code, data = api_call("/api/device_details", method="GET")
    current_day = "N/A"
    if status_code == 200:
        current_day = data.get("fiscal_day_no", "N/A")
    try:
        next_day = int(current_day) + 1 if current_day != "N/A" else 1
    except:
        next_day = 1
        
    status_code, data = api_call("/api/open_day", method="POST", json_data={"fiscalDayNo": next_day})
    if status_code == 200:
        http_status = data.get("http_status")
        if http_status == 200:
            show_notification("✅ Fiscal Day Opened", f"Day {next_day} opened successfully")
        else:
            zimra_resp = data.get("zimra_response", {})
            error_msg = zimra_resp if isinstance(zimra_resp, str) else str(zimra_resp)
            show_notification("⚠️ ZIMRA Error", f"Failed to open day:\n{error_msg[:200]}")
    else:
        show_notification("❌ Error", f"Failed: {data.get('error', str(data))}")

def on_close_fiscal_day(icon, item):
    print("\n📋 Closing fiscal day and generating Z-Report...")
    status_code, data = api_call("/api/close_day", method="POST", json_data={})
    if status_code == 200:
        http_status = data.get("http_status")
        if http_status == 200:
            z_report = data.get("z_report", {})
            currencies = z_report.get("currencies", {})
            usd_sales = currencies.get("USD", {}).get("total_sales", 0)
            usd_tax = currencies.get("USD", {}).get("total_tax", 0)
            zwg_sales = currencies.get("ZWG", {}).get("total_sales", 0)
            zwg_tax = currencies.get("ZWG", {}).get("total_tax", 0)
            total_receipts = z_report.get("total_receipts", 0)
            message = (
                f"Fiscal Day Closed Successfully!\n\n"
                f"Total Receipts: {total_receipts}\n"
                f"USD Sales: ${usd_sales:,.2f} (VAT: ${usd_tax:,.2f})\n"
                f"ZWG Sales: ${zwg_sales:,.2f} (VAT: ${zwg_tax:,.2f})"
            )
            show_notification("✅ Z-Report Generated", message, timeout=10)
        else:
            zimra_resp = data.get("zimra_response", {})
            error_msg = json.dumps(zimra_resp, indent=2) if isinstance(zimra_resp, dict) else str(zimra_resp)
            show_notification(" ZIMRA Error", f"Z-Report failed:\n{error_msg[:400]}", timeout=15)
    else:
        error_msg = data.get('error', str(data))
        show_notification("❌ Error", f"Failed to close fiscal day:\n{error_msg}", timeout=10)

def on_start_scanner(icon, item):
    """Start the folder scanner."""
    print("\n▶️ Starting scanner...")
    status_code, settings = api_call("/api/scanner_settings", method="GET")
    
    folder_path = settings.get("folder_path", r"C:\Receipt") if status_code == 200 else r"C:\Receipt"
    print_format = settings.get("print_format", "InvoiceA4") if status_code == 200 else "InvoiceA4"
    
    # RESTORED: Dynamically fetch the template from the dashboard settings
    template = settings.get("template", "feedmix") if status_code == 200 else "feedmix" 
    
    print(f"   Settings: folder={folder_path}, template={template}, format={print_format}")
    
    status_code, data = api_call("/api/start_scanning", method="POST", json_data={
        "folder_path": folder_path,
        "receipt_template": template,
        "receipt_print_format": print_format,
        "process_pdfs": True
    })
    
    print(f"   Response: {status_code} - {data}")
    if status_code == 200:
        result_status = data.get("status")
        if result_status == "started":
            show_notification("▶️ Scanner Started", f"Monitoring: {folder_path}\nTemplate: {template.upper()}")
        elif result_status == "already_running":
            show_notification("ℹ️ Info", "Scanner is already running")
    else:
        show_notification(" Error", f"Failed to start scanner: {data.get('error', str(data))}")

def on_stop_scanner(icon, item):
    print("\n⏹️ Stopping scanner...")
    status_code, data = api_call("/api/stop_scanning", method="POST", json_data={})
    if status_code == 200:
        show_notification("⏹️ Scanner Stopped", "The folder scanner has been stopped")
    else:
        show_notification("❌ Error", f"Failed to stop scanner: {data.get('error', str(data))}")

def on_set_format_invoicea4(icon, item):
    """Set print format to InvoiceA4."""
    api_call("/api/save_scanner_settings", method="POST", json_data={"receipt_print_format": "InvoiceA4"})
    show_notification("Format Updated", "Print format set to A4 Invoice (InvoiceA4)")
    # Force the tray menu to refresh and update checkmarks
    if icon: 
        icon.update_menu()

def on_set_format_receipt48(icon, item):
    """Set print format to Receipt48."""
    api_call("/api/save_scanner_settings", method="POST", json_data={"receipt_print_format": "Receipt48"})
    show_notification("Format Updated", "Print format set to 80mm Thermal (Receipt48)")
    # Force the tray menu to refresh and update checkmarks
    if icon: 
        icon.update_menu()

def check_format_invoicea4(item):
    """Check if current format is InvoiceA4."""
    status_code, settings = api_call("/api/scanner_settings", method="GET")
    fmt = settings.get("print_format", "InvoiceA4") if status_code == 200 else "InvoiceA4"
    return fmt == "InvoiceA4"

def check_format_receipt48(item):
    """Check if current format is Receipt48."""
    status_code, settings = api_call("/api/scanner_settings", method="GET")
    fmt = settings.get("print_format", "InvoiceA4") if status_code == 200 else "InvoiceA4"
    return fmt == "Receipt48"

def on_run_zreport(icon, item):
    print("\n📄 Running Z-Report...")
    on_close_fiscal_day(icon, item)

def on_view_logs(icon, item):
    print("\n📜 Opening scanner logs...")
    webbrowser.open(f"{DASHBOARD_URL}/scanner")

def on_about(icon, item):
    show_notification(
        "FISCALINK v1.0",
        "ZIMRA Fiscal Device Gateway\n\n"
        "Comprehensive system for:\n"
        "• Automatic receipt formatting\n"
        "• Receipt fiscalization & AIBES PDF Stamping\n"
        "• Z-Report generation\n"
        "• Analytics & reporting\n\n"
        "© 2026 FISCALINK",
        timeout=10
    )

def on_exit(icon, item):
    global tray_icon
    print("\n👋 Shutting down FISCALINK...")
    logger.info("Application exit requested")
    
    stop_receipt_processor()
    
    # Clear notification queue
    while not notification_queue.empty():
        try:
            notification_queue.get_nowait()
        except:
            break
            
    if tray_icon:
        tray_icon.stop()

# ============================================================
# TRAY ICON SETUP
# ============================================================
def get_status_string(icon):
    flask_status = "Running" if is_port_open(5000) else "Stopped"
    dash_status = "Running" if is_port_open(8050) else "Stopped"
    return f"Flask: {flask_status} | Dash: {dash_status} | Processor: Auto-Running"

def setup_tray():
    global tray_icon
    try:
        import pystray
        from PIL import Image
    except ImportError as e:
        print(f"❌ pystray or Pillow not installed: {e}")
        return None

    icon_path = resource_path(os.path.join('assets', 'logo.png'))
    try:
        image = Image.open(icon_path)
        image = image.resize((64, 64), Image.Resampling.LANCZOS)
    except Exception as e:
        print(f"⚠️  Failed to load icon: {e}")
        image = Image.new('RGB', (64, 64), color=(13, 110, 253))

    menu = pystray.Menu(
        pystray.MenuItem(get_status_string, lambda: None, enabled=False),
        pystray.MenuItem(" Open Dashboard", on_open_dashboard, default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("🔍 Check Device Status", on_check_status),
        pystray.MenuItem(" Open Fiscal Day", on_open_fiscal_day),
        pystray.MenuItem("📋 Close Fiscal Day / Z-Report", on_close_fiscal_day),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("▶️ Start Scanner", on_start_scanner),
        pystray.MenuItem("️ Stop Scanner", on_stop_scanner),
        pystray.Menu.SEPARATOR,
        
        # NEW: Print Format Toggles
        pystray.MenuItem("🖨️ Format: A4 Invoice", on_set_format_invoicea4, checked=check_format_invoicea4),
        pystray.MenuItem("🖨️ Format: 80mm Thermal", on_set_format_receipt48, checked=check_format_receipt48),
        
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(" Run Z-Report", on_run_zreport),
        pystray.MenuItem("📜 View Logs", on_view_logs),
        pystray.MenuItem("️ About", on_about),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("❌ Exit", on_exit),
    )
    
    tray_icon = pystray.Icon(
        name="FISCALINK",
        icon=image,
        title="FISCALINK - ZIMRA Fiscal Device Gateway",
        menu=menu
    )
    return tray_icon

# ============================================================
# MAIN ENTRY POINT
# ============================================================
def main():
    print("\n" + "=" * 60)
    print("  FISCALINK - ZIMRA Fiscal Device Gateway")
    print("  System Tray Application v1.0")
    print("=" * 60)
    print(f"\n Working directory: {BASE_DIR}")
    
    if is_port_open(5000) and is_port_open(8050):
        print("\n⚠️  Both services are already running!")
        webbrowser.open(DASHBOARD_URL)
    elif is_port_open(5000):
        print("\n⚠️  Flask backend is already running on port 5000.")
        show_notification("Port Conflict", "Port 5000 is already in use.")
        input("\nPress Enter to exit...")
        return
    else:
        services_ok = start_services()
        if services_ok:
            print("🌐 Opening dashboard in browser...")
            try: webbrowser.open(DASHBOARD_URL)
            except: pass
            show_notification(
                "✅ FISCALINK Started",
                "All services running.\n"
                "Receipt Processor auto-monitoring.\n"
                "Right-click tray icon for options.",
                timeout=8
            )
        else:
            print("\n❌ Failed to start services. Check errors above.")
            show_notification("❌ Startup Failed", "Could not start services. Check console.")
            input("\nPress Enter to exit...")
            return

    tray = setup_tray()
    if tray:
        print("\n" + "=" * 60)
        print("✅ System tray icon is active!")
        print("=" * 60)
        print("\n📌 Right-click the tray icon (bottom-right) for options.")
        print(" Press Ctrl+C in this window OR click 'Exit' to stop.\n")
        try:
            tray.run()
        except KeyboardInterrupt:
            print("\n\n⚠️  Ctrl+C detected. Shutting down...")
    else:
        print("\n⚠️  No tray icon available. Running in console-only mode.")
        try:
            while True: time.sleep(1)
        except KeyboardInterrupt:
            print("\n\n⚠️  Shutting down...")

    stop_receipt_processor()
    logger.info("FISCALINK application stopped")
    print("\n👋 FISCALINK stopped. Goodbye!")
    try:
        input("\nPress Enter to close this window...")
    except:
        pass

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ FATAL ERROR: {e}")
        logger.critical(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
        input("\nPress Enter to exit...")
        sys.exit(1)
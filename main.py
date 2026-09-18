import os
import sys

def ensure_folders():
    """Ensure all necessary folders exist."""
    folders = [
        "data",
        "scanner/Processed",
        "scanner/Failed",
        "scanner/Error",
        "logs",
        r"C:\receipt modification",
        r"C:\Receipt"
    ]
    for folder in folders:
        os.makedirs(folder, exist_ok=True)
    print("✅ All necessary folders verified/created.")

if __name__ == "__main__":
    print("Initializing FISCALINK System...")
    ensure_folders()
    
    # Launch the system tray application
    from tray_app import main as tray_main
    tray_main()
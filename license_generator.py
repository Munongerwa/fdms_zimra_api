import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.license_manager import get_machine_id, generate_license_key

def main():
    print("="*60)
    print(" FISCALINK LICENSE GENERATOR")
    print("="*60)
    
    # In a real scenario, the client gives you their Machine ID from the app
    client_mid = input("Enter Client's Machine ID (e.g., MID-1A2B3C): ").strip().upper()
    
    if not client_mid.startswith("MID-"):
        print("❌ Invalid Machine ID format.")
        return
        
    print("\nSelect Duration:")
    print("1. 1 Month (30 Days)")
    print("2. 3 Months (90 Days)")
    print("3. 1 Year (365 Days)")
    choice = input("Choice (1/2/3): ").strip()
    
    days_map = {"1": 30, "2": 90, "3": 365}
    days = days_map.get(choice, 30)
    
    # Generate the key
    license_key = generate_license_key(client_mid, days_valid=days)
    
    print("\n" + "="*60)
    print("✅ LICENSE GENERATED SUCCESSFULLY")
    print("="*60)
    print(f"Machine ID : {client_mid}")
    print(f"Duration   : {days} Days")
    print(f"License Key:\n{license_key}")
    print("="*60)
    print("Copy the License Key above and send it to the client.")
    input("\nPress Enter to exit...")

if __name__ == "__main__":
    main()
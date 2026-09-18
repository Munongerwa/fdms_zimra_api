import re
from datetime import datetime

def read_file_smart(file_path):
    """Reads the receipt file with multiple encoding fallbacks."""
    encodings = ['utf-8-sig', 'utf-8', 'utf-16', 'latin-1']
    for enc in encodings:
        try:
            with open(file_path, 'r', encoding=enc) as f:
                return f.readlines()
        except (UnicodeDecodeError, UnicodeError):
            continue
    return []

def aggregate_taxes(items, vat_exclusive=False):
    """Aggregates taxes from parsed items."""
    tax_totals = {}
    for item in items:
        key = (item['tax_code'], item['tax_id'], item['tax_pct'])
        if key not in tax_totals:
            tax_totals[key] = {'salesAmountWithTax': 0.0, 'taxAmount': 0.0}
        
        if item['tax_pct'] > 0:
            if vat_exclusive:
                tax_amt = round(item['total'] * (item['tax_pct'] / 100.0), 2)
                sales_with_tax = item['total'] + tax_amt
            else:
                decimal_rate = item['tax_pct'] / 100.0
                tax_amt = round(item['total'] - (item['total'] / (1 + decimal_rate)), 2)
                sales_with_tax = item['total']
        else:
            tax_amt = 0.0
            sales_with_tax = item['total']

        tax_totals[key]['salesAmountWithTax'] += sales_with_tax
        tax_totals[key]['taxAmount'] += tax_amt

    taxes = []
    for (tax_code, tax_id, tax_pct), totals in tax_totals.items():
        taxes.append({
            'tax_code': tax_code, 'tax_id': tax_id, 'tax_percent': tax_pct,
            'tax_amount': round(totals['taxAmount'], 2),
            'sales_amount_with_tax': round(totals['salesAmountWithTax'], 2)
        })
    return taxes

def parse_aibes_receipt(file_path):
    """Robustly parses AIBES invoice/credit note PDFs."""
    import pdfplumber
    
    data = {
        'seller_vat': '', 'seller_tin': '', 'seller_phone': '', 'seller_email': '', 'seller_address': '',
        'buyer_name': '', 'buyer_address': '', 'buyer_vat': '', 
        'buyer_tin': '', 'buyer_phone': '', 'buyer_email': '',
        'invoice_no': '', 
        'original_invoice_no': '',
        'receipt_type': 'FiscalInvoice', 
        'date': datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), # ALWAYS USES MACHINE TIME
        'currency': 'USD', 'items': [], 'taxes': [], 'vat_exclusive': False
    }
    
    try:
        with pdfplumber.open(file_path) as pdf:
            full_text = ""
            all_tables = []
            for page in pdf.pages:
                full_text += (page.extract_text() or "") + "\n"
                all_tables.extend(page.extract_tables() or [])
            
            # Normalize whitespace
            full_text = re.sub(r'\n+', '\n', full_text)
            
            # Detect Credit Note
            if "FISCAL CREDIT NOTE" in full_text.upper():
                data['receipt_type'] = "CreditNote"
            
            # Extract basic info
            match = re.search(r'Document No[:\s]*([A-Z0-9]+)', full_text, re.IGNORECASE)
            if match: data['invoice_no'] = match.group(1)
            
            # Extract Reference No (Original Invoice being credited)
            ref_match = re.search(r'Reference No\.?[:\s]*([A-Z0-9\-]+)', full_text, re.IGNORECASE)
            if ref_match: 
                data['original_invoice_no'] = ref_match.group(1).strip()
            
            # Extract Currency (Multi-step fallback for AIBES layouts where Currency is on a different line)
            currency_match = re.search(r'Currency[:\s]*(USD|ZWG)', full_text, re.IGNORECASE)
            if not currency_match:
                currency_match = re.search(r'Invoice Total\s+(USD|ZWG)', full_text, re.IGNORECASE)
            if not currency_match:
                # Fallback for ZWG/USD appearing right before "Document No:" at the bottom
                currency_match = re.search(r'(USD|ZWG)\s*\n?\s*Document No', full_text, re.IGNORECASE)
                
            if currency_match: 
                data['currency'] = currency_match.group(1).upper()
            
            match = re.search(r'VAT Number[:\s]*(\d+)', full_text, re.IGNORECASE)
            if match: data['seller_vat'] = match.group(1)
            match = re.search(r'TIN Number[:\s]*(\d+)', full_text, re.IGNORECASE)
            if match: data['seller_tin'] = match.group(1)
            
            # Extract Customer Details using robust positive lookaheads
            name_match = re.search(r'Customer Name[:\s]+(.*?)(?=\s*Customer Address|\s*Customer VAT|\s*Customer TIN|\s*Customer Email|\s*Customer Telephone|\s*Property|$)', full_text, re.IGNORECASE | re.DOTALL)
            if name_match: data['buyer_name'] = name_match.group(1).strip()
            
            addr_match = re.search(r'Customer Address[:\s]+(.*?)(?=\s*Customer VAT|\s*Customer TIN|\s*Customer Email|\s*Customer Telephone|\s*Property|$)', full_text, re.IGNORECASE | re.DOTALL)
            if addr_match: data['buyer_address'] = addr_match.group(1).strip()
            
            vat_match = re.search(r'Customer VAT No[:\s]+(.*?)(?=\s*Customer TIN|\s*Customer Email|\s*Customer Telephone|\s*Property|$)', full_text, re.IGNORECASE | re.DOTALL)
            if vat_match:
                val = vat_match.group(1).strip()
                # Set to dummy if empty, whitespace, or '0'
                data['buyer_vat'] = val if val and val != '0' else '123456789'
            else:
                data['buyer_vat'] = '123456789'
            
            tin_match = re.search(r'Customer TIN No[:\s]+(.*?)(?=\s*Customer Email|\s*Customer Telephone|\s*Property|$)', full_text, re.IGNORECASE | re.DOTALL)
            if tin_match:
                val = tin_match.group(1).strip()
                data['buyer_tin'] = val if val and val != '0' else '1234567890'
            else:
                data['buyer_tin'] = '1234567890'
            
            email_match = re.search(r'Customer Email[:\s]+(\S+@\S+)', full_text, re.IGNORECASE)
            if email_match: data['buyer_email'] = email_match.group(1).strip()
            
            # Strict phone number regex (digits, spaces, +, - up to 20 chars)
            phone_match = re.search(r'Customer Telephone[:\s]+([\d\s\+\-]{7,20})', full_text, re.IGNORECASE)
            if phone_match: data['buyer_phone'] = phone_match.group(1).strip()
            
            # Extract Items (Strict HS Code Exclusion)
            for table in all_tables:
                if not table: continue
                
                header_idx = -1
                for i, row in enumerate(table):
                    if row and any('HS Code' in str(c) for c in row if c):
                        header_idx = i
                        break
                
                if header_idx != -1:
                    for row in table[header_idx+1:]:
                        if not row: continue
                        
                        clean_row = [str(c).strip() for c in row if c is not None and str(c).strip() != '']
                        
                        if any('Sub Total' in str(c) or 'VAT Total' in str(c) or 'Invoice Total' in str(c) for c in clean_row):
                            continue
                        
                        if len(clean_row) >= 7 and re.match(r'^\d{8}$', clean_row[0].replace(' ', '')):
                            hs_code = clean_row[0].replace(' ', '')
                            desc = clean_row[1]
                            qty_str = clean_row[2]
                            total_incl_str = clean_row[-1]
                            
                            try:
                                qty = float(qty_str.replace(',', ''))
                                total_incl = float(total_incl_str.replace(',', ''))
                                
                                if qty > 0 and total_incl > 0:
                                    vat_amt = round(total_incl - (total_incl / 1.155), 2)
                                    tax_pct = 15.5 if vat_amt > 0.01 else 0.0
                                    tax_code = "A" if tax_pct > 0 else "B"
                                    tax_id = 515 if tax_pct > 0 else 2
                                    
                                    data['items'].append({
                                        'code': hs_code, 'name': desc.strip(), 'qty': qty,
                                        'price': round(total_incl / qty, 2), 'total': total_incl,
                                        'tax_pct': tax_pct, 'tax_code': tax_code, 'tax_id': tax_id
                                    })
                            except ValueError:
                                pass
                        else:
                            hs_code = "10000000"
                            desc_idx = 1
                            for i, val in enumerate(clean_row):
                                if re.match(r'^\d{8}$', val.replace(' ', '')):
                                    hs_code = val.replace(' ', '')
                                    desc_idx = i + 1
                                    break
                            
                            desc = clean_row[desc_idx] if desc_idx < len(clean_row) else ""
                            
                            nums = []
                            for i, val in enumerate(clean_row):
                                if i == 0 and val.replace(' ', '') == hs_code:
                                    continue # CRITICAL: Skip HS code
                                try:
                                    nums.append(float(val.replace(",", "").replace("%", "")))
                                except ValueError:
                                    pass
                            
                            if len(nums) >= 2:
                                qty = nums[0]
                                total_incl = nums[-1]
                                
                                if qty > 0 and total_incl > 0:
                                    vat_amt = round(total_incl - (total_incl / 1.155), 2)
                                    tax_pct = 15.5 if vat_amt > 0.01 else 0.0
                                    tax_code = "A" if tax_pct > 0 else "B"
                                    tax_id = 515 if tax_pct > 0 else 2
                                    
                                    data['items'].append({
                                        'code': hs_code, 'name': desc.strip(), 'qty': qty,
                                        'price': round(total_incl / qty, 2), 'total': total_incl,
                                        'tax_pct': tax_pct, 'tax_code': tax_code, 'tax_id': tax_id
                                    })
            
            # Aggregate taxes
            tax_totals = {}
            for item in data['items']:
                key = (item['tax_code'], item['tax_id'], item['tax_pct'])
                if key not in tax_totals:
                    tax_totals[key] = {'salesAmountWithTax': 0.0, 'taxAmount': 0.0}
                
                if item['tax_pct'] > 0:
                    tax_amt = round(item['total'] - (item['total'] / 1.155), 2)
                else:
                    tax_amt = 0.0
                
                tax_totals[key]['salesAmountWithTax'] += item['total']
                tax_totals[key]['taxAmount'] += tax_amt
            
            data['taxes'] = []
            for (tax_code, tax_id, tax_pct), totals in tax_totals.items():
                data['taxes'].append({
                    'tax_code': tax_code,
                    'tax_id': tax_id,
                    'tax_percent': tax_pct,
                    'tax_amount': round(totals['taxAmount'], 2),
                    'sales_amount_with_tax': round(totals['salesAmountWithTax'], 2)
                })
                
    except Exception as e:
        print(f"[AIBES] Error parsing PDF: {e}")
        import traceback
        traceback.print_exc()
    
    print(f"\n[AIBES] Type: {data['receipt_type']}")
    print(f"[AIBES] Invoice: {data['invoice_no']}, Original Ref: {data['original_invoice_no']}")
    print(f"[AIBES] Buyer Name: '{data['buyer_name']}'")
    print(f"[AIBES] Parsed {len(data['items'])} items.\n")
    
    return data


def parse_pdf_receipt(file_path):
    """Fallback generic PDF parser, now with strict HS code exclusion and machine time."""
    import pdfplumber
    
    data = {
        'seller_vat': '', 'seller_tin': '', 'buyer_name': '', 'buyer_address': '', 'buyer_vat': '', 
        'buyer_tin': '', 'buyer_phone': '', 'buyer_email': '', 'invoice_no': '', 
        'date': datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), # ALWAYS USES MACHINE TIME
        'currency': 'USD', 'items': [], 'taxes': [], 'vat_exclusive': False
    }
    
    try:
        with pdfplumber.open(file_path) as pdf:
            full_text = ""
            all_tables = []
            for page in pdf.pages:
                full_text += (page.extract_text() or "") + "\n"
                all_tables.extend(page.extract_tables() or [])
            
            match = re.search(r'Document\s*NO[:\s]*([A-Z0-9]+)', full_text, re.IGNORECASE)
            if match: data['invoice_no'] = match.group(1)
            
            match = re.search(r'Currency[:\s]*(USD|ZWG)', full_text, re.IGNORECASE)
            if match: data['currency'] = match.group(1).upper()
            
            for table in all_tables:
                if not table: continue
                header_idx = -1
                for i, row in enumerate(table):
                    if row and any('HS CODE' in str(c).upper() for c in row if c):
                        header_idx = i; break
                
                if header_idx != -1:
                    for row in table[header_idx+1:]:
                        if not row: continue
                        clean_row = [str(c).strip() for c in row if c is not None and str(c).strip() != '']
                        if len(clean_row) < 5: continue
                        
                        if len(clean_row) >= 7 and re.match(r'^\d{8}$', clean_row[0].replace(' ', '')):
                            hs_code = clean_row[0].replace(' ', '')
                            desc = clean_row[1]
                            qty_str = clean_row[2]
                            total_incl_str = clean_row[-1]
                            try:
                                qty = float(qty_str.replace(',', ''))
                                total_incl = float(total_incl_str.replace(',', ''))
                                if qty > 0 and total_incl > 0:
                                    tax_pct = 15.5 if float(clean_row[-2].replace(',','')) > 0 else 0.0
                                    tax_code = "A" if tax_pct > 0 else "B"
                                    tax_id = 515 if tax_pct > 0 else 2
                                    data['items'].append({
                                        'code': hs_code, 'name': desc, 'qty': qty, 
                                        'price': round(total_incl / qty, 2), 'total': total_incl, 
                                        'tax_pct': tax_pct, 'tax_code': tax_code, 'tax_id': tax_id
                                    })
                            except: pass
                        else:
                            hs_code = "10000000"
                            desc_idx = 2
                            for i, val in enumerate(clean_row):
                                if re.match(r'^\d{8}$', val.replace(' ', '')):
                                    hs_code = val.replace(' ', '')
                                    desc_idx = i + 1
                                    break
                            
                            desc = clean_row[desc_idx] if desc_idx < len(clean_row) else ""
                            
                            nums = []
                            for i, val in enumerate(clean_row):
                                if i == 0 and val.replace(' ', '') == hs_code:
                                    continue
                                try:
                                    nums.append(float(val.replace(",", "").replace("%", "")))
                                except ValueError:
                                    pass
                            
                            if len(nums) >= 2:
                                qty = nums[0]
                                total_incl = nums[-1]
                                if qty > 0 and total_incl > 0:
                                    tax_pct = 15.5 if len(nums) >= 3 and nums[1] > 0 else 0.0
                                    tax_code = "A" if tax_pct > 0 else "B"
                                    tax_id = 515 if tax_pct > 0 else 2
                                    data['items'].append({
                                        'code': hs_code, 'name': desc, 'qty': qty, 
                                        'price': round(total_incl / qty, 2), 'total': total_incl, 
                                        'tax_pct': tax_pct, 'tax_code': tax_code, 'tax_id': tax_id
                                    })
                                    
        tax_totals = {}
        for item in data['items']:
            key = (item['tax_code'], item['tax_id'], item['tax_pct'])
            if key not in tax_totals: tax_totals[key] = {'salesAmountWithTax': 0.0, 'taxAmount': 0.0}
            tax_amt = round(item['total'] - (item['total'] / (1 + (item['tax_pct']/100))), 2) if item['tax_pct'] > 0 else 0.0
            tax_totals[key]['salesAmountWithTax'] += item['total']
            tax_totals[key]['taxAmount'] += tax_amt
            
        for (tax_code, tax_id, tax_pct), totals in tax_totals.items():
            data['taxes'].append({
                'tax_code': tax_code, 'tax_id': tax_id, 'tax_percent': tax_pct,
                'tax_amount': round(totals['taxAmount'], 2),
                'sales_amount_with_tax': round(totals['salesAmountWithTax'], 2)
            })
    except Exception as e:
        print(f"Error parsing PDF {file_path}: {e}")
    return data

def parse_melivo_receipt(lines):
    """Parses Melivo POS receipts (VAT inclusive, 15.5%)."""
    machine_datetime = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    data = {
        'seller_vat': '', 'seller_tin': '', 'buyer_name': '', 'buyer_address': '', 'buyer_vat': '', 
        'buyer_tin': '', 'buyer_phone': '', 'buyer_email': '', 'invoice_no': '', 'date': machine_datetime,
        'currency': 'USD', 'cashier': '', 'total_ex': '0.00', 'invoice_total': '0.00',
        'items': [], 'taxes': [], 'vat_exclusive': False
    }
    for line in lines:
        ls = line.strip()
        if not ls: continue
        if ls.startswith("VAT Reg. No."): data['seller_vat'] = ls.split("VAT Reg. No.")[-1].strip()
        elif ls.startswith("TIN."): data['seller_tin'] = ls.split("TIN.")[-1].strip()
        elif ls.startswith("Buyer's Name:"): data['buyer_name'] = ls.split("Buyer's Name:")[-1].strip()
        elif ls.startswith("Buyer's Address:"): data['buyer_address'] = ls.split("Buyer's Address:")[-1].strip()
        elif ls.startswith("Buyer's VAT:"): data['buyer_vat'] = ls.split("Buyer's VAT:")[-1].strip()
        elif ls.startswith("Buyer's TIN:"): data['buyer_tin'] = ls.split("Buyer's TIN:")[-1].strip()
        elif ls.startswith("Buyer's TEL:"): data['buyer_phone'] = ls.split("Buyer's TEL:")[-1].strip()
        elif ls.startswith("Buyer's EMAIL:"): data['buyer_email'] = ls.split("Buyer's EMAIL:")[-1].strip()
        elif "INVOICE No." in ls:
            parts = ls.split()
            for i, part in enumerate(parts):
                if part == "No." and i + 1 < len(parts):
                    data['invoice_no'] = re.sub(r'[^a-zA-Z0-9]', '', parts[i + 1]); break
        elif ls.startswith("CURRENCY"): data['currency'] = ls.split("CURRENCY")[-1].strip()
        elif ls.startswith("SALES PERSON"): data['cashier'] = ls.split("SALES PERSON")[-1].strip()
        elif ls.startswith("SUBTOTAL"):
            parts = ls.split()
            if parts: data['total_ex'] = re.sub(r'[^\d.]', '', parts[-1])
        elif ls.startswith("INVOICE TOTAL"):
            parts = ls.split()
            if parts: data['invoice_total'] = re.sub(r'[^\d.]', '', parts[-1])

    product_start = -1; product_end = -1
    for i, line in enumerate(lines):
        ls = line.strip()
        if "QTY" in ls and "UNIT PRICE" in ls: product_start = i
        if ls.startswith("SUBTOTAL") and product_start != -1: product_end = i; break

    if product_start != -1 and product_end != -1:
        item_name = ""; item_code = ""
        for i in range(product_start + 1, product_end):
            ls = lines[i].strip()
            if not ls: continue
            has_enough_dots = ls.count('.') >= 3
            if not has_enough_dots and "Price" not in ls and "----" not in ls and "QTY" not in ls:
                temp_prod = re.sub(r'^\d+', '', ls)
                hyphen_index = temp_prod.find('-')
                if hyphen_index != -1: temp_prod = temp_prod[hyphen_index + 1:].strip()
                item_name = temp_prod.replace(":", "").strip()
                code_match = re.match(r'^(\d+)', ls)
                item_code = code_match.group(1) if code_match else "10000000"
            elif has_enough_dots and item_name:
                arrayprod = [x for x in ls.split(' ') if x]
                if len(arrayprod) >= 4:
                    try:
                        qty_str = arrayprod[-4].replace("$", "").replace(",", "").replace("-", "")
                        price_str = arrayprod[-3].replace("$", "").replace(",", "").replace("-", "").replace("T1", "")
                        amount_str = arrayprod[-1].replace("$", "").replace(",", "").replace("-", "").replace("T", "")
                        qty, price, total = float(qty_str), float(price_str), float(amount_str)
                        is_zero_rated = "#B" in item_name.upper()
                        tax_code, tax_id, tax_pct = ("B", 2, 0.0) if is_zero_rated else ("A", 515, 15.5)
                        item_name = re.sub(r'[!@#$%^&*()\-+~<>/\[\]{}|`]', ' ', item_name).strip()
                        data['items'].append({'code': item_code, 'name': item_name, 'qty': qty, 'price': price, 'total': total, 'tax_pct': tax_pct, 'tax_code': tax_code, 'tax_id': tax_id})
                        item_name, item_code = "", ""
                    except ValueError as e: print(f"[Melivo] Error parsing item: {ls} - {e}")
    data['taxes'] = aggregate_taxes(data['items'], vat_exclusive=False)
    return data

def parse_feedmix_receipt(lines):
    """Parses FEEDMIX POS receipts (VAT inclusive, 15.5%)."""
    machine_datetime = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    data = {
        'seller_vat': '', 'seller_tin': '', 'buyer_name': '', 'buyer_address': '', 'buyer_vat': '', 
        'buyer_tin': '', 'buyer_phone': '', 'buyer_email': '', 'invoice_no': '', 'date': machine_datetime,
        'currency': 'USD', 'cashier': '', 'total_ex': '0.00', 'invoice_total': '0.00',
        'items': [], 'taxes': [], 'vat_exclusive': False
    }
    for line in lines:
        ls = line.strip()
        if not ls: continue
        if ls.startswith("OUR VAT REG #"): data['seller_vat'] = ls.split("OUR VAT REG #", 1)[-1].replace(":", "").strip()
        elif ls.startswith("OUR TIN"): data['seller_tin'] = ls.split("OUR TIN", 1)[-1].replace(":", "").strip()
        elif ls.startswith("DOCUMENT NO"): data['invoice_no'] = ls.split("DOCUMENT NO", 1)[-1].replace(":", "").replace(" ", "").strip()
        elif ls.startswith("CURRENCY:") and "TENDERED" not in ls.upper(): data['currency'] = ls.split("CURRENCY:", 1)[-1].strip()
        elif ls.startswith("CUSTOMER NAME:"): data['buyer_name'] = ls.split("CUSTOMER NAME:", 1)[-1].strip()
        elif ls.startswith("CUSTOMER ADDRESS:"): data['buyer_address'] = ls.split("CUSTOMER ADDRESS:", 1)[-1].strip()
        elif ls.startswith("CUSTOMER TIN:"): data['buyer_tin'] = ls.split("CUSTOMER TIN:", 1)[-1].strip()
        elif ls.startswith("CUSTOMER VAT"): data['buyer_vat'] = ls.split("CUSTOMER VAT", 1)[-1].replace(":", "").strip()
        elif ls.startswith("CUSTOMER TEL/MOBILE"): data['buyer_phone'] = ls.split("CUSTOMER TEL/MOBILE", 1)[-1].strip()
        elif ls.startswith("CUSTOMER EMAIL"): data['buyer_email'] = ls.split("CUSTOMER EMAIL", 1)[-1].strip()
        elif ls.startswith("SUBTOTAL(EXCL)"): data['total_ex'] = ls.split("SUBTOTAL(EXCL)", 1)[-1].replace(",", "").strip()
        elif ls.startswith("INVOICE TOTAL"): data['invoice_total'] = ls.split("INVOICE TOTAL", 1)[-1].replace("USD", "").replace("ZWG", "").replace(",", "").strip()

    in_items = False
    for line in lines:
        ls = line.strip()
        if not ls: continue
        if "DISC." in ls or "VAT AMNT" in ls or "PRICE (INCL)" in ls: in_items = True; continue
        if ls.startswith("SUBTOTAL"): in_items = False; continue
        if in_items and ls.count('.') >= 5:
            parts = ls.split()
            if len(parts) >= 7:
                try:
                    amount_str = parts[-1].replace(",", "").replace("$", "")
                    price_str = parts[-4].replace(",", "").replace("$", "")
                    qty_str = parts[-6].replace(",", "").replace("$", "")
                    qty, price, total = float(qty_str), float(price_str), float(amount_str)
                except ValueError: continue
                name_parts = parts[:-6]
                code = name_parts[0] if name_parts else '10000000'
                name = " ".join(name_parts[1:] if code.isdigit() else name_parts)
                name = name.replace("VAT", "").replace("AMNTTOTAL", "").replace("(INCL)", "").strip()
                name = re.sub(r'[!@#$%^&*()\-+~<>/\[\]{}|`]', ' ', name).strip()
                data['items'].append({'code': code, 'name': name, 'qty': qty, 'price': price, 'total': total, 'tax_pct': 15.5, 'tax_code': 'A', 'tax_id': 515})
    data['taxes'] = aggregate_taxes(data['items'], vat_exclusive=False)
    return data

def parse_receipt_file(file_path, template="melivo"):
    """Parse a receipt file using the specified template."""
    template_lower = template.lower()
    if template_lower == "feedmix":
        return parse_feedmix_receipt(read_file_smart(file_path))
    elif template_lower == "aibes":
        return parse_aibes_receipt(file_path)
    elif template_lower == "pdf":
        return parse_pdf_receipt(file_path)
    else:
        return parse_melivo_receipt(read_file_smart(file_path))

def build_zimra_payload(parsed_data, device_id=None, receipt_counter=1, receipt_global_no=1, fiscal_day_no=1):
    """Build the ZIMRA payload, handling Credit Notes and conditional buyer data."""
    receipt_type = parsed_data.get('receipt_type', 'FiscalInvoice')
    original_invoice_no = parsed_data.get('original_invoice_no', '')
    
    receipt_lines = []
    for idx, item in enumerate(parsed_data['items']):
        qty = abs(item['qty']) 
        price = item['price']
        total = item['total']
        
        if receipt_type == 'CreditNote':
            price = -abs(price)
            total = -abs(total)
            
        correct_tax_id = 515 if item['tax_pct'] > 0 else 2
        
        receipt_lines.append({
            "receiptLineType": "Sale",
            "receiptLineNo": idx + 1,
            "receiptLineHSCode": item.get('code', '10000000')[:8].ljust(8, '0'),
            "receiptLineName": item['name'],
            "receiptLinePrice": price,
            "receiptLineQuantity": qty,
            "receiptLineTotal": total,
            "taxCode": item['tax_code'],
            "taxPercent": item['tax_pct'],
            "taxID": correct_tax_id
        })

    receipt_taxes = []
    for tax in parsed_data['taxes']:
        tax_amt = tax['tax_amount']
        sales_with_tax = tax['sales_amount_with_tax']
        
        if receipt_type == 'CreditNote':
            tax_amt = -abs(tax_amt)
            sales_with_tax = -abs(sales_with_tax)
            
        correct_tax_id = 515 if tax['tax_percent'] > 0 else 2
        
        receipt_taxes.append({
            "taxCode": tax['tax_code'], 
            "taxPercent": tax['tax_percent'],
            "taxID": correct_tax_id,
            "taxAmount": tax_amt,
            "salesAmountWithTax": sales_with_tax
        })
    
    is_vat_exclusive = parsed_data.get('vat_exclusive', False)
    if is_vat_exclusive:
        line_totals_excl = round(sum(abs(item['total']) for item in parsed_data['items']), 2)
        total_tax = round(sum(abs(tax['tax_amount']) for tax in parsed_data['taxes']), 2)
        receipt_total = round(line_totals_excl + total_tax, 2)
    else:
        receipt_total = round(sum(abs(item['total']) for item in parsed_data['items']), 2)
        
    if receipt_type == 'CreditNote':
        receipt_total = -abs(receipt_total)
        
    payment_amount = receipt_total

    # ============================================================
    # CONDITIONAL BUYER DATA LOGIC
    # ============================================================
    buyer_name = str(parsed_data.get('buyer_name', '')).strip()
    
    if not buyer_name:
        # 1. If NO buyer name is provided, omit buyer details entirely (Cash Sale)
        buyer_data_payload = None
    else:
        # 2. If buyer name IS provided, fill missing fields with dummies
        buyer_tin = str(parsed_data.get('buyer_tin', '')).strip()
        if not buyer_tin or buyer_tin == '0' or buyer_tin == '0000000000':
            buyer_tin = "1234567890"  
            
        buyer_vat = str(parsed_data.get('buyer_vat', '')).strip()
        if not buyer_vat or buyer_vat == '0' or buyer_vat == '000000000':
            buyer_vat = "123456789"    

        buyer_address = str(parsed_data.get('buyer_address', '')).strip()
        if not buyer_address:
            buyer_address = "Harare, Zimbabwe"

        buyer_data_payload = {
            "buyerRegisterName": buyer_name,
            "buyerTIN": buyer_tin,
            "vatNumber": buyer_vat,
            "buyerContacts": {
                "email": str(parsed_data.get('buyer_email', '')).strip(), 
                "phoneNo": str(parsed_data.get('buyer_phone', '')).strip()
            },
            "buyerAddress": {
                "street": buyer_address, 
                "city": "", 
                "province": "", 
                "houseNo": ""
            }
        }

    # Build the main payload
    payload = {
        "receiptType": receipt_type,
        "receiptCurrency": parsed_data['currency'],
        "receiptCounter": receipt_counter,
        "receiptGlobalNo": receipt_global_no,
        "invoiceNo": parsed_data['invoice_no'],
        "receiptNotes": f"Credit Note for {original_invoice_no}" if receipt_type == 'CreditNote' else "Invoice is issued after purchasing goods",
        "receiptDate": parsed_data['date'],
        "receiptLinesTaxInclusive": not is_vat_exclusive,
        "receiptLines": receipt_lines, 
        "receiptTaxes": receipt_taxes,
        "receiptPayments": [{"moneyTypeCode": "Cash", "paymentAmount": payment_amount}],
        "receiptTotal": receipt_total, 
        "receiptPrintForm": "InvoiceA4"
    }
    
    # Only add buyerData if we have a name
    if buyer_data_payload:
        payload["buyerData"] = buyer_data_payload

    # Credit Note logic
    if receipt_type == 'CreditNote' and original_invoice_no:
        orig_global_no = receipt_global_no - 1 if receipt_global_no > 1 else 1
        orig_fiscal_day = fiscal_day_no
        
        try:
            from core.zimra_client import DB_PATH
            import sqlite3
            with sqlite3.connect(DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute("""
                    SELECT receipt_global_no, fiscal_day_no 
                    FROM receipt_audit 
                    WHERE invoice_no = ? AND status = 'SUCCESS'
                    ORDER BY created_at DESC LIMIT 1
                """, (original_invoice_no,)).fetchone()
                
                if row:
                    orig_global_no = row['receipt_global_no']
                    orig_fiscal_day = row['fiscal_day_no']
        except Exception as e:
            print(f"Warning: Could not lookup original invoice {original_invoice_no} in DB: {e}")
            
        payload['creditDebitNote'] = {
            "deviceID": int(device_id) if device_id else 0,
            "receiptGlobalNo": orig_global_no,
            "fiscalDayNo": orig_fiscal_day
        }
        
    return payload
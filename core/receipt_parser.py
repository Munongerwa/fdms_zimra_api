import re
import json
from datetime import datetime
import pdfplumber
import os
from config import Config

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
        'date': datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        'currency': 'USD', 'items': [], 'taxes': [], 'vat_exclusive': False
    }
    try:
        with pdfplumber.open(file_path) as pdf:
            full_text = ""
            all_tables = []
            for page in pdf.pages:
                full_text += (page.extract_text() or "") + "\n"
                all_tables.extend(page.extract_tables() or [])
            full_text = re.sub(r'\n+', '\n', full_text)
            if "FISCAL CREDIT NOTE" in full_text.upper():
                data['receipt_type'] = "CreditNote"
            match = re.search(r'Document No[:\s]*([A-Z0-9]+)', full_text, re.IGNORECASE)
            if match: data['invoice_no'] = match.group(1)
            ref_match = re.search(r'Reference\s+No\.[:\s].*?([A-Z0-9\-]{10,})', full_text, re.IGNORECASE | re.DOTALL)
            if ref_match: 
                data['original_invoice_no'] = ref_match.group(1).strip()
            currency_match = re.search(r'Currency[:\s]*(USD|ZWG)', full_text, re.IGNORECASE)
            if not currency_match:
                currency_match = re.search(r'Invoice Total\s+(USD|ZWG)', full_text, re.IGNORECASE)
            if not currency_match:
                currency_match = re.search(r'(USD|ZWG)\s*\n?\s*Document No', full_text, re.IGNORECASE)
            if currency_match: 
                data['currency'] = currency_match.group(1).upper()
            match = re.search(r'VAT Number[:\s]*(\d+)', full_text, re.IGNORECASE)
            if match: data['seller_vat'] = match.group(1)
            match = re.search(r'TIN Number[:\s]*(\d+)', full_text, re.IGNORECASE)
            if match: data['seller_tin'] = match.group(1)
            name_match = re.search(r'Customer Name[:\s]+(.*?)(?=\s*Customer Address|\s*Customer VAT|\s*Customer TIN|\s*Customer Email|\s*Customer Telephone|\s*Property|\s*Document No:|$)', full_text, re.IGNORECASE | re.DOTALL)
            if name_match: data['buyer_name'] = name_match.group(1).strip()
            addr_match = re.search(r'Customer Address[:\s]+(.*?)(?=\s*Customer VAT|\s*Customer TIN|\s*Customer Email|\s*Customer Telephone|\s*Property|\s*Document No:|$)', full_text, re.IGNORECASE | re.DOTALL)
            if addr_match: 
                addr = addr_match.group(1).strip()
                addr = re.sub(r'\s*Document No:.*', '', addr, flags=re.IGNORECASE | re.DOTALL)
                addr = re.sub(r',\s*,', ',', addr)
                data['buyer_address'] = addr.replace('\n', ' ').strip()
            vat_match = re.search(r'Customer VAT No[:\s]+(\d{9})', full_text, re.IGNORECASE)
            if vat_match: data['buyer_vat'] = vat_match.group(1)
            else: data['buyer_vat'] = '123456789'
            tin_match = re.search(r'Customer TIN No[:\s]+(\d{10})', full_text, re.IGNORECASE)
            if tin_match: data['buyer_tin'] = tin_match.group(1)
            else: data['buyer_tin'] = '1234567890'
            email_match = re.search(r'Customer Email[:\s]+(\S+@\S+)', full_text, re.IGNORECASE)
            if email_match: data['buyer_email'] = email_match.group(1).strip()
            phone_match = re.search(r'Customer Telephone[:\s]+([\d\s\+\-]{7,20})', full_text, re.IGNORECASE)
            if phone_match: data['buyer_phone'] = phone_match.group(1).strip()
            
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
                        hs_code = ""
                        hs_idx = -1
                        for i, val in enumerate(clean_row):
                            if re.match(r'^\d{8}$', val.replace(' ', '')):
                                hs_code = val.replace(' ', '')
                                hs_idx = i
                                break
                        if not hs_code: continue
                        row_text = " ".join(clean_row[hs_idx+1:])
                        row_text = re.sub(r'\s+', ' ', row_text).strip()
                        qty = 0
                        price = 0
                        total_incl = 0
                        tax_pct = 0.0
                        desc = row_text
                        m5 = re.search(r'^(.*?)\s+([\d,]+(?:\.\d+)?)\s+([\d,]+\.\d+)\s+([\d,]+\.\d+)\s+([\d,]+\.\d+)\s+([\d,]+\.\d+)$', row_text)
                        if m5:
                            desc = m5.group(1).strip()
                            qty = float(m5.group(2).replace(',', ''))
                            price = float(m5.group(3).replace(',', ''))
                            total_excl = float(m5.group(4).replace(',', ''))
                            vat_amt = float(m5.group(5).replace(',', ''))
                            total_incl = float(m5.group(6).replace(',', ''))
                            tax_pct = 15.5 if vat_amt > 0.01 else 0.0
                        else:
                            m4 = re.search(r'^(.*?)\s+([\d,]+\.\d+)\s+([\d,]+\.\d+)\s+([\d,]+\.\d+)\s+([\d,]+\.\d+)$', row_text)
                            if m4:
                                desc = m4.group(1).strip()
                                price = float(m4.group(2).replace(',', ''))
                                total_excl = float(m4.group(3).replace(',', ''))
                                vat_amt = float(m4.group(4).replace(',', ''))
                                total_incl = float(m4.group(5).replace(',', ''))
                                qty = total_excl / price if price > 0 else 1.0
                                tax_pct = 15.5 if vat_amt > 0.01 else 0.0
                            else:
                                nums = re.findall(r'[\d,]+(?:\.\d+)?', row_text)
                                if len(nums) >= 5:
                                    total_incl = float(nums[-1].replace(',', ''))
                                    vat_amt = float(nums[-2].replace(',', ''))
                                    total_excl = float(nums[-3].replace(',', ''))
                                    price = float(nums[-4].replace(',', ''))
                                    qty = float(nums[-5].replace(',', ''))
                                    tax_pct = 15.5 if vat_amt > 0.01 else 0.0
                                elif len(nums) >= 2:
                                    total_incl = float(nums[-1].replace(',', ''))
                                    qty = 1.0
                                    for n_str in nums[:-2]:
                                        n = float(n_str.replace(',', ''))
                                        if n == int(n) and n < 100:
                                            qty = n
                                            break
                                    price = total_incl / qty if qty > 0 else 0
                                    vat_amt = total_incl - (total_incl / 1.155)
                                    tax_pct = 15.5 if vat_amt > 0.01 else 0.0
                        if qty > 0 and total_incl > 0:
                            tax_code = "A" if tax_pct > 0 else "B"
                            tax_id = Config.TAX_ID if tax_pct > 0 else 2
                            desc = re.sub(r'[!@#$%^&*()\-+~<>/\[\]{}|`]', ' ', desc).strip()
                            data['items'].append({
                                'code': hs_code, 
                                'name': desc, 
                                'qty': qty,
                                'price': round(price, 2), 
                                'total': round(total_incl, 2),
                                'tax_pct': tax_pct, 
                                'tax_code': tax_code, 
                                'tax_id': tax_id
                            })
            extracted_vat_total = None
            vat_total_match = re.search(r'VAT\s+T\s*o\s*t\s*a\s*l\s+([\d,]+(?:\.\d+)?)', full_text, re.IGNORECASE)
            if vat_total_match:
                extracted_vat_total = float(vat_total_match.group(1).replace(',', ''))
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
            if extracted_vat_total is not None:
                for key in tax_totals:
                    if key[2] > 0:
                        tax_totals[key]['taxAmount'] = extracted_vat_total
                        break
            data['taxes'] = []
            for (tax_code, tax_id, tax_pct), totals in tax_totals.items():
                data['taxes'].append({
                    'tax_code': tax_code, 'tax_id': tax_id, 'tax_percent': tax_pct,
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

def parse_aibes_incl_receipt(file_path):
    """Robustly parses AIBES invoice/credit note PDFs (Inclusive layout)."""
    return parse_aibes_receipt(file_path)

def parse_pdf_receipt(file_path):
    """Fallback generic PDF parser."""
    data = {
        'seller_vat': '', 'seller_tin': '', 'buyer_name': '', 'buyer_address': '', 'buyer_vat': '',
        'buyer_tin': '', 'buyer_phone': '', 'buyer_email': '', 'invoice_no': '',
        'date': datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
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
                                    tax_id = Config.TAX_ID if tax_pct > 0 else 2
                                    data['items'].append({'code': hs_code, 'name': desc, 'qty': qty, 'price': round(total_incl / qty, 2), 'total': total_incl, 'tax_pct': tax_pct, 'tax_code': tax_code, 'tax_id': tax_id})
                            except: pass
                        else:
                            hs_code = "10000000"
                            desc_idx = 2
                            for i, val in enumerate(clean_row):
                                if re.match(r'^\d{8}$', val.replace(' ', '')): hs_code = val.replace(' ', ''); desc_idx = i + 1; break
                            desc = clean_row[desc_idx] if desc_idx < len(clean_row) else ""
                            nums = []
                            for i, val in enumerate(clean_row):
                                if i == 0 and val.replace(' ', '') == hs_code: continue
                                try: nums.append(float(val.replace(",", "").replace("%", "")))
                                except ValueError: pass
                            if len(nums) >= 2:
                                qty = nums[0]
                                total_incl = nums[-1]
                                if qty > 0 and total_incl > 0:
                                    tax_pct = 15.5 if len(nums) >= 3 and nums[1] > 0 else 0.0
                                    tax_code = "A" if tax_pct > 0 else "B"
                                    tax_id = Config.TAX_ID if tax_pct > 0 else 2
                                    data['items'].append({'code': hs_code, 'name': desc, 'qty': qty, 'price': round(total_incl / qty, 2), 'total': total_incl, 'tax_pct': tax_pct, 'tax_code': tax_code, 'tax_id': tax_id})
            tax_totals = {}
            for item in data['items']:
                key = (item['tax_code'], item['tax_id'], item['tax_pct'])
                if key not in tax_totals: tax_totals[key] = {'salesAmountWithTax': 0.0, 'taxAmount': 0.0}
                tax_amt = round(item['total'] - (item['total'] / (1 + (item['tax_pct']/100))), 2) if item['tax_pct'] > 0 else 0.0
                tax_totals[key]['salesAmountWithTax'] += item['total']
                tax_totals[key]['taxAmount'] += tax_amt
            for (tax_code, tax_id, tax_pct), totals in tax_totals.items():
                data['taxes'].append({'tax_code': tax_code, 'tax_id': tax_id, 'tax_percent': tax_pct, 'tax_amount': round(totals['taxAmount'], 2), 'sales_amount_with_tax': round(totals['salesAmountWithTax'], 2)})
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
        'items': [], 'taxes': [], 'vat_exclusive': False, 'original_invoice_no': '', 'receipt_type': 'FiscalInvoice'
    }
    for line in lines:
        ls = line.strip()
        if not ls: continue
        if ls.startswith("VAT Reg. No."): data['seller_vat'] = ls.split("VAT Reg. No.")[-1].strip()
        elif ls.startswith("TIN."): data['seller_tin'] = ls.split("TIN.")[-1].strip()
        elif ls.startswith("Buyer's Name:"): data['buyer_name'] = ls.split("Buyer's Name:")[-1].strip()
        elif ls.startswith("Buyer's Address:"): data['buyer_address'] = ls.split("Buyer's Address:")[-1].strip()
        elif ls.startswith("Buyer's VAT:"): 
            val = ls.split("Buyer's VAT:")[-1].strip()
            data['buyer_vat'] = val if val and val != '0' else '123456789'
        elif ls.startswith("Buyer's TIN:"): 
            val = ls.split("Buyer's TIN:")[-1].strip()
            data['buyer_tin'] = val if val and val != '0' else '1234567890'
        elif ls.startswith("Buyer's Phone:"): data['buyer_phone'] = ls.split("Buyer's Phone:")[-1].strip()
        elif ls.startswith("Buyer's Email:"): data['buyer_email'] = ls.split("Buyer's Email:")[-1].strip()
        elif "INVOICE No." in ls:
            parts = ls.split()
            for i, part in enumerate(parts):
                if part == "No." and i + 1 < len(parts):
                    data['invoice_no'] = re.sub(r'[^a-zA-Z0-9]', '', parts[i + 1])
                    break
        elif ls.startswith("ORIGINAL"):
            parts = ls.split("ORIGINAL")
            if len(parts) > 1:
                data['original_invoice_no'] = parts[1].strip()
        elif ls.startswith("SALES PERSON"):
            parts = ls.split("SALES PERSON")
            if len(parts) > 1:
                data['cashier'] = parts[1].strip()
        elif ls.startswith("CURRENCY"): data['currency'] = ls.split("CURRENCY")[-1].strip()
        elif ls.startswith("SUBTOTAL"):
            parts = ls.split()
            if parts: data['total_ex'] = re.sub(r'[^\d.]', '', parts[-1])
        elif ls.startswith("INVOICE TOTAL"):
            parts = ls.split()
            if parts: data['invoice_total'] = re.sub(r'[^\d.]', '', parts[-1])
            
    if data['invoice_no'].upper().startswith('CRN'):
        data['receipt_type'] = 'CreditNote'
        
    product_start = -1
    product_end = -1
    for i, line in enumerate(lines):
        ls = line.strip()
        if "QTY" in ls and "UNIT PRICE" in ls: product_start = i
        if ls.startswith("SUBTOTAL") and product_start != -1: product_end = i; break
        
    if product_start != -1 and product_end != -1:
        item_name = ""
        item_code = ""
        for i in range(product_start + 1, product_end):
            ls = lines[i].strip()
            if not ls: continue
            has_enough_dots = ls.count('.') >= 3
            if not has_enough_dots and "Price" not in ls and "----" not in ls and "QTY" not in ls:
                temp_prod = re.sub(r'^\d+\s*-\s*', '', ls)
                item_name = temp_prod.strip()
                code_match = re.match(r'^(\d+)', ls)
                item_code = code_match.group(1) if code_match else "10000000"
            elif has_enough_dots and item_name:
                arrayprod = [x for x in ls.split(' ') if x]
                if len(arrayprod) >= 4:
                    try:
                        qty_str = arrayprod[0]
                        price_str = arrayprod[1]
                        amount_str = arrayprod[-1] 
                        qty = float(qty_str.replace(",", ""))
                        price = float(price_str.replace(",", ""))
                        total = float(amount_str.replace(",", ""))
                        is_zero_rated = "Zero Rated" in item_name or "0.00" in arrayprod[2] if len(arrayprod) > 2 else False
                        tax_code = "B" if is_zero_rated else "A"
                        tax_id = 2 if is_zero_rated else Config.TAX_ID
                        tax_pct = 0.0 if is_zero_rated else 15.5
                        item_name = re.sub(r'[!@#$%^&*()\-+~<>/\[\]{}|`]', ' ', item_name).strip()
                        data['items'].append({
                            'code': item_code, 'name': item_name, 'qty': qty, 
                            'price': price, 'total': total, 
                            'tax_pct': tax_pct, 'tax_code': tax_code, 'tax_id': tax_id
                        })
                        item_name, item_code = "", ""
                    except ValueError as e:
                        print(f"[Melivo] Error parsing item: {ls} - {e}")
                        
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
        if ls.startswith("OUR VAT REG # "): data['seller_vat'] = ls.split("OUR VAT REG # ", 1)[-1].replace(": ", " ").strip()
        elif ls.startswith("OUR TIN "): data['seller_tin'] = ls.split("OUR TIN ", 1)[-1].replace(": ", " ").strip()
        elif ls.startswith("DOCUMENT NO "): data['invoice_no'] = ls.split("DOCUMENT NO ", 1)[-1].replace(": ", " ").replace("  ", " ").strip()
        elif ls.startswith("CURRENCY: ") and "TENDERED " not in ls.upper(): data['currency'] = ls.split("CURRENCY: ", 1)[-1].strip()
        elif ls.startswith("CUSTOMER NAME: "): data['buyer_name'] = ls.split("CUSTOMER NAME: ", 1)[-1].strip()
        elif ls.startswith("CUSTOMER ADDRESS: "): data['buyer_address'] = ls.split("CUSTOMER ADDRESS: ", 1)[-1].strip()
        elif ls.startswith("CUSTOMER TIN: "): data['buyer_tin'] = ls.split("CUSTOMER TIN: ", 1)[-1].strip()
        elif ls.startswith("CUSTOMER VAT "): data['buyer_vat'] = ls.split("CUSTOMER VAT ", 1)[-1].replace(": ", " ").strip()
        elif ls.startswith("CUSTOMER TEL/MOBILE "): data['buyer_phone'] = ls.split("CUSTOMER TEL/MOBILE ", 1)[-1].strip()
        elif ls.startswith("CUSTOMER EMAIL "): data['buyer_email'] = ls.split("CUSTOMER EMAIL ", 1)[-1].strip()
        elif ls.startswith("SUBTOTAL(EXCL) "): data['total_ex'] = ls.split("SUBTOTAL(EXCL) ", 1)[-1].replace(", ", " ").strip()
        elif ls.startswith("INVOICE TOTAL "): data['invoice_total'] = ls.split("INVOICE TOTAL ", 1)[-1].replace("USD ", " ").replace("ZWG ", " ").replace(", ", " ").strip()
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
                data['items'].append({'code': code, 'name': name, 'qty': qty, 'price': price, 'total': total, 'tax_pct': 15.5, 'tax_code': 'A', 'tax_id': Config.TAX_ID})
    data['taxes'] = aggregate_taxes(data['items'], vat_exclusive=False)
    return data

def parse_receipt_file(file_path, template="melivo"):
    template_lower = template.lower()
    if template_lower == "feedmix": return parse_feedmix_receipt(read_file_smart(file_path))
    elif template_lower == "aibes": return parse_aibes_receipt(file_path)
    elif template_lower == "aibes_incl": return parse_aibes_incl_receipt(file_path)
    elif template_lower == "pdf": return parse_pdf_receipt(file_path)
    else: return parse_melivo_receipt(read_file_smart(file_path))

def build_zimra_payload(parsed_data, device_id=None, receipt_counter=1, receipt_global_no=1, fiscal_day_no=1):
    """Build the ZIMRA payload, handling Credit Notes and conditional buyer data."""
    receipt_type = parsed_data.get('receipt_type', 'FiscalInvoice')
    original_invoice_no = parsed_data.get('original_invoice_no', 'UNKNOWN')
    receipt_lines = []
    
    for idx, item in enumerate(parsed_data['items']):
        qty = abs(item['qty']) 
        total = item['total']
        if qty > 0:
            price = round(total / qty, 2)
        else:
            price = 0.0
        if receipt_type == 'CreditNote':
            price = -abs(price)
            total = -abs(total)
        correct_tax_id = Config.TAX_ID if item['tax_pct'] > 0 else 2
        receipt_lines.append({
            "receiptLineType": "Sale", "receiptLineNo": idx + 1,
            "receiptLineHSCode": item.get('code', '10000000')[:8].ljust(8, '0'),
            "receiptLineName": item['name'], "receiptLinePrice": price,
            "receiptLineQuantity": qty, "receiptLineTotal": total,
            "taxCode": item['tax_code'], "taxPercent": item['tax_pct'], "taxID": correct_tax_id
        })
        
    receipt_taxes = []
    for tax in parsed_data['taxes']:
        tax_amt = tax['tax_amount']
        sales_with_tax = tax['sales_amount_with_tax']
        if receipt_type == 'CreditNote':
            tax_amt = -abs(tax_amt)
            sales_with_tax = -abs(sales_with_tax)
        correct_tax_id = Config.TAX_ID if tax['tax_percent'] > 0 else 2
        receipt_taxes.append({
            "taxCode": tax['tax_code'], "taxPercent": tax['tax_percent'],
            "taxID": correct_tax_id, "taxAmount": tax_amt, "salesAmountWithTax": sales_with_tax
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
    
    buyer_name = str(parsed_data.get('buyer_name', '')).strip()
    if not buyer_name:
        buyer_data_payload = None
    else:
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
    
    if buyer_data_payload:
        payload["buyerData"] = buyer_data_payload
        
    if receipt_type == 'CreditNote':
        orig_global_no = receipt_global_no - 1 if receipt_global_no > 1 else 1
        orig_fiscal_day = fiscal_day_no
        orig_date = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        try:
            from core.zimra_client import DB_PATH
            import sqlite3
            with sqlite3.connect(DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute("""
                    SELECT receipt_global_no, fiscal_day_no, created_at 
                    FROM receipt_audit 
                    WHERE invoice_no = ? AND status = 'SUCCESS'
                    ORDER BY created_at DESC LIMIT 1
                """, (original_invoice_no,)).fetchone()
                if row:
                    orig_global_no = row['receipt_global_no']
                    orig_fiscal_day = row['fiscal_day_no']
                    if row['created_at']:
                        orig_date = row['created_at'].replace(' ', 'T') 
        except Exception as e:
            print(f"️ Warning: Could not lookup original invoice {original_invoice_no} in DB: {e}")
        payload['creditDebitNote'] = {
            "deviceID": int(device_id) if device_id else 0,
            "receiptGlobalNo": int(orig_global_no),
            "fiscalDayNo": int(orig_fiscal_day),
            "receiptDate": orig_date
        }
        
    return payload

def clean_pdf_duplication(text):
    if not text: return ""
    lines = text.split('\n')
    cleaned_lines = []
    for line in lines:
        line = line.strip()
        if not line: continue
        parts = line.split()
        if len(parts) >= 2 and len(parts) % 2 == 0:
            mid = len(parts) // 2
            if parts[:mid] == parts[mid:]:
                line = " ".join(parts[:mid])
        cleaned_lines.append(line)
    final_lines = []
    for line in cleaned_lines:
        if not final_lines or final_lines[-1] != line:
            final_lines.append(line)
    return "\n".join(final_lines).strip()

def split_name_and_address(full_text):
    if not full_text: return "", ""
    match = re.search(r'\s+(\d+[/\d]+\s+[A-Za-z]+.*)', full_text)
    if match: return full_text[:match.start()].strip(), match.group(1).strip()
    if '\n' in full_text:
        lines = full_text.split('\n')
        return lines[0].strip(), '\n'.join(lines[1:]).strip()
    return full_text, ""

def parse_feedmix_pdf_receipt(file_path):
    """Parses a Feedmix PDF invoice or credit note with the specific NO. HS CODE DESCRIPTION... layout."""
    text = ""
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            text += page.extract_text() + "\n"
            
    feedmix_items = []
    feedmix_pattern = re.compile(
        r'^\s*(\d+)\s+(\d{8})\s+(.*?)\s+(\d+(?:\.\d+)?)\s+[A-Z]+\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)%?\s+(\d+(?:\.\d+)?)\s+([\d,]+(?:\.\d+)?)', 
        re.MULTILINE
    )
    for match in feedmix_pattern.finditer(text):
        hs_code = match.group(2)
        description = match.group(3).strip()
        qty = float(match.group(4))
        price_incl = float(match.group(5))
        tax_pct = float(match.group(6))  
        vat_amnt = float(match.group(7))
        total_incl = float(match.group(8).replace(',', ''))
        feedmix_items.append({
            'code': hs_code, 'name': description, 'qty': qty, 'price': price_incl,
            'total': total_incl, 'tax_pct': tax_pct, 'tax_code': 'A' if tax_pct > 0 else 'B',
            'tax_id': Config.TAX_ID if tax_pct > 0 else 2
        })
        
    if not feedmix_items:
        raise Exception("No items found in Feedmix PDF. Check layout.")
        
    is_credit_note = "FISCAL CREDIT NOTE" in text.upper()
    receipt_type = "CreditNote" if is_credit_note else "FiscalInvoice"
    
    inv_match = re.search(r'Document\s+NO[:\s]+([A-Z0-9\-]+)', text, re.IGNORECASE)
    invoice_no = inv_match.group(1).strip() if inv_match else os.path.basename(file_path).replace('.pdf', '')
    
    original_invoice_no = "UNKNOWN"
    if is_credit_note:
        patterns = [
            r'Reference\s+No\.[:\s]+.*?(INV[A-Z0-9]{5,})',
            r'Reference\s+No\.[:\s]+([A-Z0-9\-]{5,})',
            r'\b(INV[A-Z0-9]{5,})\b'
        ]
        for pattern in patterns:
            ref_match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if ref_match:
                original_invoice_no = ref_match.group(1).strip()
                break
        print(f"Parser Debug: Extracted Original Invoice No = '{original_invoice_no}'")
        
    credit_reason = ""
    if is_credit_note:
        reason_match = re.search(r'Reason\s+for\s+Credit\s+Note[:\s]*(.+?)(?:\n|Page:)', text, re.IGNORECASE)
        credit_reason = reason_match.group(1).strip() if reason_match else "Goods Returned"
        
    date_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    curr_match = re.search(r'Currency:\s*([A-Z]+)', text)
    currency = curr_match.group(1).strip() if curr_match else 'USD'
    
    name_match = re.search(r'Customer\s+Name:\s*(.*?)(?:\n\s*Customer\s+(?:ADDRESS|TIN):)', text, re.IGNORECASE | re.DOTALL)
    raw_name_block = name_match.group(1).strip() if name_match else ""
    addr_match = re.search(r'Customer\s+ADDRESS:\s*(.*?)(?:\n\s*Customer\s+TIN:)', text, re.IGNORECASE | re.DOTALL)
    raw_addr_block = addr_match.group(1).strip() if addr_match else ""
    
    clean_name_block = clean_pdf_duplication(raw_name_block)
    clean_addr_block = clean_pdf_duplication(raw_addr_block)
    
    buyer_name = ""
    buyer_addr = ""
    if clean_addr_block:
        buyer_addr = clean_addr_block
        buyer_name = clean_name_block
        if buyer_addr in buyer_name:
            buyer_name = buyer_name.replace(buyer_addr, "").strip()
    else:
        buyer_name, buyer_addr = split_name_and_address(clean_name_block)
        
    if len(buyer_addr) > 100:
        buyer_addr = buyer_addr[:100]
        
    buyer_tin_match = re.search(r'Customer\s+TIN:\s*(\d+)', text)
    buyer_tin = buyer_tin_match.group(1).strip() if buyer_tin_match else ""
    buyer_vat_match = re.search(r'Customer\s+VAT\s*(\d+)', text)
    buyer_vat = buyer_vat_match.group(1).strip() if buyer_vat_match else ""
    buyer_phone_match = re.search(r'Customer\s+Tel/Mobile\s*([\d\s]+)', text)
    buyer_phone = buyer_phone_match.group(1).strip() if buyer_phone_match else ""
    buyer_email_match = re.search(r'Customer\s+Email\s*([\w\.-]+@[\w\.-]+)', text)
    buyer_email = buyer_email_match.group(1).strip() if buyer_email_match else ""
    
    tax_groups = {}
    for item in feedmix_items:
        pct = item['tax_pct']
        if pct not in tax_groups:
            tax_groups[pct] = {'net': 0, 'vat': 0, 'total': 0}
        net = item['total'] / (1 + pct/100) if pct > 0 else item['total']
        vat = item['total'] - net
        tax_groups[pct]['net'] += net
        tax_groups[pct]['vat'] += vat
        tax_groups[pct]['total'] += item['total']
        
    taxes = []
    for pct, vals in tax_groups.items():
        taxes.append({
            'tax_code': 'A' if pct > 0 else 'B',
            'tax_percent': pct,
            'tax_amount': round(vals['vat'], 2),
            'sales_amount_with_tax': round(vals['total'], 2)
        })
        
    return {
        'invoice_no': invoice_no, 'original_invoice_no': original_invoice_no, 'credit_reason': credit_reason,
        'date': date_iso, 'currency': currency, 'buyer_name': buyer_name, 'buyer_tin': buyer_tin,
        'buyer_vat': buyer_vat, 'buyer_address': buyer_addr, 'buyer_phone': buyer_phone, 'buyer_email': buyer_email,
        'items': feedmix_items, 'taxes': taxes, 'receipt_type': receipt_type, 'vat_exclusive': False
    }
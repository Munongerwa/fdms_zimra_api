import math
from datetime import datetime

def validate_zimra_payload(payload):
    errors = []
    if 'receipt' not in payload:
        return ["Missing 'receipt' object in payload"]
        
    receipt = payload['receipt']
    receipt_type = receipt.get('receiptType', '').upper()
    currency = receipt.get('receiptCurrency', '')
    receipt_total = float(receipt.get('receiptTotal', 0))
    is_credit_note = receipt_type == 'CREDITNOTE'
    is_debit_note = receipt_type == 'DEBITNOTE'
    
    if receipt_type not in ['FISCALINVOICE', 'CREDITNOTE', 'DEBITNOTE']:
        errors.append("RCPT002: Invalid receiptType. Must be FISCALINVOICE, CREDITNOTE, or DEBITNOTE.")
        
    if len(currency) != 3:
        errors.append("RCPT010: Currency code must be exactly 3 characters (ISO 4217).")
        
    invoice_no = receipt.get('invoiceNo', '')
    if not invoice_no or len(invoice_no) > 50:
        errors.append("RCPT013: Invoice number is required and must be <= 50 characters.")

    receipt_date_str = receipt.get('receiptDate', '')
    try:
        receipt_date = datetime.strptime(receipt_date_str, "%Y-%m-%dT%H:%M:%S")
        if receipt_date > datetime.now():
            errors.append("RCPT031: Receipt date cannot be in the future.")
    except ValueError:
        errors.append("RCPT002: Invalid receiptDate format. Must be YYYY-MM-DDTHH:MM:SS.")

    if is_credit_note or is_debit_note:
        if not receipt.get('receiptNotes'):
            errors.append("RCPT034: receiptNotes is mandatory for Credit/Debit Notes.")
        if 'creditDebitNote' not in receipt:
            errors.append("RCPT015: creditDebitNote object is mandatory for Credit/Debit Notes.")

    lines = receipt.get('receiptLines', [])
    if not lines:
        errors.append("RCPT016: At least one receipt line must be provided.")
        
    sum_line_totals = 0.0
    tax_line_totals = {}
    
    for line in lines:
        line_total = float(line.get('receiptLineTotal', 0))
        price = float(line.get('receiptLinePrice', 0))
        qty = float(line.get('receiptLineQuantity', 0))
        tax_pct = float(line.get('taxPercent', 0))
        hs_code = str(line.get('receiptLineHSCode', ''))
        name = line.get('receiptLineName', '')
        
        sum_line_totals += line_total
        
        if hs_code and len(hs_code) not in [4, 8]:
            errors.append(f"RCPT048: Invalid HS Code length for item '{name}'. Must be 4 or 8 digits.")
            
        if len(name) > 200:
            errors.append(f"RCPT002: Item name exceeds 200 characters: '{name}'")
            
        if qty <= 0:
            errors.append(f"RCPT023: Quantity must be > 0 for item '{name}'.")
            
        if receipt_type == 'FISCALINVOICE' and price <= 0:
            errors.append(f"RCPT022: Price must be > 0 for Invoice Sale: '{name}'")
        if is_credit_note and price >= 0:
            errors.append(f"RCPT022: Price must be < 0 for Credit Note Sale: '{name}'")
            
        if not math.isclose(line_total, price * qty, rel_tol=1e-2, abs_tol=0.05):
            errors.append(f"RCPT024: Line total ({line_total}) != Price ({price}) * Qty ({qty}) for '{name}'")

        tax_key = (tax_pct, line.get('taxCode', 'A'))
        if tax_key not in tax_line_totals:
            tax_line_totals[tax_key] = 0.0
        tax_line_totals[tax_key] += line_total

    taxes = receipt.get('receiptTaxes', [])
    if not taxes:
        errors.append("RCPT017: At least one tax line must be provided.")
        
    sum_tax_sales_with_tax = 0.0
    
    for tax in taxes:
        tax_pct = float(tax.get('taxPercent', 0))
        tax_code = tax.get('taxCode', 'A')
        tax_amount = float(tax.get('taxAmount', 0))
        sales_with_tax = float(tax.get('salesAmountWithTax', 0))
        
        sum_tax_sales_with_tax += sales_with_tax
        
        expected_line_sum = tax_line_totals.get((tax_pct, tax_code), 0.0)
        
        if receipt.get('receiptLinesTaxInclusive', True):
            # Relaxed tolerance (abs_tol=0.05) to handle legacy C# rounding differences
            expected_tax = expected_line_sum * (tax_pct / (100 + tax_pct))
            if not math.isclose(tax_amount, expected_tax, rel_tol=1e-2, abs_tol=0.05):
                errors.append(f"RCPT026: Incorrect taxAmount for {tax_pct}%. Expected ~{expected_tax:.2f}, got {tax_amount:.2f}")
                
        if not math.isclose(sales_with_tax, expected_line_sum, rel_tol=1e-2, abs_tol=0.05):
            errors.append(f"RCPT027: Incorrect salesAmountWithTax for {tax_pct}%. Expected {expected_line_sum:.2f}, got {sales_with_tax:.2f}")

    payments = receipt.get('receiptPayments', [])
    if not payments:
        errors.append("RCPT018: At least one payment method must be provided.")
        
    sum_payments = 0.0
    for pay in payments:
        pay_amt = float(pay.get('paymentAmount', 0))
        sum_payments += pay_amt
        
        if (receipt_type == 'FISCALINVOICE' or is_debit_note) and pay_amt < 0:
            errors.append("RCPT028: Payment amount must be >= 0 for Invoice/Debit Note.")
        if is_credit_note and pay_amt > 0:
            errors.append("RCPT028: Payment amount must be <= 0 for Credit Note.")

    if not math.isclose(receipt_total, sum_line_totals, rel_tol=1e-2, abs_tol=0.05):
        errors.append(f"RCPT019: Receipt total ({receipt_total}) != Sum of lines ({sum_line_totals:.2f})")
        
    if not math.isclose(receipt_total, sum_tax_sales_with_tax, rel_tol=1e-2, abs_tol=0.05):
        errors.append(f"RCPT038: Receipt total ({receipt_total}) != Sum of tax salesAmountWithTax ({sum_tax_sales_with_tax:.2f})")
        
    if not math.isclose(receipt_total, sum_payments, rel_tol=1e-2, abs_tol=0.05):
        errors.append(f"RCPT039: Receipt total ({receipt_total}) != Sum of payments ({sum_payments:.2f})")
        
    if (receipt_type == 'FISCALINVOICE' or is_debit_note) and receipt_total < 0:
        errors.append("RCPT040: Receipt total must be >= 0 for Invoice/Debit Note.")
    if is_credit_note and receipt_total > 0:
        errors.append("RCPT040: Receipt total must be <= 0 for Credit Note.")

    return errors
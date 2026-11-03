import io
import os
import re
from html import escape
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, KeepTogether, HRFlowable
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import qrcode

FONT_NAME = 'Arial'
FONT_BOLD = 'Arial-Bold'
FONT_DIR = os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Fonts')
pdfmetrics.registerFont(TTFont(FONT_NAME, os.path.join(FONT_DIR, 'arial.ttf')))
pdfmetrics.registerFont(TTFont(FONT_BOLD, os.path.join(FONT_DIR, 'arialbd.ttf')))
pdfmetrics.registerFontFamily(
    'Arial',
    normal=FONT_NAME,
    bold=FONT_BOLD,
    italic=FONT_NAME,
    boldItalic=FONT_BOLD,
)

def generate_qr_code_image(qr_data, size=120):
    """Generates a QR code image in memory."""
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(qr_data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)
    return img_byte_arr

def generate_zimra_a4_pdf(pdf_payload, verification_code, qr_code_url, device_id, fiscal_day_no, print_format="InvoiceA4", seller_data=None, serial_number="N/A"):
    """
    Generates an A4 Fiscal Tax Invoice or Credit Note.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, topMargin=12*mm, bottomMargin=15*mm,
        leftMargin=15*mm, rightMargin=15*mm
    )
    styles = getSampleStyleSheet()

    style_company = ParagraphStyle(
        'A4Company', parent=styles['Normal'], fontSize=9,
        fontName=FONT_BOLD, leading=11, spaceAfter=1
    )
    style_title = ParagraphStyle(
        'A4Title', parent=styles['Normal'], fontSize=13,
        fontName=FONT_BOLD, alignment=TA_RIGHT, leading=16, spaceAfter=3
    )
    style_normal = ParagraphStyle(
        'A4Normal', parent=styles['Normal'], fontSize=8,
        fontName=FONT_NAME, leading=10, spaceAfter=0
    )
    style_right = ParagraphStyle(
        'A4Right', parent=style_normal, alignment=TA_RIGHT
    )
    style_header = ParagraphStyle(
        'A4Header', parent=styles['Normal'], fontSize=8,
        fontName=FONT_BOLD, leading=10, spaceAfter=3
    )
    style_table_header = ParagraphStyle(
        'A4TableHeader', parent=style_normal, fontName=FONT_BOLD
    )
    style_center = ParagraphStyle(
        'A4Center', parent=style_normal, alignment=TA_CENTER
    )

    def paragraph(value, style=style_normal):
        return Paragraph(escape(str(value if value is not None else "")), style)

    story = []
    receipt = pdf_payload.get('receipt', pdf_payload.get('Receipt'))
    if not isinstance(receipt, dict):
        receipt = pdf_payload
    receipt_type = receipt.get('receiptType', 'FISCALINVOICE')
    is_credit_note = 'CREDIT' in receipt_type.upper()

    if qr_code_url:
        qr_img = Image(generate_qr_code_image(qr_code_url), width=23*mm, height=23*mm)
        qr_table = Table([[qr_img]], colWidths=[180*mm])
        qr_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 1*mm),
        ]))
        story.append(qr_table)
        story.append(Paragraph(
            f"Verification code: {escape(str(verification_code))}", style_center
        ))
        story.append(Spacer(1, 4*mm))

    # Seller details on the left and invoice details on the right.
    seller_name = seller_data.get('name', pdf_payload.get('company_name', 'FISCALINK')) if seller_data else 'FISCALINK'
    seller_address = seller_data.get('address', '') if seller_data else ''
    seller_lines = [paragraph(seller_name, style_company), paragraph(seller_address)]
    if seller_data:
        seller_lines.extend([
            paragraph(f"Phone: {seller_data.get('phone', '')}"),
            paragraph(f"Email: {seller_data.get('email', '')}"),
        ])

    date_value = str(receipt.get('receiptDate', '') or '').split('T')[0]
    try:
        date_value = datetime.strptime(date_value, "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        pass
    title = ("FISCAL CREDIT NOTE" if qr_code_url else "CREDIT NOTE") if is_credit_note else (
        "FISCAL TAX INVOICE" if qr_code_url else "SALES INVOICE"
    )
    invoice_lines = [
        Paragraph(escape(title), style_title),
        paragraph(f"Document No: {receipt.get('invoiceNo', '')}", style_right),
        paragraph(f"Invoice Date: {date_value}", style_right),
        paragraph(f"VAT Number: {seller_data.get('vat', '') if seller_data else ''}", style_right),
        paragraph(f"TIN Number: {seller_data.get('tin', '') if seller_data else ''}", style_right),
        paragraph(f"Currency: {receipt.get('receiptCurrency', 'USD')}", style_right),
    ]
    if is_credit_note:
        reference_no = (
            receipt.get('originalInvoiceNo')
            or receipt.get('original_invoice_no')
            or pdf_payload.get('originalInvoiceNo')
            or pdf_payload.get('original_invoice_no')
            or ''
        )
        reference_no = str(reference_no).strip()
        if not reference_no:
            receipt_notes = str(receipt.get('receiptNotes', ''))
            reference_match = re.search(
                r'\bcredit\s+note\s+for\s+(.+?)\s*$',
                receipt_notes,
                re.IGNORECASE,
            )
            if reference_match:
                reference_no = reference_match.group(1).strip()
        invoice_lines.append(paragraph(f"Reference No: {reference_no}", style_right))
    header_table = Table(
        [[seller_lines, invoice_lines]], colWidths=[90*mm, 90*mm]
    )
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4*mm),
    ]))
    story.append(header_table)
    story.append(HRFlowable(width="100%", thickness=0.7, color=colors.black, spaceAfter=5*mm))

    # Customer details.
    buyer = receipt.get('buyerData', {})
    buyer_address = buyer.get('buyerAddress', {})
    buyer_contacts = buyer.get('buyerContacts', {})
    address_parts = [
        buyer_address.get(key, '') for key in ('houseNo', 'street', 'city')
        if buyer_address.get(key)
    ]
    story.append(Paragraph("CUSTOMER DETAILS:", style_header))
    buyer_rows = [
        [paragraph("Customer Name:"), paragraph(buyer.get('buyerRegisterName', ''))],
        [paragraph("Customer Address:"), paragraph(" ".join(address_parts))],
        [paragraph("Customer VAT No:"), paragraph(buyer.get('vatNumber', ''))],
        [paragraph("Customer TIN No:"), paragraph(buyer.get('buyerTIN', ''))],
        [paragraph("Customer Email:"), paragraph(buyer_contacts.get('email', ''))],
        [paragraph("Customer Telephone:"), paragraph(buyer_contacts.get('phoneNo', ''))],
    ]
    buyer_table = Table(buyer_rows, colWidths=[30*mm, 150*mm])
    buyer_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    story.append(buyer_table)
    property_no = buyer.get('propertyNo', buyer.get('buyerPropertyNo', ''))
    if property_no:
        story.append(Spacer(1, 2*mm))
        story.append(Paragraph(
            f"<b>Property No:</b> {escape(str(property_no))}", style_right
        ))
    story.append(Spacer(1, 4*mm))

    # Line items and invoice totals.
    story.append(HRFlowable(width="100%", thickness=0.4, color=colors.lightgrey, spaceAfter=2*mm))
    col_widths = [18*mm, 68*mm, 12*mm, 21*mm, 21*mm, 20*mm, 20*mm]
    table_data = [[
        paragraph("HS Code", style_table_header),
        paragraph("Description", style_table_header),
        paragraph("Qty", style_center),
        paragraph("Price (Incl)", style_right),
        paragraph("Total (Excl)", style_right),
        paragraph("VAT Amount", style_right),
        paragraph("Total (Incl)", style_right),
    ]]
    total_excl = 0
    total_vat = 0
    total_incl = 0
    for line in receipt.get('receiptLines', []):
        line_total_incl = float(line.get('receiptLineTotal', 0) or 0)
        line_tax_pct = float(line.get('taxPercent', 0) or 0)
        if line_tax_pct > 0:
            line_excl = line_total_incl / (1 + (line_tax_pct / 100))
            line_vat = line_total_incl - line_excl
        else:
            line_excl = line_total_incl
            line_vat = 0
        total_excl += line_excl
        total_vat += line_vat
        total_incl += line_total_incl
        table_data.append([
            paragraph(line.get('receiptLineHSCode', '')),
            paragraph(line.get('receiptLineName', '')),
            paragraph(f"{float(line.get('receiptLineQuantity', 0) or 0):.2f}", style_center),
            paragraph(f"{float(line.get('receiptLinePrice', 0) or 0):,.2f}", style_right),
            paragraph(f"{line_excl:,.2f}", style_right),
            paragraph(f"{line_vat:,.2f}", style_right),
            paragraph(f"{line_total_incl:,.2f}", style_right),
        ])
    currency = receipt.get('receiptCurrency', 'USD')
    total_labels = [
        ("Sub Total (Excl)", total_excl),
        ("VAT Total", total_vat),
        (f"Invoice Total {currency}", total_incl),
    ]
    if "posAmountReceived" in receipt and float(receipt.get("posAmountReceived") or 0) > 0:
        total_labels.extend([
            (f"Amount Received {currency}", float(receipt["posAmountReceived"])),
            (f"Change {currency}", float(receipt.get("posChangeDue") or 0)),
        ])
    total_start = len(table_data)
    for label, amount in total_labels:
        table_data.append([
            paragraph(label, style_right), "", "", "", "", "", paragraph(f"{amount:,.2f}", style_right)
        ])

    table_style = [
        ('GRID', (0, 0), (-1, -1), 0.4, colors.lightgrey),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 3),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]
    for row_index in range(total_start, len(table_data)):
        table_style.append(('SPAN', (0, row_index), (5, row_index)))
    items_table = Table(table_data, colWidths=col_widths, repeatRows=1)
    items_table.setStyle(TableStyle(table_style))
    story.append(items_table)
    story.append(Spacer(1, 3*mm))
    story.append(Paragraph(
        f"Device ID: {escape(str(device_id))} | Fiscal Day: {escape(str(fiscal_day_no))}"
        f" | Serial No: {escape(str(serial_number))}",
        style_center,
    ))
    if qr_code_url:
        story.append(Paragraph(
            f"You can verify this receipt manually at {escape(str(qr_code_url))}",
            style_center,
        ))

    doc.build(story)
    buffer.seek(0)
    return buffer

def generate_80mm_thermal_receipt(pdf_payload, verification_code, qr_code_url, device_id, fiscal_day_no, seller_data, serial_number):
    buffer = io.BytesIO()
    
    # ============================================================
    # FIX 1: DYNAMIC PAGE HEIGHT CALCULATION
    # Calculates the exact height needed so the printer never creates a blank page gap.
    # ============================================================
    receipt = pdf_payload.get('receipt', {})
    num_items = len(receipt.get('receiptLines', []))
    buyer = receipt.get('buyerData', {})
    has_buyer = bool(buyer and buyer.get('buyerRegisterName', ''))
    
    # Base height covers the header, seller info, document metadata, totals, and footer.
    base_height_mm = 170
    has_qr = bool(qr_code_url)
    if has_qr:
        base_height_mm += 40
    if has_buyer:
        base_height_mm += 45 # Add extra space if buyer details are present
    
    height_per_item_mm = 15  # Product name plus one row of numeric values
    buffer_mm = 20           # Extra buffer at the bottom for the physical paper cutter
    
    dynamic_height = (base_height_mm + (num_items * height_per_item_mm) + buffer_mm) * mm
    
    doc = SimpleDocTemplate(buffer, pagesize=(80*mm, dynamic_height), 
                            topMargin=2*mm, bottomMargin=2*mm, 
                            leftMargin=4*mm, rightMargin=4*mm)
    # ============================================================

    styles = getSampleStyleSheet()
    s_title = ParagraphStyle('Title', fontSize=14, alignment=TA_CENTER, fontName=FONT_BOLD, spaceAfter=1*mm, spaceBefore=1*mm)
    s_comp = ParagraphStyle('CompName', fontSize=12, alignment=TA_CENTER, fontName=FONT_BOLD, spaceAfter=0.5*mm)
    s_center = ParagraphStyle('Center', fontSize=9, fontName=FONT_NAME, alignment=TA_CENTER, spaceAfter=0.5*mm)
    s_bold_center = ParagraphStyle('BoldCenter', fontSize=9, fontName=FONT_BOLD, alignment=TA_CENTER, spaceAfter=0.5*mm)
    s_tbl = ParagraphStyle('Tbl', fontSize=9, fontName=FONT_NAME, spaceAfter=0.7*mm, leading=10)
    s_tbl_r = ParagraphStyle('TblR', fontSize=9, fontName=FONT_NAME, alignment=TA_RIGHT, spaceAfter=0.7*mm, leading=10)
    s_tbl_b_r = ParagraphStyle('TblBR', fontSize=9, fontName=FONT_BOLD, alignment=TA_RIGHT, spaceAfter=0.7*mm, leading=10)
    s_product_name = ParagraphStyle('ThermalProductName', fontSize=9, fontName=FONT_BOLD, spaceAfter=0.5*mm, leading=10)
    s_product_header = ParagraphStyle('ThermalProductHeader', fontSize=8, fontName=FONT_BOLD, alignment=TA_CENTER, leading=9)
    s_tbl_9pt = ParagraphStyle('Tbl9', fontSize=9, fontName=FONT_BOLD, spaceAfter=0.5*mm, leading=10)
    s_tbl_9pt_r = ParagraphStyle('Tbl9R', fontSize=9, fontName=FONT_BOLD, alignment=TA_RIGHT, spaceAfter=0.5*mm, leading=10)

    story = []
    buyer = receipt.get('buyerData', {})
    receipt_counter = receipt.get('receiptCounter', '')
    receipt_global_no = receipt.get('receiptGlobalNo', '')

    def add_dashed_line():
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.black, spaceAfter=1*mm, spaceBefore=1*mm))

    is_credit_note = "CREDIT" in str(receipt.get("receiptType", "")).upper()
    document_title = ("FISCAL CREDIT NOTE" if qr_code_url else "CREDIT NOTE") if is_credit_note else (
        "FISCAL TAX INVOICE" if qr_code_url else "SALES INVOICE"
    )
    story.append(Paragraph(document_title, s_title))
    
    logo_path = r"C:\Receipts\logo.png" 
    if os.path.exists(logo_path):
        try:
            logo_img = Image(logo_path, width=56*mm, height=18*mm)
            logo_table = Table([[logo_img]], colWidths=[72*mm])
            logo_table.setStyle(TableStyle([('ALIGN', (0,0), (-1,-1), 'CENTER')]))
            story.append(logo_table)
        except Exception as e:
            print(f"⚠️ Warning: Could not load logo: {e}")

    story.append(Paragraph(seller_data.get('name', ''), s_comp))
    story.append(Paragraph(seller_data.get('address', ''), s_center))
    story.append(Paragraph(f"Phone: {seller_data.get('phone', '')}", s_center))
    story.append(Paragraph(f"Email: {seller_data.get('email', '')}", s_center))
    story.append(Paragraph(f"VAT Number: {seller_data.get('vat', '')}", s_center))
    story.append(Paragraph(f"TIN: {seller_data.get('tin', '')}", s_center))
    add_dashed_line()

    doc_data = [
        [Paragraph("DeviceId:", s_tbl), Paragraph(f"{device_id}", s_tbl_r)],
        [Paragraph("Receipt Number:", s_tbl), Paragraph(f"{receipt_counter}", s_tbl_r)],
        [Paragraph("Customer Reference:", s_tbl), Paragraph(f"{receipt.get('invoiceNo', '')}", s_tbl_r)],
        [Paragraph("Invoice Number:", s_tbl), Paragraph(f"{receipt_global_no}", s_tbl_r)],
        [Paragraph("Fiscal Day:", s_tbl), Paragraph(f"{fiscal_day_no}", s_tbl_r)],
        [Paragraph("Date:", s_tbl), Paragraph(f"{receipt.get('receiptDate', '')}", s_tbl_r)]
    ]
    if is_credit_note:
        doc_data.append([
            Paragraph("Original Invoice:", s_tbl),
            Paragraph(escape(str(receipt.get("originalInvoiceNo", ""))), s_tbl_r),
        ])
    doc_table = Table(doc_data, colWidths=[35*mm, 37*mm])
    doc_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0.6*mm),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0.6*mm),
    ]))
    story.append(doc_table)
    add_dashed_line()

    buyer_name = buyer.get('buyerRegisterName', '') if buyer else ''
    if buyer_name:
        story.append(Paragraph("Buyer:", ParagraphStyle('BuyerHead', fontSize=10, fontName=FONT_BOLD, spaceAfter=0.5*mm)))
        add_dashed_line()
        buyer_data = [
            [Paragraph("Buyer Name:", s_tbl), Paragraph(escape(str(buyer_name)), s_tbl_r)],
            [Paragraph("Buyer TIN:", s_tbl), Paragraph(escape(str(buyer.get('buyerTIN', ''))), s_tbl_r)],
            [Paragraph("Buyer VAT:", s_tbl), Paragraph(escape(str(buyer.get('vatNumber', ''))), s_tbl_r)],
            [Paragraph("Buyer Address:", s_tbl), Paragraph(escape(str(buyer.get('buyerAddress', {}).get('street', ''))), s_tbl_r)],
            [Paragraph("Buyer Contact:", s_tbl), Paragraph(escape(str(buyer.get('buyerContacts', {}).get('phoneNo', ''))), s_tbl_r)],
            [Paragraph("Buyer Email:", s_tbl), Paragraph(escape(str(buyer.get('buyerContacts', {}).get('email', ''))), s_tbl_r)]
        ]
        buyer_table = Table(buyer_data, colWidths=[35*mm, 37*mm])
        buyer_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0.6*mm),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0.6*mm),
        ]))
        
        # FIX 2: Wrap buyer table in KeepTogether to prevent it from splitting across pages
        story.append(KeepTogether([buyer_table]))
        add_dashed_line()

    col_widths = [28*mm, 10*mm, 12*mm, 12*mm, 10*mm] 
    table_data = [[
        Paragraph("<b>Description</b>", s_tbl),
        Paragraph("<b>Qty</b>", s_tbl_r),
        Paragraph("<b>Price Incl</b>", s_tbl_r),
        Paragraph("<b>Amt Incl</b>", s_tbl_r),
        Paragraph("<b>Vat</b>", s_tbl_r)
    ]]

    table_style = [
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, 0), 0.8*mm),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 1.8*mm),
    ]
    total_excl_sum = 0
    total_vat_sum = 0
    total_incl_sum = 0
    row_idx = 1
    for line in receipt.get('receiptLines', []):
        line_total_incl = float(line.get('receiptLineTotal', 0) or 0)
        line_tax_pct = float(line.get('taxPercent', 0) or 0)
        line_price_incl = float(line.get('receiptLinePrice', 0) or 0)
        line_quantity = float(line.get('receiptLineQuantity', 0) or 0)
        if line_tax_pct > 0:
            line_excl = line_total_incl / (1 + (line_tax_pct / 100))
            line_vat = line_total_incl - line_excl
        else:
            line_excl = line_total_incl
            line_vat = 0
        total_excl_sum += line_excl
        total_vat_sum += line_vat
        total_incl_sum += line_total_incl
        product_name = escape(str(line.get('receiptLineName', '')))
        table_data.append([Paragraph(product_name, s_product_name), "", "", ""])
        table_style.append(('SPAN', (0, row_idx), (-1, row_idx)))
        row_idx += 1

        product_values = (
            line_quantity,
            line_price_incl,
            line_total_incl,
            line_vat,
        )
        value_cells = []
        for value, column_width in zip(product_values, col_widths):
            value_text = f"{value:,.2f}"
            available_width = column_width - 1*mm
            base_font_size = 8
            text_width = pdfmetrics.stringWidth(value_text, FONT_NAME, base_font_size)
            font_size = min(
                base_font_size,
                max(4.5, base_font_size * available_width / text_width),
            )
            value_style = ParagraphStyle(
                'ThermalProductValue',
                fontName=FONT_NAME,
                fontSize=font_size,
                leading=font_size + 1,
                alignment=TA_RIGHT,
            )
            value_cells.append(Paragraph(escape(value_text), value_style))
        table_data.append(value_cells)
        row_idx += 1
        table_style.extend([
            ('TOPPADDING', (0, row_idx - 2), (-1, row_idx - 2), 0.8*mm),
            ('TOPPADDING', (0, row_idx - 1), (-1, row_idx - 1), 0.5*mm),
            ('LINEBELOW', (0, row_idx - 1), (-1, row_idx - 1), 0.4, colors.lightgrey),
            ('BOTTOMPADDING', (0, row_idx - 1), (-1, row_idx - 1), 1.5*mm),
        ])

    t = Table(table_data, colWidths=col_widths)
    t.setStyle(TableStyle(table_style))
    story.append(t)
    add_dashed_line()

    # Determine Cashier Name: Use parsed cashier (Sales Person) if available, else fallback to Company Name
    cashier_name = pdf_payload.get('cashier_name', '') 

    totals_data = [
        [Paragraph("<b>Total Excl:</b>", s_tbl), Paragraph(f"{total_excl_sum:.2f}", s_tbl_r)],
        [Paragraph("<b>Total VAT:</b>", s_tbl), Paragraph(f"{total_vat_sum:.2f}", s_tbl_r)],
        [Paragraph("Total Incl:", s_tbl_9pt), Paragraph(f"{total_incl_sum:.2f}", s_tbl_9pt_r)],
        [Paragraph("Currency:", s_tbl), Paragraph(f"<b>{receipt.get('receiptCurrency', 'USD')}</b>", s_tbl_r)],
    ]
    if float(receipt.get("posAmountReceived") or 0) > 0:
        totals_data.extend([
            [Paragraph("Amount Received:", s_tbl), Paragraph(
                f"{float(receipt['posAmountReceived']):.2f}", s_tbl_r
            )],
            [Paragraph("Change:", s_tbl), Paragraph(
                f"{float(receipt.get('posChangeDue', 0) or 0):.2f}", s_tbl_r
            )],
        ])
    totals_data.append([Paragraph("Cashier:", s_tbl), Paragraph(cashier_name, s_tbl_r)])
    
    totals_table = Table(totals_data, colWidths=[35*mm, 37*mm])
    totals_table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0), ('TOPPADDING', (0, 0), (-1, -1), 1*mm), ('BOTTOMPADDING', (0, 0), (-1, -1), 1*mm)]))
    story.append(totals_table)
    add_dashed_line()

    vat_data = [[Paragraph("<b>Vat %</b>", s_tbl), Paragraph("<b>Net.Amt</b>", s_tbl_r), Paragraph("<b>VAT</b>", s_tbl_r), Paragraph("<b>Amount</b>", s_tbl_r)]]
    tax_groups = {}
    for line in receipt.get('receiptLines', []):
        pct = line.get('taxPercent', 0)
        total = line.get('receiptLineTotal', 0)
        if pct > 0:
            excl = total / (1 + (pct/100))
            vat = total - excl
        else:
            excl = total
            vat = 0
        if pct not in tax_groups:
            tax_groups[pct] = {'net': 0, 'vat': 0, 'total': 0}
        tax_groups[pct]['net'] += excl
        tax_groups[pct]['vat'] += vat
        tax_groups[pct]['total'] += total
    for pct, vals in tax_groups.items():
        vat_data.append([Paragraph(f"{pct:.2f}", s_tbl), Paragraph(f"{vals['net']:.2f}", s_tbl_r), Paragraph(f"{vals['vat']:.2f}", s_tbl_r), Paragraph(f"{vals['total']:.2f}", s_tbl_r)])
    vat_table = Table(vat_data, colWidths=[15*mm, 20*mm, 20*mm, 17*mm])
    vat_table.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0), ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 0)]))
    story.append(vat_table)
    add_dashed_line()

    if qr_code_url:
        qr_img_data = generate_qr_code_image(qr_code_url)
        qr_img = Image(qr_img_data, width=32*mm, height=32*mm)
        qr_table = Table([[qr_img]], colWidths=[72*mm])
        qr_table.setStyle(TableStyle([('ALIGN', (0,0), (-1,-1), 'CENTER')]))
        story.append(qr_table)
        story.append(Paragraph(f"Verification code: {verification_code}", s_bold_center))
        story.append(Paragraph("You can verify this receipt manually at", s_center))
        story.append(Paragraph("https://fdms.zimra.co.zw/", s_center))
    elif not is_credit_note:
        story.append(Paragraph("NON-FISCAL INVOICE - NOT FISCALISED", s_bold_center))
    else:
        story.append(Paragraph("NON-FISCAL CREDIT NOTE - NOT FISCALISED", s_bold_center))
    
    # Final spacer for cutter
    story.append(Spacer(1, 10*mm)) 

    doc.build(story)
    buffer.seek(0)
    return buffer

def generate_z_report_pdf(z_report_data):
    """Generates a PDF Z-Report for a closed fiscal day."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=20*mm, bottomMargin=20*mm, leftMargin=20*mm, rightMargin=20*mm)
    styles = getSampleStyleSheet()
    style_title = ParagraphStyle('Title', parent=styles['Normal'], fontSize=18, fontName=FONT_BOLD, alignment=TA_CENTER, spaceAfter=10)
    style_header = ParagraphStyle('Header', parent=styles['Normal'], fontSize=12, fontName=FONT_BOLD, spaceAfter=5)
    style_normal = ParagraphStyle(
        'ZReportNormal', parent=styles['Normal'], fontSize=10,
        fontName=FONT_NAME, spaceAfter=3
    )
    
    story = []
    story.append(Paragraph("ZIMRA Z-REPORT", style_title))
    story.append(Spacer(1, 10*mm))
    story.append(Paragraph(f"Fiscal Day No: {z_report_data.get('fiscal_day_no', 'N/A')}", style_normal))
    story.append(Paragraph(f"Device ID: {z_report_data.get('device_id', 'N/A')}", style_normal))
    story.append(Paragraph(f"Closed Date: {z_report_data.get('close_date', 'N/A')}", style_normal))
    story.append(Paragraph(f"Total Receipts: {z_report_data.get('total_receipts', 0)}", style_normal))
    story.append(Spacer(1, 10*mm))
    story.append(Paragraph("CURRENCY BREAKDOWN", style_header))
    currencies = z_report_data.get('currencies', {})
    for curr, data in currencies.items():
        story.append(Paragraph(f"<b>{curr}</b>", style_normal))
        story.append(Paragraph(f"Total Sales: {data.get('total_sales', 0):,.2f}", style_normal))
        story.append(Paragraph(f"Total Tax: {data.get('total_tax', 0):,.2f}", style_normal))
        story.append(Spacer(1, 5*mm))
        
    doc.build(story)
    buffer.seek(0)
    return buffer
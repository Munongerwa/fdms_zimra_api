import io
import os
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, KeepTogether
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, KeepTogether, HRFlowable
from reportlab.lib import colors
import qrcode

# Try to register a standard font if available, otherwise fallback to Helvetica
try:
    # You can place a .ttf font in your assets folder if you want custom fonts
    # pdfmetrics.registerFont(TTFont('CustomFont', 'assets/arial.ttf'))
    FONT_NAME = 'Helvetica'
    FONT_BOLD = 'Helvetica-Bold'
except:
    FONT_NAME = 'Helvetica'
    FONT_BOLD = 'Helvetica-Bold'

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
    Generates a standard A4 Fiscal Tax Invoice or Credit Note.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=15*mm, bottomMargin=15*mm, leftMargin=15*mm, rightMargin=15*mm)
    styles = getSampleStyleSheet()
    
    # Custom Styles
    style_company = ParagraphStyle('Company', parent=styles['Normal'], fontSize=14, fontName=FONT_BOLD, alignment=TA_CENTER, spaceAfter=2)
    style_address = ParagraphStyle('Address', parent=styles['Normal'], fontSize=9, alignment=TA_CENTER, spaceAfter=1)
    style_title = ParagraphStyle('Title', parent=styles['Normal'], fontSize=16, fontName=FONT_BOLD, alignment=TA_CENTER, spaceAfter=10, spaceBefore=10)
    style_header = ParagraphStyle('Header', parent=styles['Normal'], fontSize=10, fontName=FONT_BOLD, spaceAfter=4)
    style_normal = ParagraphStyle('Normal', parent=styles['Normal'], fontSize=9, spaceAfter=2)
    style_small = ParagraphStyle('Small', parent=styles['Normal'], fontSize=8, textColor=colors.grey)
    
    story = []
    receipt = pdf_payload.get('receipt', {})
    receipt_type = receipt.get('receiptType', 'FISCALINVOICE')
    is_credit_note = 'CREDIT' in receipt_type.upper()
    
    # 1. Seller Information
    seller_name = seller_data.get('name', pdf_payload.get('company_name', 'FISCALINK')) if seller_data else 'FISCALINK'
    seller_address = seller_data.get('address', '') if seller_data else ''
    
    story.append(Paragraph(seller_name, style_company))
    story.append(Paragraph(seller_address, style_address))
    if seller_data:
        story.append(Paragraph(f"Phone: {seller_data.get('phone', '')} | Email: {seller_data.get('email', '')}", style_address))
        story.append(Paragraph(f"VAT Number: {seller_data.get('vat', '')} | TIN: {seller_data.get('tin', '')}", style_address))
    story.append(Spacer(1, 10*mm))
    
    # 2. Document Title
    title = "FISCAL CREDIT NOTE" if is_credit_note else "FISCAL TAX INVOICE"
    story.append(Paragraph(title, style_title))
    
    # 3. Invoice Meta Data (Two Columns)
    meta_data = [
        [Paragraph("<b>Document No:</b>", style_normal), Paragraph(receipt.get('invoiceNo', ''), style_normal),
         Paragraph("<b>Invoice Date:</b>", style_normal), Paragraph(receipt.get('receiptDate', '').split('T')[0], style_normal)],
        [Paragraph("<b>Device ID:</b>", style_normal), Paragraph(str(device_id), style_normal),
         Paragraph("<b>Fiscal Day:</b>", style_normal), Paragraph(str(fiscal_day_no), style_normal)],
        [Paragraph("<b>Serial No:</b>", style_normal), Paragraph(serial_number, style_normal),
         Paragraph("<b>Receipt No:</b>", style_normal), Paragraph(str(receipt.get('receiptGlobalNo', '')), style_normal)]
    ]
    meta_table = Table(meta_data, colWidths=[80, 120, 80, 120])
    meta_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 10*mm))
    
    # 4. Buyer Information
    buyer = receipt.get('buyerData', {})
    if buyer:
        story.append(Paragraph("CUSTOMER DETAILS:", style_header))
        buyer_addr = buyer.get('buyerAddress', {})
        buyer_contacts = buyer.get('buyerContacts', {})
        buyer_info = [
            [Paragraph("<b>Customer Name:</b>", style_normal), Paragraph(buyer.get('buyerRegisterName', ''), style_normal)],
            [Paragraph("<b>Customer Address:</b>", style_normal), Paragraph(f"{buyer_addr.get('street', '')} {buyer_addr.get('city', '')}", style_normal)],
            [Paragraph("<b>Customer TIN:</b>", style_normal), Paragraph(buyer.get('buyerTIN', ''), style_normal),
             Paragraph("<b>Customer VAT:</b>", style_normal), Paragraph(buyer.get('vatNumber', ''), style_normal)],
            [Paragraph("<b>Customer Email:</b>", style_normal), Paragraph(buyer_contacts.get('email', ''), style_normal),
             Paragraph("<b>Customer Phone:</b>", style_normal), Paragraph(buyer_contacts.get('phoneNo', ''), style_normal)]
        ]
        buyer_table = Table(buyer_info, colWidths=[100, 150, 80, 120])
        buyer_table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP')]))
        story.append(buyer_table)
        story.append(Spacer(1, 10*mm))
    
    # 5. Items Table
    story.append(Paragraph("ITEMS:", style_header))
    col_widths = [60, 180, 40, 60, 60, 60, 60]
    table_data = [[
        Paragraph("<b>HS Code</b>", style_normal),
        Paragraph("<b>Description</b>", style_normal),
        Paragraph("<b>Qty</b>", style_normal),
        Paragraph("<b>Price(Incl)</b>", style_normal),
        Paragraph("<b>Total(Excl)</b>", style_normal),
        Paragraph("<b>VAT Amount</b>", style_normal),
        Paragraph("<b>Total(Incl)</b>", style_normal)
    ]]
    
    total_excl = 0
    total_vat = 0
    total_incl = 0
    
    for line in receipt.get('receiptLines', []):
        line_total_incl = line.get('receiptLineTotal', 0)
        line_tax_pct = line.get('taxPercent', 0)
        
        # Calculate Excl and VAT from Incl total
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
            Paragraph(line.get('receiptLineHSCode', ''), style_normal),
            Paragraph(line.get('receiptLineName', ''), style_normal),
            Paragraph(f"{line.get('receiptLineQuantity', 0):.2f}", style_normal),
            Paragraph(f"{line.get('receiptLinePrice', 0):.2f}", style_normal),
            Paragraph(f"{line_excl:.2f}", style_normal),
            Paragraph(f"{line_vat:.2f}", style_normal),
            Paragraph(f"{line_total_incl:.2f}", style_normal)
        ])
        
    # Totals Row
    table_data.append([Paragraph("", style_normal), Paragraph("", style_normal), Paragraph("", style_normal), Paragraph("", style_normal),
                       Paragraph(f"<b>{total_excl:.2f}</b>", style_normal), Paragraph(f"<b>{total_vat:.2f}</b>", style_normal), Paragraph(f"<b>{total_incl:.2f}</b>", style_normal)])
    
    items_table = Table(table_data, colWidths=col_widths, repeatRows=1)
    items_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('GRID', (0, 0), (-1, -2), 0.5, colors.grey),
        ('LINEABOVE', (0, -1), (-1, -1), 1, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(items_table)
    story.append(Spacer(1, 10*mm))
    
    # 6. Verification & QR Code
    qr_img_data = generate_qr_code_image(qr_code_url)
    qr_img = Image(qr_img_data, width=80, height=80)
    
    ver_text = f"Verification Code: {verification_code}<br/>You can manually verify this receipt at<br/><b>{qr_code_url}</b>"
    ver_para = Paragraph(ver_text, style_normal)
    
    ver_table = Table([[qr_img, ver_para]], colWidths=[100, 300])
    ver_table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'MIDDLE')]))
    story.append(ver_table)
    
    doc.build(story)
    buffer.seek(0)
    return buffer

def generate_80mm_thermal_receipt(pdf_payload, verification_code, qr_code_url, device_id, fiscal_day_no, receipt_no, seller_data, serial_number):
    """
    Generates an 80mm thermal receipt matching the exact ZIMRA/QuickBooks layout.
    """
    buffer = io.BytesIO()
    
    # 80mm width is approx 226 points.
    doc = SimpleDocTemplate(buffer, pagesize=(226, 1000), topMargin=5*mm, bottomMargin=5*mm, leftMargin=2*mm, rightMargin=2*mm)
    styles = getSampleStyleSheet()
    
    # Custom styles for thermal receipt (Small fonts for 80mm paper)
    s_title = ParagraphStyle('Title', fontSize=10, alignment=TA_CENTER, fontName=FONT_BOLD, spaceAfter=2)
    s_comp = ParagraphStyle('CompName', fontSize=8, alignment=TA_CENTER, fontName=FONT_BOLD, spaceAfter=1)
    s_norm = ParagraphStyle('Norm', fontSize=7, fontName=FONT_NAME, spaceAfter=1)
    s_bold = ParagraphStyle('Bold', fontSize=7, fontName=FONT_BOLD, spaceAfter=1)
    s_center = ParagraphStyle('Center', fontSize=7, fontName=FONT_NAME, alignment=TA_CENTER, spaceAfter=1)
    s_right = ParagraphStyle('Right', fontSize=7, fontName=FONT_NAME, alignment=TA_RIGHT, spaceAfter=1)
    
    story = []
    receipt = pdf_payload.get('receipt', {})
    buyer = receipt.get('buyerData', {})
    
    # Helper for dividing lines
    def add_line():
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.black, spaceAfter=2*mm, spaceBefore=2*mm))

    # 1. FISCAL TAX INVOICE (Top)
    story.append(Paragraph("FISCAL TAX INVOICE", s_title))
    add_line()
    
    # 2. Company Details
    story.append(Paragraph(seller_data.get('name', ''), s_comp))
    story.append(Paragraph(seller_data.get('address', ''), s_center))
    story.append(Paragraph(f"Phone: {seller_data.get('phone', '')}", s_center))
    story.append(Paragraph(f"VAT: {seller_data.get('vat', '')} | TIN: {seller_data.get('tin', '')}", s_center))
    add_line()
    
    # 3. Device & Document Details
    story.append(Paragraph(f"DeviceId: {device_id}", s_norm))
    story.append(Paragraph(f"Receipt Number: {receipt_no}", s_norm))
    story.append(Paragraph(f"Customer Reference: {receipt.get('invoiceNo', '')}", s_norm))
    story.append(Paragraph(f"Invoice Number: {receipt.get('receiptGlobalNo', '')}", s_norm))
    story.append(Paragraph(f"Fiscal Day: {fiscal_day_no}", s_norm))
    story.append(Paragraph(f"Date: {receipt.get('receiptDate', '')}", s_norm))
    add_line()
    
    # 4. Buyer Details
    if buyer:
        story.append(Paragraph(f"Buyer Name: {buyer.get('buyerRegisterName', '')}", s_norm))
        story.append(Paragraph(f"Buyer TIN: {buyer.get('buyerTIN', '')}", s_norm))
        story.append(Paragraph(f"Buyer VAT: {buyer.get('vatNumber', '')}", s_norm))
        addr = buyer.get('buyerAddress', {})
        story.append(Paragraph(f"Buyer Address: {addr.get('street', '')} {addr.get('city', '')}", s_norm))
        contacts = buyer.get('buyerContacts', {})
        story.append(Paragraph(f"Buyer Contact: {contacts.get('phoneNo', '')}", s_norm))
        add_line()
    
    # 5. Product Lines (Description on top line, values on bottom line)
    total_excl_sum = 0
    total_vat_sum = 0
    
    for line in receipt.get('receiptLines', []):
        line_total_incl = line.get('receiptLineTotal', 0)
        line_tax_pct = line.get('taxPercent', 0)
        
        if line_tax_pct > 0:
            line_excl = line_total_incl / (1 + (line_tax_pct / 100))
            line_vat = line_total_incl - line_excl
        else:
            line_excl = line_total_incl
            line_vat = 0
            
        total_excl_sum += line_excl
        total_vat_sum += line_vat
        
        # Description on the line above
        story.append(Paragraph(line.get('receiptLineName', ''), s_norm))
        
        # Qty, Price, Amount, VAT on the line below (using a small table for alignment)
        val_data = [[
            Paragraph(f"Qty: {line.get('receiptLineQuantity', 0):.2f}", s_norm),
            Paragraph(f"Price: {line.get('receiptLinePrice', 0):.2f}", s_norm),
            Paragraph(f"Amt: {line_excl:.2f}", s_norm),
            Paragraph(f"VAT: {line_vat:.2f}", s_norm)
        ]]
        val_table = Table(val_data, colWidths=[55, 55, 55, 55])
        val_table.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP')]))
        story.append(val_table)
        story.append(Spacer(1, 1*mm))
        
    add_line()
    
    # 6. Totals (Excl, VAT, Incl, Change, Currency)
    total_incl = receipt.get('receiptTotal', total_excl_sum + total_vat_sum)
    
    story.append(Paragraph(f"Total Excl: {total_excl_sum:.2f}", s_norm))
    story.append(Paragraph(f"Total VAT: {total_vat_sum:.2f}", s_norm))
    story.append(Paragraph(f"Total Incl: {total_incl:.2f}", s_bold))
    story.append(Paragraph(f"Currency: {receipt.get('receiptCurrency', 'USD')}", s_norm))
    story.append(Paragraph(f"Change: 0.00", s_norm))
    add_line()
    
    # 7. VAT % Table
    vat_data = [[
        Paragraph("<b>Vat%</b>", s_norm),
        Paragraph("<b>Net.Amt</b>", s_norm),
        Paragraph("<b>VAT Amount</b>", s_norm),
        Paragraph("<b>Total</b>", s_norm)
    ]]
    
    # Group taxes by percentage
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
        vat_data.append([
            Paragraph(f"{pct:.2f}", s_norm),
            Paragraph(f"{vals['net']:.2f}", s_norm),
            Paragraph(f"{vals['vat']:.2f}", s_norm),
            Paragraph(f"{vals['total']:.2f}", s_norm)
        ])

    vat_table = Table(vat_data, colWidths=[55, 55, 55, 55])
    vat_table.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP')]))
    story.append(vat_table)
    add_line()
    
    # 8. QR Code & Verification (At the bottom)
    qr_img_data = generate_qr_code_image(qr_code_url)
    qr_img = Image(qr_img_data, width=60, height=60)
    story.append(qr_img)
    story.append(Spacer(1, 2*mm))
    
    story.append(Paragraph(f"Verification code: {verification_code}", s_bold))
    story.append(Paragraph("You can verify this receipt manually at", s_center))
    story.append(Paragraph("https://fdms.zimra.co.zw/", s_center))

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
    style_normal = ParagraphStyle('Normal', parent=styles['Normal'], fontSize=10, spaceAfter=3)
    
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
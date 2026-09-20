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
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, HRFlowable

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

def generate_80mm_thermal_receipt(pdf_payload, verification_code, qr_code_url, device_id, fiscal_day_no, seller_data, serial_number):
    buffer = io.BytesIO()
    
    # FIX 5: Increased margins to 4mm on left/right for better spacing
    doc = SimpleDocTemplate(buffer, pagesize=(80*mm, 300*mm), 
                            topMargin=2*mm, bottomMargin=2*mm, 
                            leftMargin=4*mm, rightMargin=4*mm)
    styles = getSampleStyleSheet()
    
    s_title = ParagraphStyle('Title', fontSize=9, alignment=TA_CENTER, fontName='Helvetica-Bold', spaceAfter=1*mm, spaceBefore=1*mm)
    s_comp = ParagraphStyle('CompName', fontSize=7, alignment=TA_CENTER, fontName='Helvetica-Bold', spaceAfter=0.5*mm)
    s_center = ParagraphStyle('Center', fontSize=7, fontName='Helvetica', alignment=TA_CENTER, spaceAfter=0.5*mm)
    s_bold_center = ParagraphStyle('BoldCenter', fontSize=7, fontName='Helvetica-Bold', alignment=TA_CENTER, spaceAfter=0.5*mm)
    
    s_tbl = ParagraphStyle('Tbl', fontSize=7, fontName='Helvetica', spaceAfter=0, leading=8)
    s_tbl_r = ParagraphStyle('TblR', fontSize=7, fontName='Helvetica', alignment=TA_RIGHT, spaceAfter=0, leading=8)
    s_tbl_b_r = ParagraphStyle('TblBR', fontSize=7, fontName='Helvetica-Bold', alignment=TA_RIGHT, spaceAfter=0, leading=8)
    s_tbl_9pt = ParagraphStyle('Tbl9', fontSize=9, fontName='Helvetica-Bold', spaceAfter=0, leading=10)
    s_tbl_9pt_r = ParagraphStyle('Tbl9R', fontSize=9, fontName='Helvetica-Bold', alignment=TA_RIGHT, spaceAfter=0, leading=10)

    story = []
    receipt = pdf_payload.get('receipt', {})
    buyer = receipt.get('buyerData', {})
    
    receipt_counter = receipt.get('receiptCounter', '')
    receipt_global_no = receipt.get('receiptGlobalNo', '')
    
    def add_dashed_line():
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.black, spaceAfter=1*mm, spaceBefore=1*mm))

    story.append(Paragraph("FISCAL TAX INVOICE", s_title))
    
    logo_path = r"C:\Receipts\logo.png" 
    if os.path.exists(logo_path):
        try:
            logo_img = Image(logo_path, width=56*mm, height=24*mm)
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
    doc_table = Table(doc_data, colWidths=[35*mm, 37*mm])
    doc_table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0), ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 0)]))
    story.append(doc_table)
    add_dashed_line()
    
    buyer_name = buyer.get('buyerRegisterName', '') if buyer else ''
    if buyer_name:
        story.append(Paragraph("Buyer:", ParagraphStyle('BuyerHead', fontSize=7, fontName='Helvetica-Bold', spaceAfter=0.5*mm)))
        add_dashed_line()
        
        # FIX 4: Removed duplicate "Buyer Trading Name" and simplified address
        buyer_data = [
            [Paragraph("Buyer Name:", s_tbl), Paragraph(buyer_name, s_tbl_r)],
            [Paragraph("Buyer TIN:", s_tbl), Paragraph(buyer.get('buyerTIN', ''), s_tbl_r)],
            [Paragraph("Buyer VAT:", s_tbl), Paragraph(buyer.get('vatNumber', ''), s_tbl_r)],
            [Paragraph("Buyer Address:", s_tbl), Paragraph(buyer.get('buyerAddress', {}).get('street', ''), s_tbl_r)],
            [Paragraph("Buyer Contact:", s_tbl), Paragraph(buyer.get('buyerContacts', {}).get('phoneNo', ''), s_tbl_r)]
        ]
        buyer_table = Table(buyer_data, colWidths=[35*mm, 37*mm])
        buyer_table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0), ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 0)]))
        story.append(buyer_table)
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
    ]

    total_excl_sum = 0
    total_vat_sum = 0
    total_incl_sum = 0
    row_idx = 1

    for line in receipt.get('receiptLines', []):
        line_total_incl = line.get('receiptLineTotal', 0)
        line_tax_pct = line.get('taxPercent', 0)
        line_price_incl = line.get('receiptLinePrice', 0)
        
        if line_tax_pct > 0:
            line_excl = line_total_incl / (1 + (line_tax_pct / 100))
            line_vat = line_total_incl - line_excl
        else:
            line_excl = line_total_incl
            line_vat = 0
            
        total_excl_sum += line_excl
        total_vat_sum += line_vat
        total_incl_sum += line_total_incl
        
        table_data.append([Paragraph(line.get('receiptLineName', ''), s_tbl), "", "", "", ""])
        table_style.append(('SPAN', (0, row_idx), (4, row_idx)))
        row_idx += 1
        
        table_data.append(["", Paragraph(f"{line.get('receiptLineQuantity', 0):.2f}", s_tbl_r), Paragraph(f"{line_price_incl:.2f}", s_tbl_r), Paragraph(f"{line_total_incl:.2f}", s_tbl_r), Paragraph(f"{line_vat:.2f}", s_tbl_r)])
        row_idx += 1
        
    # FIX 3: Totals are NO LONGER added to the product table here.
    t = Table(table_data, colWidths=col_widths)
    t.setStyle(TableStyle(table_style))
    story.append(t)
    add_dashed_line()
    
    # FIX 3: Totals moved here to the Currency/Change section
    totals_data = [
        [Paragraph("<b>Total Excl:</b>", s_tbl), Paragraph(f"{total_excl_sum:.2f}", s_tbl_r)],
        [Paragraph("<b>Total VAT:</b>", s_tbl), Paragraph(f"{total_vat_sum:.2f}", s_tbl_r)],
        [Paragraph("Total Incl:", s_tbl_9pt), Paragraph(f"{total_incl_sum:.2f}", s_tbl_9pt_r)],
        [Paragraph("Currency:", s_tbl), Paragraph(f"<b>{receipt.get('receiptCurrency', 'USD')}</b>", s_tbl_r)],
        [Paragraph("Change:", s_tbl), Paragraph("0.00", s_tbl_r)],
        [Paragraph("Cashier:", s_tbl), Paragraph(seller_data.get('name', ''), s_tbl_r)]
    ]
    totals_table = Table(totals_data, colWidths=[35*mm, 37*mm])
    totals_table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0), ('TOPPADDING', (0, 0), (-1, -1), 1*mm), ('BOTTOMPADDING', (0, 0), (-1, -1), 1*mm)]))
    story.append(totals_table)
    add_dashed_line()
    
    vat_data = [[Paragraph("<b>Vat %</b>", s_tbl), Paragraph("<b>Net.Amt</b>", s_tbl_r), Paragraph("<b>VAT Amount</b>", s_tbl_r), Paragraph("<b>Amount</b>", s_tbl_r)]]
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
    
    qr_img_data = generate_qr_code_image(qr_code_url)
    qr_img = Image(qr_img_data, width=32*mm, height=32*mm) 
    qr_table = Table([[qr_img]], colWidths=[72*mm])
    qr_table.setStyle(TableStyle([('ALIGN', (0,0), (-1,-1), 'CENTER')]))
    story.append(qr_table)
    
    story.append(Paragraph(f"Verification code: {verification_code}", s_bold_center))
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
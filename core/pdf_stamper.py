import fitz  # PyMuPDF
import qrcode
import io

def stamp_qr_on_pdf(pdf_path, qr_data, output_path, fiscal_day_no="N/A", device_id="N/A", receipt_counter="N/A", verification_code="N/A"):
    """
    AIBES Stamper: Stamps a QR code and verification details just above 
    the footer line on the right side.
    """
    try:
        # Generate QR Code
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(qr_data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Convert image to bytes
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)
        
        # Open PDF and stamp each page
        doc = fitz.open(pdf_path)
        for page in doc:
            page_width = page.rect.width
            page_height = page.rect.height
            
            # 1. Dynamically find the footer line to position the stamp just above it
            # Searches for common AIBES footer text
            footer_search_terms = ["Generated from", "LG-IMS"]
            target_y = page_height - 95  # Default fallback if footer isn't found
            for term in footer_search_terms:
                instances = page.search_for(term)
                if instances:
                    # Get the lowest instance (closest to the bottom of the page)
                    lowest_rect = max(instances, key=lambda r: r.y0)
                    target_y = lowest_rect.y0 - 5  # 5 points padding above the footer text
                    break
            
            # Dimensions of the stamp block
            stamp_height = 80
            stamp_width = 265
            
            # Calculate coordinates for the white background mask
            bg_y0 = target_y - stamp_height
            bg_y1 = target_y
            
            # 2. Draw a white background rectangle to mask any underlying text
            bg_rect = fitz.Rect(page_width - stamp_width - 15, bg_y0, page_width - 15, bg_y1)
            page.draw_rect(bg_rect, color=(1, 1, 1), fill=(1, 1, 1)) # White background
            
            # 3. Insert QR Code (60x60 points) on the far right of the mask
            qr_y0 = bg_y0 + 10
            qr_y1 = qr_y0 + 60
            qr_rect = fitz.Rect(page_width - 75, qr_y0, page_width - 15, qr_y1)
            page.insert_image(qr_rect, stream=img_byte_arr.getvalue())
            
            # 4. Insert Text details to the left of the QR code
            text_x = page_width - stamp_width
            text_y_start = bg_y0 + 15
            line_height = 12
            lines = [
                f"Fiscal Day: {fiscal_day_no}",
                f"Device ID: {device_id}",
                f"Receipt No: {receipt_counter}",  # CHANGED FROM receipt_global_no TO receipt_counter
                f"Verification Code: {verification_code}",
                "You can manually verify this receipt at",
                "https://fdms.zimra.co.zw/"
            ]
            for i, line in enumerate(lines):
                # First 4 lines slightly larger, last 2 lines smaller for the URL
                fontsize = 6 if i < 4 else 5
                page.insert_text(
                    (text_x, text_y_start + (i * line_height)),
                    line,
                    fontsize=fontsize,
                    fontname="helv", # Built-in Helvetica font
                    color=(0, 0, 0)
                )
        doc.save(output_path)
        doc.close()
        return True
    except Exception as e:
        print(f"Error stamping PDF (AIBES): {e}")
        import traceback
        traceback.print_exc()
        return False


def stamp_qr_on_pdf_feedmix(pdf_path, qr_data, output_path, fiscal_day_no="N/A", device_id="N/A", receipt_counter="N/A", verification_code="N/A"):
    """
    Feedmix Stamper: Stamps a QR code and verification details at the 
    BOTTOM CENTER of the PDF.
    """
    try:
        # Generate QR Code
        qr = qrcode.QRCode(version=1, box_size=8, border=1)
        qr.add_data(qr_data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)
        
        # Open PDF and stamp only the last page
        doc = fitz.open(pdf_path)
        page = doc[-1]
        
        mm = 2.83465
        margin_y_bottom = 15 * mm   # 15mm from the bottom edge
        qr_size = 25 * mm           # 25mm x 25mm QR code
        
        # Calculate Center X for QR Code
        qr_x = (page.rect.width - qr_size) / 2
        
        rect_y_top = page.rect.height - margin_y_bottom - qr_size
        rect_y_bottom = page.rect.height - margin_y_bottom
        
        qr_rect = fitz.Rect(qr_x, rect_y_top, qr_x + qr_size, rect_y_bottom)
        page.insert_image(qr_rect, stream=img_byte_arr.getvalue())
        
        # Text below QR Code (Centered using insert_textbox)
        text_rect = fitz.Rect(10*mm, rect_y_bottom + (2*mm), page.rect.width - 10*mm, page.rect.height)
        
        stamp_text = (
            f"Verification code: {verification_code}\n"
            f"Fiscal Day: {fiscal_day_no} | Device: {device_id} | Invoice: {receipt_counter}\n"  # CHANGED FROM receipt_global_no TO receipt_counter
            f"Verify manually at: https://fdmstest.zimra.co.zw/"
        )
        
        page.insert_textbox(
            text_rect,
            stamp_text,
            fontsize=7,
            fontname="helv",
            color=(0, 0, 0),
            align=fitz.TEXT_ALIGN_CENTER  # Perfectly centers the text block
        )
        
        doc.save(output_path, garbage=4, deflate=True)
        doc.close()
        return True
    except Exception as e:
        print(f"Error stamping PDF (Feedmix): {e}")
        import traceback
        traceback.print_exc()
        return False
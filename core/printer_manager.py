import os
import threading
import time


_reported_printers = set()


def _resolve_printer(configured_name):
    import win32print

    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    printers = win32print.EnumPrinters(flags, None, 2)
    printer_names = [printer['pPrinterName'] for printer in printers]

    if configured_name:
        match = next(
            (name for name in printer_names if name.casefold() == configured_name.casefold()),
            None,
        )
        if match:
            return match
        if configured_name.startswith('\\\\'):
            return configured_name
        raise RuntimeError(
            f"Configured printer '{configured_name}' was not found in Windows printer queues."
        )

    try:
        default_printer = win32print.GetDefaultPrinter()
    except Exception as exc:
        raise RuntimeError('No default Windows printer is configured.') from exc

    match = next(
        (name for name in printer_names if name.casefold() == default_printer.casefold()),
        None,
    )
    return match or default_printer


def _notify_printer_detected(printer_name, notify):
    if printer_name not in _reported_printers:
        _reported_printers.add(printer_name)
        notify('Printer detected', f'{printer_name} is available in the Windows print queue.')


def _monitor_job(printer_name, job_id, document_name, notify, timeout=300):
    import win32print

    failed_statuses = (
        win32print.JOB_STATUS_ERROR
        | win32print.JOB_STATUS_DELETED
        | win32print.JOB_STATUS_DELETING
        | win32print.JOB_STATUS_PAPEROUT
        | win32print.JOB_STATUS_OFFLINE
        | win32print.JOB_STATUS_BLOCKED_DEVQ
        | win32print.JOB_STATUS_USER_INTERVENTION
    )
    deadline = time.monotonic() + timeout
    seen_in_queue = False

    while time.monotonic() < deadline:
        printer_handle = None
        try:
            printer_handle = win32print.OpenPrinter(printer_name)
            job = win32print.GetJob(printer_handle, job_id, 1)
            seen_in_queue = True
            status = job.get('Status', 0)
            if status & failed_statuses:
                detail = job.get('pStatus') or f'Windows spooler status: {status}'
                notify('Print job needs attention', f'{document_name}: {detail}')
                return
        except Exception as exc:
            error_code = getattr(exc, 'winerror', None)
            if error_code is None and exc.args and isinstance(exc.args[0], int):
                error_code = exc.args[0]
            if seen_in_queue and error_code == 87:
                notify(
                    'Print job completed',
                    f'{document_name} left the Windows queue. Physical paper output is not confirmed.',
                )
            else:
                notify(
                    'Print status unavailable',
                    f'{document_name} was accepted, but its queue status could not be read. Physical output is not confirmed.',
                )
            return
        finally:
            if printer_handle:
                win32print.ClosePrinter(printer_handle)
        time.sleep(2)

    notify(
        'Print status unavailable',
        f'{document_name} is still in or could not be verified in the Windows queue.',
    )


def send_pdf_to_printer(pdf_path, configured_name, notify):
    if os.name != 'nt':
        raise RuntimeError('Automatic thermal printing is supported only on Windows.')

    import fitz
    import win32con
    import win32print
    import win32ui
    from PIL import Image, ImageWin

    printer_name = _resolve_printer(configured_name)
    printer_handle = None
    device_context = None
    document_started = False

    try:
        printer_handle = win32print.OpenPrinter(printer_name)
        _notify_printer_detected(printer_name, notify)

        document = fitz.open(pdf_path)
        if document.page_count == 0:
            raise RuntimeError('The receipt PDF contains no pages.')

        device_context = win32ui.CreateDC()
        device_context.CreatePrinterDC(printer_name)
        printable_width = device_context.GetDeviceCaps(win32con.HORZRES)
        if printable_width <= 0:
            raise RuntimeError(f'Printer {printer_name} reported no printable width.')

        document_name = os.path.basename(pdf_path)
        job_id = device_context.StartDoc(document_name)
        if job_id == 0:
            raise RuntimeError(f'Windows could not create a print job for {printer_name}.')
        document_started = True

        try:
            for page in document:
                pixmap = page.get_pixmap(dpi=203, alpha=False)
                image = Image.frombytes('RGB', (pixmap.width, pixmap.height), pixmap.samples)
                image_height = max(1, round(image.height * printable_width / image.width))

                device_context.StartPage()
                ImageWin.Dib(image).draw(
                    device_context.GetHandleOutput(),
                    (0, 0, printable_width, image_height),
                )
                device_context.EndPage()
            device_context.EndDoc()
            document_started = False
        finally:
            document.close()

        notify('Receipt sent to printer', f'{document_name} was submitted to {printer_name}.')
        if job_id is not None:
            threading.Thread(
                target=_monitor_job,
                args=(printer_name, job_id, document_name, notify),
                daemon=True,
            ).start()
        else:
            notify(
                'Print status unavailable',
                f'{document_name} was submitted to {printer_name}, but Windows did not return a job ID.',
            )
        return printer_name, job_id
    except Exception:
        if document_started and device_context is not None:
            try:
                device_context.AbortDoc()
            except Exception:
                pass
        raise
    finally:
        if device_context is not None:
            device_context.DeleteDC()
        if printer_handle is not None:
            win32print.ClosePrinter(printer_handle)
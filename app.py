import io
import re
import subprocess
import tempfile
from datetime import datetime
from urllib.parse import unquote

from flask import Flask, jsonify, render_template, request, send_file
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

app = Flask(__name__)
app.json.ensure_ascii = False
LABEL_WIDTH, LABEL_HEIGHT = 154, 286  # CUPS PPD 99014, points
PRINTER_NAME = "NotePrinter"
FONT = "DejaVu"
BOLD = "DejaVu-Bold"
TEMPLATE_HEADINGS = {
    "shopping": "BOODSCHAPPEN",
    "tasks": "TAKEN",
    "reminder": "HERINNERING",
    "message": "BERICHT",
}
TEMPLATE_TITLES = {
    "shopping": "Boodschappen",
    "tasks": "Taken",
    "message": "Berichtje",
}
pdfmetrics.registerFont(TTFont(FONT, "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont(BOLD, "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"))


def command(args, timeout=12):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)


def find_printer():
    result = command(["lpinfo", "-v"])
    for line in result.stdout.splitlines():
        match = re.search(r"(usb://\S+)", line)
        if match and "DYMO" in unquote(match.group(1)).upper() and re.search(r"LabelWriter\s*(400|450)", unquote(match.group(1)), re.I):
            return match.group(1), "400" if "400" in unquote(match.group(1)) else "450"
    return None, None


def configure_printer():
    uri, model = find_printer()
    if not uri:
        raise ValueError("Geen DYMO LabelWriter 400/450 gevonden. Controleer de USB-aansluiting en herlaad de pagina.")
    models = command(["lpinfo", "-m"]).stdout.splitlines()
    driver = next((line.split()[0] for line in models if re.search(rf"(?:^|/)lw{model}\.ppd\b", line.split()[0], re.I)), None)
    if not driver:
        raise ValueError(f"DYMO-stuurprogramma voor LabelWriter {model} ontbreekt.")
    result = command(["lpadmin", "-p", PRINTER_NAME, "-E", "-v", uri, "-m", driver, "-o", "PageSize=w154h286.1"])
    if result.returncode:
        raise ValueError(result.stderr.strip() or "De printer kon niet ingesteld worden.")
    command(["cupsaccept", PRINTER_NAME])
    command(["cupsenable", PRINTER_NAME])
    return model


def validate(payload):
    if not isinstance(payload, dict):
        raise ValueError("Ongeldige invoer.")
    title = str(payload.get("title", "")).strip()
    body = str(payload.get("body", "")).strip().replace("\r\n", "\n").replace("\r", "\n")
    qr = str(payload.get("qr", "")).strip()
    if not title and not body and not qr:
        raise ValueError("Vul een titel, notitie of QR-inhoud in.")
    if len(title) > 80 or len(body) > 2500:
        raise ValueError("De notitie is te lang (maximaal 80 tekens titel en 2500 tekens tekst).")
    if len(qr) > 300:
        raise ValueError("De QR-inhoud mag maximaal 300 tekens bevatten.")
    template = str(payload.get("template", "") or "")
    if template and template not in TEMPLATE_HEADINGS:
        raise ValueError("Onbekend sjabloon.")
    try:
        copies = int(payload.get("copies", 1))
    except (TypeError, ValueError):
        raise ValueError("Het aantal exemplaren moet tussen 1 en 10 liggen.") from None
    if copies < 1 or copies > 10:
        raise ValueError("Het aantal exemplaren moet tussen 1 en 10 liggen.")
    return {
        "title": title, "body": body, "copies": copies,
        "date": payload.get("date") is True,
        "checklist": payload.get("checklist") is True,
        "paginate": payload.get("paginate") is True,
        "qr": qr,
        "template": template,
    }


def wrap_line(line, font, size, width):
    if not line:
        return [""]
    output, current = [], ""
    for word in line.split():
        candidate = f"{current} {word}" if current else word
        if pdfmetrics.stringWidth(candidate, font, size) <= width:
            current = candidate
            continue
        if current:
            output.append(current)
            current = ""
        while pdfmetrics.stringWidth(word, font, size) > width:
            cut = 1
            while cut < len(word) and pdfmetrics.stringWidth(word[:cut + 1], font, size) <= width:
                cut += 1
            output.append(word[:cut])
            word = word[cut:]
        current = word
    if current:
        output.append(current)
    return output


def plan_labels(note):
    pad, usable = 11, LABEL_WIDTH - 22
    template = note["template"]
    title = note["title"]
    visible_title = "" if title.casefold() == TEMPLATE_TITLES.get(template, "\0").casefold() else title
    title_size = 16 if template == "reminder" else (12 if template else 14)
    while title_size > 9 and len(wrap_line(visible_title, BOLD, title_size, usable - (8 if template in ("reminder", "message") else 0))) > 3:
        title_size -= 1
    title_lines = wrap_line(visible_title, BOLD, title_size, usable - (8 if template in ("reminder", "message") else 0)) if visible_title else []
    if len(title_lines) > 3:
        raise ValueError("De titel past niet op het label.")
    banner_height = {"shopping": 31, "tasks": 28, "reminder": 31, "message": 29}.get(template, 0)
    header_height = banner_height + sum(title_size * 1.28 for _ in title_lines) + (16 if title_lines else 0)
    top = LABEL_HEIGHT - 13 - header_height
    footer = 22 if note["date"] or note["paginate"] else 11
    qr_height = 93 if note["qr"] else 0
    sizes = ((10,) if template == "reminder" else (9,)) if note["paginate"] else ((12, 11, 10, 9, 8) if template == "reminder" else (11, 10, 9, 8, 7))
    offset = 28 if template == "tasks" else 16 if template == "shopping" else 10 if template in ("reminder", "message") else 14 if note["checklist"] else 0
    spacing = 1.6 if template in ("shopping", "tasks") else 1.45 if template in ("reminder", "message") else 1.35
    for size in sizes:
        lines = []
        item_number = 0
        for raw in note["body"].split("\n") if note["body"] else []:
            if raw.strip():
                item_number += 1
            wrapped = wrap_line(raw, FONT, size, usable - offset)
            lines.extend((part, index == 0 and bool(raw.strip()), item_number, index == len(wrapped) - 1) for index, part in enumerate(wrapped))
        step = size * spacing
        capacity = int((top - footer) / step)
        final_capacity = int((top - footer - qr_height) / step)
        if capacity < 1 or final_capacity < 0:
            raise ValueError("De titel en QR-code laten geen ruimte voor de notitie.")
        if not note["paginate"]:
            if len(lines) <= final_capacity:
                return {"pages": [lines], "size": size, "title_lines": title_lines, "title_size": title_size, "top": top, "banner_height": banner_height, "visible_title": visible_title, "offset": offset, "step": step}
            continue
        if len(lines) <= final_capacity:
            pages = [lines]
        else:
            final_lines = lines[-final_capacity:] if final_capacity else []
            remaining = lines[:-final_capacity] if final_capacity else lines
            pages = [remaining[i:i + capacity] for i in range(0, len(remaining), capacity)] + [final_lines]
        if len(pages) > 10:
            raise ValueError("Maximaal 10 labels per notitie. Kort de tekst in.")
        return {"pages": pages, "size": size, "title_lines": title_lines, "title_size": title_size, "top": top, "banner_height": banner_height, "visible_title": visible_title, "offset": offset, "step": step}
    raise ValueError("De tekst past niet op één label. Zet ‘Meerdere labels’ aan of kort de notitie in.")


def make_pdf(note, plan=None):
    plan = plan or plan_labels(note)
    buf = io.BytesIO()
    pdf = canvas.Canvas(buf, pagesize=(LABEL_WIDTH, LABEL_HEIGHT), pageCompression=1)
    pdf.setTitle("Note Printer")
    pad, usable = 11, LABEL_WIDTH - 22
    count = len(plan["pages"])
    template = note["template"]
    for page_number, lines in enumerate(plan["pages"], 1):
        y = LABEL_HEIGHT - 13
        if template == "shopping":
            pdf.setFillColor(HexColor("#17202b"))
            pdf.roundRect(pad, y - 27, usable, 27, 4, stroke=0, fill=1)
            pdf.setFillColor(HexColor("#ffffff"))
            pdf.setFont(BOLD, 10)
            pdf.drawCentredString(LABEL_WIDTH / 2, y - 17, TEMPLATE_HEADINGS[template])
        elif template == "tasks":
            pdf.setFillColor(HexColor("#17202b"))
            pdf.setFont(BOLD, 11)
            pdf.drawString(pad, y - 12, TEMPLATE_HEADINGS[template])
            pdf.setLineWidth(2)
            pdf.line(pad, y - 20, LABEL_WIDTH - pad, y - 20)
        elif template == "reminder":
            pdf.setFillColor(HexColor("#17202b"))
            pdf.rect(pad, y - 20, 4, 20, stroke=0, fill=1)
            pdf.setFont(BOLD, 8)
            pdf.drawString(pad + 11, y - 13, TEMPLATE_HEADINGS[template])
            pdf.setLineWidth(0.5)
            pdf.line(pad + 11, y - 22, LABEL_WIDTH - pad, y - 22)
        elif template == "message":
            pdf.setFillColor(HexColor("#17202b"))
            pdf.setFont(BOLD, 8)
            pdf.drawCentredString(LABEL_WIDTH / 2, y - 12, TEMPLATE_HEADINGS[template])
            pdf.setLineWidth(0.5)
            pdf.line(pad, y - 15, pad + 32, y - 15)
            pdf.line(LABEL_WIDTH - pad - 32, y - 15, LABEL_WIDTH - pad, y - 15)
        y -= plan["banner_height"]
        if plan["visible_title"]:
            pdf.setFont(BOLD, plan["title_size"])
            for line in plan["title_lines"]:
                y -= plan["title_size"] * 1.28
                pdf.drawString(pad + (6 if template in ("reminder", "message") else 0), y, line)
            y -= 8
            if template not in ("reminder", "message"):
                pdf.setStrokeColor(HexColor("#aaaaaa"))
                pdf.setLineWidth(0.5)
                pdf.line(pad, y, LABEL_WIDTH - pad, y)
            y -= 8
        body_top = y
        pdf.setFillColor(HexColor("#17202b"))
        pdf.setFont(FONT, plan["size"])
        for line, first, item_number, last in lines:
            y -= plan["step"]
            if template == "tasks" and first:
                pdf.setFont(BOLD, 7)
                pdf.drawString(pad, y + 1, f"{item_number}.")
                pdf.setFont(FONT, plan["size"])
            if note["checklist"] and first:
                pdf.setLineWidth(0.7)
                pdf.setStrokeColor(HexColor("#333333"))
                checkbox_x = pad + (14 if template == "tasks" else 0)
                pdf.rect(checkbox_x, y - 1, 7, 7, fill=0, stroke=1)
            if template in ("shopping", "tasks") and last and line:
                pdf.setLineWidth(0.35)
                pdf.setStrokeColor(HexColor("#cccccc"))
                pdf.line(pad, y - 5, LABEL_WIDTH - pad, y - 5)
            pdf.drawString(pad + plan["offset"], y, line)
        if lines and template == "reminder":
            pdf.setStrokeColor(HexColor("#222222"))
            pdf.setLineWidth(2)
            pdf.line(pad + 2, body_top + 1, pad + 2, y - 4)
        elif lines and template == "message":
            pdf.setStrokeColor(HexColor("#999999"))
            pdf.setLineWidth(0.7)
            pdf.roundRect(pad, y - 8, usable, body_top - y + 14, 5, stroke=1, fill=0)
        if note["qr"] and page_number == count:
            qr = QrCodeWidget(note["qr"], barLevel="M")
            left, bottom, right, top = qr.getBounds()
            size = 80
            drawing = Drawing(size, size, transform=[size / (right - left), 0, 0, size / (top - bottom), 0, 0])
            drawing.add(qr)
            renderPDF.draw(drawing, pdf, pad, 24 if note["date"] or count > 1 else 11)
        pdf.setFont(FONT, 7)
        pdf.setFillColor(HexColor("#555555"))
        if note["date"]:
            pdf.drawString(pad, 9, datetime.now().strftime("%d-%m-%Y %H:%M"))
        if count > 1:
            pdf.drawRightString(LABEL_WIDTH - pad, 9, f"{page_number}/{count}")
        pdf.showPage()
    pdf.save()
    buf.seek(0)
    return buf


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/status")
def status():
    try:
        uri, model = find_printer()
        return jsonify(connected=bool(uri), model=model, message="Printer verbonden" if uri else "Geen DYMO LabelWriter 400/450 gevonden")
    except Exception:
        return jsonify(connected=False, model=None, message="Printerstatus niet beschikbaar")


@app.post("/api/preview")
def preview():
    try:
        note = validate(request.get_json(silent=True))
        return send_file(make_pdf(note), mimetype="application/pdf", download_name="notitie.pdf", as_attachment=False)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400


@app.post("/api/layout")
def layout():
    try:
        note = validate(request.get_json(silent=True))
        plan = plan_labels(note)
        return jsonify(
            pages=len(plan["pages"]), template=note["template"], title=plan["visible_title"],
            first_page=[{"text": line, "checkbox": first, "number": number, "last": last} for line, first, number, last in plan["pages"][0]],
        )
    except ValueError as exc:
        return jsonify(error=str(exc)), 400


@app.post("/api/print")
def print_note():
    try:
        note = validate(request.get_json(silent=True))
        pdf = make_pdf(note)
        configure_printer()
        with tempfile.NamedTemporaryFile(suffix=".pdf") as file:
            file.write(pdf.getvalue())
            file.flush()
            result = command(["lp", "-d", PRINTER_NAME, "-n", str(note["copies"]), "-o", "media=w154h286.1", "-o", "fit-to-page", "-o", "Collate=True", file.name], timeout=30)
        if result.returncode:
            raise ValueError(result.stderr.strip() or "De afdruktaak is mislukt.")
        return jsonify(message="Afdruktaak verzonden", job=result.stdout.strip())
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except (OSError, subprocess.TimeoutExpired):
        return jsonify(error="De printer reageert niet. Controleer de USB-aansluiting."), 503


@app.get("/health")
def health():
    return "ok"

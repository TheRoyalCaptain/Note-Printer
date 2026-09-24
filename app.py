import io
import base64
import json
import math
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
from reportlab.lib.utils import ImageReader
from PIL import Image, UnidentifiedImageError

import storage

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
    "appointment": "AFSPRAAK",
    "parcel": "PAKKET",
    "warning": "LET OP",
    "instructions": "INSTRUCTIES",
    "contact": "CONTACT",
}
TEMPLATE_STYLES = {
    "shopping": "shopping", "tasks": "tasks", "reminder": "reminder", "message": "message",
    "appointment": "reminder", "parcel": "message", "warning": "reminder",
    "instructions": "tasks", "contact": "message",
}
TEMPLATE_TITLES = {
    "shopping": "Boodschappen",
    "tasks": "Taken",
    "message": "Berichtje",
    "appointment": "Afspraak",
    "parcel": "Pakket",
    "warning": "Let op",
    "instructions": "Instructies",
    "contact": "Contact",
}
ICONS = ("", "warning", "info", "star", "heart", "home")
app.config["MAX_CONTENT_LENGTH"] = 1_000_000
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


def decode_photo(value):
    if not value:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"data:image/(?:png|jpeg);base64,[A-Za-z0-9+/=]+", value):
        raise ValueError("Gebruik een PNG- of JPEG-foto.")
    encoded = value.split(",", 1)[1]
    if len(encoded) > 360_000:
        raise ValueError("De foto is te groot. Kies een kleinere foto.")
    try:
        image = Image.open(io.BytesIO(base64.b64decode(encoded, validate=True)))
        image.load()
        if image.width > 1024 or image.height > 1024 or image.width < 1 or image.height < 1:
            raise ValueError("De foto moet tussen 1 en 1024 pixels per zijde zijn.")
        if image.format not in ("PNG", "JPEG"):
            raise ValueError("Gebruik een PNG- of JPEG-foto.")
        return image.convert("L")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, ValueError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith(("De foto", "Gebruik een")):
            raise
        raise ValueError("De foto kon niet worden gelezen.") from None


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
    heading = str(payload.get("heading", "") or "").strip()
    if len(heading) > 30:
        raise ValueError("De koptekst mag maximaal 30 tekens bevatten.")
    try:
        font_size = int(payload.get("font_size", 0) or 0)
    except (TypeError, ValueError):
        raise ValueError("Kies een lettergrootte tussen 8 en 14.") from None
    if font_size and not 8 <= font_size <= 14:
        raise ValueError("Kies een lettergrootte tussen 8 en 14.")
    icon = str(payload.get("icon", "") or "")
    if icon not in ICONS:
        raise ValueError("Onbekend pictogram.")
    photo = payload.get("photo", "") or ""
    if photo:
        decode_photo(photo)
    recipient = str(payload.get("recipient", "") or "").strip()
    sender = str(payload.get("sender", "") or "").strip()
    if len(recipient) > 80 or len(sender) > 80:
        raise ValueError("Aan en Van mogen maximaal 80 tekens bevatten.")
    event_at = str(payload.get("event_at", "") or "").strip()
    if event_at:
        try:
            event_at = datetime.fromisoformat(event_at).strftime("%d-%m-%Y %H:%M")
        except ValueError:
            # Saved notes already store the normalized displayed value.
            if not re.fullmatch(r"\d{2}-\d{2}-\d{4} \d{2}:\d{2}", event_at):
                raise ValueError("Vul een geldige datum en tijd in.") from None
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
        "heading": heading, "font_size": font_size,
        "recipient": recipient, "sender": sender, "event_at": event_at,
        "icon": icon, "photo": photo,
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
    style = TEMPLATE_STYLES.get(template, "")
    heading = note["heading"] or TEMPLATE_HEADINGS.get(template, "")
    if heading and not style:
        style = "free"
    title = note["title"]
    visible_title = "" if title.casefold() == TEMPLATE_TITLES.get(template, "\0").casefold() else title
    title_size = 16 if style == "reminder" else (12 if style else 14)
    while title_size > 9 and len(wrap_line(visible_title, BOLD, title_size, usable - (8 if style in ("reminder", "message") else 0))) > 3:
        title_size -= 1
    title_lines = wrap_line(visible_title, BOLD, title_size, usable - (8 if style in ("reminder", "message") else 0)) if visible_title else []
    if len(title_lines) > 3:
        raise ValueError("De titel past niet op het label.")
    banner_height = {"shopping": 31, "tasks": 28, "reminder": 31, "message": 29, "free": 25}.get(style, 0)
    meta_lines = []
    for label, value in (("AAN", note["recipient"]), ("VAN", note["sender"]), ("WANNEER", note["event_at"])):
        if value:
            meta_lines.extend(wrap_line(f"{label}: {value}", FONT, 7, usable - 10))
    meta_height = len(meta_lines) * 10 + (6 if meta_lines else 0)
    art_height = 56 if note["photo"] or note["icon"] else 0
    header_height = banner_height + sum(title_size * 1.28 for _ in title_lines) + (16 if title_lines else 0) + meta_height + art_height
    top = LABEL_HEIGHT - 13 - header_height
    footer = 22 if note["date"] or note["paginate"] else 11
    qr_height = 93 if note["qr"] else 0
    sizes = ((note["font_size"],) if note["font_size"] else ((10,) if style == "reminder" else (9,)) if note["paginate"] else ((12, 11, 10, 9, 8) if style == "reminder" else (11, 10, 9, 8, 7)))
    offset = 28 if style == "tasks" else 16 if style == "shopping" else 10 if style in ("reminder", "message") else 14 if note["checklist"] else 0
    spacing = 1.6 if style in ("shopping", "tasks") else 1.45 if style in ("reminder", "message") else 1.35
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
                return {"pages": [lines], "size": size, "title_lines": title_lines, "title_size": title_size, "top": top, "banner_height": banner_height, "visible_title": visible_title, "offset": offset, "step": step, "style": style, "heading": heading, "meta_lines": meta_lines, "art_height": art_height}
            continue
        if len(lines) <= final_capacity:
            pages = [lines]
        else:
            final_lines = lines[-final_capacity:] if final_capacity else []
            remaining = lines[:-final_capacity] if final_capacity else lines
            pages = [remaining[i:i + capacity] for i in range(0, len(remaining), capacity)] + [final_lines]
        if len(pages) > 10:
            raise ValueError("Maximaal 10 labels per notitie. Kort de tekst in.")
        return {"pages": pages, "size": size, "title_lines": title_lines, "title_size": title_size, "top": top, "banner_height": banner_height, "visible_title": visible_title, "offset": offset, "step": step, "style": style, "heading": heading, "meta_lines": meta_lines, "art_height": art_height}
    raise ValueError("De tekst past niet op één label. Zet ‘Meerdere labels’ aan of kort de notitie in.")


def draw_icon(pdf, kind, x, y):
    """Draw small monochrome symbols that remain sharp on a thermal printer."""
    pdf.setStrokeColor(HexColor("#17202b"))
    pdf.setFillColor(HexColor("#17202b"))
    pdf.setLineWidth(2)
    if kind == "warning":
        path = pdf.beginPath()
        path.moveTo(x + 22, y + 43)
        path.lineTo(x + 1, y + 4)
        path.lineTo(x + 43, y + 4)
        path.close()
        pdf.drawPath(path, fill=0, stroke=1)
        pdf.setFont(BOLD, 24)
        pdf.drawCentredString(x + 22, y + 10, "!")
    elif kind == "info":
        pdf.circle(x + 22, y + 22, 20, fill=0, stroke=1)
        pdf.setFont(BOLD, 25)
        pdf.drawCentredString(x + 22, y + 13, "i")
    elif kind == "star":
        path = pdf.beginPath()
        for index in range(10):
            angle = math.pi / 2 + index * math.pi / 5
            radius = 21 if index % 2 == 0 else 9
            px, py = x + 22 + radius * math.cos(angle), y + 22 + radius * math.sin(angle)
            (path.moveTo if index == 0 else path.lineTo)(px, py)
        path.close()
        pdf.drawPath(path, fill=1, stroke=0)
    elif kind == "heart":
        path = pdf.beginPath()
        path.moveTo(x + 22, y + 4)
        path.curveTo(x - 4, y + 21, x + 3, y + 46, x + 22, y + 35)
        path.curveTo(x + 41, y + 46, x + 48, y + 21, x + 22, y + 4)
        pdf.drawPath(path, fill=1, stroke=0)
    elif kind == "home":
        roof = pdf.beginPath()
        roof.moveTo(x + 2, y + 22)
        roof.lineTo(x + 22, y + 43)
        roof.lineTo(x + 42, y + 22)
        pdf.drawPath(roof, fill=0, stroke=1)
        pdf.rect(x + 8, y + 3, 28, 22, fill=0, stroke=1)
        pdf.rect(x + 19, y + 3, 7, 12, fill=0, stroke=1)


def make_pdf(note, plan=None):
    plan = plan or plan_labels(note)
    buf = io.BytesIO()
    pdf = canvas.Canvas(buf, pagesize=(LABEL_WIDTH, LABEL_HEIGHT), pageCompression=1)
    pdf.setTitle("Note Printer")
    pad, usable = 11, LABEL_WIDTH - 22
    count = len(plan["pages"])
    style = plan["style"]
    heading = plan["heading"]
    heading_size = 10 if style == "shopping" else 11 if style == "tasks" else 8
    while heading and pdfmetrics.stringWidth(heading, BOLD, heading_size) > usable - 12 and heading_size > 6:
        heading_size -= 1
    for page_number, lines in enumerate(plan["pages"], 1):
        y = LABEL_HEIGHT - 13
        if style == "shopping":
            pdf.setFillColor(HexColor("#17202b"))
            pdf.roundRect(pad, y - 27, usable, 27, 4, stroke=0, fill=1)
            pdf.setFillColor(HexColor("#ffffff"))
            pdf.setFont(BOLD, heading_size)
            pdf.drawCentredString(LABEL_WIDTH / 2, y - 17, heading)
        elif style == "tasks":
            pdf.setFillColor(HexColor("#17202b"))
            pdf.setFont(BOLD, heading_size)
            pdf.drawString(pad, y - 12, heading)
            pdf.setLineWidth(2)
            pdf.line(pad, y - 20, LABEL_WIDTH - pad, y - 20)
        elif style == "reminder":
            pdf.setFillColor(HexColor("#17202b"))
            pdf.rect(pad, y - 20, 4, 20, stroke=0, fill=1)
            pdf.setFont(BOLD, heading_size)
            pdf.drawString(pad + 11, y - 13, heading)
            pdf.setLineWidth(0.5)
            pdf.line(pad + 11, y - 22, LABEL_WIDTH - pad, y - 22)
        elif style == "message":
            pdf.setFillColor(HexColor("#17202b"))
            pdf.setFont(BOLD, heading_size)
            pdf.drawCentredString(LABEL_WIDTH / 2, y - 12, heading)
            pdf.setLineWidth(0.5)
            pdf.line(pad, y - 15, pad + 32, y - 15)
            pdf.line(LABEL_WIDTH - pad - 32, y - 15, LABEL_WIDTH - pad, y - 15)
        elif style == "free":
            pdf.setFillColor(HexColor("#17202b"))
            pdf.setFont(BOLD, heading_size)
            pdf.drawString(pad, y - 12, heading)
            pdf.setLineWidth(0.5)
            pdf.line(pad, y - 17, LABEL_WIDTH - pad, y - 17)
        y -= plan["banner_height"]
        if plan["visible_title"]:
            pdf.setFont(BOLD, plan["title_size"])
            for line in plan["title_lines"]:
                y -= plan["title_size"] * 1.28
                pdf.drawString(pad + (6 if style in ("reminder", "message") else 0), y, line)
            y -= 8
            if style not in ("reminder", "message"):
                pdf.setStrokeColor(HexColor("#aaaaaa"))
                pdf.setLineWidth(0.5)
                pdf.line(pad, y, LABEL_WIDTH - pad, y)
            y -= 8
        if plan["meta_lines"]:
            pdf.setFillColor(HexColor("#333333"))
            pdf.setFont(BOLD, 7)
            for meta in plan["meta_lines"]:
                y -= 10
                pdf.drawString(pad + 5, y, meta)
            y -= 6
        if plan["art_height"]:
            if note["photo"]:
                pdf.drawImage(ImageReader(decode_photo(note["photo"])), pad, y - 47, width=46, height=46, preserveAspectRatio=True, anchor="c")
            else:
                draw_icon(pdf, note["icon"], pad, y - 46)
            y -= plan["art_height"]
        body_top = y
        pdf.setFillColor(HexColor("#17202b"))
        pdf.setFont(FONT, plan["size"])
        for line, first, item_number, last in lines:
            y -= plan["step"]
            if style == "tasks" and first:
                pdf.setFont(BOLD, 7)
                pdf.drawString(pad, y + 1, f"{item_number}.")
                pdf.setFont(FONT, plan["size"])
            if note["checklist"] and first:
                pdf.setLineWidth(0.7)
                pdf.setStrokeColor(HexColor("#333333"))
                checkbox_x = pad + (14 if style == "tasks" else 0)
                pdf.rect(checkbox_x, y - 1, 7, 7, fill=0, stroke=1)
            if style in ("shopping", "tasks") and last and line:
                pdf.setLineWidth(0.35)
                pdf.setStrokeColor(HexColor("#cccccc"))
                pdf.line(pad, y - 5, LABEL_WIDTH - pad, y - 5)
            pdf.drawString(pad + plan["offset"], y, line)
        if lines and style == "reminder":
            pdf.setStrokeColor(HexColor("#222222"))
            pdf.setLineWidth(2)
            pdf.line(pad + 2, body_top + 1, pad + 2, y - 4)
        elif lines and style == "message":
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


@app.get("/api/printer")
def printer_details():
    try:
        uri, model = find_printer()
        state = command(["lpstat", "-p", PRINTER_NAME])
        jobs = command(["lpstat", "-o", PRINTER_NAME])
        return jsonify(
            connected=bool(uri), model=model,
            state=state.stdout.strip() if state.returncode == 0 else "Nog geen printerwachtrij ingesteld",
            jobs=[line.strip() for line in jobs.stdout.splitlines() if line.strip()] if jobs.returncode == 0 else [],
            error="" if uri else "Geen DYMO LabelWriter 400/450 via USB gevonden.",
        )
    except (OSError, subprocess.TimeoutExpired):
        return jsonify(connected=False, model=None, state="Onbekend", jobs=[], error="CUPS reageert niet."), 503


@app.post("/api/printer/cancel")
def cancel_job():
    value = (request.get_json(silent=True) or {}).get("job", "")
    if not isinstance(value, str) or not re.fullmatch(r"NotePrinter-\d+", value):
        return jsonify(error="Ongeldige afdruktaak."), 400
    result = command(["cancel", value])
    if result.returncode:
        return jsonify(error=result.stderr.strip() or "Afdruktaak kon niet worden geannuleerd."), 400
    return jsonify(message="Afdruktaak geannuleerd.")


@app.get("/api/templates")
def templates_list():
    return jsonify(items=[{"id": item["id"], "name": item["name"], "updated_at": item["updated_at"]} for item in storage.list_items("templates")])


@app.get("/api/templates/<int:item_id>")
def template_detail(item_id):
    item = storage.get_item("templates", item_id)
    return jsonify(item={**item, "payload": json.loads(item["payload"])}) if item else (jsonify(error="Sjabloon niet gevonden."), 404)


def write_template(item_id=None):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="Ongeldig sjabloon."), 400
    name = str(data.get("name", "") or "").strip()
    if not name or len(name) > 50:
        return jsonify(error="Geef het sjabloon een naam van maximaal 50 tekens."), 400
    try:
        note = validate(data.get("note"))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    saved_id = storage.save_item("templates", name, note, item_id)
    return jsonify(id=saved_id, message="Sjabloon bewaard.") if saved_id else (jsonify(error="Sjabloon niet gevonden."), 404)


@app.post("/api/templates")
def template_create():
    return write_template()


@app.put("/api/templates/<int:item_id>")
def template_update(item_id):
    return write_template(item_id)


@app.delete("/api/templates/<int:item_id>")
def template_delete(item_id):
    return jsonify(message="Sjabloon verwijderd.") if storage.delete_item("templates", item_id) else (jsonify(error="Sjabloon niet gevonden."), 404)


@app.get("/api/notes")
def notes_list():
    return jsonify(items=[{"id": item["id"], "title": item["title"], "updated_at": item["updated_at"]} for item in storage.list_items("notes")])


@app.get("/api/notes/<int:item_id>")
def note_detail(item_id):
    item = storage.get_item("notes", item_id)
    return jsonify(item={**item, "payload": json.loads(item["payload"])}) if item else (jsonify(error="Notitie niet gevonden."), 404)


def write_note(item_id=None):
    try:
        note = validate(request.get_json(silent=True))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    saved_id = storage.save_item("notes", note["title"] or "Notitie", note, item_id)
    return jsonify(id=saved_id, message="Notitie bewaard.") if saved_id else (jsonify(error="Notitie niet gevonden."), 404)


@app.post("/api/notes")
def note_create():
    return write_note()


@app.put("/api/notes/<int:item_id>")
def note_update(item_id):
    return write_note(item_id)


@app.delete("/api/notes/<int:item_id>")
def note_delete(item_id):
    return jsonify(message="Notitie verwijderd.") if storage.delete_item("notes", item_id) else (jsonify(error="Notitie niet gevonden."), 404)


@app.get("/api/history")
def history_list():
    return jsonify(items=[
        {key: item[key] for key in ("id", "title", "status", "detail", "created_at")}
        for item in storage.list_items("print_log", 50)
    ])


@app.get("/api/history/<int:item_id>")
def history_detail(item_id):
    item = storage.get_item("print_log", item_id)
    return jsonify(item={**item, "payload": json.loads(item["payload"])}) if item else (jsonify(error="Afdruk niet gevonden."), 404)


@app.delete("/api/history/<int:item_id>")
def history_delete(item_id):
    return jsonify(message="Geschiedenisitem verwijderd.") if storage.delete_item("print_log", item_id) else (jsonify(error="Afdruk niet gevonden."), 404)


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
            pages=len(plan["pages"]), template=note["template"], style=plan["style"], heading=plan["heading"], title=plan["visible_title"],
            meta=plan["meta_lines"], image=bool(plan["art_height"]), font_size=plan["size"],
            first_page=[{"text": line, "checkbox": first, "number": number, "last": last} for line, first, number, last in plan["pages"][0]],
        )
    except ValueError as exc:
        return jsonify(error=str(exc)), 400


def submit_print(note):
    pdf = make_pdf(note)
    configure_printer()
    with tempfile.NamedTemporaryFile(suffix=".pdf") as file:
        file.write(pdf.getvalue())
        file.flush()
        result = command(["lp", "-d", PRINTER_NAME, "-n", str(note["copies"]), "-o", "media=w154h286.1", "-o", "fit-to-page", "-o", "Collate=True", file.name], timeout=30)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "De afdruktaak is mislukt.")
    return result.stdout.strip()


def print_validated(note):
    try:
        job = submit_print(note)
        storage.record_print(note, "sent", job)
        return jsonify(message="Afdruktaak verzonden", job=job)
    except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        detail = str(exc) if not isinstance(exc, (OSError, subprocess.TimeoutExpired)) else "De printer reageert niet. Controleer de USB-aansluiting."
        storage.record_print(note, "failed", detail)
        return jsonify(error=detail), 503


@app.post("/api/print")
def print_note():
    try:
        note = validate(request.get_json(silent=True))
        plan_labels(note)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    return print_validated(note)


@app.post("/api/history/<int:item_id>/reprint")
def reprint(item_id):
    item = storage.get_item("print_log", item_id)
    if not item:
        return jsonify(error="Afdruk niet gevonden."), 404
    try:
        note = validate(json.loads(item["payload"]))
        plan_labels(note)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    return print_validated(note)


@app.get("/health")
def health():
    return "ok"

import io
import os
import re
import subprocess
import tempfile
from datetime import datetime
from urllib.parse import unquote

from flask import Flask, jsonify, render_template, request, send_file
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
    if not title and not body:
        raise ValueError("Vul een titel of een notitie in.")
    if len(title) > 80 or len(body) > 2500:
        raise ValueError("De notitie is te lang (maximaal 80 tekens titel en 2500 tekens tekst).")
    try:
        copies = int(payload.get("copies", 1))
    except (TypeError, ValueError):
        raise ValueError("Het aantal exemplaren moet tussen 1 en 10 liggen.") from None
    if copies < 1 or copies > 10:
        raise ValueError("Het aantal exemplaren moet tussen 1 en 10 liggen.")
    return title, body, copies, bool(payload.get("date", False))


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


def make_pdf(title, body, include_date):
    buf = io.BytesIO()
    pdf = canvas.Canvas(buf, pagesize=(LABEL_WIDTH, LABEL_HEIGHT), pageCompression=1)
    pdf.setTitle("Note Printer")
    pad, usable = 11, LABEL_WIDTH - 22
    y = LABEL_HEIGHT - 13
    if title:
        title_size = 14
        while title_size >= 9 and len(wrap_line(title, BOLD, title_size, usable)) > 3:
            title_size -= 1
        lines = wrap_line(title, BOLD, title_size, usable)
        if len(lines) > 3:
            raise ValueError("De titel past niet op het label.")
        pdf.setFont(BOLD, title_size)
        for line in lines:
            y -= title_size * 1.28
            pdf.drawString(pad, y, line)
        y -= 8
        pdf.setStrokeColor(HexColor("#aaaaaa"))
        pdf.line(pad, y, LABEL_WIDTH - pad, y)
        y -= 8
    if body:
        best = None
        for size in (11, 10, 9, 8, 7):
            lines = [part for paragraph in body.split("\n") for part in wrap_line(paragraph, FONT, size, usable)]
            bottom = 20 if include_date else 11
            if y - (len(lines) * size * 1.35) >= bottom:
                best = size, lines
                break
        if best is None:
            raise ValueError("De tekst past niet op één label. Kort de notitie in.")
        size, lines = best
        pdf.setFont(FONT, size)
        for line in lines:
            y -= size * 1.35
            pdf.drawString(pad, y, line)
    if include_date:
        pdf.setFont(FONT, 7)
        pdf.setFillColor(HexColor("#555555"))
        pdf.drawString(pad, 9, datetime.now().strftime("%d-%m-%Y %H:%M"))
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
        title, body, _, date = validate(request.get_json(silent=True))
        return send_file(make_pdf(title, body, date), mimetype="application/pdf", download_name="notitie.pdf", as_attachment=False)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400


@app.post("/api/print")
def print_note():
    try:
        title, body, copies, date = validate(request.get_json(silent=True))
        pdf = make_pdf(title, body, date)
        configure_printer()
        with tempfile.NamedTemporaryFile(suffix=".pdf") as file:
            file.write(pdf.getvalue())
            file.flush()
            result = command(["lp", "-d", PRINTER_NAME, "-n", str(copies), "-o", "media=w154h286.1", "-o", "fit-to-page", file.name], timeout=30)
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

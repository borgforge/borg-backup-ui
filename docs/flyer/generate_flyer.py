#!/usr/bin/env python3
"""Generate the German Borg Backup UI product flyer."""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "docs" / "flyer" / "assets"
OUTPUT = ROOT / "output" / "pdf" / "borg-backup-ui-flyer-de.pdf"

PAGE_W, PAGE_H = A4

NAVY = HexColor("#0B1119")
NAVY_CARD = HexColor("#151D28")
BLUE = HexColor("#2F80ED")
BLUE_LIGHT = HexColor("#E9F2FF")
GREEN = HexColor("#1E9E5A")
TEXT = HexColor("#172033")
MUTED = HexColor("#627089")
SURFACE = HexColor("#F3F6FA")
BORDER = HexColor("#D8E0EA")


def register_fonts() -> None:
    pdfmetrics.registerFont(
        TTFont("DejaVu", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    )
    pdfmetrics.registerFont(
        TTFont("DejaVu-Bold", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
    )


def rounded_image(
    page: canvas.Canvas,
    image_path: Path,
    x: float,
    y: float,
    width: float,
    height: float,
    radius: float = 3 * mm,
) -> None:
    """Draw an image with cover scaling and a rounded clipping path."""
    with Image.open(image_path) as image:
        source_w, source_h = image.size
    scale = max(width / source_w, height / source_h)
    draw_w = source_w * scale
    draw_h = source_h * scale
    draw_x = x + (width - draw_w) / 2
    draw_y = y + (height - draw_h) / 2

    page.saveState()
    clip = page.beginPath()
    clip.roundRect(x, y, width, height, radius)
    page.clipPath(clip, stroke=0, fill=0)
    page.drawImage(
        str(image_path),
        draw_x,
        draw_y,
        width=draw_w,
        height=draw_h,
        preserveAspectRatio=True,
        mask="auto",
    )
    page.restoreState()
    page.setStrokeColor(BORDER)
    page.setLineWidth(0.7)
    page.roundRect(x, y, width, height, radius, stroke=1, fill=0)


def draw_check(page: canvas.Canvas, x: float, y: float) -> None:
    page.setFillColor(GREEN)
    page.circle(x, y, 2.35 * mm, stroke=0, fill=1)
    page.setStrokeColor(white)
    page.setLineWidth(1.2)
    page.line(x - 1.1 * mm, y, x - 0.2 * mm, y - 0.9 * mm)
    page.line(x - 0.2 * mm, y - 0.9 * mm, x + 1.35 * mm, y + 1 * mm)


def draw_feature(
    page: canvas.Canvas,
    x: float,
    y: float,
    title: str,
    description: str,
) -> None:
    draw_check(page, x + 3 * mm, y + 9 * mm)
    page.setFillColor(TEXT)
    page.setFont("DejaVu-Bold", 8.3)
    page.drawString(x + 8 * mm, y + 11 * mm, title)
    page.setFillColor(MUTED)
    page.setFont("DejaVu", 6.8)
    page.drawString(x + 8 * mm, y + 6.2 * mm, description)


def draw_screenshot_card(
    page: canvas.Canvas,
    image: str,
    x: float,
    y: float,
    width: float,
    height: float,
    title: str,
    description: str,
) -> None:
    page.setFillColor(white)
    page.setStrokeColor(BORDER)
    page.roundRect(x, y, width, height, 3.2 * mm, stroke=1, fill=1)
    image_margin = 3 * mm
    caption_height = 13.5 * mm
    rounded_image(
        page,
        ASSETS / image,
        x + image_margin,
        y + caption_height,
        width - 2 * image_margin,
        height - caption_height - image_margin,
        2 * mm,
    )
    page.setFillColor(TEXT)
    page.setFont("DejaVu-Bold", 8.5)
    page.drawString(x + 4 * mm, y + 8 * mm, title)
    page.setFillColor(MUTED)
    page.setFont("DejaVu", 6.6)
    page.drawString(x + 4 * mm, y + 3.8 * mm, description)


def generate() -> None:
    register_fonts()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    page = canvas.Canvas(str(OUTPUT), pagesize=A4)
    page.setTitle("Borg Backup UI - Produktflyer")
    page.setAuthor("borgforge")

    page.setFillColor(SURFACE)
    page.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)

    # Header
    header_h = 72 * mm
    page.setFillColor(NAVY)
    page.rect(0, PAGE_H - header_h, PAGE_W, header_h, stroke=0, fill=1)
    page.setFillColor(NAVY_CARD)
    page.circle(PAGE_W - 15 * mm, PAGE_H - 9 * mm, 42 * mm, stroke=0, fill=1)
    page.circle(PAGE_W - 50 * mm, PAGE_H - 70 * mm, 30 * mm, stroke=0, fill=1)

    logo_size = 28 * mm
    page.drawImage(
        str(ROOT / "plugin" / "plugin-icon.png"),
        15 * mm,
        PAGE_H - 43 * mm,
        logo_size,
        logo_size,
        mask="auto",
    )
    page.setFillColor(BLUE)
    page.roundRect(49 * mm, PAGE_H - 20 * mm, 28 * mm, 7 * mm, 3.5 * mm, stroke=0, fill=1)
    page.setFillColor(white)
    page.setFont("DejaVu-Bold", 7.1)
    page.drawCentredString(63 * mm, PAGE_H - 17.6 * mm, "FÜR UNRAID")

    page.setFillColor(white)
    page.setFont("DejaVu-Bold", 24)
    page.drawString(49 * mm, PAGE_H - 31 * mm, "Borg Backup UI")
    page.setFillColor(HexColor("#B9C7DA"))
    page.setFont("DejaVu", 10.2)
    page.drawString(
        49 * mm,
        PAGE_H - 39.5 * mm,
        "Backups planen. Repositories verwalten. Restores verifizieren.",
    )

    page.setFillColor(white)
    page.setFont("DejaVu-Bold", 11.4)
    page.drawString(15 * mm, PAGE_H - 56 * mm, "BorgBackup verständlich und zentral verwalten")
    page.setFillColor(HexColor("#B9C7DA"))
    page.setFont("DejaVu", 8.2)
    page.drawString(
        15 * mm,
        PAGE_H - 63 * mm,
        "Eine moderne Oberfläche für Backup-Jobs, Speicherziele, Wartung und Wiederherstellung.",
    )

    # Feature strip
    strip_x = 12 * mm
    strip_y = PAGE_H - header_h - 30 * mm
    strip_w = PAGE_W - 24 * mm
    page.setFillColor(white)
    page.setStrokeColor(BORDER)
    page.roundRect(strip_x, strip_y, strip_w, 24 * mm, 3 * mm, stroke=1, fill=1)
    col_w = strip_w / 3
    draw_feature(page, strip_x + 4 * mm, strip_y + 1.5 * mm, "Geführte Einrichtung", "Job-Wizard mit sicheren Vorgaben")
    draw_feature(page, strip_x + col_w + 4 * mm, strip_y + 1.5 * mm, "Zentrale Kontrolle", "Status, Historie und Benachrichtigungen")
    draw_feature(page, strip_x + 2 * col_w + 4 * mm, strip_y + 1.5 * mm, "Wiederherstellbar", "Browse & Restore plus Restore-Tests")
    page.setStrokeColor(BORDER)
    page.line(strip_x + col_w, strip_y + 4 * mm, strip_x + col_w, strip_y + 20 * mm)
    page.line(strip_x + 2 * col_w, strip_y + 4 * mm, strip_x + 2 * col_w, strip_y + 20 * mm)

    # Screenshots
    dashboard_y = strip_y - 72 * mm
    draw_screenshot_card(
        page,
        "dashboard.jpg",
        12 * mm,
        dashboard_y,
        PAGE_W - 24 * mm,
        66 * mm,
        "Übersicht auf einen Blick",
        "Backup-Status, Speicherentwicklung und Restore-Nachweise zentral erfassen.",
    )

    lower_y = dashboard_y - 75 * mm
    card_gap = 5 * mm
    card_w = (PAGE_W - 24 * mm - card_gap) / 2
    draw_screenshot_card(
        page,
        "repositories.jpg",
        12 * mm,
        lower_y,
        card_w,
        69 * mm,
        "Repositories zentral verwalten",
        "Informationen, Archive und Wartung pro Repository.",
    )
    draw_screenshot_card(
        page,
        "restore-tests.jpg",
        12 * mm + card_w + card_gap,
        lower_y,
        card_w,
        69 * mm,
        "Wiederherstellbarkeit nachweisen",
        "Geplante Restore-Tests machen Backups überprüfbar.",
    )

    # Footer
    footer_h = 36 * mm
    page.setFillColor(NAVY)
    page.rect(0, 0, PAGE_W, footer_h, stroke=0, fill=1)
    page.setFillColor(white)
    page.setFont("DejaVu-Bold", 11.5)
    page.drawString(15 * mm, 24 * mm, "Für zuverlässige Backups auf Unraid")
    page.setFillColor(HexColor("#B9C7DA"))
    page.setFont("DejaVu", 7.5)
    page.drawString(15 * mm, 16.5 * mm, "Lokale, USB-, SMB- und SSH-Speicherziele · Docker- und VM-Steuerung")
    page.drawString(15 * mm, 11 * mm, "E-Mail-, Unraid- und ntfy-Benachrichtigungen · Deutsch und Englisch")

    page.setFillColor(BLUE)
    page.roundRect(PAGE_W - 72 * mm, 12 * mm, 57 * mm, 13 * mm, 3 * mm, stroke=0, fill=1)
    page.setFillColor(white)
    page.setFont("DejaVu-Bold", 8.2)
    page.drawCentredString(PAGE_W - 43.5 * mm, 20.1 * mm, "Open Source auf GitHub")
    page.setFont("DejaVu", 6.7)
    page.drawCentredString(PAGE_W - 43.5 * mm, 15.6 * mm, "github.com/borgforge/borg-backup-ui")

    page.showPage()
    page.save()
    print(OUTPUT)


if __name__ == "__main__":
    generate()

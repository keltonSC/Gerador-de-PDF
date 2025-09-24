"""
PDF — A4 em pé, fundo preto, 4 quadrantes
Q1: foto principal (cover) + faixa de preço dourada arredondada (com borda)
Q2: logo topo do projeto centralizada (maior) → EMPREENDIMENTO e BAIRRO (cada um pode quebrar em 2 linhas, auto-fit) → endereço (menor)
Q3: descrição do imóvel (justificada, Arial/Helvetica). **Sem CTA e sem WhatsApp**
Q4: 4 fotos 2x2 cobrindo TODO o espaço (cover), sem margens

Inferior: proporção fixa **40% (esq.) / 60% (dir.)**. Marca d’água translucida (~30%) em todas as fotos.

Requisitos: pip install streamlit pillow reportlab
Fonts opcionais (para usar Arial):
- arial.ttf
- arialbd.ttf
Caso não existam, cai para Helvetica.
"""

import io
from datetime import datetime
from typing import List, Dict, Optional
import os

from PIL import Image, ImageOps
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import streamlit as st

# Ícones embutidos (base64)
try:
    from ICONS_B64_snippet import ICONS_B64
except Exception:
    ICONS_B64 = {}

st.set_page_config(page_title="PDF Imóvel — Quadrantes (preto)", layout="wide")

PAGE_SIZE = A4
PAGE_W, PAGE_H = PAGE_SIZE
MARGIN = 24

# ---------------- fontes ----------------
FONT_REGULAR = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
try:
    if os.path.exists("arial.ttf") and os.path.exists("arialbd.ttf"):
        pdfmetrics.registerFont(TTFont("Arial", "arial.ttf"))
        pdfmetrics.registerFont(TTFont("Arial-Bold", "arialbd.ttf"))
        FONT_REGULAR = "Arial"
        FONT_BOLD = "Arial-Bold"
except Exception:
    pass

# ---------------- utils (logos locais + watermark + imagens + ícones) ----------------
LOGO_PATH = "logotopo.png"
WATERMARK_PATH = "marcadagua.png"


def pil_from_upload(uploaded_file) -> Optional[Image.Image]:
    if not uploaded_file:
        return None
    img = Image.open(uploaded_file)
    try:
        img = ImageOps.exif_transpose(img)
        return img.convert("RGBA")
    finally:
        try:
            uploaded_file.seek(0)
        except Exception:
            pass


def get_native_logo() -> Optional[ImageReader]:
    if os.path.exists(LOGO_PATH):
        try:
            return ImageReader(LOGO_PATH)
        except Exception:
            return None
    return None


def get_native_watermark() -> Optional[Image.Image]:
    if os.path.exists(WATERMARK_PATH):
        try:
            return Image.open(WATERMARK_PATH).convert("RGBA")
        except Exception:
            return None
    return None


def icon_reader(key: str) -> Optional[ImageReader]:
    """Lê um ícone do dicionário base64 usando a chave informada."""
    b64 = ICONS_B64.get(key)
    if not b64:
        return None
    try:
        import base64, io as _io
        buf = _io.BytesIO(base64.b64decode(b64))
        return ImageReader(buf)
    except Exception:
        return None


def apply_watermark(img: Image.Image, wm: Optional[Image.Image], scale: float = 0.3, opacity: float = 0.22) -> Image.Image:
    if wm is None or img is None:
        return img
    base = img.convert("RGBA")
    mark = wm.convert("RGBA")
    iw, ih = base.size
    target = int(min(iw, ih) * scale)
    mw, mh = mark.size
    ratio = target / max(1, max(mw, mh))
    mark = mark.resize((int(mw * ratio), int(mh * ratio)), Image.LANCZOS)
    alpha = mark.split()[3].point(lambda a: int(a * opacity))
    mark.putalpha(alpha)
    x = (iw - mark.size[0]) // 2
    y = (ih - mark.size[1]) // 2
    base.alpha_composite(mark, dest=(x, y))
    return base


def draw_image_cover(c: canvas.Canvas, img: Image.Image, x, y, w, h, *, wm: Optional[Image.Image] = None):
    if img is None:
        return
    img = apply_watermark(img, wm)
    iw, ih = img.size
    ratio = max(w / iw, h / ih)
    tw, th = int(iw * ratio), int(ih * ratio)
    buf = io.BytesIO(); img.convert("RGB").save(buf, format="JPEG", quality=95); buf.seek(0)
    c.saveState(); p = c.beginPath(); p.rect(x, y, w, h); c.clipPath(p, stroke=0, fill=0)
    c.drawImage(ImageReader(buf), x + (w - tw) / 2, y + (h - th) / 2, width=tw, height=th, mask="auto")
    c.restoreState()


def wrap_text(text: str, max_width: float, font_name: str, font_size: int) -> List[str]:
    if not text:
        return []
    words = text.split()
    lines, cur = [], ""
    for w in words:
        cand = (cur + " " + w).strip()
        if pdfmetrics.stringWidth(cand, font_name, font_size) <= max_width:
            cur = cand
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def draw_justified_text(c: canvas.Canvas, x_left: float, y_top: float, max_w: float, lines: List[str], font_name: str, font_size: int, leading: float):
    for i, line in enumerate(lines):
        y = y_top - i * leading
        c.setFont(font_name, font_size)
        c.drawString(x_left, y, line)


def fit_single_line(text: str, max_w: float, font_name: str, max_size: int, min_size: int = 12) -> int:
    size = max_size
    while size > min_size and pdfmetrics.stringWidth(text, font_name, size) > max_w:
        size -= 1
    return size


# --------------- render 1 página ---------------
def draw_onepage_portrait_quadrants(
    c: canvas.Canvas,
    page_w: float,
    page_h: float,
    foto_top_left: Optional[Image.Image],
    fotos_bottom_right: List[Optional[Image.Image]],
    empreendimento: str,
    bairro: str,
    endereco: str,
    preco_texto: str,
    detalhes: Dict[str, str],
    descricao_cta: str = "",
    *,
    baseline_offset: int = -12,
    grid_thickness: float = 2.0,
):
    c.setFillColor(colors.black)
    c.rect(0, 0, page_w, page_h, stroke=0, fill=1)

    wm_embedded = get_native_watermark()

    mid_x = page_w / 2
    mid_y = page_h / 2

    # Q1
    x1, y1, w1, h1 = 0, mid_y, mid_x, mid_y
    draw_image_cover(c, foto_top_left, x1, y1, w1, h1, wm=wm_embedded)
    if preco_texto:
        band_h = 40
        gold = colors.HexColor("#D4AF37")
        c.saveState()
        c.setFillColor(gold)
        c.setStrokeColor(colors.white)
        c.setLineWidth(2)
        c.roundRect(x1 + 12, y1 + 8, w1 - 24, band_h, 8, stroke=1, fill=1)
        c.setFillColor(colors.white); c.setFont(FONT_BOLD, 18)
        c.drawCentredString(x1 + w1 / 2, y1 + 8 + band_h / 2 - 6, preco_texto)
        c.restoreState()

    # Q2
    x2, y2, w2, h2 = mid_x, mid_y, mid_x, mid_y
    pad_out = 30
    tx = x2 + pad_out
    top_y = y2 + h2 - pad_out
    cursor = top_y

    def draw_logo_center(y_top):
        ir = get_native_logo()
        if ir is None:
            return y_top
        iw, ih = ir.getSize()
        target_w = min(w2 * 0.55, 280)
        ratio = target_w / iw
        target_h = ih * ratio
        cx = x2 + (w2 - target_w) / 2
        c.drawImage(ir, cx, y_top - target_h, width=target_w, height=target_h, mask="auto")
        return y_top - target_h

    cursor = draw_logo_center(cursor) - 40

    # ====== NOVO: EMPREENDIMENTO e BAIRRO em blocos separados, até 2 linhas cada, com auto-fit ======
    max_w = w2 - 2 * pad_out

    # EMPREENDIMENTO
    emp_text = (empreendimento or "EMPREENDIMENTO").upper()
    emp_size = 26
    while emp_size > 12:
        emp_lines = wrap_text(emp_text, max_w, FONT_BOLD, emp_size)
        if len(emp_lines) <= 2:
            break
        emp_size -= 1

    c.setFillColor(colors.white)
    c.setFont(FONT_BOLD, emp_size)
    for ln in emp_lines[:2]:
        c.drawString(tx, cursor, ln)
        cursor -= (emp_size + 6)

    cursor -= 4  # respiro entre EMP e BAIRRO

    # BAIRRO
    bai_text = (bairro or "BAIRRO").upper()
    bai_size = 26
    while bai_size > 12:
        bai_lines = wrap_text(bai_text, max_w, FONT_BOLD, bai_size)
        if len(bai_lines) <= 2:
            break
        bai_size -= 1

    c.setFont(FONT_BOLD, bai_size)
    for ln in bai_lines[:2]:
        c.drawString(tx, cursor, ln)
        cursor -= (bai_size + 6)

    cursor -= 6  # respiro antes do endereço
    # ====== FIM DO NOVO BLOCO ======

    if endereco:
        c.setFillColor(colors.HexColor("#C9C9C9"))
        c.setFont(FONT_REGULAR, 12)
        lines = wrap_text(endereco, max_w, FONT_REGULAR, 12)[:3]
        text = c.beginText(); text.setTextOrigin(tx, cursor); text.setLeading(16)
        for ln in lines:
            text.textLine(ln)
        c.drawText(text)
        cursor -= min(len(lines) * 16 + 12, 72)

    pad_in = 20
    cursor -= pad_in
    available_h = cursor - y2
    icon_h, line_h = 22, 30
    max_rows = max(1, int(available_h // line_h))

    detail_items = [
        ("Quartos", detalhes.get("quartos", "-")),
        ("Suítes", detalhes.get("suites", "-")),
        ("Banheiros", detalhes.get("banheiros", "-")),
        ("Vagas", detalhes.get("vagas", "-")),
        ("Área", f"{detalhes.get('m2','-')} m²" if detalhes.get("m2") else "-"),
        ("Pet", detalhes.get("pet","-")),
    ][:max_rows]

    icon_h = 22
    gap = 8
    label_x = tx + icon_h + gap
    value_x = label_x + 110
    y_line = cursor
    # mapeia rótulo -> chave de ícone
    key_map = {
        "Quartos": "quartos",
        "Suítes": "suites",
        "Banheiros": "banheiros",
        "Vagas": "vagas",
        "Área": "m2",
        "Pet": "pet",
    }
    for rotulo, value in detail_items:
        # desenha ícone (se existir)
        ir = icon_reader(key_map.get(rotulo, ""))
        if ir is not None:
            try:
                iw, ih = ir.getSize()
                ratio = icon_h / max(1, ih)
                tw, th = iw * ratio, icon_h
                c.drawImage(ir, tx, y_line - th + 2, width=tw, height=th, mask='auto')
            except Exception:
                pass
        c.setFillColor(colors.HexColor("#C9C9C9")); c.setFont(FONT_REGULAR, 12)
        c.drawString(label_x, y_line + baseline_offset, f"{rotulo}:")
        c.setFillColor(colors.white); c.setFont(FONT_BOLD, 13)
        c.drawString(value_x, y_line + baseline_offset, str(value))
        y_line -= line_h

    # Q3 (40%)
    left_w = page_w * 0.40
    right_w = page_w * 0.60
    x3, y3, w3, h3 = 0, 0, left_w, mid_y
    if descricao_cta:
        pad = 24
        max_w = w3 - 2 * pad
        font_name = FONT_REGULAR
        cur_font = 14
        leading = cur_font * 1.35
        lines = wrap_text(descricao_cta, max_w, font_name, cur_font)
        start_y = y3 + h3 - pad - leading
        c.setFillColor(colors.HexColor("#E6E6E6"))
        draw_justified_text(c, x3 + pad, start_y, max_w, lines, font_name, cur_font, leading)

    # Q4 (60%)
    x4, y4, w4, h4 = left_w, 0, right_w, mid_y
    area_x, area_y, area_w, area_h = x4, y4, w4, h4

    v_x = area_x + area_w / 2
    h_y = area_y + area_h / 2
    cells = [
        (area_x, h_y, area_w / 2, area_h / 2),
        (v_x, h_y, area_w / 2, area_h / 2),
        (area_x, area_y, area_w / 2, area_h / 2),
        (v_x, area_y, area_w / 2, area_h / 2),
    ]

    for idx in range(4):
        img = fotos_bottom_right[idx] if idx < len(fotos_bottom_right) else None
        if not img:
            continue
        cx, cy, cw, ch = cells[idx]
        draw_image_cover(c, img, cx, cy, cw, ch, wm=wm_embedded)

    c.setStrokeColor(colors.white); c.setLineWidth(grid_thickness)
    c.line(v_x, area_y, v_x, area_y + area_h)
    c.line(area_x, h_y, area_x + area_w, h_y)


# --------------- builder ---------------
@st.cache_data(show_spinner=False)
def build_pdf(
    foto_principal: Optional[Image.Image],
    fotos_quadrante4: List[Optional[Image.Image]],
    empreendimento: str,
    bairro: str,
    endereco: str,
    preco_texto: str,
    detalhes: Dict[str, str],
    descricao_cta: str,
    *,
    baseline_offset: int = -12,
    grid_thickness: float = 2.0,
) -> bytes:
    output = io.BytesIO()
    c = canvas.Canvas(output, pagesize=PAGE_SIZE, pageCompression=1)

    draw_onepage_portrait_quadrants(
        c,
        PAGE_W,
        PAGE_H,
        foto_principal.convert("RGB") if foto_principal else None,
        [im.convert("RGB") for im in fotos_quadrante4 if im][:4],
        empreendimento,
        bairro,
        endereco,
        preco_texto,
        detalhes,
        descricao_cta,
        baseline_offset=baseline_offset,
        grid_thickness=grid_thickness,
    )

    c.showPage(); c.save(); output.seek(0)
    return output.read()


# ---------------- UI ----------------
st.title("Gerador de PDF Luciano Cavalcante")

with st.sidebar:
    st.header("Ajustes finos")
    baseline_offset = st.slider("Baseline dos textos (detalhes)", -24, 8, -12, 1)
    grid_thickness = st.slider("Espessura das divisórias (px)", 1.0, 6.0, 2.0, 0.5)

col1, col2 = st.columns(2)
with col1:
    foto_top_left_file = st.file_uploader("Foto principal (topo-esquerda)", type=["jpg", "jpeg", "png"])
with col2:
    extra_files = st.file_uploader(
        "Quadrante inferior direito — até 4 fotos",
        type=["jpg", "jpeg", "png"],
        accept_multiple_files=True,
    )

empreendimento = st.text_input("Empreendimento", "Edifício Itagua")
bairro = st.text_input("Bairro", "Aldeota")
endereco = st.text_input("Endereço completo", "Rua Exemplo, 123 — Aldeota — Fortaleza/CE")
preco_texto = st.text_input("Preço (faixa no Q1)", "R$ 720.000,00")

col3, col4, col5 = st.columns(3)
with col3:
    quartos = st.text_input("Quartos", "3")
    banheiros = st.text_input("Banheiros", "3")
with col4:
    suites = st.text_input("Suítes", "2")
    vagas = st.text_input("Vagas", "2")
with col5:
    m2 = st.text_input("Área (m²)", "111")
    pet = st.selectbox("Aceita pet?", ["Sim", "Não"], index=0)

descricao_cta = st.text_area(
    "Descrição do imóvel (Q3)",
    "Sala integrada à varanda, ventilação cruzada e cozinha funcional."
)

if st.button("Gerar PDF", type="primary"):
    if not foto_top_left_file:
        st.error("Envie a foto principal!")
    else:
        with st.spinner("Gerando PDF..."):
            foto_principal = pil_from_upload(foto_top_left_file)
            fotos_q4 = [pil_from_upload(f) for f in (extra_files or [])][:4]
            detalhes = {
                "quartos": quartos,
                "suites": suites,
                "banheiros": banheiros,
                "vagas": vagas,
                "m2": m2,
                "pet": pet,
            }

            pdf_bytes = build_pdf(
                foto_principal,
                fotos_q4,
                empreendimento,
                bairro,
                endereco,
                preco_texto,
                detalhes,
                descricao_cta,
                baseline_offset=baseline_offset,
                grid_thickness=grid_thickness,
            )
            st.download_button(
                "Baixar PDF",
                pdf_bytes,
                file_name=f"quadrantes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                mime="application/pdf",
            )

st.caption(
    "• Q2: logo do topo carregada do arquivo local; EMPREENDIMENTO e BAIRRO com auto-fit (até 2 linhas cada); endereço menor. "
    "• Inferior 40/60 (E/D). • Q3 justificado (sem CTA/WhatsApp). • Q4 cobre 100% das células. "
    "• Q1 com faixa de preço arredondada. • Marca d'água central ~30% com opacidade 22% em todas as fotos."
)

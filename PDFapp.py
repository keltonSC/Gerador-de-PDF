"""
App único:
1) Folheto (layout tipo Q2 expandido: logo, título, pílulas, preço e foto)
2) Marca d'água em lote (PDF único / arquivos / ZIP)
3) Folheto + anexar fotos do lote

Requisitos: pip install streamlit pillow reportlab
Arquivos opcionais na pasta:
- logotopo.png         (logo do cabeçalho)
- marcadagua.png       (logo da marca d'água nas fotos)
- arial.ttf / arialbd.ttf (se quiser Arial; senão cai em Helvetica)
- ICONS_B64_snippet.py (opcional, com dicionário ICONS_B64)
"""

import io
import os
import zipfile
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import streamlit as st
from PIL import Image, ImageOps

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


# ====================== CONFIG GERAL ======================
st.set_page_config(page_title="Gerador de PDF Luciano Cavalcante", layout="wide")

PAGE_SIZE = A4
PAGE_W, PAGE_H = PAGE_SIZE
MARGIN = 24

# Arquivos locais padrão
LOGO_PATH = "logotopo.png"
WATERMARK_PATH = "marcadagua.png"

# Ícones embutidos (opcionais)
try:
    from ICONS_B64_snippet import ICONS_B64
except Exception:
    ICONS_B64 = {}

# ====================== FONTES ======================
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

# ====================== HELPERS GERAIS ======================
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
    b64 = ICONS_B64.get(key)
    if not b64:
        return None
    try:
        import base64
        buf = io.BytesIO(base64.b64decode(b64))
        return ImageReader(buf)
    except Exception:
        return None

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

def draw_justified_text(c: canvas.Canvas, x_left: float, y_top: float, max_w: float,
                        lines: List[str], font_name: str, font_size: int, leading: float):
    for i, line in enumerate(lines):
        y = y_top - i * leading
        c.setFont(font_name, font_size)
        c.drawString(x_left, y, line)

def fit_one_line(text: str, max_w: float, max_size: int, min_size: int = 10) -> int:
    """Ajusta a fonte para caber em UMA linha."""
    size = max_size
    while size >= min_size:
        if pdfmetrics.stringWidth(text, FONT_BOLD, size) <= max_w:
            return size
        size -= 1
    return min_size

def layout_title_line(text: str, max_w: float, max_size: int):
    """Retorna (linha única, font_size) já reduzindo ~20% na base e caindo até caber."""
    base = int(max_size * 0.80)  # -20% na base
    fs = fit_one_line(text, max_w, base, min_size=10)
    return text, fs

# ===== Marca d'água - utilitários =====
def apply_opacity(wm: Image.Image, opacity: float) -> Image.Image:
    if wm.mode != "RGBA":
        wm = wm.convert("RGBA")
    alpha = wm.split()[3]
    alpha = alpha.point(lambda p: int(p * opacity))
    wm.putalpha(alpha)
    return wm

def scaled_watermark(base: Image.Image, wm: Image.Image, scale: float) -> Image.Image:
    shorter = min(base.width, base.height)
    target = max(1, int(shorter * scale))
    w, h = wm.size
    ratio = w / h if h else 1
    if w >= h:
        new_w = target
        new_h = int(target / ratio)
    else:
        new_h = target
        new_w = int(target * ratio)
    return wm.resize((max(1, new_w), max(1, new_h)), Image.Resampling.LANCZOS)

def place_position(base_size: Tuple[int, int], wm_size: Tuple[int, int], pos_name: str, margin: int):
    W, H = base_size
    w, h = wm_size
    x_center = (W - w) // 2
    y_center = (H - h) // 2
    positions = {
        "Canto superior esquerdo": (margin, margin),
        "Topo centro": (x_center, margin),
        "Canto superior direito": (W - w - margin, margin),
        "Meio esquerdo": (margin, y_center),
        "Centro": (x_center, y_center),
        "Meio direito": (W - w - margin, y_center),
        "Canto inferior esquerdo": (margin, H - h - margin),
        "Base centro": (x_center, H - h - margin),
        "Canto inferior direito": (W - w - margin, H - h - margin),
    }
    return positions[pos_name]

def watermark_once(base: Image.Image, wm: Image.Image, pos_name: str,
                   scale: float, opacity: float, margin: int, tile: bool) -> Image.Image:
    base = base.convert("RGBA")
    wm = scaled_watermark(base, wm, scale)
    wm = apply_opacity(wm, opacity)
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    if tile:
        step_x = wm.width + margin * 2
        step_y = wm.height + margin * 2
        for y in range(margin, base.height, step_y):
            for x in range(margin, base.width, step_x):
                overlay.alpha_composite(wm, dest=(x, y))
    else:
        x, y = place_position(base.size, wm.size, pos_name, margin)
        overlay.alpha_composite(wm, dest=(x, y))
    return Image.alpha_composite(base, overlay)

def normalized_format_and_ext(filename: str):
    suf = Path(filename).suffix.lower()
    if suf in {".jpg", ".jpeg"}:
        return "JPEG", "jpg", "image/jpeg"
    elif suf == ".png":
        return "PNG", "png", "image/png"
    return "PNG", "png", "image/png"

def process_file(f, wm_img: Image.Image, pos_name: str, scale: float,
                 opacity: float, margin: int, tile: bool):
    base = Image.open(f)
    exif_bytes = base.info.get("exif")
    icc = base.info.get("icc_profile")
    processed = watermark_once(base, wm_img, pos_name, scale, opacity, margin, tile)
    fmt, ext, mime = normalized_format_and_ext(f.name)
    buf = io.BytesIO()
    try:
        if fmt == "JPEG":
            save_kwargs = {"format": "JPEG", "quality": 95, "optimize": False, "progressive": False, "subsampling": 0}
            if exif_bytes:
                save_kwargs["exif"] = exif_bytes
            if icc:
                save_kwargs["icc_profile"] = icc
            processed.convert("RGB").save(buf, **save_kwargs)
        else:
            save_kwargs = {"format": "PNG"}
            if exif_bytes:
                save_kwargs["exif"] = exif_bytes
            if icc:
                save_kwargs["icc_profile"] = icc
            if processed.mode != "RGBA":
                processed = processed.convert("RGBA")
            processed.save(buf, **save_kwargs)
    except Exception:
        # fallback
        if fmt == "JPEG":
            processed.convert("RGB").save(buf, format="JPEG", quality=95)
        else:
            processed.convert("RGBA").save(buf, format="PNG")
    return buf.getvalue(), ext, mime

def process_image_for_pdf(f, wm_img: Image.Image, pos_name: str, scale: float,
                          opacity: float, margin: int, tile: bool) -> Image.Image:
    base = Image.open(f)
    processed = watermark_once(base, wm_img, pos_name, scale, opacity, margin, tile)
    return processed.convert("RGB")

# ====================== DESENHO BASE DE IMAGEM ======================
def draw_image_cover(c: canvas.Canvas, img: Image.Image, x, y, w, h):
    if img is None:
        return
    iw, ih = img.size
    ratio = max(w / iw, h / ih)
    tw, th = int(iw * ratio), int(ih * ratio)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=95)
    buf.seek(0)
    c.saveState()
    p = c.beginPath()
    p.rect(x, y, w, h)
    c.clipPath(p, stroke=0, fill=0)
    c.drawImage(ImageReader(buf), x + (w - tw) / 2, y + (h - th) / 2, width=tw, height=th, mask="auto")
    c.restoreState()

# ====================== FOLHETO (Q2 expandido) ======================
def draw_q2_expanded_page(
    c: canvas.Canvas,
    page_w: float,
    page_h: float,
    *,
    hero_img: Optional[Image.Image],
    empreendimento: str,
    bairro: str,
    detalhes: Dict[str, str],
    preco_texto: str,
    # marca d'água da capa
    wm_img: Optional[Image.Image],
    wm_position: str,
    wm_scale: float,
    wm_opacity: float,
    wm_margin: int,
    wm_tile: bool,
):
    c.setFillColor(colors.black)
    c.rect(0, 0, page_w, page_h, stroke=0, fill=1)

    pad = 36
    content_x = pad
    content_w = page_w - 2 * pad
    cursor_y = page_h - pad

    # ===== LOGO (-20%) =====
    logo_ir = get_native_logo()
    if logo_ir is not None:
        try:
            iw, ih = logo_ir.getSize()
            base_w = min(content_w * 0.45, 260)
            target_w = base_w * 0.80  # -20%
            ratio = target_w / iw
            target_h = ih * ratio
            cx = content_x + (content_w - target_w) / 2
            c.drawImage(logo_ir, cx, cursor_y - target_h, width=target_w, height=target_h, mask="auto")
            cursor_y -= (target_h + 10)   # gap curto para subir título
        except Exception:
            cursor_y -= 8

    # ===== TÍTULO (sempre 1 linha; -20% base e cai até caber) =====
    title_text = f"{(empreendimento or 'EMPREENDIMENTO').upper()} / {(bairro or 'BAIRRO').upper()}"
    one_line, title_fs = layout_title_line(title_text, content_w, max_size=30)
    c.setFillColor(colors.white); c.setFont(FONT_BOLD, title_fs)
    y_title = cursor_y - title_fs
    c.drawCentredString(content_x + content_w/2, y_title, one_line)

    # espaço controlado para evitar sobreposição
    cursor_y = y_title - 20

    # ===== TÓPICOS (pílulas em 1 linha; coladas no preço) =====
    key_map = {"Quartos": "quartos", "Suítes": "suites", "Banheiros": "banheiros",
               "Vagas": "vagas", "Área": "m2", "Pet": "pet"}
    items = [
        ("Quartos", detalhes.get("quartos", "-")),
        ("Suítes", detalhes.get("suites", "-")),
        ("Banheiros", detalhes.get("banheiros", "-")),
        ("Vagas", detalhes.get("vagas", "-")),
        ("Área", f"{detalhes.get('m2','-')} m²" if detalhes.get("m2") else "-"),
        ("Pet", detalhes.get("pet","-") or "-"),
    ]

    best = None
    for base_fs in range(16, 8, -1):  # tenta maior e vai reduzindo
        icon_h = int(base_fs * 1.9)
        gap_x  = 10
        left_pad, right_pad = 10, 12
        widths = []
        for rotulo, valor in items:
            lw = pdfmetrics.stringWidth(f"{rotulo}: ", FONT_REGULAR, base_fs)
            vw = pdfmetrics.stringWidth(f"{valor}",     FONT_BOLD,    base_fs)
            pill_w = left_pad + icon_h + 6 + lw + vw + right_pad
            widths.append(pill_w)
        total_w = sum(widths) + gap_x * (len(items) - 1)
        if total_w <= content_w:
            best = (base_fs, icon_h, gap_x, widths, left_pad, right_pad)
            break
    if best is None:
        base_fs, icon_h, gap_x, widths, left_pad, right_pad = 9, int(9*1.8), 6, [], 8, 10
        for rotulo, valor in items:
            lw = pdfmetrics.stringWidth(f"{rotulo}: ", FONT_REGULAR, base_fs)
            vw = pdfmetrics.stringWidth(f"{valor}",     FONT_BOLD,    base_fs)
            widths.append(left_pad + icon_h + 4 + lw + vw + right_pad)

    total_w = sum(widths) + gap_x * (len(items) - 1)
    start_x = content_x + (content_w - total_w) / 2

    # desce bem os tópicos
    y_pill = cursor_y - 10

    c.setStrokeColor(colors.HexColor("#2A2A2A"))
    x = start_x
    for i, (rotulo, valor) in enumerate(items):
        pill_w = widths[i]
        ir = icon_reader(key_map.get(rotulo, ""))
        try:
            if ir is not None:
                iw, ih = ir.getSize()
                ratio = icon_h / max(1, ih)
                tw, th = iw * ratio, icon_h
                c.drawImage(ir, x + left_pad, y_pill - (icon_h*0.10), width=tw, height=th, mask='auto')
                icon_right = x + left_pad + tw
            else:
                c.setFillColor(colors.white)
                r = icon_h/2.8
                c.circle(x + left_pad + icon_h/2, y_pill + icon_h/2, r, stroke=0, fill=1)
                icon_right = x + left_pad + icon_h
        except Exception:
            icon_right = x + left_pad + icon_h

        label = f"{rotulo}: "
        value = f"{valor}"
        text_y = y_pill + icon_h/2 - base_fs/2 + 2
        c.setFillColor(colors.HexColor("#C9C9C9")); c.setFont(FONT_REGULAR, base_fs)
        c.drawString(icon_right + 6, text_y, label)
        lw = pdfmetrics.stringWidth(label, FONT_REGULAR, base_fs)
        c.setFillColor(colors.white); c.setFont(FONT_BOLD, base_fs)
        c.drawString(icon_right + 6 + lw, text_y, value)

        c.setStrokeColor(colors.HexColor("#2A2A2A"))
        c.roundRect(x, y_pill - 6, pill_w, icon_h + 12, 10, stroke=1, fill=0)

        x += pill_w + gap_x

    # ===== FAIXA DE PREÇO =====
    cursor_y = y_pill - 10
    if preco_texto:
        price_fs = 14  # reduzido
        text_w = pdfmetrics.stringWidth(preco_texto, FONT_BOLD, price_fs)
        pad_w = 18
        band_w = min(content_w, text_w + pad_w*2)
        band_h = int(price_fs * 1.8)  # menor
        band_x = content_x + (content_w - band_w)/2
        band_y = cursor_y - band_h
        gold = colors.HexColor("#D4AF37")
        c.saveState()
        c.setFillColor(gold)

        c.setStrokeColor(colors.black)
        c.setLineWidth(1.5)
        c.roundRect(band_x, band_y, band_w, band_h, 8, stroke=1, fill=1)
        c.setFillColor(colors.black); c.setFont(FONT_BOLD, price_fs)
        c.drawCentredString(band_x + band_w/2, band_y + band_h/2 - price_fs*0.4, preco_texto)
        c.restoreState()
        cursor_y = band_y - 12
    else:
        cursor_y -= 16

    # ===== FOTO (embaixo; aplica a mesma marca d’água) =====
    photo_h = max(220, int(cursor_y - MARGIN))
    if hero_img is not None:
        if wm_img is not None:
            try:
                hero_img = watermark_once(hero_img, wm_img, wm_position, wm_scale, wm_opacity, wm_margin, wm_tile)
            except Exception:
                pass
        draw_image_cover(c, hero_img, content_x, MARGIN, content_w, photo_h)

# Builder do folheto
@st.cache_data(show_spinner=False)
def build_folheto_pdf(
    hero_img: Optional[Image.Image],
    empreendimento: str,
    bairro: str,
    preco_texto: str,
    detalhes: Dict[str, str],
    *,
    wm_for_cover: Optional[Image.Image],
    wm_position: str,
    wm_scale: float,
    wm_opacity: float,
    wm_margin: int,
    wm_tile: bool,
) -> bytes:
    output = io.BytesIO()
    c = canvas.Canvas(output, pagesize=PAGE_SIZE, pageCompression=1)
    draw_q2_expanded_page(
        c, PAGE_W, PAGE_H,
        hero_img=hero_img,
        empreendimento=empreendimento,
        bairro=bairro,
        detalhes=detalhes,
        preco_texto=preco_texto,
        wm_img=wm_for_cover,
        wm_position=wm_position,
        wm_scale=wm_scale,
        wm_opacity=wm_opacity,
        wm_margin=wm_margin,
        wm_tile=wm_tile,
    )
    c.showPage()
    c.save()
    output.seek(0)
    return output.read()

# ============== UI ==============
st.title("Gerador de PDF Luciano Cavalcante")

# --------- Sidebar: MODO ---------
modo = st.sidebar.radio(
    "Modo de uso",
    ["Folheto (Layout único)", "Marca d'água em lote", "Folheto + anexar fotos do lote"],
    index=0
)

# --------- Sidebar: Marca d'água (para fotos e capa) ---------
with st.sidebar.expander("Marca d'água (para fotos e capa)", expanded=True):
    position = st.selectbox(
        "Posição", [
            "Canto superior esquerdo", "Topo centro", "Canto superior direito",
            "Meio esquerdo", "Centro", "Meio direito",
            "Canto inferior esquerdo", "Base centro", "Canto inferior direito",
        ], index=8,
    )
    scale_pct = st.slider("Tamanho da marca d'água (% do lado menor)", 5, 60, 20, 1)
    opacity_pct = st.slider("Opacidade da marca d'água (%)", 5, 100, 60, 1)
    margin_px = st.number_input("Margem (px)", min_value=0, max_value=2000, value=24, step=1)
    repeat_tile = st.checkbox("Repetir (mosaico)", value=False)

wm_img_selected = get_native_watermark()
if wm_img_selected is None:
    st.warning("Coloque o arquivo 'marcadagua.png' na pasta do app para usar a marca d'água.")

# --------- COLUNAS DE UPLOAD ---------
col1, col2 = st.columns(2)

with col1:
    if modo in ("Folheto (Layout único)", "Folheto + anexar fotos do lote"):
        st.subheader("Capa do folheto")
        hero_file = st.file_uploader("Foto de capa (JPG/PNG)", type=["jpg", "jpeg", "png"])

with col2:
    if modo in ("Marca d'água em lote", "Folheto + anexar fotos do lote"):
        st.subheader("Fotos do lote (para marca d'água)")
        img_files = st.file_uploader(
            "Imagens originais (JPG/PNG) — selecione várias",
            type=["jpg", "jpeg", "png"],
            accept_multiple_files=True,
        )

# --------- Inputs de texto do folheto ---------
empreendimento = st.text_input("Empreendimento", "")
bairro = st.text_input("Bairro", "")
preco_texto = st.text_input("Preço (faixa)", "")

col3, col4, col5 = st.columns(3)
with col3:
    quartos = st.text_input("Quartos", "")
    banheiros = st.text_input("Banheiros", "")
with col4:
    suites = st.text_input("Suítes", "")
    vagas = st.text_input("Vagas", "")
with col5:
    m2 = st.text_input("Área (m²)", "")
    pet = st.selectbox("Aceita pet?", ["", "Sim", "Não"], index=0)

# --------- Saída do modo 2 ---------
if modo == "Marca d'água em lote":
    st.subheader("Saída do lote")
    output_mode = st.radio("Como deseja baixar?", ["PDF único", "Arquivos individuais", "ZIP"], index=0)

# ====================== BOTÕES/EXECUÇÃO ======================
def detalhes_from_inputs():
    return {"quartos": quartos, "suites": suites, "banheiros": banheiros,
            "vagas": vagas, "m2": m2, "pet": pet}

# ---- MODO 1: Folheto solo ----
if modo == "Folheto (Layout único)":
    if st.button("Gerar PDF (folheto)", type="primary"):
        if not hero_file:
            st.error("Envie a foto de capa!")
        elif wm_img_selected is None:
            st.error("Coloque o arquivo 'marcadagua.png' na pasta do app.")
        else:
            with st.spinner("Gerando PDF do folheto..."):
                hero_img = pil_from_upload(hero_file)
                pdf_bytes = build_folheto_pdf(
                    hero_img,
                    empreendimento,
                    bairro,
                    preco_texto,
                    detalhes_from_inputs(),
                    wm_for_cover=wm_img_selected,
                    wm_position=position,
                    wm_scale=scale_pct/100.0,
                    wm_opacity=opacity_pct/100.0,
                    wm_margin=margin_px,
                    wm_tile=repeat_tile,
                )
                st.download_button(
                    "Baixar PDF (folheto)",
                    pdf_bytes,
                    file_name=f"folheto_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                    mime="application/pdf",
                )

# ---- MODO 2: Lote (marca d'água) ----
if modo == "Marca d'água em lote":
    if img_files and wm_img_selected is not None:
        total = len(img_files)
        prog = st.progress(0, text="Processando…")

        if output_mode == "PDF único":
            pages = []
            done = 0
            for f in img_files:
                pages.append(process_image_for_pdf(
                    f, wm_img_selected, position, scale_pct/100.0, opacity_pct/100.0, margin_px, repeat_tile
                ))
                done += 1
                prog.progress(int(done/total*100), text=f"{done}/{total} páginas preparadas")
            if pages:
                pdf_buf = io.BytesIO()
                pages[0].save(pdf_buf, format="PDF", save_all=True, append_images=pages[1:], resolution=300)
                st.download_button(
                    label="⬇️ Baixar PDF único",
                    data=pdf_buf.getvalue(),
                    file_name="imagens_marcadagua.pdf",
                    mime="application/pdf",
                )

        elif output_mode == "Arquivos individuais":
            done = 0
            for f in img_files:
                data, ext, mime = process_file(
                    f, wm_img_selected, position, scale_pct/100.0, opacity_pct/100.0, margin_px, repeat_tile
                )
                base_name = Path(f.name).stem
                st.download_button(
                    label=f"⬇️ Baixar {base_name}_marcadagua.{ext}",
                    data=data,
                    file_name=f"{base_name}_marcadagua.{ext}",
                    mime=mime,
                )
                done += 1
                prog.progress(int(done/total*100), text=f"{done}/{total} concluídas")

        else:  # ZIP
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_STORED) as zf:
                done = 0
                for f in img_files:
                    data, ext, _ = process_file(
                        f, wm_img_selected, position, scale_pct/100.0, opacity_pct/100.0, margin_px, repeat_tile
                    )
                    base_name = Path(f.name).stem
                    zf.writestr(f"{base_name}_marcadagua.{ext}", data)
                    done += 1
                    prog.progress(int(done/total*100), text=f"{done}/{total} adicionadas ao ZIP")
            st.download_button(
                label="⬇️ Baixar todas em .zip",
                data=zip_buffer.getvalue(),
                file_name="imagens_marcadagua.zip",
                mime="application/zip",
            )
    else:
        st.info("Envie as **imagens do lote** e garanta que exista **marcadagua.png** na pasta do app.")

# ---- MODO 3: Folheto + anexar fotos do lote ----
if modo == "Folheto + anexar fotos do lote":
    if st.button("Gerar PDF (folheto + fotos do lote)", type="primary"):
        if not hero_file:
            st.error("Envie a foto de capa!")
        elif not img_files:
            st.error("Envie também as imagens do lote para anexar.")
        elif wm_img_selected is None:
            st.error("Coloque o arquivo 'marcadagua.png' na pasta do app.")
        else:
            with st.spinner("Montando PDF completo..."):
                out = io.BytesIO()
                c = canvas.Canvas(out, pagesize=PAGE_SIZE, pageCompression=1)

                # 1) Página 1: folheto (capa com a MESMA marca d'água e configurações)
                hero_img = pil_from_upload(hero_file)
                draw_q2_expanded_page(
                    c, PAGE_W, PAGE_H,
                    hero_img=hero_img,
                    empreendimento=empreendimento,
                    bairro=bairro,
                    detalhes=detalhes_from_inputs(),
                    preco_texto=preco_texto,
                    wm_img=wm_img_selected,
                    wm_position=position,
                    wm_scale=scale_pct/100.0,
                    wm_opacity=opacity_pct/100.0,
                    wm_margin=margin_px,
                    wm_tile=repeat_tile,
                )
                c.showPage()

                # 2) Demais páginas: cada foto do lote com marca d'água
                def draw_fullpage_cover(img_rgb: Image.Image):
                    iw, ih = img_rgb.size
                    ratio = max(PAGE_W / iw, PAGE_H / ih)
                    tw, th = int(iw * ratio), int(ih * ratio)
                    buf = io.BytesIO()
                    img_rgb.convert("RGB").save(buf, format="JPEG", quality=95)
                    buf.seek(0)
                    c.saveState()
                    p = c.beginPath()
                    p.rect(0, 0, PAGE_W, PAGE_H)
                    c.clipPath(p, stroke=0, fill=0)
                    c.drawImage(ImageReader(buf), (PAGE_W - tw) / 2, (PAGE_H - th) / 2, width=tw, height=th, mask="auto")
                    c.restoreState()

                for f in img_files:
                    img = process_image_for_pdf(
                        f, wm_img_selected, position, scale_pct/100.0, opacity_pct/100.0, margin_px, repeat_tile
                    )
                    draw_fullpage_cover(img)
                    c.showPage()

                c.save()
                out.seek(0)

                st.download_button(
                    "Baixar PDF (folheto + fotos do lote)",
                    out.getvalue(),
                    file_name=f"folheto_com_lote_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                    mime="application/pdf",
                )

# Rodapé
st.caption(
    "• Folheto com logo reduzida, título em 1 linha (auto-fit), pílulas numa linha e faixa de preço compacta.  "
    "• Lote com marca d'água: PDF único / arquivos / ZIP.  "
    "• Modo combinado: folheto na 1ª página e fotos do lote em páginas extras, todas com a mesma marca d'água."
)

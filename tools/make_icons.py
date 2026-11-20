"""
Genera il logo RouteRewind (doppia R speculare + percorso e segnaposto) in PNG/ICO
e i loghi del pacchetto MSIX. Le immagini prodotte sono già incluse nel progetto:
lo script serve solo se si vuole modificare il logo (richiede il font Poppins Bold
oppure un altro font grassetto indicato in FONT_CANDIDATES).
"""
import os

from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf",
    "C:/Windows/Fonts/seguisb.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]
NAVY = (15, 32, 64, 255)
BLUE = (96, 165, 250, 255)
WHITE = (255, 255, 255, 255)
RED = (239, 68, 68, 255)
GREEN = (34, 197, 94, 255)


def _font(px):
    for f in FONT_CANDIDATES:
        if os.path.exists(f):
            return ImageFont.truetype(f, px)
    raise SystemExit("Nessun font grassetto trovato: modifica FONT_CANDIDATES")


def _letter(S, color):
    """Una R centrata in un riquadro S x S, ritagliata al suo ingombro."""
    font = _font(int(S * 0.62))
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.text((S // 2, S // 2), "R", font=font, fill=color, anchor="mm")
    return im.crop(im.getbbox())


def draw_icon(size: int, background=True) -> Image.Image:
    s = 4
    S = size * s
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if background:
        d.rounded_rectangle([0, 0, S - 1, S - 1], int(S * 0.22), fill=NAVY)

    right = _letter(S, WHITE)
    left = ImageOps.mirror(_letter(S, BLUE))
    gap = int(S * 0.025)
    total_w = left.width + gap + right.width
    x0 = (S - total_w) // 2
    y0 = int(S * 0.20)
    im.alpha_composite(left, (x0, y0))
    im.alpha_composite(right, (x0 + left.width + gap, y0))

    # percorso tratteggiato sotto le lettere, dal punto verde al segnaposto
    base_y = y0 + right.height + int(S * 0.10)
    xa, xb = int(S * 0.15), int(S * 0.77)
    w = max(2, int(S * 0.032))
    dash = int(S * 0.045)
    x = xa
    while x < xb - dash:
        d.line([(x, base_y), (x + dash, base_y)], fill=BLUE, width=w)
        x += dash * 2
    r = int(S * 0.045)
    d.ellipse([xa - r, base_y - r, xa + r, base_y + r], fill=GREEN)
    # segnaposto con la punta sul percorso
    tip = (xb + int(S * 0.06), base_y + int(S * 0.005))
    hw = int(S * 0.085)
    cy = tip[1] - int(S * 0.15)
    d.ellipse([tip[0] - hw, cy - hw, tip[0] + hw, cy + hw], fill=RED)
    d.polygon([(tip[0] - hw * 0.86, cy + hw * 0.5), (tip[0] + hw * 0.86, cy + hw * 0.5), tip], fill=RED)
    ir = int(hw * 0.42)
    d.ellipse([tip[0] - ir, cy - ir, tip[0] + ir, cy + ir], fill=WHITE)
    return im.resize((size, size), Image.LANCZOS)


def main():
    assets = os.path.join(ROOT, "assets")
    os.makedirs(assets, exist_ok=True)
    big = draw_icon(512)
    big.resize((256, 256), Image.LANCZOS).save(os.path.join(assets, "icon.png"))
    big.save(os.path.join(assets, "icon.ico"),
             sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    draw_icon(512, background=False).save(os.path.join(assets, "logo_transparent.png"))

    store = os.path.join(ROOT, "packaging", "Assets")
    os.makedirs(store, exist_ok=True)
    for name, (w, h) in {"StoreLogo.png": (50, 50), "Square44x44Logo.png": (44, 44),
                         "Square71x71Logo.png": (71, 71), "Square150x150Logo.png": (150, 150),
                         "Square310x310Logo.png": (310, 310), "Wide310x150Logo.png": (310, 150),
                         "SplashScreen.png": (620, 300)}.items():
        if w == h:
            draw_icon(w).save(os.path.join(store, name))
        else:
            canvas = Image.new("RGBA", (w, h), NAVY)
            icon = draw_icon(int(h * 0.8), background=False)
            canvas.alpha_composite(icon, ((w - icon.width) // 2, (h - icon.height) // 2))
            canvas.save(os.path.join(store, name))
    print("Icone create.")


if __name__ == "__main__":
    main()

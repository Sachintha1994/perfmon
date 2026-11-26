"""Draws the PerfMon app icon (gradient tile + pulse line) and saves icon.ico."""
from pathlib import Path

from PIL import Image, ImageDraw

S = 1024
A, B = (77, 141, 255), (155, 107, 255)

grad = Image.new("RGBA", (S, S))
px = grad.load()
for y in range(S):
    for x in range(S):
        t = (x + y) / (2 * S - 2)
        px[x, y] = tuple(round(A[i] + (B[i] - A[i]) * t) for i in range(3)) + (255,)

mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle((0, 0, S - 1, S - 1), radius=230, fill=255)
icon = Image.new("RGBA", (S, S), (0, 0, 0, 0))
icon.paste(grad, (0, 0), mask)

# pulse line: M3 12 h4 l3-8 4 16 3-8 h4 on a 24-unit grid
u, off = S * 0.70 / 18, S * 0.15
pts = [(3, 12), (7, 12), (10, 4), (14, 20), (17, 12), (21, 12)]
pts = [(off + (x - 3) * u, off + (y - 3) * u * 0.9 + S * 0.04) for x, y in pts]
d = ImageDraw.Draw(icon)
w = int(S * 0.085)
d.line(pts, fill="white", width=w, joint="curve")
for p in (pts[0], pts[-1]):
    d.ellipse((p[0] - w / 2, p[1] - w / 2, p[0] + w / 2, p[1] + w / 2), fill="white")

out = Path(__file__).parent / "icon.ico"
icon.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
icon.resize((256, 256), Image.LANCZOS).save(out.with_suffix(".png"))
print("wrote", out)

"""Vertical before/after clip for Instagram Reels, TikTok and stories.

Built from the two photos only (no AI), so the dish is exactly what the photos
show. 720x1280, 30 fps, about 8 seconds, H.264 MP4 that phones can play.

Timeline:
    0.0-3.0s  the original photo, slowly zooming in
    3.0-4.2s  a wipe from left to right reveals the finished photo
    4.2-8.0s  the finished photo, still zooming in
"""

import io
import os
import tempfile
from pathlib import Path

import imageio.v2 as imageio
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

WIDTH, HEIGHT = 720, 1280
FPS = 30
BEFORE_END, WIPE_END, CLIP_END = 3.0, 4.2, 8.0

BOX_W, BOX_H = 648, 486  # the photo panel, 4:3
BOX_X = (WIDTH - BOX_W) // 2
BOX_Y = 400

INK = (42, 33, 28)
ACCENT = (183, 65, 42)
WHITE = (255, 255, 255)

# Japanese-capable fonts: Streamlit Cloud (packages.txt installs fonts-noto-cjk), then macOS.
FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W7.ttc",
]


def _font(size):
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            return ImageFont.truetype(path, size), True
    return ImageFont.load_default(size=size), False


def _open(image_bytes):
    with Image.open(io.BytesIO(image_bytes)) as original:
        return ImageOps.exif_transpose(original).convert("RGB")


def _backdrop(image):
    """Blurred, darkened full-screen version of the photo behind the panel."""
    cover = ImageOps.fit(image, (WIDTH // 4, HEIGHT // 4), Image.Resampling.LANCZOS)
    cover = cover.filter(ImageFilter.GaussianBlur(6)).resize((WIDTH, HEIGHT), Image.Resampling.BILINEAR)
    return Image.blend(cover, Image.new("RGB", (WIDTH, HEIGHT), INK), 0.45)


# Caption sizes to try, largest first: short captions stay big and bold,
# long ones shrink until they fit in at most three lines.
CAPTION_SIZES = range(76, 33, -4)
CAPTION_MAX_LINES = 3
CAPTION_WIDTH = WIDTH - 96
# Good places to break a line, and characters that must not start one.
BREAK_AFTER = set(" 　、。，．・/／!！?？)）」』】")
NO_LINE_START = set("、。，．・!！?？)）」』】ーぁぃぅぇぉっゃゅょァィゥェォッャュョ")


MEASURE_SIZE = 100


# Particles after which Japanese reads naturally on a new line, when the next
# character starts a new word (kanji or katakana), e.g. じゃがいもと|厚切り.
SOFT_BREAK_AFTER = set("のとをにでがはへや")
HIRAGANA = range(0x3041, 0x30A0)


def _break_points(text):
    """{position: penalty} for places a line may end: 0 after spaces or
    punctuation, more after a particle (used when no better break is near)."""
    points = {}
    for i in range(1, len(text)):
        before, after = text[i - 1], text[i]
        if after in NO_LINE_START:
            continue
        if before in BREAK_AFTER:
            points[i] = 0
        elif before in SOFT_BREAK_AFTER and ord(after) not in HIRAGANA and not after.isspace():
            points[i] = 14
    return points


def _balanced_cuts(text, lines_wanted):
    """Character positions that split `text` into equal-length lines."""
    cuts = []
    for k in range(1, lines_wanted):
        cut = round(len(text) * k / lines_wanted)
        while cut < len(text) and text[cut] in NO_LINE_START:
            cut += 1
        cuts.append(cut)
    return cuts


def _candidates(text):
    """(lines, penalty) layouts with up to three lines."""
    yield [text], 0
    points = _break_points(text)
    ordered = sorted(points)
    for i, a in enumerate(ordered):
        yield [text[:a], text[a:]], points[a]
        for b in ordered[i + 1:]:
            yield [text[:a], text[a:b], text[b:]], points[a] + points[b]
    # Evenly split, possibly mid-word (a last resort).
    for lines_wanted in (2, 3):
        cuts = [0] + _balanced_cuts(text, lines_wanted) + [len(text)]
        if all(x < y for x, y in zip(cuts, cuts[1:])):
            yield [text[x:y] for x, y in zip(cuts, cuts[1:])], 16 * (lines_wanted - 1)


LINE_SPACING = 1.3
# Instagram/TikTok draw their own buttons over the top of the screen.
SAFE_TOP = 170


def _fit_caption(draw, text, max_width=CAPTION_WIDTH, max_height=10_000):
    """(font, size, lines) that read best: a big size, few lines, and line
    breaks at spaces or punctuation rather than in the middle of a word."""
    text = " ".join(text.split())
    probe, _ = _font(MEASURE_SIZE)
    best = None
    for lines, penalty in _candidates(text):
        lines = [line.strip() for line in lines if line.strip()]
        widest = max(draw.textlength(line, font=probe) for line in lines)
        size = min(CAPTION_SIZES[0], int(max_width * MEASURE_SIZE / widest) // 2 * 2)
        size = min(size, int(max_height / (len(lines) * LINE_SPACING)) // 2 * 2)
        if size < CAPTION_SIZES[-1]:
            continue
        score = size - 8 * (len(lines) - 1) - penalty
        if best is None or score > best[0]:
            best = (score, size, lines)
    if best:
        _, size, lines = best
        return _font(size)[0], size, lines
    # Very long text: smallest size, wrapped greedily.
    size = CAPTION_SIZES[-1]
    font, _ = _font(size)
    lines, line = [], ""
    for ch in text:
        if draw.textlength(line + ch, font=font) > max_width and line:
            lines.append(line)
            line = ch
        else:
            line += ch
    return font, size, (lines + [line])[:CAPTION_MAX_LINES]


def _draw_caption(draw, text, bottom, outline, top_limit=SAFE_TOP):
    """Draw `text` centred, its last line ending at `bottom` and its first
    line no higher than `top_limit`; returns the top."""
    font, size, lines = _fit_caption(draw, text, max_height=bottom - top_limit)
    line_height = round(size * LINE_SPACING)
    top = bottom - line_height * len(lines)
    y = top
    for line in lines:
        w = draw.textlength(line, font=font)
        if outline:
            draw.text(((WIDTH - w) / 2, y), line, font=font, fill=WHITE,
                      stroke_width=max(2, size // 18), stroke_fill=(20, 16, 13, 160))
        else:
            draw.text(((WIDTH - w) / 2, y), line, font=font, fill=WHITE)
        y += line_height
    return top


def _overlay(caption, credit):
    """Text layers drawn once: the caption above the panel and the credit below."""
    layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    _, has_japanese = _font(56)
    text = caption.strip() if caption and caption.strip() and has_japanese else "BEFORE → AFTER"
    # Sits just above the photo panel, growing upward with more lines.
    _draw_caption(draw, text, bottom=BOX_Y - 40, outline=True)

    if credit:
        small, has_japanese = _font(26)
        text = "Menu Photo Pro で仕上げました" if has_japanese else "Edited with Menu Photo Pro"
        w = draw.textlength(text, font=small)
        draw.text(((WIDTH - w) / 2, BOX_Y + BOX_H + 330), text, font=small, fill=(255, 255, 255, 210))
    return layer


def _label(text, fill):
    font, _ = _font(30)
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    w = int(probe.textlength(text, font=font)) + 36
    tag = Image.new("RGBA", (w, 50), (0, 0, 0, 0))
    ImageDraw.Draw(tag).rounded_rectangle((0, 0, w - 1, 49), 10, fill=fill)
    ImageDraw.Draw(tag).text((18, 6), text, font=font, fill=WHITE)
    return tag


def _zoomed(image, zoom):
    """The panel's view of `image`, cropped toward the centre by `zoom`."""
    w, h = image.size
    cw, ch = w / zoom, h / zoom
    left, top = (w - cw) / 2, (h - ch) / 2
    return image.resize((BOX_W, BOX_H), Image.Resampling.BILINEAR, box=(left, top, left + cw, top + ch))


def _ease(p):
    return p * p * (3 - 2 * p)


def _writer(path):
    return imageio.get_writer(
        path, fps=FPS, codec="libx264", quality=8, pixelformat="yuv420p",
        macro_block_size=16, ffmpeg_params=["-movflags", "+faststart"],
    )


def _faded(layer, k):
    if k >= 1:
        return layer
    faded = layer.copy()
    faded.putalpha(layer.getchannel("A").point(lambda a: int(a * k)))
    return faded


def _bottom_caption(caption, credit):
    """Caption near the bottom over a soft dark gradient, for full-screen clips."""
    layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    shade = Image.linear_gradient("L").resize((WIDTH, 520)).point(lambda v: int(v * 0.75))
    layer.paste((20, 16, 13, 255), (0, HEIGHT - 520), shade)
    draw = ImageDraw.Draw(layer)

    _, has_japanese = _font(56)
    if caption and caption.strip() and has_japanese:
        # Ends above the credit line, growing upward with more lines.
        _draw_caption(draw, caption.strip(), bottom=HEIGHT - 120, outline=False)
    if credit:
        small, has_japanese = _font(26)
        text = "Menu Photo Pro で仕上げました" if has_japanese else "Edited with Menu Photo Pro"
        w = draw.textlength(text, font=small)
        draw.text(((WIDTH - w) / 2, HEIGHT - 70), text, font=small, fill=(255, 255, 255, 210))
    return layer


def make_image_video(after_bytes, caption="", credit=True, style="full"):
    """An ~8 second clip of the finished photo alone.

    style "full":  fills the vertical screen and drifts slowly across the dish.
    style "panel": shows the whole dish on a blurred backdrop, slowly zooming.
    The caption fades in after a moment.
    """
    image = _open(after_bytes)
    fd, path = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)
    try:
        writer = _writer(path)
        if style == "panel":
            photo = ImageOps.fit(image, (BOX_W * 2, BOX_H * 2), Image.Resampling.LANCZOS)
            back = _backdrop(photo)
            text = _overlay(caption, credit)
            mask = Image.new("L", (BOX_W, BOX_H), 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, BOX_W - 1, BOX_H - 1), 22, fill=255)
        else:
            # Scale so the photo is a little taller than the screen, leaving room to zoom.
            scale = HEIGHT * 1.1 / image.height
            photo = image.resize((max(WIDTH + 2, round(image.width * scale)), round(HEIGHT * 1.1)),
                                 Image.Resampling.LANCZOS)
            text = _bottom_caption(caption, credit)

        for n in range(int(CLIP_END * FPS)):
            t = n / FPS
            p = _ease(t / CLIP_END)
            if style == "panel":
                frame = back.copy()
                frame.paste(_zoomed(photo, 1.0 + 0.12 * p), (BOX_X, BOX_Y), mask)
            else:
                zoom = 1.0 + 0.08 * p
                win_h = photo.height / zoom
                win_w = min(win_h * WIDTH / HEIGHT, photo.width)
                left = (photo.width - win_w) * (0.15 + 0.7 * p)
                top = (photo.height - win_h) / 2
                frame = photo.resize((WIDTH, HEIGHT), Image.Resampling.BILINEAR,
                                     box=(left, top, left + win_w, top + win_h))
            frame = frame.convert("RGBA")
            frame.alpha_composite(_faded(text, min(1.0, max(0.0, (t - 0.8) / 0.8))))
            frame = frame.convert("RGB")
            if t < 0.4:
                frame = Image.blend(Image.new("RGB", (WIDTH, HEIGHT), INK), frame, t / 0.4)
            writer.append_data(np.asarray(frame))
        writer.close()
        return Path(path).read_bytes()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def make_video(before_bytes, after_bytes, caption="", credit=True):
    """Return the MP4 bytes of the before/after clip."""
    # Both photos share the panel's 4:3 framing so the wipe lines up.
    source = ImageOps.fit(_open(before_bytes), (BOX_W * 2, BOX_H * 2), Image.Resampling.LANCZOS)
    result = ImageOps.fit(_open(after_bytes), (BOX_W * 2, BOX_H * 2), Image.Resampling.LANCZOS)
    back_before, back_after = _backdrop(source), _backdrop(result)
    text = _overlay(caption, credit)
    tag_before, tag_after = _label("BEFORE", (20, 16, 13, 215)), _label("AFTER", ACCENT + (255,))

    mask = Image.new("L", (BOX_W, BOX_H), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, BOX_W - 1, BOX_H - 1), 22, fill=255)

    fd, path = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)
    try:
        writer = imageio.get_writer(
            path, fps=FPS, codec="libx264", quality=8, pixelformat="yuv420p",
            macro_block_size=16, ffmpeg_params=["-movflags", "+faststart"],
        )
        for n in range(int(CLIP_END * FPS)):
            t = n / FPS
            zoom = 1.0 + 0.10 * (t / CLIP_END)
            if t < BEFORE_END:
                progress = 0.0
            elif t < WIPE_END:
                progress = _ease((t - BEFORE_END) / (WIPE_END - BEFORE_END))
            else:
                progress = 1.0

            frame = Image.blend(back_before, back_after, progress) if 0 < progress < 1 else (
                back_after if progress >= 1 else back_before
            ).copy()

            panel = _zoomed(source, zoom)
            if progress > 0:
                edge = int(BOX_W * progress)
                if edge >= BOX_W:
                    panel = _zoomed(result, zoom)
                elif edge > 0:
                    panel.paste(_zoomed(result, zoom).crop((0, 0, edge, BOX_H)), (0, 0))
                    ImageDraw.Draw(panel).rectangle((edge - 2, 0, edge + 2, BOX_H), fill=WHITE)
            frame.paste(panel, (BOX_X, BOX_Y), mask)

            frame = frame.convert("RGBA")
            tag = tag_after if progress >= 0.5 else tag_before
            frame.alpha_composite(tag, (BOX_X + 18, BOX_Y + 18))
            frame.alpha_composite(text)
            frame = frame.convert("RGB")

            if t < 0.3:  # short fade in from the page colour
                frame = Image.blend(Image.new("RGB", (WIDTH, HEIGHT), INK), frame, t / 0.3)
            writer.append_data(np.asarray(frame))
        writer.close()
        return Path(path).read_bytes()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass

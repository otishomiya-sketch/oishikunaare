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


def _wrap(draw, text, font, max_width):
    lines, line = [], ""
    for ch in text:
        if draw.textlength(line + ch, font=font) > max_width and line:
            lines.append(line)
            line = ch
        else:
            line += ch
    if line:
        lines.append(line)
    return lines[:2]


def _overlay(caption, credit):
    """Text layers drawn once: the caption above the panel and the credit below."""
    layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    title_font, has_japanese = _font(56)
    text = caption.strip() if caption and has_japanese else "BEFORE → AFTER"
    lines = _wrap(draw, text, title_font, WIDTH - 96)
    y = BOX_Y - 60 - len(lines) * 72
    for line in lines:
        w = draw.textlength(line, font=title_font)
        draw.text(((WIDTH - w) / 2, y), line, font=title_font, fill=WHITE,
                  stroke_width=3, stroke_fill=(20, 16, 13, 160))
        y += 72

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

    title_font, has_japanese = _font(56)
    if caption and caption.strip() and has_japanese:
        lines = _wrap(draw, caption.strip(), title_font, WIDTH - 96)
        y = HEIGHT - 190 - len(lines) * 72
        for line in lines:
            w = draw.textlength(line, font=title_font)
            draw.text(((WIDTH - w) / 2, y), line, font=title_font, fill=WHITE)
            y += 72
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

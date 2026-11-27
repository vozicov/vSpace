import logging
import shutil
import struct
import subprocess
import tempfile
import uuid
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, ImageSequence, UnidentifiedImageError

logger = logging.getLogger(__name__)

Image.MAX_IMAGE_PIXELS = 60_000_000  # reject decompression bombs

# Only these formats can be real animations. Pillow also reports "frames" for other files:
# an iPhone photo is a JPEG (an "MPO") with extra pictures attached (Live Photo, depth map, HDR
# gain map). Those extras are not animation frames, and treating them as such made profile
# pictures blink between the photo and a dark picture.
ANIMATED_FORMATS = {'GIF', 'WEBP', 'PNG'}

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp'}
VIDEO_EXTENSIONS = {'.mp4', '.mov', '.m4v', '.webm'}


def _random_name(ext):
    return f'{uuid.uuid4().hex}{ext}'


def check_size(uploaded, max_mb, label):
    if uploaded.size > max_mb * 1024 * 1024:
        raise ValidationError(f'{label} must be {max_mb} MB or smaller.')


def _open(source):
    try:
        source.seek(0)
        img = Image.open(source)
        img.load()  # decode the first frame now so broken files fail here
        return img
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError):
        raise ValidationError('That file is not a valid image.')


def _load_image(source):
    return ImageOps.exif_transpose(_open(source))


def _to_webp(img, quality):
    has_alpha = img.mode in ('RGBA', 'LA', 'P') or 'transparency' in img.info
    img = img.convert('RGBA' if has_alpha else 'RGB')
    buf = BytesIO()
    img.save(buf, 'WEBP', quality=quality, method=6)
    return buf.getvalue()


def _shrink(img, max_side):
    img = img.copy()
    img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    return img


def _animated_webp(img, transform):
    """Apply `transform` to every frame and save an animated WebP.

    Too many frames are thinned out (their durations are merged), so the
    animation keeps its total length.
    """
    total = getattr(img, 'n_frames', 1)
    if total > settings.ANIMATION_MAX_SOURCE_FRAMES:
        raise ValidationError('That animation is too long. Try a shorter one.')
    step = -(-total // settings.ANIMATION_MAX_FRAMES)  # ceil division

    frames, durations = [], []
    try:
        for i, frame in enumerate(ImageSequence.Iterator(img)):
            duration = frame.info.get('duration', 100)
            if duration <= 10:  # browsers treat tiny GIF delays as 100 ms
                duration = 100
            if i % step == 0:
                frames.append(transform(frame.convert('RGBA')))
                durations.append(duration)
            else:
                durations[-1] += duration
    except (OSError, SyntaxError):
        raise ValidationError('That file is not a valid image.')

    buf = BytesIO()
    frames[0].save(
        buf, 'WEBP', save_all=True, append_images=frames[1:],
        duration=durations, loop=0, quality=settings.IMAGE_QUALITY, method=4,
    )
    return ContentFile(buf.getvalue(), name=_random_name('.webp'))


def _is_animation(img):
    return img.format in ANIMATED_FORMATS and getattr(img, 'is_animated', False)


def _render(source, still, animated_transform=None, quality=None):
    """Still images -> `still(img)` as WebP. If `animated_transform` is given and the
    upload is an animation (GIF, animated WebP/PNG), it stays animated."""
    img = _open(source)
    if animated_transform is not None and _is_animation(img):
        return _animated_webp(img, animated_transform)
    img.seek(0)  # anything else: only the main picture counts
    img = ImageOps.exif_transpose(img)
    quality = quality or settings.IMAGE_QUALITY
    return ContentFile(_to_webp(still(img), quality), name=_random_name('.webp'))


def compress_image(source, max_side=None, animated_max_side=None):
    """Resize so the longest side is max_side and re-encode as WebP.
    Pass animated_max_side to let animations stay animated (at that size)."""
    max_side = max_side or settings.IMAGE_MAX_SIDE
    anim = (lambda f: _shrink(f, animated_max_side)) if animated_max_side else None
    return _render(source, lambda img: _shrink(img, max_side), anim)


def fit_image(source, width, height, animated_size=None):
    """Center-crop to an exact width x height and re-encode as WebP (used for banners).
    Pass animated_size=(w, h) to let animations stay animated (at that size)."""
    fit = lambda w, h: (lambda img: ImageOps.fit(img, (w, h), Image.Resampling.LANCZOS))
    anim = fit(*animated_size) if animated_size else None
    return _render(source, fit(width, height), anim)


def make_thumbnail(source, size=None, animated=False):
    """Square, center-cropped WebP. Used for grid thumbnails and avatars.
    Pass animated=True to let animations stay animated."""
    size = size or settings.THUMB_SIZE

    def thumb(img):
        return ImageOps.fit(img, (size, size), Image.Resampling.LANCZOS)

    return _render(source, thumb, thumb if animated else None, quality=75)


# ---------- Mouse cursors (still or animated) ----------
# An animated cursor is stored as ONE png: its frames stacked on top of each other (a "strip"),
# plus a list of steps [[frame, milliseconds], ...] kept on the profile. static/js/cursor_anim.js
# cuts the strip up again in the browser and swaps the cursor picture on a timer, because browsers
# cannot play .ani files (or animated pictures) as a cursor themselves.
MAX_CURSOR_FRAMES = 40     # different pictures in one animation
MAX_CURSOR_STEPS = 300     # pictures shown in one loop (a frame can be shown more than once)
MIN_FRAME_MS, MAX_FRAME_MS = 20, 10_000
MAX_ICON_SIDE = 256        # an icon or cursor inside a .ani file is at most 256 x 256


def _clamp_ms(ms):
    return max(MIN_FRAME_MS, min(int(ms), MAX_FRAME_MS))


def _too_many_frames():
    return ValidationError(
        f'That animation has too many frames. Use at most {MAX_CURSOR_FRAMES} different pictures.')


def _bad_ani(why='That is not a valid .ani file.'):
    return ValidationError(why)


def _icon_to_image(raw):
    """One frame of a .ani file is a whole .cur (or .ico) file. Read it with Pillow."""
    # a .cur file is an .ico file with another type number; Pillow only reads the .ico one
    if len(raw) < 22 or raw[:2] != b'\0\0' or raw[2:4] not in (b'\1\0', b'\2\0'):
        raise _bad_ani('A picture inside that .ani file is damaged.')
    raw = raw[:2] + b'\1\0' + raw[4:]

    # Do not trust the sizes in the file: look before Pillow allocates anything for them.
    count = struct.unpack_from('<H', raw, 4)[0]
    if not 1 <= count <= 16 or len(raw) < 6 + 16 * count:
        raise _bad_ani('A picture inside that .ani file is damaged.')
    for i in range(count):
        size, offset = struct.unpack_from('<II', raw, 6 + 16 * i + 8)
        if offset + size > len(raw) or size < 8:
            raise _bad_ani('A picture inside that .ani file is damaged.')
        if raw[offset:offset + 8] == b'\x89PNG\r\n\x1a\n':
            if size < 24:
                raise _bad_ani('A picture inside that .ani file is damaged.')
            width, height = struct.unpack_from('>II', raw, offset + 16)
        else:
            if size < 16:
                raise _bad_ani('A picture inside that .ani file is damaged.')
            width, height = struct.unpack_from('<ii', raw, offset + 4)
            height = abs(height) // 2          # a .ico bitmap holds the picture and its mask
            width = abs(width)
        if not (0 < width <= MAX_ICON_SIDE and 0 < height <= MAX_ICON_SIDE):
            raise _bad_ani('A picture inside that .ani file is too big.')

    try:
        img = Image.open(BytesIO(raw))
        img.load()
        return img.convert('RGBA')
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, struct.error, EOFError):
        raise _bad_ani('A picture inside that .ani file is damaged.')


def _read_ani(data):
    """Windows animated cursor (.ani) -> ([frame images], [[frame index, milliseconds], ...]).

    The file is a RIFF container: an 'anih' header, an optional 'rate' list (how long each step
    lasts, in 1/60 s), an optional 'seq ' list (which frame each step shows) and a LIST 'fram'
    holding the frames, each one a complete .cur file. Every length is checked against the file.
    """
    if len(data) < 12 or data[:4] != b'RIFF' or data[8:12] != b'ACON':
        raise _bad_ani()
    end = min(len(data), 8 + struct.unpack_from('<I', data, 4)[0])

    header, rates, order, icons = None, [], [], []
    pos = 12
    while pos + 8 <= end:
        chunk_id = data[pos:pos + 4]
        size = struct.unpack_from('<I', data, pos + 4)[0]
        body = pos + 8
        if body + size > len(data):
            raise _bad_ani()
        chunk = data[body:body + size]

        if chunk_id == b'anih':
            if size < 36:
                raise _bad_ani()
            header = struct.unpack_from('<9I', chunk, 0)
        elif chunk_id == b'rate':
            rates = list(struct.unpack_from(f'<{size // 4}I', chunk, 0))
        elif chunk_id == b'seq ':
            order = list(struct.unpack_from(f'<{size // 4}I', chunk, 0))
        elif chunk_id == b'LIST' and chunk[:4] == b'fram':
            inner = 4
            while inner + 8 <= size:
                inner_id = chunk[inner:inner + 4]
                inner_size = struct.unpack_from('<I', chunk, inner + 4)[0]
                if inner + 8 + inner_size > size:
                    raise _bad_ani()
                if inner_id == b'icon':
                    icons.append(chunk[inner + 8:inner + 8 + inner_size])
                    if len(icons) > MAX_CURSOR_FRAMES:
                        raise _too_many_frames()
                inner += 8 + inner_size + (inner_size & 1)
        pos = body + size + (size & 1)

    if header is None or not icons:
        raise _bad_ani()
    _, _, step_count, _, _, _, _, default_rate, flags = header
    if not flags & 1:
        raise _bad_ani('That .ani file stores raw bitmaps, which are not supported.')

    steps = order[:step_count] if flags & 2 and order else list(range(len(icons)))
    if not steps:
        raise _bad_ani()
    if len(steps) > MAX_CURSOR_STEPS:
        raise ValidationError(f'That animation is too long. Use at most {MAX_CURSOR_STEPS} steps.')
    if any(i >= len(icons) for i in steps):
        raise _bad_ani()

    jiffies = [(rates[n] if n < len(rates) else default_rate) or 6 for n in range(len(steps))]
    # only the frames that are shown, numbered in the order they first appear
    used = list(dict.fromkeys(steps))
    renumber = {old: new for new, old in enumerate(used)}
    frames = [_icon_to_image(icons[old]) for old in used]
    return frames, [[renumber[i], _clamp_ms(round(j * 1000 / 60))] for i, j in zip(steps, jiffies)]


def _cursor_frames(source):
    """Any cursor upload -> ([RGBA frames], steps). `steps` is [] unless it really is an animation."""
    source.seek(0)
    head = source.read(12)
    source.seek(0)
    if head[:4] == b'RIFF' and head[8:12] == b'ACON':
        return _read_ani(source.read())

    img = _open(source)
    if _is_animation(img):                         # animated GIF, APNG or WebP
        if img.n_frames > MAX_CURSOR_FRAMES:
            raise _too_many_frames()
        frames, steps = [], []
        try:
            for i, frame in enumerate(ImageSequence.Iterator(img)):
                ms = frame.info.get('duration', 100)
                if img.format == 'GIF' and ms <= 10:   # browsers treat tiny GIF delays as 100 ms
                    ms = 100
                frames.append(frame.convert('RGBA'))
                steps.append([i, _clamp_ms(ms)])
        except (OSError, SyntaxError):
            raise ValidationError('That file is not a valid image.')
        return frames, steps

    img.seek(0)                                    # a still picture (or an iPhone photo): the main picture only
    return [ImageOps.exif_transpose(img).convert('RGBA')], []


def make_cursor(source, max_side=None):
    """A mouse cursor from a picture, an animated GIF/PNG/WebP, or a Windows .ani file.

    Returns (png ContentFile, steps).

    1. See-through borders are trimmed away, so the visible art starts at the top-left corner
       (that corner is the cursor's "click point") and a small arrow on a big canvas is not
       shrunk to a speck. An animation is trimmed as a whole, so every frame stays lined up.
    2. The picture is made small enough to be a cursor (never enlarged), and saved as PNG
       so it keeps its transparency. Browsers ignore cursor images over 128px; 32px is the
       classic size that works everywhere.
    3. For an animation the png is a strip of all the frames, one above the other, and
       `steps` says which frame to show and for how many milliseconds. For a still cursor
       `steps` is [] and the png is the cursor itself.
    """
    max_side = max_side or getattr(settings, 'CURSOR_MAX_SIDE', 32)
    frames, steps = _cursor_frames(source)

    box = None
    for frame in frames:
        found = frame.getchannel('A').point(lambda a: 255 if a > 8 else 0).getbbox()
        if found:
            box = found if box is None else (
                min(box[0], found[0]), min(box[1], found[1]), max(box[2], found[2]), max(box[3], found[3]))
    if box is None:
        raise ValidationError('That picture is completely see-through. Pick one with something visible in it.')

    box_w, box_h = box[2] - box[0], box[3] - box[1]
    scale = min(1, max_side / max(box_w, box_h))                  # only ever shrinks
    width, height = max(1, round(box_w * scale)), max(1, round(box_h * scale))

    tiles = []
    for frame in frames:
        tile = frame.crop(box)
        if (width, height) != (box_w, box_h):
            tile = tile.resize((width, height), Image.Resampling.LANCZOS)
        tiles.append(tile)

    strip = Image.new('RGBA', (width, height * len(tiles)))
    for n, tile in enumerate(tiles):
        strip.paste(tile, (0, n * height))

    buf = BytesIO()
    strip.save(buf, 'PNG', optimize=True)
    return ContentFile(buf.getvalue(), name=_random_name('.png')), (steps if len(tiles) > 1 else [])


def ffmpeg_available():
    return shutil.which('ffmpeg') is not None


def _run(cmd, label='video'):
    try:
        subprocess.run(cmd, check=True, capture_output=True,
                       timeout=settings.VIDEO_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        raise ValidationError(f'The {label} took too long to process. Try a shorter one.')
    except subprocess.CalledProcessError:
        raise ValidationError(f'That file is not a valid {label}.')


def compress_video(uploaded):
    """Returns (video ContentFile, thumbnail ContentFile or None)."""
    ext = Path(uploaded.name).suffix.lower()

    if not ffmpeg_available():
        logger.warning('ffmpeg not found: storing video without compression.')
        uploaded.seek(0)
        return ContentFile(uploaded.read(), name=_random_name(ext)), None

    side = settings.VIDEO_MAX_SIDE
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        src, out, frame = tmp / f'input{ext}', tmp / 'out.mp4', tmp / 'frame.jpg'
        with open(src, 'wb') as fh:
            for chunk in uploaded.chunks():
                fh.write(chunk)

        _run([
            'ffmpeg', '-y', '-i', str(src),
            '-vf', f"scale='min({side},iw)':'min({side},ih)':"
                   "force_original_aspect_ratio=decrease:force_divisible_by=2",
            '-c:v', 'libx264', '-crf', str(settings.VIDEO_CRF),
            '-preset', 'veryfast', '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-b:a', '96k',
            '-map_metadata', '-1', '-movflags', '+faststart',
            str(out),
        ])

        thumb = None
        try:
            _run(['ffmpeg', '-y', '-i', str(out), '-vf', 'thumbnail',
                  '-frames:v', '1', str(frame)])
            with open(frame, 'rb') as fh:
                thumb = make_thumbnail(fh)
        except (ValidationError, OSError):
            thumb = None  # a missing thumbnail is not fatal

        return ContentFile(out.read_bytes(), name=_random_name('.mp4')), thumb





AUDIO_EXTENSIONS = {'.mp3', '.m4a', '.aac', '.ogg', '.opus', '.wav', '.flac'}


def compress_audio(uploaded):
    """Re-encode to AAC (.m4a). Without ffmpeg the file is stored as is."""
    ext = Path(uploaded.name).suffix.lower()

    if not ffmpeg_available():
        logger.warning('ffmpeg not found: storing audio without compression.')
        uploaded.seek(0)
        return ContentFile(uploaded.read(), name=_random_name(ext))

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        src, out = tmp / f'input{ext}', tmp / 'out.m4a'
        with open(src, 'wb') as fh:
            for chunk in uploaded.chunks():
                fh.write(chunk)

        _run([
            'ffmpeg', '-y', '-protocol_whitelist', 'file',  # never let a crafted file fetch URLs
            '-i', str(src),
            '-vn', '-c:a', 'aac', '-b:a', settings.AUDIO_BITRATE,
            '-map_metadata', '-1', '-movflags', '+faststart',
            str(out),
        ], label='audio file')

        return ContentFile(out.read_bytes(), name=_random_name('.m4a'))

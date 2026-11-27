import json
import os
import shutil
import struct
import tempfile
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from config import media_tools as mt

User = get_user_model()
MEDIA = tempfile.mkdtemp(prefix='space-test-cursors-')
FORM = {'display_name': '', 'bio': '', 'avatar_shape': 'circle', 'font': 'default',
        'background_color': '#f3f4f6', 'card_color': '#ffffff'}


# ---- building test files ----

def cur_file(color, size=32, box=None):
    """A real .cur file: Pillow writes an .ico, and a .cur is the same with another type number."""
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    x0, y0, x1, y1 = box or (2, 2, size - 2, size - 2)
    for x in range(x0, x1):
        for y in range(y0, y1):
            img.putpixel((x, y), color)
    buf = BytesIO()
    img.save(buf, 'ICO', sizes=[(size, size)])
    data = bytearray(buf.getvalue())
    data[2:4] = b'\x02\x00'
    return bytes(data)


def chunk(chunk_id, body):
    return chunk_id + struct.pack('<I', len(body)) + body + (b'\0' if len(body) & 1 else b'')


def ani_file(icons, rates=None, seq=None, default_rate=6, flags=None):
    """A Windows animated cursor: RIFF 'ACON' with an 'anih' header, 'rate', 'seq ' and the frames."""
    steps = len(seq) if seq else len(icons)
    flags = (1 | (2 if seq else 0)) if flags is None else flags
    body = b'ACON' + chunk(b'anih', struct.pack('<9I', 36, len(icons), steps, 0, 0, 0, 1, default_rate, flags))
    if rates:
        body += chunk(b'rate', struct.pack(f'<{len(rates)}I', *rates))
    if seq:
        body += chunk(b'seq ', struct.pack(f'<{len(seq)}I', *seq))
    body += chunk(b'LIST', b'fram' + b''.join(chunk(b'icon', icon) for icon in icons))
    return b'RIFF' + struct.pack('<I', len(body)) + body


def upload(data, name):
    return SimpleUploadedFile(name, data, content_type='application/octet-stream')


def png_bytes(size=(400, 300)):
    img = Image.new('RGBA', size, (0, 0, 0, 0))
    for x in range(150, 250):
        for y in range(100, 200):
            img.putpixel((x, y), (255, 0, 0, 255))
    buf = BytesIO()
    img.save(buf, 'PNG')
    return buf.getvalue()


def gif_bytes():
    frames = [Image.new('RGBA', (40, 40), c) for c in ((255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255))]
    buf = BytesIO()
    frames[0].save(buf, 'GIF', save_all=True, append_images=frames[1:], duration=[50, 100, 5], loop=0)
    return buf.getvalue()


# ---- the conversion itself ----

class MakeCursorTests(TestCase):
    def convert(self, data, name='x'):
        cursor, steps = mt.make_cursor(upload(data, name))
        return Image.open(BytesIO(cursor.read())), steps

    def test_still_picture_is_trimmed_and_shrunk_and_has_no_steps(self):
        img, steps = self.convert(png_bytes(), 'a.png')
        self.assertEqual(img.size, (32, 32))
        self.assertEqual(steps, [])

    def test_ani_becomes_a_strip_with_steps(self):
        icons = [cur_file((255, 0, 0, 255)), cur_file((0, 255, 0, 255))]
        img, steps = self.convert(ani_file(icons, rates=[6, 12, 3], seq=[0, 1, 0]), 'a.ani')
        self.assertEqual(steps, [[0, 100], [1, 200], [0, 50]])       # 6 jiffies = 100 ms
        self.assertEqual(img.size, (28, 56))                          # two frames of 28 x 28, one above the other
        self.assertEqual(img.getpixel((5, 5))[:3], (255, 0, 0))
        self.assertEqual(img.getpixel((5, 33))[:3], (0, 255, 0))

    def test_ani_without_rate_uses_the_default_rate(self):
        icons = [cur_file((255, 0, 0, 255)), cur_file((0, 255, 0, 255))]
        _, steps = self.convert(ani_file(icons, default_rate=10), 'a.ani')
        self.assertEqual(steps, [[0, 167], [1, 167]])

    def test_ani_is_found_by_content_not_by_name(self):
        icons = [cur_file((255, 0, 0, 255)), cur_file((0, 255, 0, 255))]
        _, steps = self.convert(ani_file(icons), 'cursor.png')
        self.assertEqual(len(steps), 2)

    def test_frames_that_are_never_shown_are_left_out(self):
        icons = [cur_file((255, 0, 0, 255)), cur_file((0, 255, 0, 255)), cur_file((0, 0, 255, 255))]
        img, steps = self.convert(ani_file(icons, seq=[2, 2, 0]), 'a.ani')
        self.assertEqual(steps, [[0, 100], [0, 100], [1, 100]])
        self.assertEqual(img.size[1], 56)

    def test_frames_stay_lined_up_and_big_ones_shrink(self):
        icons = [cur_file((255, 0, 0, 255), size=64, box=(0, 0, 20, 20)),
                 cur_file((0, 255, 0, 255), size=64, box=(40, 40, 60, 60))]
        img, _ = self.convert(ani_file(icons), 'a.ani')
        self.assertEqual(img.size, (32, 64))

    def test_animated_gif_keeps_its_timing(self):
        img, steps = self.convert(gif_bytes(), 'a.gif')
        self.assertEqual([s[0] for s in steps], [0, 1, 2])
        self.assertEqual([s[1] for s in steps], [50, 100, 100])       # tiny GIF delays count as 100 ms
        self.assertEqual(img.size, (32, 96))

    def test_bad_files_are_turned_away(self):
        good = ani_file([cur_file((255, 0, 0, 255))])
        liar = bytearray(good)
        liar[16:20] = struct.pack('<I', 0xFFFFFFF0)                   # a chunk that claims to be huge
        cases = {
            'not an image': b'hello world',
            'cut off': good[:len(good) // 2],
            'lying length': bytes(liar),
            'raw bitmaps': ani_file([cur_file((255, 0, 0, 255))], flags=0),
            'frame out of range': ani_file([cur_file((255, 0, 0, 255))], seq=[5]),
            'too many frames': ani_file([cur_file((255, 0, 0, 255))] * (mt.MAX_CURSOR_FRAMES + 1)),
            'broken frame': ani_file([b'\x00\x00\x02\x00\x01\x00' + b'x' * 40]),
            'nothing visible': ani_file([cur_file((0, 0, 0, 0)), cur_file((0, 0, 0, 0))]),
        }
        for name, data in cases.items():
            with self.subTest(name), self.assertRaises(ValidationError):
                mt.make_cursor(upload(data, 'bad.ani'))


# ---- through the profile editor ----

@override_settings(MEDIA_ROOT=MEDIA)
class CursorUploadTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.ann = User.objects.create_user('ann', password='pw')
        self.client.force_login(self.ann)
        self.icons = [cur_file((255, 0, 0, 255)), cur_file((0, 255, 0, 255))]

    def save_cursor(self, data, name, **extra):
        return self.client.post(reverse('profile_edit'), {**FORM, 'cursor': upload(data, name), **extra})

    def profile(self):
        self.ann.profile.refresh_from_db()
        return self.ann.profile

    def test_ani_upload_is_saved_as_a_strip_with_steps(self):
        r = self.save_cursor(ani_file(self.icons, rates=[6, 12]), 'wiggle.ani')
        self.assertRedirects(r, reverse('profile', args=['ann']))
        profile = self.profile()
        self.assertTrue(profile.cursor_animated)
        self.assertEqual(profile.cursor_steps, [[0, 100], [1, 200]])
        self.assertEqual(profile.cursor_frames, 2)
        self.assertTrue(profile.cursor.name.endswith('.png'))
        self.assertTrue(os.path.exists(profile.cursor.path))

    def test_bad_ani_shows_an_error_and_changes_nothing(self):
        r = self.save_cursor(b'RIFF....ACON nonsense', 'bad.ani')
        self.assertEqual(r.status_code, 200)
        profile = self.profile()
        self.assertFalse(profile.cursor)
        self.assertEqual(profile.cursor_steps, [])

    def test_a_still_cursor_after_an_animated_one_stops_the_animation(self):
        self.save_cursor(ani_file(self.icons), 'a.ani')
        old = self.profile().cursor.path
        self.save_cursor(png_bytes(), 'still.png')
        profile = self.profile()
        self.assertTrue(profile.cursor)
        self.assertEqual(profile.cursor_steps, [])
        self.assertFalse(os.path.exists(old))                         # the replaced strip is deleted

    def test_saving_without_a_new_file_keeps_the_animation(self):
        self.save_cursor(ani_file(self.icons), 'a.ani')
        self.client.post(reverse('profile_edit'), {**FORM, 'bio': 'hello'})
        profile = self.profile()
        self.assertEqual(profile.bio, 'hello')
        self.assertTrue(profile.cursor_animated)

    def test_removing_the_cursor_clears_the_steps_and_the_file(self):
        self.save_cursor(ani_file(self.icons), 'a.ani')
        old = self.profile().cursor.path
        self.client.post(reverse('profile_edit'), {**FORM, 'remove_cursor': 'on'})
        profile = self.profile()
        self.assertFalse(profile.cursor)
        self.assertEqual(profile.cursor_steps, [])
        self.assertFalse(os.path.exists(old))

    def test_profile_page_hands_the_frames_to_the_browser(self):
        self.save_cursor(ani_file(self.icons, rates=[6, 12]), 'a.ani')
        page = self.client.get(reverse('profile', args=['ann']))
        self.assertContains(page, 'has-cursor')
        self.assertContains(page, 'data-cursor-src="')
        self.assertContains(page, 'data-cursor-frames="2"')
        self.assertContains(page, 'data-cursor-steps="[[0,100],[1,200]]"')
        self.assertNotContains(page, '--profile-cursor:')             # the script sets it, frame by frame

    def test_profile_page_with_a_still_cursor_sets_it_directly(self):
        self.save_cursor(png_bytes(), 'still.png')
        page = self.client.get(reverse('profile', args=['ann']))
        self.assertContains(page, '--profile-cursor: url(')
        self.assertNotContains(page, 'data-cursor-src')

    def test_steps_json_is_valid(self):
        self.save_cursor(ani_file(self.icons, rates=[6, 12]), 'a.ani')
        self.assertEqual(json.loads(self.profile().cursor_steps_json), [[0, 100], [1, 200]])

    def test_edit_page_offers_ani_files(self):
        page = self.client.get(reverse('profile_edit'))
        self.assertContains(page, '.ani,image/*')

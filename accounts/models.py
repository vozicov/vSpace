import json
import secrets

from django.conf import settings
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.db.models import F, Q

BIO_MAX_LENGTH = 150
DEFAULT_PAGE_BG = '#f3ece1'
DEFAULT_CARD_BG = '#faf6f0'

AVATAR_SHAPES = [
    ('circle', 'Circle'),
    ('squircle', 'Squircle'),
    ('square', 'Square'),
    ('triangle', 'Triangle'),
    ('diamond', 'Diamond'),
    ('pentagon', 'Pentagon'),
    ('hexagon', 'Hexagon'),
    ('octagon', 'Octagon'),
    ('star', 'Star'),
    ('heart', 'Heart'),
    ('flower', 'Flower'),
]

FONTS = [
    ('default', 'Default'),
    ('inter', 'Inter'),
    ('playfair', 'Playfair Display'),
    ('spacemono', 'Space Mono'),
    ('pacifico', 'Pacifico'),
    ('lobster', 'Lobster'),
    ('dancing', 'Dancing Script'),
    ('caveat', 'Caveat'),
    ('marker', 'Permanent Marker'),
    ('bebas', 'Bebas Neue'),
    ('pixel', 'Press Start 2P'),
]

THEMES = [
    ('light', 'Light'),
    ('dark', 'Dark'),
    ('system', 'Same as my device'),
]

hex_color = RegexValidator(r'^#[0-9a-fA-F]{6}\Z', 'Enter a color like #1a2b3c.')


# No 0/O/1/I, so a code read out loud or copied by hand is hard to get wrong
CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'


def make_code():
    """A random code like K7QM-2XPD (about a trillion possibilities, so it cannot be guessed)."""
    return '-'.join(''.join(secrets.choice(CODE_ALPHABET) for _ in range(4)) for _ in range(2))


class Profile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile'
    )
    display_name = models.CharField(max_length=50, blank=True)
    bio = models.CharField(max_length=BIO_MAX_LENGTH, blank=True)
    avatar = models.ImageField(upload_to='avatars/', blank=True)
    avatar_shape = models.CharField(max_length=20, choices=AVATAR_SHAPES, default='circle')

    # Look of the profile page
    banner = models.ImageField(upload_to='banners/', blank=True)
    background_color = models.CharField(
        max_length=7, default=DEFAULT_PAGE_BG, validators=[hex_color]
    )
    background_image = models.ImageField(upload_to='backgrounds/', blank=True)
    card_color = models.CharField(
        max_length=7, default=DEFAULT_CARD_BG, validators=[hex_color]
    )
    font = models.CharField(max_length=20, choices=FONTS, default='default')
    # A custom mouse cursor, shown to people looking at this profile (already shrunk to cursor size)
    cursor = models.ImageField(upload_to='cursors/', blank=True)
    # For an animated cursor: which frame to show and for how many ms, [[frame, ms], ...].
    # Then `cursor` is a strip of all the frames, one above the other. [] means a still cursor.
    cursor_steps = models.JSONField(default=list, blank=True)
    # Light or dark look of the site around you (sidebars, home, explore, tweets...). It never
    # touches how a profile page looks: that is always the owner's own styling.
    theme = models.CharField(max_length=6, choices=THEMES, default='light')
    # Privacy: what people who are NOT signed in may see. Signed-in members always see everything.
    # Off by default, because until now nothing was visible without an account.
    is_public = models.BooleanField(
        default=False, help_text='People who are not signed in can open this profile.')
    public_posts = models.BooleanField(
        default=True, help_text='...and see its posts (also pins and collections).')
    public_tweets = models.BooleanField(
        default=True, help_text='...and see its tweets and comments.')
    # The invite this person signed up with (empty for accounts made in the admin)
    referral_code = models.ForeignKey(
        'ReferralCode', null=True, blank=True, on_delete=models.SET_NULL, related_name='profiles'
    )

    @property
    def name(self):
        return self.display_name or self.user.username

    @property
    def cursor_animated(self):
        return bool(self.cursor and self.cursor_steps)

    @property
    def cursor_frames(self):
        """How many pictures are stacked in the cursor strip."""
        return max((step[0] for step in self.cursor_steps), default=-1) + 1

    @property
    def cursor_steps_json(self):
        return json.dumps(self.cursor_steps, separators=(',', ':'))

    @staticmethod
    def _text_on(hex_color):
        """Light text on dark colors, dark text on light colors."""
        h = hex_color.lstrip('#')
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        return '#faf6f0' if (0.299 * r + 0.587 * g + 0.114 * b) < 140 else '#080603'

    @property
    def card_text_color(self):
        return self._text_on(self.card_color)

    @property
    def background_text_color(self):
        """Readable text color on the profile's page background (used by posts on the home feed)."""
        return self._text_on(self.background_color)

    def __str__(self):
        return f'Profile of {self.user}'


class Follow(models.Model):
    follower = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='following_links'
    )
    following = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='follower_links'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['follower', 'following'], name='unique_follow'),
            models.CheckConstraint(condition=~Q(follower=F('following')), name='no_self_follow'),
        ]

    def __str__(self):
        return f'{self.follower} -> {self.following}'


class ReferralCode(models.Model):
    """An invite. Signing up needs one. Made in the admin; leave `code` empty to get a random one."""
    code = models.CharField(
        max_length=32, unique=True, blank=True,
        help_text='Leave empty to make a random code. Letters are saved in capitals.',
    )
    note = models.CharField(max_length=100, blank=True, help_text='Who it is for. Only you see this.')
    max_uses = models.PositiveIntegerField(
        default=1, validators=[MinValueValidator(1)],
        help_text='How many people can sign up with it. 1 = a personal invite.',
    )
    uses = models.PositiveIntegerField(default=0, editable=False)
    is_active = models.BooleanField(default=True, help_text='Untick to switch the code off.')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def save(self, *args, **kwargs):
        self.code = (self.code or '').strip().upper()
        while not self.code:
            candidate = make_code()
            if not ReferralCode.objects.filter(code=candidate).exists():
                self.code = candidate
        super().save(*args, **kwargs)

    @property
    def is_usable(self):
        return self.is_active and self.uses < self.max_uses

    def __str__(self):
        return f'{self.code} ({self.uses}/{self.max_uses})'

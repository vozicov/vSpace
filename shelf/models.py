from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

MAX_ROTATION = 15        # degrees, either direction (column kept from the old shelf)
PIN_SLOTS = 4            # posts shown next to the profile picture
# Slots 1-2 sit left of the picture, 3-4 right. Each gets its own fixed tilt.
PIN_ROTATIONS = {1: -8, 2: 5, 3: -5, 4: 9}


def http_url(value):
    """Not used any more (shelf links are gone), but migration 0001 still points at it."""
    if not value.lower().startswith(('http://', 'https://')):
        raise ValidationError('Only http and https links are allowed.')


def entry_preview_url(entry):
    """Picture for a post: its image, else its video thumbnail, else its song cover, else ''."""
    return entry.preview_url


class ShelfItem(models.Model):
    """One thing on a user's shelf. The shelf only holds posts and collections.

    - kind='post':   points at a feed.Entry (a post, never a tweet).
    - kind='folder': a named collection of posts (shown as "Collection").
    Posts with `parent` set live inside that collection; everything else is on the
    top level. Collections cannot nest, and a post can be on your shelf only once.
    """

    class Kind(models.TextChoices):
        POST = 'post', 'Post'
        FOLDER = 'folder', 'Collection'

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='shelf_items'
    )
    parent = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.CASCADE, related_name='children'
    )
    kind = models.CharField(max_length=6, choices=Kind.choices)
    title = models.CharField(max_length=60, blank=True)   # collection name
    entry = models.ForeignKey(
        'feed.Entry', null=True, blank=True, on_delete=models.CASCADE, related_name='shelf_items'
    )
    rotation = models.SmallIntegerField(
        default=0,
        validators=[MinValueValidator(-MAX_ROTATION), MaxValueValidator(MAX_ROTATION)],
    )
    position = models.PositiveIntegerField(default=0)   # order among siblings

    class Meta:
        ordering = ['position', 'id']
        constraints = [
            models.UniqueConstraint(
                fields=['owner', 'entry'], condition=Q(entry__isnull=False),
                name='unique_shelf_entry'),
        ]

    @property
    def label(self):
        if self.kind == self.Kind.POST and self.entry_id:
            return self.entry.title or self.entry.body
        return self.title

    @property
    def preview_url(self):
        if self.kind == self.Kind.POST and self.entry_id:
            return entry_preview_url(self.entry)
        return ''

    def clean(self):
        if self.kind == self.Kind.POST:
            if not self.entry_id or self.entry.kind != 'post':
                raise ValidationError('A shelf post must point at a post.')
        elif self.kind == self.Kind.FOLDER:
            if self.entry_id:
                raise ValidationError('A collection cannot point at a post.')
            if not self.title:
                raise ValidationError('Give the collection a name.')
        if self.parent_id:
            if self.kind == self.Kind.FOLDER:
                raise ValidationError('Collections cannot go inside collections.')
            if self.parent.kind != self.Kind.FOLDER or self.parent.owner_id != self.owner_id:
                raise ValidationError('Pick one of your own collections.')

    def __str__(self):
        return f'{self.get_kind_display()} of {self.owner}'


class InterestPin(models.Model):
    """A post pinned next to the profile picture to show an interest (max PIN_SLOTS)."""
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='interest_pins'
    )
    entry = models.ForeignKey('feed.Entry', on_delete=models.CASCADE, related_name='pins')
    slot = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(PIN_SLOTS)])
    rotation = models.SmallIntegerField(default=0)

    class Meta:
        ordering = ['slot']
        constraints = [
            models.UniqueConstraint(fields=['owner', 'slot'], name='unique_pin_slot'),
            models.UniqueConstraint(fields=['owner', 'entry'], name='unique_pin_entry'),
            models.CheckConstraint(
                condition=Q(slot__gte=1) & Q(slot__lte=PIN_SLOTS), name='pin_slot_range'),
        ]

    @property
    def preview_url(self):
        return entry_preview_url(self.entry)

    def __str__(self):
        return f'{self.owner} pin {self.slot}'

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.urls import reverse

TWEET_MAX_LENGTH = 280

# Posts that have some picture to show: an image, a video thumbnail, or the song's cover.
# Keep in step with Entry.preview_url below.
HAS_PICTURE = Q(media_type='image') | ~Q(thumbnail='') | ~Q(music_art='')


class Entry(models.Model):
    class Kind(models.TextChoices):
        POST = 'post', 'Post'
        TWEET = 'tweet', 'Tweet'

    class MediaType(models.TextChoices):
        IMAGE = 'image', 'Image'
        VIDEO = 'video', 'Video'

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='entries'
    )
    kind = models.CharField(max_length=5, choices=Kind.choices, default=Kind.TWEET)
    title = models.CharField(max_length=150, blank=True)  # posts only
    body = models.TextField()
    media = models.FileField(upload_to='entries/%Y/%m/', blank=True, max_length=255)
    media_type = models.CharField(max_length=5, choices=MediaType.choices, blank=True)
    thumbnail = models.ImageField(upload_to='thumbs/%Y/%m/', blank=True, max_length=255)
    # A song attached to a post, found by name through Apple's iTunes Search (see feed/music.py)
    music_id = models.CharField(max_length=20, blank=True)
    music_title = models.CharField(max_length=200, blank=True)
    music_artist = models.CharField(max_length=200, blank=True)
    music_art = models.URLField(max_length=500, blank=True)
    music_preview = models.URLField(max_length=500, blank=True)   # 30 second clip
    music_url = models.URLField(max_length=500, blank=True)       # the song on Apple Music
    # If set, this entry is a comment on another entry (and is always a tweet).
    parent = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.CASCADE, related_name='replies'
    )
    # One-time token from the form that created this entry. Unique, so a double submit can
    # only ever create one row. Old entries keep NULL (SQLite allows many NULLs under UNIQUE).
    submit_token = models.UUIDField(null=True, blank=True, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        verbose_name_plural = 'entries'

    def clean(self):
        if self.parent_id and self.kind != self.Kind.TWEET:
            raise ValidationError('A comment is always a tweet.')
        if self.kind == self.Kind.TWEET:
            if len(self.body) > TWEET_MAX_LENGTH:
                raise ValidationError(
                    {'body': f'Tweets can be at most {TWEET_MAX_LENGTH} characters.'}
                )
            if self.title or self.media:
                raise ValidationError('Tweets cannot have a title or media.')
            if self.music_id:
                raise ValidationError('Tweets cannot have music.')

    @property
    def preview_url(self):
        """The picture that stands for this post in grids, pins and collections:
        its image, else its video thumbnail, else the cover of its song, else ''."""
        if self.media_type == self.MediaType.IMAGE and self.media:
            return self.media.url
        if self.thumbnail:
            return self.thumbnail.url
        return self.music_art

    def get_absolute_url(self):
        return reverse('entry_detail', args=[self.pk])

    def __str__(self):
        return f'{self.get_kind_display()} by {self.author} (#{self.pk})'


class Like(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='likes'
    )
    entry = models.ForeignKey(Entry, on_delete=models.CASCADE, related_name='likes')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'entry'], name='unique_like'),
        ]

    def __str__(self):
        return f'{self.user} likes #{self.entry_id}'

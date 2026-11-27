from django.conf import settings
from django.db import models
from django.db.models import Q


class Notification(models.Model):
    """Something that happened to `recipient`, caused by `actor`. Made by signals.py."""

    class Kind(models.TextChoices):
        FOLLOW = 'follow', 'Follow'
        LIKE = 'like', 'Like'
        COMMENT = 'comment', 'Comment'

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications')
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    kind = models.CharField(max_length=7, choices=Kind.choices)
    # like: the entry that was liked. comment: the new comment itself (its `parent` is what was
    # commented on). follow: empty. When the entry is deleted, the notification goes with it.
    entry = models.ForeignKey(
        'feed.Entry', null=True, blank=True, on_delete=models.CASCADE, related_name='+')
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [models.Index(fields=['recipient', 'is_read'])]
        constraints = [
            # one "X followed you" and one "X liked this" at a time, however often it is toggled
            models.UniqueConstraint(
                fields=['recipient', 'actor'], condition=Q(kind='follow'),
                name='notif_unique_follow'),
            models.UniqueConstraint(
                fields=['recipient', 'actor', 'entry'], condition=Q(kind='like'),
                name='notif_unique_like'),
            models.CheckConstraint(condition=~Q(recipient=models.F('actor')), name='notif_not_self'),
        ]

    def __str__(self):
        return f'{self.actor} {self.kind} -> {self.recipient}'

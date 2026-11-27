"""Notifications are made here, so no view has to remember to. Taking the action back (unlike,
unfollow, deleting the comment) takes the notification back too."""
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from accounts.models import Follow
from feed.models import Entry, Like

from .models import Notification

K = Notification.Kind


@receiver(post_save, sender=Follow, dispatch_uid='notif.follow')
def on_follow(sender, instance, created, **kwargs):
    if created:
        Notification.objects.get_or_create(
            recipient_id=instance.following_id, actor_id=instance.follower_id, kind=K.FOLLOW)


@receiver(post_delete, sender=Follow, dispatch_uid='notif.unfollow')
def on_unfollow(sender, instance, **kwargs):
    Notification.objects.filter(
        recipient_id=instance.following_id, actor_id=instance.follower_id, kind=K.FOLLOW).delete()


@receiver(post_save, sender=Like, dispatch_uid='notif.like')
def on_like(sender, instance, created, **kwargs):
    owner_id = instance.entry.author_id
    if created and owner_id != instance.user_id:
        Notification.objects.get_or_create(
            recipient_id=owner_id, actor_id=instance.user_id, kind=K.LIKE, entry_id=instance.entry_id)


@receiver(post_delete, sender=Like, dispatch_uid='notif.unlike')
def on_unlike(sender, instance, **kwargs):
    Notification.objects.filter(
        actor_id=instance.user_id, kind=K.LIKE, entry_id=instance.entry_id).delete()


@receiver(post_save, sender=Entry, dispatch_uid='notif.comment')
def on_comment(sender, instance, created, **kwargs):
    """A comment is an entry with a parent: tell the author of what it was written under."""
    if created and instance.parent_id and instance.parent.author_id != instance.author_id:
        Notification.objects.create(
            recipient_id=instance.parent.author_id, actor_id=instance.author_id,
            kind=K.COMMENT, entry=instance)

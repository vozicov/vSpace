import uuid
from pathlib import Path

from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile

from config import media_tools as mt

from . import music as music_service
from .models import TWEET_MAX_LENGTH, Entry


class OnceModelForm(forms.ModelForm):
    """Adds a hidden one-time token, so the same form can never create two entries.
    The token is made when the empty form is shown and stored on the entry when it is saved."""
    submit_token = forms.UUIDField(widget=forms.HiddenInput, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.initial['submit_token'] = uuid.uuid4()

    def save(self, commit=True):
        # edit forms have no token: the one the entry was made with must stay as it is
        if 'submit_token' in self.fields:
            self.instance.submit_token = self.cleaned_data.get('submit_token')
        return super().save(commit=commit)


class TweetForm(OnceModelForm):
    class Meta:
        model = Entry
        fields = ['body']
        widgets = {
            'body': forms.Textarea(attrs={
                'rows': 3,
                'maxlength': TWEET_MAX_LENGTH,
                'placeholder': "What's on your mind?",
                'aria-label': 'Tweet',
                'data-counter': '',
            }),
        }
        labels = {'body': ''}


class PostForm(OnceModelForm):
    # The song picked in the search box. Only its id travels: the server looks the rest up itself.
    music = forms.CharField(
        required=False, max_length=20,
        widget=forms.HiddenInput(attrs={'data-music-id': ''}),
    )

    class Meta:
        model = Entry
        fields = ['title', 'body', 'media']
        widgets = {
            'title': forms.TextInput(attrs={
                'placeholder': 'Title', 'aria-label': 'Title', 'autocomplete': 'off',
            }),
            'body': forms.Textarea(attrs={
                'rows': 8, 'placeholder': 'Write your post...', 'aria-label': 'Post text',
            }),
            'media': forms.FileInput(attrs={'accept': 'image/*,video/*'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['title'].required = True
        self._media_type = ''
        self._thumb = None
        self.music_data = None      # the song, once it has been checked with Apple

    def clean_music(self):
        track_id = (self.cleaned_data.get('music') or '').strip()
        if not track_id:
            return ''
        try:
            song = music_service.lookup(track_id)
        except music_service.MusicError as exc:
            raise ValidationError(f'{exc} Try again, or remove the song.')
        if not song:
            raise ValidationError('We could not find that song. Search for it again.')
        self.music_data = song
        return song['id']

    def clean_media(self):
        f = self.cleaned_data.get('media')
        if not isinstance(f, UploadedFile):
            return f

        ext = Path(f.name).suffix.lower()
        if ext in mt.IMAGE_EXTENSIONS:
            mt.check_size(f, settings.MAX_IMAGE_UPLOAD_MB, 'Images')
            media = mt.compress_image(f)
            self._thumb = mt.make_thumbnail(media)
            self._media_type = Entry.MediaType.IMAGE
            return media

        if ext in mt.VIDEO_EXTENSIONS:
            mt.check_size(f, settings.MAX_VIDEO_UPLOAD_MB, 'Videos')
            media, self._thumb = mt.compress_video(f)
            self._media_type = Entry.MediaType.VIDEO
            return media

        raise ValidationError('Unsupported file. Use JPG, PNG, WebP, GIF, MP4, MOV or WebM.')

    def save(self, commit=True):
        entry = super().save(commit=False)
        if self.music_data:
            song = self.music_data
            entry.music_id = song['id']
            entry.music_title = song['title']
            entry.music_artist = song['artist']
            entry.music_art = song['art']
            entry.music_preview = song['preview']
            entry.music_url = song['url']
        if self._media_type:
            entry.media_type = self._media_type
            if self._thumb:
                entry.thumbnail = self._thumb
        if commit:
            entry.save()
        return entry


class TweetEditForm(TweetForm):
    """Change the text of your own tweet or comment."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields.pop('submit_token', None)


class PostEditForm(PostForm):
    """Change your own post: title, text, picture or video, and song.

    - A new file replaces the old one (the old files are deleted from disk).
    - "remove_media" takes the picture or video off without adding another.
    - The song is kept when its id comes back unchanged (Apple is not asked again),
      replaced when another id comes back, and removed when the id is empty.
    """
    remove_media = forms.BooleanField(required=False, label='Remove the current picture or video')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields.pop('submit_token', None)
        entry = self.instance
        # remember the files, so replaced or removed ones can be deleted after saving
        self._old_files = {'media': entry.media.name, 'thumbnail': entry.thumbnail.name}
        if entry.music_id:
            self.music_data = self._saved_song()
            self.initial['music'] = entry.music_id

    def _saved_song(self):
        entry = self.instance
        return {
            'id': entry.music_id, 'title': entry.music_title, 'artist': entry.music_artist,
            'art': entry.music_art, 'preview': entry.music_preview, 'url': entry.music_url,
        }

    def clean_music(self):
        track_id = (self.cleaned_data.get('music') or '').strip()
        if track_id and track_id == self.instance.music_id:
            self.music_data = self._saved_song()      # same song as before: nothing to look up
            return track_id
        self.music_data = None
        return super().clean_music()

    def save(self, commit=True):
        entry = super().save(commit=False)            # sets the new song and a newly uploaded file
        if self._media_type:
            if not self._thumb:
                entry.thumbnail = ''                  # a new video without a thumbnail: drop the old one
        elif self.cleaned_data.get('remove_media'):
            entry.media = ''
            entry.media_type = ''
            entry.thumbnail = ''
        if not self.cleaned_data.get('music'):
            entry.music_id = entry.music_title = entry.music_artist = ''
            entry.music_art = entry.music_preview = entry.music_url = ''
        if commit:
            entry.save()
            for name, old in self._old_files.items():
                if old and old != getattr(entry, name).name:
                    entry._meta.get_field(name).storage.delete(old)
        return entry

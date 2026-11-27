from django import forms

from .models import ShelfItem
from .queries import next_position

Kind = ShelfItem.Kind


class CollectionForm(forms.ModelForm):
    """Create or rename a collection."""

    class Meta:
        model = ShelfItem
        fields = ['title']
        labels = {'title': 'Collection name'}
        widgets = {'title': forms.TextInput(attrs={'placeholder': 'Life in five senses', 'autofocus': True})}

    def clean_title(self):
        title = self.cleaned_data['title'].strip()
        if not title:
            raise forms.ValidationError('Give the collection a name.')
        return title


class MoveForm(forms.ModelForm):
    """Move a post between your shelf and one of your collections."""

    class Meta:
        model = ShelfItem
        fields = ['parent']
        labels = {'parent': 'Put it in'}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        field = self.fields['parent']
        field.required = False
        field.queryset = ShelfItem.objects.filter(owner=user, kind=Kind.FOLDER)
        field.empty_label = 'On the shelf (no collection)'
        field.label_from_instance = lambda c: c.title

    def save(self, commit=True):
        if 'parent' in self.changed_data:
            self.instance.position = next_position(self.instance.owner, self.instance.parent_id)
        return super().save(commit)

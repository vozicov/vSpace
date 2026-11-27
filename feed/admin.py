from django.contrib import admin

from .models import Entry


@admin.register(Entry)
class EntryAdmin(admin.ModelAdmin):
    list_display = ('id', 'author', 'kind', 'parent', 'created_at')
    list_filter = ('kind',)

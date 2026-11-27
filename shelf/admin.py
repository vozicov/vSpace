from django.contrib import admin

from .models import InterestPin, ShelfItem

admin.site.register(ShelfItem)
admin.site.register(InterestPin)

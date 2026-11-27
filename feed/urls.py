from django.urls import path

from . import music, views

urlpatterns = [
    path('', views.home, name='home'),
    path('explore/', views.explore, name='explore'),
    path('create/', views.post_create, name='post_create'),
    path('tweets/', views.tweets, name='tweets'),
    path('music/search/', music.music_search, name='music_search'),
    path('entry/<int:pk>/', views.entry_detail, name='entry_detail'),
    path('entry/<int:pk>/edit/', views.entry_edit, name='entry_edit'),
    path('entry/<int:pk>/delete/', views.entry_delete, name='entry_delete'),
    path('entry/<int:pk>/like/', views.like_toggle, name='like_toggle'),
    path('u/<str:username>/', views.profile, name='profile'),
]

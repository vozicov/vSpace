from django.urls import path

from . import views

urlpatterns = [
    path('signup/', views.signup, name='signup'),
    path('edit-profile/', views.profile_edit, name='profile_edit'),
    path('settings/', views.settings_page, name='settings'),
    path('follow/<str:username>/', views.follow_toggle, name='follow_toggle'),
]

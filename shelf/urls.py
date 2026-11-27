from django.urls import path

from . import views

urlpatterns = [
    path('', views.shelf_edit, name='shelf_edit'),
    path('add/', views.add_posts, name='add_posts'),
    path('collection/new/', views.collection_create, name='collection_create'),
    path('collection/<int:pk>/', views.collection_detail, name='collection'),
    path('collection/<int:pk>/add/', views.add_posts, name='collection_add_posts'),
    path('item/<int:pk>/edit/', views.item_edit, name='item_edit'),
    path('item/<int:pk>/delete/', views.item_delete, name='item_delete'),
    path('item/<int:pk>/move/<str:direction>/', views.item_move, name='item_move'),
    path('post/<int:entry_pk>/shelf/', views.shelf_toggle_post, name='shelf_toggle_post'),
    path('post/<int:entry_pk>/pin/', views.pin_toggle, name='pin_toggle'),
    path('pin/set/', views.pin_set, name='pin_set'),
    path('pin/<int:slot>/remove/', views.pin_remove, name='pin_remove'),
]

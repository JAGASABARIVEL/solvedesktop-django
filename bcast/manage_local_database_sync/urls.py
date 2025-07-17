from django.urls import path
from . import views

urlpatterns = [
    path('sync/mapping', views.sync_mapping),
    path('sync/data', views.sync_data),
]

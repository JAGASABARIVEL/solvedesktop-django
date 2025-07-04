from django.urls import path
from . import views

urlpatterns = [
    path('summary', views.org_summary),
    path('my_summary', views.my_summary),
    path('employee/<int:user_id>', views.user_detail),
    path('apps', views.app_usage_summary),
    path('sync', views.sync_activity_data)
]

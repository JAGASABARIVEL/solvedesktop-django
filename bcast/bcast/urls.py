"""
URL configuration for bcast project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('users/', include('manage_users.urls')),
    path('organization/', include('manage_organization.urls')),
    path('platforms/', include('manage_platform.urls')),
    path('contacts/', include('manage_contact.urls')),
    path('groups/', include('manage_contact.urls_groups')),
    path('group-members/', include('manage_contact.urls_group_members')),
    path('conversations/', include('manage_conversation.urls')),
    path('campaign/', include('manage_campaign.urls')),
    path('files/', include('manage_files.urls')), # new
    path('subscriptions/', include('manage_subscriptions.urls')),
    path('productivity/', include('manage_productivity_tracker.urls')),
    path('database_sync/', include('manage_local_database_sync.urls')),
    path('crm/', include('manage_crm.urls')),
    #path("auth/", include("rest_framework.urls")), # added
]

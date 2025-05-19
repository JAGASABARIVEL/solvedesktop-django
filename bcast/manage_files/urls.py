from django.urls import path
from . import views

urlpatterns = [
    path('list', views.FileListView.as_view()),
    path('list/<int:pk>', views.FileRetrieveView.as_view()),
    path("list/organize", views.OrganizedFileListView.as_view()),
    path('folder', views.FolderCreateView.as_view()),
    path('file', views.FileUploadView .as_view()),
    path("delete", views.FileDeleteView.as_view()),
    path("download/<int:file_id>", views.FileDownloadView.as_view()),
    path('grant', views.FilePermissionView.as_view()),
    path('revoke', views.FilePermissionDeleteView.as_view()),
    path('permission/list/<int:file_id>', views.FilePermissionListView.as_view()),
    path('permission/update', views.FilePermissionUpdateView.as_view()),
    path("cost-report", views.CostReportView.as_view()),
]
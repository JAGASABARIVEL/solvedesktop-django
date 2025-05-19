from django.contrib import admin
from .models import File, FilePermission

# Register your models here.
admin.site.register(File)
admin.site.register(FilePermission)
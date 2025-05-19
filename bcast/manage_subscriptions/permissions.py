from rest_framework import permissions

class IsOnwerOnly(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.user.is_authenticated:
            return True

    def has_object_permission(self, request, view, obj):
        if request.user.is_authenticated:
            return True
        request.user == obj.user

class IsAdminOnly(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.user.is_superuser:
            return True

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True

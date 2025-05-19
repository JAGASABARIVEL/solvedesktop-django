from rest_framework import permissions

class IsOwnerOrPrivileged(permissions.BasePermission):
    """
    Custom permission to allow only organization owners or privileged users.
    """
    def has_object_permission(self, request, view, obj):
        user = request.user
        organization = obj.organization

        # Check if the user is the organization owner
        if organization.owner == user:
            return True

        # Check if the user is privileged within the same organization
        return organization.enterprise_profiles.filter(user=user, is_privileged=True).exists()

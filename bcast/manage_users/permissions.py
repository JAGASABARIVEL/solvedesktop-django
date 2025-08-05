from rest_framework import permissions
from manage_subscriptions.models import Subscription, UserSubscription


class NotLoggedIn(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return True

    def has_object_permission(self, request, view, obj):
        if not request.user.is_authenticated:
            return True


class AnyUser(permissions.BasePermission):
    def has_permission(self, request, view):
        return True

    def has_object_permission(self, request, view, obj):
        return True


def verify_enterprise_subscription(user):
    file_plans = Subscription.objects.filter(app__app_name__in=("manage_users", "manage_files", "manage_contacts", "manage_campaigns", "manage_conversations")).all()
    
    for file_plan in file_plans:
        subscription = UserSubscription.objects.filter(user=user, plan=file_plan).first()
        if not subscription:
            return False
        if subscription.status != "active":
            return False
    return True


def verify_individual_subscription(user):
    file_plans = Subscription.objects.filter(app__app_name__in=("manage_users", "manage_files")).all()
    
    for file_plan in file_plans:
        subscription = UserSubscription.objects.filter(user=user, plan=file_plan).first()
        if not subscription:
            return False
        if subscription.status != "active":
            return False
    return True


def verify_individual_enterprise_common_subscription(user):
    file_plans = Subscription.objects.filter(app__app_name__in=("manage_users", "manage_files")).all()
    for file_plan in file_plans:
        subscription = UserSubscription.objects.filter(user=user, plan=file_plan).first()
        if not subscription:
            return False
        if subscription.status != "active":
            return False
    return True


def is_subscription_complete(user):
    return user.is_subscription_complete == True

def is_payment_complete(user):
    return user.is_payment_complete == True


class EnterpriserUsers(permissions.BasePermission):
    def has_permission(self, request, view):
        if (request.user.is_authenticated and request.user.user_type in {"owner", "employee", "intern", "manager", "nontech"}) and is_subscription_complete(request.user) and is_payment_complete(request.user):
            return True#verify_enterprise_subscription(request.user.enterprise_profile.organization.owner)

    def has_object_permission(self, request, view, obj):
        if request.user.is_authenticated and request.user.user_type in {"owner", "employee", "intern", "manager", "nontech"} and is_subscription_complete(request.user) and is_payment_complete(request.user):
             return True#verify_enterprise_subscription(request.user.enterprise_profile.organization.owner)


class IndividualUsers(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.user.is_authenticated and request.user.user_type == "individual" and is_subscription_complete(request.user) and is_payment_complete(request.user):
            return True#verify_individual_subscription(request.user)

    def has_object_permission(self, request, view, obj):
        if request.user.is_authenticated and request.user.user_type == "individual" and is_subscription_complete(request.user) and is_payment_complete(request.user):
            return True#verify_individual_subscription(request.user)


class EnterpriseIndividualUsers(permissions.BasePermission):
    def has_permission(self, request, view):
        if (request.user.is_authenticated and request.user.user_type in {"individual", "owner", "employee", "intern", "manager", "nontech"}) and is_subscription_complete(request.user) and is_payment_complete(request.user):
            return True#verify_individual_enterprise_common_subscription(request.user)

    def has_object_permission(self, request, view, obj):
        if (request.user.is_authenticated and request.user.user_type in {"individual", "owner", "employee", "intern", "manager", "nontech"}) and is_subscription_complete(request.user) and is_payment_complete(request.user):
            return True#verify_individual_enterprise_common_subscription(request.user)


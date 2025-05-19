from django.shortcuts import render

from django.db import transaction

from rest_framework import generics, serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.status import HTTP_201_CREATED

from .models import Apps, Subscription, UserSubscription, Payment
from .serializers import AppsSerializer, SubscriptionSerializer, UserSubscriptionSerializer, PaymentSerializer
from .permissions import IsOnwerOnly, IsAdminOnly
from manage_users.permissions import AnyUser

# Create your views here.

class AppsView(generics.ListCreateAPIView):
    serializer_class = AppsSerializer
    permission_classes = (IsAdminOnly,)
    queryset = Apps.objects.all()


class SubscriptionView(generics.ListAPIView):
    authentication_classes = []  # <-- Allow unauthenticated access
    permission_classes = (AnyUser,)
    serializer_class = SubscriptionSerializer
    queryset = Subscription.objects.all()

class UserSubscriptionCreateView(generics.ListCreateAPIView):
    serializer_class = UserSubscriptionSerializer
    permission_classes = (IsAuthenticated,)
    queryset = UserSubscription.objects.all()

    def perform_create(self, serializer):
        user = self.request.user
        existing_plans = None
        if user.user_type == "owner":
            existing_plans = ("manage_users", "manage_files", "manage_contacts", "manage_campaigns", "manage_conversations")
        elif user.user_type == "individual":
            existing_plans = ("manage_users", "manage_files")
        existing_subscriptions = [Subscription.objects.get(app__app_name=plan_name) for plan_name in existing_plans]
        existing_user_subscriptions = [UserSubscription.objects.filter(user=user, plan=existing_subscription).first() for existing_subscription in existing_subscriptions]
        existing_status = set()
        for subs in existing_user_subscriptions:
            if subs:
                existing_status.add(subs.status)
        if len(existing_status) == 1 and "active" in existing_status:
            raise serializers.ValidationError(
                "Subscription is already active. "
            )
        plan = None
        subscriptions = []
        for plan in existing_subscriptions:
            # Check for active or pending subscription
            existing_user_subscription = UserSubscription.objects.filter(user=user, plan=plan).first()
            if not existing_user_subscription:
                # Create subscription atomically
                with transaction.atomic():
                    data = {
                        "user": user.id,
                        "plan": plan.id
                    }
                    subscription_serializer = UserSubscriptionSerializer(data=data)
                    subscription_serializer.is_valid(raise_exception=True)
                    subscription = subscription_serializer.save()
                    subscriptions.append(subscription)
            elif existing_user_subscription and existing_user_subscription.status in ("pending", "expired"):
                if existing_user_subscription.status == "expired":
                    user.is_payment_complete = False
                    user.is_subscription_complete = True
                    user.save()
                return Response(
                    {
                        "message": "Subscriptions is pending or expired. Please complete the payment.",
                        "user": {
                            "id": user.id,
                            "email": user.email,
                            "username": user.username,
                            "user_type": user.user_type,
                            "is_registration_complete": user.is_registration_complete,
                            "is_subscription_complete": user.is_subscription_complete,
                            "is_payment_complete": user.is_payment_complete,
                            "subscriptions": subscriptions
                        },
                    },
                    status=HTTP_201_CREATED,
                )
        user.is_subscription_complete = True
        user.save()
        return Response(
                {
                    "message": "Subscriptions completed successfully.",
                    "user": {
                        "id": user.id,
                        "email": user.email,
                        "username": user.username,
                        "user_type": user.user_type,
                        "is_registration_complete": user.is_registration_complete,
                        "is_subscription_complete": user.is_subscription_complete,
                        "is_payment_complete": user.is_payment_complete,
                        "subscriptions": subscriptions
                    },
                },
                status=HTTP_201_CREATED,
            )

    # added
    def filter_queryset(self, queryset):
        queryset = queryset.filter(user=self.request.user)
        return super().filter_queryset(queryset)

class UserSubscriptionUpdateView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = UserSubscriptionSerializer
    permission_classes = (IsOnwerOnly,)
    queryset = UserSubscription.objects.all()


from functools import reduce
class PaymentCreateView(generics.ListCreateAPIView):
    serializer_class = PaymentSerializer
    permission_classes = (IsAuthenticated,)
    queryset = Payment.objects.all()

    def validate(self, user, subscription_id):
        try:
            user_subscription = UserSubscription.objects.get(id=subscription_id)
        except UserSubscription.DoesNotExist:
            raise serializers.ValidationError("Invalid subscription ID")

        if user_subscription.status in {"active"}:
            raise serializers.ValidationError("Subscription is already active.")
        active_payment = Payment.objects.filter(user=user, subscription=user_subscription, status="pending").first()
        if active_payment:
            raise serializers.ValidationError("A payment is already in progress.")
        return user_subscription

    def call_payment_gateway(self, serializer, amount):
        try:
            # TODO: Call Payment Gateway (e.g., Razorpay/Stripe)
            payment_status = "pending"  # Replace with real response
            transaction_id = "cash_dummy_txn_123456"  # Replace with actual transaction ID
            return (payment_status, transaction_id)
        except Exception as e:
            raise serializers.ValidationError(f"Payment processing error: {str(e)}")

    def perform_create(self, serializer):
        user = self.request.user
        existing_plans = None
        if user.user_type == "owner":
            existing_plans = ("manage_users", "manage_files", "manage_contacts", "manage_campaigns", "manage_conversations")
        elif user.user_type == "individual":
            existing_plans = ("manage_users", "manage_files")
        amount = sum(Subscription.objects.get(app__app_name=plan_name).price for plan_name in existing_plans)
        transaction_status, transaction_id = self.call_payment_gateway(serializer, amount)    
        if transaction_status in ("completed", "pending"):
            with transaction.atomic():
                for plan_name in existing_plans:
                    try:
                        plan = Subscription.objects.get(app__app_name=plan_name)
                    except Subscription.DoesNotExist:
                        raise serializers.ValidationError("Invalid plan ID.")
                    existing_user_subscription = UserSubscription.objects.filter(user=user, plan=plan).first()
                    if existing_user_subscription:
                        payment_data = {
                            "user": user.id,
                            "subscription": existing_user_subscription.id,
                            "transaction_type": "subscription",
                            "amount": plan.price,
                            "status": transaction_status,
                            "transaction_id": transaction_id,
                        }
                        payment_serializer = PaymentSerializer(data=payment_data)
                        payment_serializer.is_valid(raise_exception=True)
                        payment = payment_serializer.save()
                        payment.complete_payment()
                # This is to update user is_subscription_complete to complete irrespective of payment completed/not
                # But this can be re-evaluated later based on the requirement 
                user.is_subscription_complete = True
                user.save()
                if transaction_status == "completed":
                    user.is_payment_complete = True
                    user.save()
            return Response(
                {
                    "message": "Payment completed successfully.",
                    "user": {
                        "id": user.id,
                        "email": user.email,
                        "username": user.username,
                        "user_type": user.user_type,
                        "is_registration_complete": user.is_registration_complete,
                        "is_subscription_complete": user.is_subscription_complete,
                        "is_payment_complete": user.is_payment_complete,
                    },
                },
                status=HTTP_201_CREATED,
            )
        else:
            raise serializers.ValidationError("No subscription available for user.")
    
    # Filter payments for the logged-in user
    def filter_queryset(self, queryset):
        return queryset.filter(user=self.request.user)


class PaymentUpdateView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = PaymentSerializer
    permission_classes = (IsAuthenticated,) 
    queryset = Payment.objects.all()

    def validate(self, user, payment):
        payment_id = self.request.data.get('payment_id')  # Get Payment ID from URL
        try:
            payment = Payment.objects.get(id=payment_id, user=self.request.user)
            if payment.status == "completed":
                raise serializers.ValidationError("Cannot update a completed payment.")
            if payment.status == "pending":
                raise serializers.ValidationError("Payment is already in progress.")
        except Payment.DoesNotExist:
            raise serializers.ValidationError("Invalid payment ID")

    def save_payment(self, serializer):
        try:
            with transaction.atomic():
                # TODO: Call Payment Gateway for Retry
                payment_status = "completed"  # Replace with real response
                transaction_id = "txn_789124"  # Replace with real transaction ID
                payment = serializer.save(status=payment_status, transaction_id=transaction_id)
                if payment_status == "completed":
                    payment.complete_payment()
                return payment

        except Exception as e:
            raise serializers.ValidationError(f"Payment processing error: {str(e)}")

    def perform_update(self, serializer):
        self.validate(self.request.user)
        self.save_payment(serializer)

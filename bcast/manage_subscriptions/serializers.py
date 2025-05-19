from rest_framework import serializers

from .models import Apps, Subscription, UserSubscription, Payment

class AppsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Apps
        fields = '__all__'
        read_only_fields = '__all__'

class SubscriptionSerializer(serializers.ModelSerializer):
    app = serializers.StringRelatedField(read_only=True)
    class Meta:
        model = Subscription
        fields = '__all__'
        read_only_fields = [field.name for field in Subscription._meta.fields]

from manage_users.models import CustomUser
class UserSubscriptionSerializer(serializers.ModelSerializer):
    user = serializers.PrimaryKeyRelatedField(queryset=CustomUser.objects.all(), required=False)
    plan = serializers.PrimaryKeyRelatedField(queryset=Subscription.objects.all(), required=False)
    class Meta:
        model = UserSubscription
        fields = '__all__'


class PaymentSerializer(serializers.ModelSerializer):
    user = serializers.PrimaryKeyRelatedField(queryset=CustomUser.objects.all(), required=False)
    subscription = serializers.PrimaryKeyRelatedField(queryset=UserSubscription.objects.all(), required=False)
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)


    class Meta:
        model = Payment
        fields = '__all__'
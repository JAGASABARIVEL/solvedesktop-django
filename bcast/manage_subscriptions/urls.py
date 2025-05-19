from django.urls import path
from . import views

urlpatterns = [
    path('subscriptions', views.SubscriptionView.as_view()),
    path('active', views.UserSubscriptionCreateView.as_view()),
    path('active/<int:pk>', views.UserSubscriptionUpdateView.as_view()),
    path('payment', views.PaymentCreateView.as_view()),
    path('payment/<int:pk>', views.PaymentUpdateView.as_view()),
]
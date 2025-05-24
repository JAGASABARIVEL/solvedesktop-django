from django.urls import path
from . import views

urlpatterns = [
    #path('register', views.UserRegistration.as_view()),
    #path('login', views.LoginView.as_view()),
    path('guest', views.GuestJWTView.as_view(), name='guest-jwt'),
    #path('api/gmail/oauth/callback', views.GmailOAuthCallback.as_view()),
    path('login/google', views.GoogleLoginView.as_view()),
    path('ping', views.LoginPing.as_view()),
    path('list', views.UserListEnterpriseView.as_view()),
    path('list_agents', views.AgentListEnterpriseView.as_view()),
    path('list_all_users', views.UserListAllView.as_view()),
    path('list_all_agents', views.AgentListAllView.as_view()),
    path('employees/<int:pk>/remove', views.RemoveEmployeeView.as_view(), name='employee-remove'),
    path('agents/<int:pk>/remove', views.RemoveAgentView.as_view(), name='agent-remove'),
    path('logout', views.LogoutView.as_view()),
    path('refresh', views.RefreshTokenView.as_view()),
    path("request-otp", views.RequestPasswordResetOTPView.as_view()),
    path("verify-otp", views.VerifyOTPView.as_view()),
    path("reset-password", views.ResetPasswordView.as_view()),

    path("register/owner/", views.EnterpriseOwnerRegistrationView.as_view(), name="owner-registration"),
    path("register/employee/", views.EmployeeRegistrationView.as_view(), name="employee-registration"),
    path("register/individual/", views.IndividualRegistrationView.as_view(), name="individual-registration"),
    path("register/agent/", views.AgentRegistrationView.as_view(), name="agent-registration")


]
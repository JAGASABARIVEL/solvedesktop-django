from rest_framework_simplejwt.tokens import AccessToken

class CustomAccessToken(AccessToken):
    @property
    def payload(self):
        data = super().payload
        user = self.user

        enterprise_profile = getattr(user, "enterprise_profile", None)
        organization = None
        if enterprise_profile:
            organization = getattr(enterprise_profile, "organization", None)
        data["role"] = "frontend"
        data["service"] = "ui_main_client"
        data["guest"] = False,
        data["organization_id"] = organization.id if organization else None
        return data
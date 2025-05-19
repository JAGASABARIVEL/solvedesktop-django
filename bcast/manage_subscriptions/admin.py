from django.contrib import admin

from .models import Apps, Subscription, UserSubscription, UserWallet, Payment

# Register your models here.

admin.site.register(Apps)
admin.site.register(Subscription)
admin.site.register(UserSubscription)
admin.site.register(UserWallet)
admin.site.register(Payment)
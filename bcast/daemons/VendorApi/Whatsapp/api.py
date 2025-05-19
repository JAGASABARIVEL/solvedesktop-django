############## CRUD API ##############
send = "https://graph.facebook.com/v21.0/{phone_number_id}/messages"

############# TEMPLATES ##############
get_templates = "https://graph.facebook.com/v22.0/{whatsapp_business_id}/message_templates"

############## Webhook Notification ##############
status = "https://solvedesktop-whatsapp-webhook.onrender.com/schedule/notifications/{phone_number_id}/{recipient_phone_number}/{messageid}"

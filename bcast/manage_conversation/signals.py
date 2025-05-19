import socketio
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import IncomingMessage, UserMessage

sio = socketio.Client()
SOCKET_URL = "http://localhost:5001"
sio.connect(SOCKET_URL)

@receiver(post_save, sender=IncomingMessage)
def emit_incoming_message(sender, instance, created, **kwargs):
    if created:
        to_be_emit = instance.to_dict()
        to_be_emit.update({"msg_from_type": "CUSTOMER"})
        sio.emit('whatsapp_chat', to_be_emit)

@receiver(post_save, sender=UserMessage)
def emit_user_message(sender, instance, **kwargs):
    sio.emit('whatsapp_chat', {
        "conversation_id": instance.conversation.id,
        "msg_from_type": "ORG"
    })

from django.db import connections
from django.db.utils import ConnectionDoesNotExist
from decouple import config


def get_dynamic_cursor(database_name):
    if database_name not in connections.databases:
        connections.databases[database_name] = {
            'ENGINE': 'django.db.backends.postgresql',  # or other DB engine
            'NAME': database_name,
            'USER': config("PG_USER"),
            'PASSWORD': config("PG_PASSWORD"),
            'HOST': config("PG_HOST"),  # or internal network DNS/IP
            'PORT': config("PG_PORT")
        }
    return connections[database_name].cursor()
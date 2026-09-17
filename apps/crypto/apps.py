from django.apps import AppConfig


class CryptoConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.crypto"
    label = "redscribe_crypto"
    verbose_name = "Encryption / Keystore"

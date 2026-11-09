from django.apps import AppConfig
from django.db.models.signals import post_migrate, post_save


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"

    def ready(self):
        from . import roles
        from .models import User

        def on_user_saved(sender, instance, **kwargs):
            roles.sync_user_groups(instance)

        def on_migrated(sender, **kwargs):
            roles.ensure_role_groups()

        post_save.connect(on_user_saved, sender=User, dispatch_uid="accounts_sync_groups")
        post_migrate.connect(on_migrated, dispatch_uid="accounts_role_groups")

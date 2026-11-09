"""
Maps EUnited roles to Django permission groups.

Superadmins are Django superusers and can do everything.
Editors and moderators are staff users whose admin rights come from these groups.
Club accounts and students never get admin access.
"""
from django.contrib.auth.models import Group, Permission

# role -> list of "app_label.codename"
ROLE_PERMISSIONS = {
    "editor": [
        "pulse.view_post",
        "pulse.add_post",
        "pulse.change_post",
        "pulse.view_reviewqueue",
        "pulse.change_reviewqueue",
        "pulse.view_tag",
        "pulse.add_tag",
        "pulse.change_tag",
        "pulse.view_source",
    ],
    "moderator": [
        "pulse.view_post",
        "pulse.hide_post",
        "pulse.view_tag",
        "pulse.view_reviewqueue",
    ],
}

GROUP_NAMES = {"editor": "Editors", "moderator": "Moderators"}


def ensure_role_groups():
    """Create the Editors / Moderators groups and give them their permissions."""
    groups = {}
    for role, perm_names in ROLE_PERMISSIONS.items():
        group, _ = Group.objects.get_or_create(name=GROUP_NAMES[role])
        perms = []
        for full_name in perm_names:
            app_label, codename = full_name.split(".")
            perm = Permission.objects.filter(
                content_type__app_label=app_label, codename=codename
            ).first()
            if perm:
                perms.append(perm)
        group.permissions.set(perms)
        groups[role] = group
    return groups


def sync_user_groups(user):
    """Put a user in exactly the role group that matches user.role."""
    role_groups = Group.objects.filter(name__in=GROUP_NAMES.values())
    user.groups.remove(*role_groups)
    group_name = GROUP_NAMES.get(user.role)
    if group_name:
        group = Group.objects.filter(name=group_name).first()
        if group is None:
            group = ensure_role_groups()[user.role]
        user.groups.add(group)

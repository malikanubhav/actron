"""Finance export policy shared by reports and invoices."""


def can_export(user, project):
    return user.get("role") == "finance" and project in user.get("projects", [])

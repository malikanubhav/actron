from app.permissions import can_export


def export_invoice(user, project):
    return can_export(user, project)

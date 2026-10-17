from app.permissions import can_export


def export_report(user, project):
    return can_export(user, project)

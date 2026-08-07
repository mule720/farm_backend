"""
Notification helpers — call these from any app to create in-app notifications.

Usage:
    from apps.notifications.utils import notify, notify_org, notify_roles

    # Notify one user
    notify(user, 'Borehole critically low', 'Water level at 12%', priority='critical',
           category='irrigation', action_url='/irrigation')

    # Notify everyone in the same organisation
    notify_org(user.organization, 'Weather alert', 'Frost expected tonight',
               category='weather', priority='warning')

    # Notify only specific roles
    notify_roles(user.organization, ['director', 'production_manager'],
                 'KPI target missed', 'Egg production below 80%', category='kpi')
"""

from .models import Notification


def notify(user, title: str, message: str, *,
           category: str = 'system',
           priority: str = 'info',
           action_url: str = '',
           ref_id: str = '') -> Notification:
    """Create a single notification for one user."""
    return Notification.objects.create(
        recipient=user,
        title=title,
        message=message,
        category=category,
        priority=priority,
        action_url=action_url,
        ref_id=ref_id,
    )


def notify_org(organization, title: str, message: str, *,
               category: str = 'system',
               priority: str = 'info',
               action_url: str = '',
               ref_id: str = '',
               exclude_user=None) -> int:
    """
    Notify every active member of an organisation.
    Returns the number of notifications created.
    """
    from apps.accounts.models import Profile
    users = Profile.objects.filter(organization=organization, is_active=True)
    if exclude_user:
        users = users.exclude(pk=exclude_user.pk)

    notifications = [
        Notification(
            recipient=u,
            title=title,
            message=message,
            category=category,
            priority=priority,
            action_url=action_url,
            ref_id=ref_id,
        )
        for u in users
    ]
    Notification.objects.bulk_create(notifications)
    return len(notifications)


def notify_roles(organization, roles: list, title: str, message: str, *,
                 category: str = 'system',
                 priority: str = 'info',
                 action_url: str = '',
                 ref_id: str = '') -> int:
    """
    Notify only users with specific roles within an organisation.
    Returns the number of notifications created.
    """
    from apps.accounts.models import Profile
    users = Profile.objects.filter(
        organization=organization,
        is_active=True,
        role__in=roles,
    )
    notifications = [
        Notification(
            recipient=u,
            title=title,
            message=message,
            category=category,
            priority=priority,
            action_url=action_url,
            ref_id=ref_id,
        )
        for u in users
    ]
    Notification.objects.bulk_create(notifications)
    return len(notifications)

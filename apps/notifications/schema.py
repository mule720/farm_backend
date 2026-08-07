import graphene
from graphene_django import DjangoObjectType
from django.utils import timezone
from .models import Notification


class NotificationType(DjangoObjectType):
    class Meta:
        model = Notification
        fields = [
            'id', 'title', 'message', 'category', 'priority',
            'is_read', 'read_at', 'action_url', 'ref_id', 'created_at',
        ]


def _user(info):
    user = info.context.user
    if user.is_anonymous:
        raise Exception('Not authenticated')
    return user


# ─── Queries ─────────────────────────────────────────────────────────────────

class NotificationQuery(graphene.ObjectType):

    notifications = graphene.List(
        NotificationType,
        unread_only=graphene.Boolean(),
        category=graphene.String(),
        limit=graphene.Int(),
    )
    unread_count = graphene.Int()

    def resolve_notifications(self, info, unread_only=False, category=None, limit=50):
        user = _user(info)
        qs = Notification.objects.filter(recipient=user)
        if unread_only:
            qs = qs.filter(is_read=False)
        if category:
            qs = qs.filter(category=category)
        return qs[:limit]

    def resolve_unread_count(self, info):
        user = _user(info)
        return Notification.objects.filter(recipient=user, is_read=False).count()


# ─── Mutations ───────────────────────────────────────────────────────────────

class MarkNotificationRead(graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)

    notification = graphene.Field(NotificationType)

    def mutate(self, info, id):
        user = _user(info)
        n = Notification.objects.get(id=id, recipient=user)
        if not n.is_read:
            n.is_read = True
            n.read_at = timezone.now()
            n.save(update_fields=['is_read', 'read_at'])
        return MarkNotificationRead(notification=n)


class MarkAllNotificationsRead(graphene.Mutation):
    count = graphene.Int()

    def mutate(self, info):
        user = _user(info)
        count = Notification.objects.filter(
            recipient=user, is_read=False
        ).update(is_read=True, read_at=timezone.now())
        return MarkAllNotificationsRead(count=count)


class DeleteNotification(graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)

    success = graphene.Boolean()

    def mutate(self, info, id):
        user = _user(info)
        Notification.objects.filter(id=id, recipient=user).delete()
        return DeleteNotification(success=True)


class ClearAllNotifications(graphene.Mutation):
    """Delete all read notifications for the current user."""
    count = graphene.Int()

    def mutate(self, info):
        user = _user(info)
        count, _ = Notification.objects.filter(recipient=user, is_read=True).delete()
        return ClearAllNotifications(count=count)


class NotificationMutation(graphene.ObjectType):
    mark_notification_read     = MarkNotificationRead.Field()
    mark_all_notifications_read = MarkAllNotificationsRead.Field()
    delete_notification        = DeleteNotification.Field()
    clear_all_notifications    = ClearAllNotifications.Field()

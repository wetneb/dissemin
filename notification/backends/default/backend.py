
from .. import signals
from ...models import Inbox
from ...models import Notification
from ...models import NotificationArchive
from ...settings import notification_settings
from ..base import NotificationBackend
from ..exceptions import NotificationDoesNotExist
from ..exceptions import NotificationTypeNotSupported


class DefaultBackend(NotificationBackend):

    def inbox_list(self, user):
        if user.is_anonymous():
            return []
        inbox = Inbox.objects.filter(user=user).select_related('notification')
        return (m.notification for m in inbox)

    def inbox_purge(self, user):
        if user.is_authenticated():
            Inbox.objects.filter(user=user).delete()
            signals.inbox_purged.send(sender=self.__class__, user=user)

    def inbox_store(self, users, notification):
        if not self.can_handle(notification):
            raise NotificationTypeNotSupported

        for user in users:
            Inbox.objects.get_or_create(user=user, notification=notification)
            signals.inbox_stored.send(
                sender=self.__class__, user=user, notification=notification)

    def inbox_delete(self, user, notification_id):
        try:
            Inbox.objects.filter(
                user=user, notification=notification_id).delete()
            signals.inbox_deleted.send(
                sender=self.__class__, user=user, notification_id=notification_id)
        except Inbox.DoesNotExist:
            raise NotificationDoesNotExist(
                "Notification with id {} does not exist".format(notification_id))

    def inbox_clean_per_tag(self, user, tag):
        try:
            Inbox.objects.filter(user=user, notification__tag=tag).delete()
            signals.inbox_cleaned.send(
                sender=self.__class__, user=user, tag=tag)
        except Inbox.DoesNotExist:
            raise NotificationDoesNotExist(
                "Notification(s) with tag {} does not exist".format(tag))

    def inbox_get(self, user, notification_id):
        try:
            return Inbox.objects.get(pk=notification_id).notification
        except Inbox.DoesNotExist:
            raise NotificationDoesNotExist(
                "Notification with id {} does not exist".format(notification_id))

    def create_notification(self, level, payload, tag='', date=None):
        notif_args = {
            'payload': payload,
            'level': level,
            'tag': tag
        }

        if date is not None:
            notif_args['date'] = date

        return Notification.objects.create(**notif_args)

    def archive_store(self, users, notification):
        if not self.can_handle(notification):
            raise NotificationTypeNotSupported

        for user in users:
            NotificationArchive.objects.create(
                user=user, notification=notification)
            signals.archive_stored.send(
                sender=self.__class__, user=user, notification=notification)

    def archive_list(self, user):
        return list(NotificationArchive.objects.filter(user=user))

    def can_handle(self, notification):
        return isinstance(notification, Notification)

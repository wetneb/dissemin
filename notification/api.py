import importlib

from django.utils.translation import ungettext as _plural

from .settings import notification_settings

__all__ = (
    'get_notifications',
    'add_notification_for',
    'broadcast_notification',
    'mark_read',
    'mark_all_read',
    'delete_notification_per_tag'
)


def get_backend_class():
    module, _, klass = notification_settings['STORAGE_BACKEND'].rpartition('.')
    imported_module = importlib.import_module(module)
    if not hasattr(imported_module, klass):
        raise RuntimeError(
            'STORAGE_BACKEND {} specified for notification does not exists')

    return getattr(importlib.import_module(module), klass)


def get_notifications(request):
    """
    Get all unread messages from a user.

    :param request: the request containing eventually a user
    """
    BackendClass = get_backend_class()
    backend = BackendClass()

    notifications = backend.inbox_list(request.user)
    return notifications


def add_notification_for(users, level, payload, tag='', date=None):
    """
    Add a notification to a list of users.

    :param users: an iterable containing the recipients of the notification.
    :param level: a notification level (could be interpreted as priority)
    :param payload: a dict containing a message, a tag, or a URL (should be serializable into JSON)
    :param date: a date to deliver the notification on, by default: timezone.now()
    """

    BackendClass = get_backend_class()
    backend = BackendClass()

    notif = backend.create_notification(level, payload, tag, date)
    backend.archive_store(users, notif)
    backend.inbox_store(users, notif)


def broadcast_notification(level, payload, tag='', date=None):
    """
    Add a notifiation to all users (a.k.a. broadcast)

    :param level: a notification level (could be interpreted as priority)
    :param payload: a dict containing a message, a tag or a URL (should be serializable into JSON)
    :param date: a date to deliver the notification on, by default: timezone.now()
    """
    from django.contrib.auth import get_user_model
    users = get_user_model().objects.all()
    add_notification_for(users, level, payload, tag, date)


def mark_read(user, notification):
    """
    Mark the notification instance as read for the user provided.

    :param user: user instance for the recipient
    :param notification: a Notification instance to mark as read
    """
    BackendClass = get_backend_class()
    backend = BackendClass()
    backend.inbox_delete(user, notification)


def mark_all_read(user):
    """
    Mark all the notifications instances as read for a user provided.

    :param user: user instance for the recipient
    """
    BackendClass = get_backend_class()
    backend = BackendClass()
    backend.inbox_purge(user)


def delete_notification_per_tag(user, tag):
    """
    Delete the notifications for the user and tag provided.

    :param user: user instance for the recipient
    :param tag: tag used to create the notification
    """
    BackendClass = get_backend_class()
    backend = BackendClass()
    backend.inbox_clean_per_tag(user, tag)

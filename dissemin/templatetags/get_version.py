from django import template
from dissemin import VERSION

register = template.Library()

@register.simple_tag
def get_version():
    return VERSION

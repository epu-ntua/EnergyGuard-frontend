from django import template

register = template.Library()

@register.filter(name='dict_key')
def dict_key(d, k):
    """Επιστρέφει την τιμή από το dictionary d για το κλειδί k"""
    if d:
        return d.get(k)
    return None
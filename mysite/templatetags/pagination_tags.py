from django import template

register = template.Library()

@register.inclusion_tag('mysite/pagination.html', takes_context=True)
def smart_pagination(context, page_obj, adjacent_pages=1):
    """
    Inclusion tag: returns context with pagination data and request object
    """
    total_pages = page_obj.paginator.num_pages
    current = page_obj.number
    pages = []

    for i in range(1, total_pages + 1):
        if (
            i == 1 or
            i == total_pages or
            (i >= current - adjacent_pages and i <= current + adjacent_pages)
        ):
            pages.append(i)

    display = []
    last = 0
    for p in pages:
        if p - last > 1:
            display.append('...')
        display.append(p)
        last = p

    # Add request to context
    return {
        'page_obj': page_obj,
        'page_list': display,
        'request': context['request'],
        'query_string_page': query_string (context, exclude='page'),
    }

@register.simple_tag(takes_context=True)
def query_string(context, exclude=None):
    """
    Returns the current GET query string, optionally excluding keys.
    Usage: {% query_string 'page,sort' %}
    """
    request = context['request']
    querydict = request.GET.copy()
    if exclude:
        for key in exclude.split(','):
            querydict.pop(key, None)
    qs = querydict.urlencode()
    return qs + '&' if qs else ''
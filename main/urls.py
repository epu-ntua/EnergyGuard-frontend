"""
URL configuration for main project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.templatetags.static import static as static_url
from django.views.generic import RedirectView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('core.urls')),
    path('projects/', include('projects.urls')),
    path('datasets/', include('datasets.urls')),
    path('accounts/', include('accounts.urls')),
    # Unrouted: billing is not in use yet (payments come much later in the
    # project). Models, migrations and templates are kept as reference for when
    # it is picked up - only the URLs are off, so nothing serves the leftover
    # template scaffolding in the meantime.
    # path('billing/', include('billing.urls')),
    path('digitaltwins/', include('digitaltwins.urls')),
    path('dataspace/', include('dataspace.urls')),
    path('trustworthiness/', include('trustworthiness.urls', namespace='trustworthiness')),
    path('trustworthiness/code-analysis/', include('code_analysis.urls')),
    path('trustworthiness/robustness/', include('robustness.urls')),
    path('accounts/', include('allauth.urls')),
    path('surveys/', include('questionnaire.config.urls')),
]

# The Oct 2026 legal PDFs link to each other as /static/assets/docs/<NAME>_10_2026
# (no .pdf, and not the names the files are published under), so those links 404.
# WhiteNoise passes unknown /static/ paths on to Django, so redirect them here until
# the lawyer fixes the links in the next revision of the documents.
LEGAL_DOC_ALIASES = {
    'PRIVACY_POLICY_10_2026': 'privacy-policy.pdf',
    'TERMS_10_2026': 'terms.pdf',
    'COOKIES_POLICY_10_2026': 'cookies_policy.pdf',
    'DPA_WITH_USERS_10_2026': 'DPA_with_users.pdf',
}
urlpatterns += [
    path(f'{settings.STATIC_URL.lstrip("/")}assets/docs/{alias}', RedirectView.as_view(url=static_url(f'assets/docs/{filename}')))
    for alias, filename in LEGAL_DOC_ALIASES.items()
]

# Serve media files during development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

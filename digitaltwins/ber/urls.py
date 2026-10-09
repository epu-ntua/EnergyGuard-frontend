"""BER routes, mounted under digitaltwins/ber-hydrogen/ber-hydrogen-dt/.

URL names stay global (no app namespace): templates across the platform reverse
them, and the paths are already in emails and notifications sent to users.
"""

from django.urls import path

from .views import management, requester

urlpatterns = [
    path('', requester.ber_hydrogen_dt, name='ber-hydrogen-dt'),
    path('documentation/', requester.ber_hydrogen_documentation, name='ber-hydrogen-documentation'),
    path('submit/', requester.ber_experiment_submit, name='ber-hydrogen-submit'),
    path('requests/', requester.ber_hydrogen_runs, name='ber-hydrogen-runs'),
    path('requests/<int:request_id>/', requester.ber_hydrogen_request_detail, name='ber-hydrogen-request-detail'),
    path('requests/<int:request_id>/cancel/', requester.ber_hydrogen_request_cancel, name='ber-hydrogen-request-cancel'),
    path('requests/<int:request_id>/hide/', requester.ber_hydrogen_request_hide, name='ber-hydrogen-request-hide'),
    path('requests/<int:request_id>/result/', requester.ber_hydrogen_request_result_download, name='ber-hydrogen-request-result-download'),
    path('requests/<int:request_id>/status/', requester.ber_hydrogen_request_status, name='ber-hydrogen-request-status'),
    path('management/', management.ber_management_list, name='ber-management-list'),
    path('management/<int:request_id>/', management.ber_management_detail, name='ber-management-detail'),
    path('management/upload-progress/', management.ber_management_upload_progress, name='ber-management-upload-progress'),
    path('management/<int:request_id>/replace-result/', management.ber_management_replace_result, name='ber-management-replace-result'),
    path('management/<int:request_id>/archive/', management.ber_management_archive, name='ber-management-archive'),
    path('management/<int:request_id>/restore/', management.ber_management_restore, name='ber-management-restore'),
    path('management/<int:request_id>/panel/', management.ber_management_panel, name='ber-management-panel'),
    path('management/<int:request_id>/experiment.json', management.ber_management_experiment_download, name='ber-management-experiment-download'),
    path('management/<int:request_id>/download/', management.ber_management_download, name='ber-management-download'),
]

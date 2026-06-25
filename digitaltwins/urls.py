from django.urls import path
from . import views

urlpatterns = [
    path('', views.map_view, name='riga-map'),
    path('list/', views.digitaltwins_list, name='digitaltwins-list'),
    path('hydrogen-platforms/cea/', views.cea_node_workspace, name='cea-node-workspace'),
    path('ber-hydrogen/ber-hydrogen-dt/', views.ber_hydrogen_dt, name='ber-hydrogen-dt'),
    path('<slug:slug>/', views.digitaltwins_detail, name='digitaltwins-detail'),
]

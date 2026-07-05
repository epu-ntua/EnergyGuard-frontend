from django.urls import path
from . import views

urlpatterns = [
    path('riga/rea-riga-dt/', views.rea_riga_dt, name='riga-map'),
    path('riga/rea-riga-dt/buildings/', views.rea_riga_buildings_api, name='rea-riga-buildings-api'),
    path('list/', views.digitaltwins_list, name='digitaltwins-list'),
    path('hydrogen-platforms/cea/', views.cea_node_workspace, name='cea-node-workspace'),
    path('ber-hydrogen/ber-hydrogen-dt/', views.ber_hydrogen_dt, name='ber-hydrogen-dt'),
    path('cartif-hydrogen/cartif-hydrogen-dt/', views.cartif_hydrogen_dt, name='cartif-hydrogen-dt'),
    path('antrodoco/engreen-antrodoco-dt/', views.engreen_antrodoco_dt, name='engreen-antrodoco-dt'),
    path('antrodoco/engreen-antrodoco-dt/simulate/', views.engreen_pv_simulate, name='engreen-pv-simulate'),
    path('antrodoco/engreen-antrodoco-dt/stations/', views.engreen_stations_api, name='engreen-stations-api'),
    path('<slug:slug>/', views.digitaltwins_detail, name='digitaltwins-detail'),
]

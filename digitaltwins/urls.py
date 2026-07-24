from django.urls import path
from . import views

urlpatterns = [
    path('riga/rea-riga-dt/', views.rea_riga_dt, name='riga-map'),
    path('riga/rea-riga-dt/buildings/', views.rea_riga_buildings_api, name='rea-riga-buildings-api'),
    path('list/', views.digitaltwins_list, name='digitaltwins-list'),
    path('cea-hydrogen/ai-scenario-generation/', views.cea_ai_scenario_generation, name='cea-ai-scenario-generation'),
    path('cea-hydrogen/dt-simulation/', views.cea_dt_simulation, name='cea-dt-simulation'),
    path('ber-hydrogen/ber-hydrogen-dt/', views.ber_hydrogen_dt, name='ber-hydrogen-dt'),
    path('ber-hydrogen/ber-hydrogen-dt/documentation/', views.ber_hydrogen_documentation, name='ber-hydrogen-documentation'),
    path('ber-hydrogen/ber-hydrogen-results/', views.ber_hydrogen_results, name='ber-hydrogen-results'),
    path('cartif-hydrogen/cartif-hydrogen-dt/', views.cartif_hydrogen_dt, name='cartif-hydrogen-dt'),
    path('antrodoco/engreen-antrodoco-dt/', views.engreen_antrodoco_dt, name='engreen-antrodoco-dt'),
    path('antrodoco/engreen-antrodoco-dt/simulate/', views.engreen_pv_simulate, name='engreen-pv-simulate'),
    path('antrodoco/engreen-antrodoco-dt/stations/', views.engreen_stations_api, name='engreen-stations-api'),
    path('rdn-grid/rdn-grid-dt/', views.rdn_grid_dt, name='rdn-grid-dt'),
    path('rdn-grid/rdn-grid-dt/simulate/', views.rdn_grid_simulate, name='rdn-grid-simulate'),
    path('rdn-grid/rdn-grid-dt/follow/', views.rdn_grid_follow_lookup, name='rdn-grid-follow'),
    path('results/save/', views.dt_save_result, name='dt-save-result'),
    path('<slug:slug>/', views.digitaltwins_detail, name='digitaltwins-detail'),
]

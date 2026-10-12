"""Routes of the digital twins, mounted under digitaltwins/.

Each twin with its own package keeps its routes there; URL names are global (no
app namespace) because templates across the platform reverse them and their paths
are already in emails sent to users.
"""

from django.urls import include, path

from . import pages

urlpatterns = [
    path('riga/rea-riga-dt/', include('digitaltwins.riga.urls')),
    path('list/', pages.digitaltwins_list, name='digitaltwins-list'),
    path('cea-hydrogen/ai-scenario-generation/', pages.cea_ai_scenario_generation, name='cea-ai-scenario-generation'),
    path('cea-hydrogen/dt-simulation/', pages.cea_dt_simulation, name='cea-dt-simulation'),
    path('cea-hydrogen/dt-simulation/documentation/', pages.cea_dt_documentation, name='cea-dt-simulation-documentation'),
    path('ber-hydrogen/ber-hydrogen-dt/', include('digitaltwins.ber.urls')),
    path('cartif-hydrogen/cartif-hydrogen-dt/', pages.cartif_hydrogen_dt, name='cartif-hydrogen-dt'),
    path('antrodoco/engreen-antrodoco-dt/', include('digitaltwins.engreen.urls')),
    path('ciemat/ciemat-forecasting-dt/', include('digitaltwins.ciemat.urls')),
    path('rdn-grid/rdn-grid-dt/', include('digitaltwins.rdn.urls')),
    path('results/save/', pages.dt_save_result, name='dt-save-result'),
    # Last: the <slug> catch-all would otherwise shadow the fixed routes above.
    path('<slug:slug>/', pages.digitaltwins_detail, name='digitaltwins-detail'),
]

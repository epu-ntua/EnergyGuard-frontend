"""The digital twins listed on the platform.

Each twin's overview page is the template digitaltwins/<slug>.html.
"""

DIGITAL_TWINS = [
    {
        'slug': 'rdn-grid',
        'name': 'Large-Scale Portuguese Transmission Network',
        'description': "A comprehensive Digital Twin of Portugal's large-scale transmission grid, designed to support power systems with high shares of renewable energy.",
        'image': 'assets/img/digital_twins/thumbs/RDN.webp',
    },
    {
        'slug': 'ciemat-microgrid',
        'name': 'CIEMAT Microgrid with Distributed Energy Resources',
        'description': 'A real renewable microgrid with solar, wind, storage, and hydrogen integration, supported by a Digital Twin for testing intelligent energy management strategies.',
        'image': 'assets/img/digital_twins/thumbs/Ceder-Lubia.webp',
    },
    {
        'slug': 'cea-hydrogen',
        'name': 'Solid Oxide Electrolysis Cell System',
        'description': 'A physics-based Digital Twin of a Solid Oxide Electrolysis Cell (SOEC) system, enabling scenario configuration, simulation execution, and performance analysis.',
        'image': 'assets/img/digital_twins/thumbs/hydrogenCEA.webp',
    },
    {
        'slug': 'ber-hydrogen',
        'name': 'PEM Electrolyzer Testing Facility',
        'description': 'Physical PEM Electrolyzer Testing Facility. Experiments are executed manually by the BER laboratory team.',
        'image': 'assets/img/digital_twins/thumbs/BER.webp',
    },
    {
        'slug': 'cartif-hydrogen',
        'name': 'CARTIF Hybrid Hydrogen-Electrical-Thermal Energy System',
        'description': 'Hybrid hydrogen-electric-thermal energy system combining hydrogen production, storage, batteries, and thermal storage for Digital Twin-based simulation and AI optimization.',
        'image': 'assets/img/digital_twins/thumbs/DT_CARTIF updated.webp',
    },
    {
        'slug': 'rea-riga',
        'name': "Riga's Multi-Apartment Residential Buildings",
        'description': "A city-scale Digital Twin of Riga's residential buildings, supporting energy efficiency analysis and renovation planning.",
        'image': 'assets/img/digital_twins/thumbs/REA.webp',
    },
    {
        'slug': 'engreen-antrodoco',
        'name': 'Antrodoco Renewable Energy Community',
        'description': 'A renewable energy community, digitally modelled for community-level energy management and optimization.',
        'image': 'assets/img/digital_twins/thumbs/antrodoco.webp',
    },
]

DT_BY_SLUG = {dt['slug']: dt for dt in DIGITAL_TWINS}

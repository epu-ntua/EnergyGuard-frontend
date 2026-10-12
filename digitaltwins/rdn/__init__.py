"""RDN Grid DT: simulations on R&D Nester's large-scale Portuguese transmission network.

Calls the real RDN Digital Twin API (services/client.py). RDN jobs run for many
minutes to over an hour, so simulation is asynchronous: the simulate view uploads
the input and returns immediately, tasks.py polls RDN in the background (via
django_q), and the frontend polls the job-status view.
"""

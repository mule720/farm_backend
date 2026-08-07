import multiprocessing

# Bind
bind = "0.0.0.0:8000"

# Workers: 2 * CPU cores + 1 (good for I/O-bound Django)
workers = multiprocessing.cpu_count() * 2 + 1

# Worker type — sync is fine for Django + graphene
worker_class = "sync"

# Timeout — raise for long AI vision calls
timeout = 120
graceful_timeout = 30
keepalive = 5

# Logging — stdout/stderr so GKE captures them
accesslog = "-"
errorlog = "-"
loglevel = "info"

# Reload on code change in dev (disabled in prod via env)
reload = False

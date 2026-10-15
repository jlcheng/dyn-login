bind = "0.0.0.0:8000"
workers = 2
threads = 4
timeout = 30
accesslog = "-"
errorlog = "-"
# U contains only the path. Never log the query string or form body.
access_log_format = "%(m)s %(U)s %(s)s %(L)s"

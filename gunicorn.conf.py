# Gunicorn reads this file automatically, so the Render start command stays
# just "gunicorn app:app". Render provides $PORT; gunicorn binds to it.
# 2 workers x 4 threads = 8 requests at once. Each worker has its own DB pool
# (max 5), so at most 10 DB connections, within Supabase's free pooler limit.
workers = 2
threads = 4
timeout = 60
accesslog = "-"   # request lines only (no headers, no cookies, no secrets)

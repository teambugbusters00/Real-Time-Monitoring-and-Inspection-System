"""
WSGI config for dosje_backend project.

The Render service uses the repository's WSGI entrypoint directly. We run
database migrations once during process startup so a newly provisioned Neon
database is usable even when the Render dashboard still has an older build
command configured.
"""

import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dosje_backend.settings')

import django
from django.core.management import call_command

django.setup()

# Render's existing service configuration may not run "manage.py migrate"
# during the build. Keep migrations safe and automatic at startup.
if os.environ.get('RUN_MIGRATIONS_ON_STARTUP', 'true').lower() in ('1', 'true', 'yes', 'on'):
    call_command('migrate', interactive=False, verbosity=0)

# If Render provides DJANGO_SUPERUSER_* variables, create the admin account once.
if os.environ.get('DJANGO_SUPERUSER_USERNAME') and os.environ.get('DJANGO_SUPERUSER_PASSWORD'):
    try:
        call_command('createsuperuser', interactive=False, verbosity=0)
    except Exception:
        pass

if os.environ.get('RUN_SEED_DATA_ON_STARTUP', 'false').lower() in ('1', 'true', 'yes', 'on'):
    call_command('seed_data', verbosity=0)

from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()

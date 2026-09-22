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

from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()

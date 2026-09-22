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

# Bootstrap the first NIRIKSHAN Super Admin from Render environment variables.
# This is separate from Django's raw /django-admin/ account and uses the same
# email + password login as every other NIRIKSHAN role.
if os.environ.get('DJANGO_SUPERUSER_USERNAME') and os.environ.get('DJANGO_SUPERUSER_PASSWORD'):
    try:
        from accounts.models import User
        username = os.environ['DJANGO_SUPERUSER_USERNAME'].strip()
        password = os.environ['DJANGO_SUPERUSER_PASSWORD']
        email = os.environ.get('DJANGO_SUPERUSER_EMAIL', '').strip().lower()
        if '@' in username and not email:
            email = username.lower()
        user = User.objects.filter(username=username).first()
        if user is None:
            if not email:
                email = f'{username.lower()}@nirikshan.local'
            user = User(
                username=username,
                email=email,
                role='super_admin',
                is_active=True,
                is_staff=True,
                is_superuser=True,
            )
            user.set_password(password)
            user.save()
        else:
            changed = []
            if user.role != 'super_admin':
                user.role = 'super_admin'
                changed.append('role')
            if not user.is_staff:
                user.is_staff = True
                changed.append('is_staff')
            if not user.is_superuser:
                user.is_superuser = True
                changed.append('is_superuser')
            if not user.is_active:
                user.is_active = True
                changed.append('is_active')
            if email and user.email.lower() != email:
                user.email = email
                changed.append('email')
            if changed:
                user.save(update_fields=changed)
    except Exception:
        # Never prevent Gunicorn from starting because bootstrap credentials
        # are absent or an existing database has a conflicting record.
        pass

if os.environ.get('RUN_SEED_DATA_ON_STARTUP', 'false').lower() in ('1', 'true', 'yes', 'on'):
    call_command('seed_data', verbosity=0)

from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()

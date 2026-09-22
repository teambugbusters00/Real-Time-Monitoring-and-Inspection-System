from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0006_alter_user_role'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='role',
            field=models.CharField(
                choices=[
                    ('super_admin', 'Super Admin'),
                    ('official', 'Official'),
                    ('inspector', 'Inspector'),
                    ('ngo', 'NGO'),
                    ('nss_volunteer', 'NSS Volunteer'),
                    ('citizen', 'Citizen'),
                ],
                max_length=20,
            ),
        ),
    ]

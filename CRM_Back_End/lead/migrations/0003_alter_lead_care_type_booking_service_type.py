from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('lead', '0002_leaddocument'),
    ]

    operations = [
        migrations.AlterField(
            model_name='lead',
            name='care_type',
            field=models.CharField(blank=True, choices=[('AT_HOME', 'At Home'), ('OPD', 'OPD'), ('IPD', 'IPD')], max_length=24),
        ),
        migrations.AlterField(
            model_name='booking',
            name='service_type',
            field=models.CharField(choices=[('AT_HOME', 'At Home'), ('OPD', 'OPD'), ('IPD', 'IPD')], max_length=24),
        ),
    ]

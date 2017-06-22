# -*- coding: utf-8 -*-
# Generated by Django 1.10.7 on 2017-06-14 19:34
from __future__ import unicode_literals

import corehq.warehouse.etl
import corehq.warehouse.models.shared
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('warehouse', '0003_userstagingtable'),
    ]

    operations = [
        migrations.CreateModel(
            name='ApplicationStatusFact',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('last_form_submission_date', models.DateTimeField(null=True)),
                ('last_sync_log_date', models.DateTimeField(null=True)),
                ('last_form_app_build_version', models.CharField(max_length=255)),
                ('last_form_app_commcare_version', models.CharField(max_length=255)),
                ('last_form_app_source', models.CharField(max_length=255)),
                ('last_sync_log_app_build_version', models.CharField(max_length=255)),
                ('last_sync_log_app_commcare_version', models.CharField(max_length=255)),
                ('last_sync_log_app_source', models.CharField(max_length=255)),
            ],
            options={
                'abstract': False,
            },
            bases=(models.Model, corehq.warehouse.models.shared.WarehouseTable, corehq.warehouse.etl.CustomSQLETLMixin),
        ),
        migrations.CreateModel(
            name='FormFact',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('form_id', models.CharField(max_length=255, unique=True)),
                ('domain', models.CharField(max_length=255)),
                ('app_id', models.CharField(max_length=255, null=True)),
                ('xmlns', models.CharField(max_length=255)),
                ('user_id', models.CharField(max_length=255, null=True)),
                ('received_on', models.DateTimeField(db_index=True)),
                ('deleted_on', models.DateTimeField(null=True)),
                ('edited_on', models.DateTimeField(null=True)),
                ('last_modified', models.DateTimeField(null=True)),
                ('build_id', models.CharField(max_length=255, null=True)),
                ('state', models.PositiveSmallIntegerField(choices=[(1, b'normal'), (2, b'archived'), (4, b'deprecated'), (8, b'duplicate'), (16, b'error'), (32, b'submission_error'), (64, b'deleted')])),
            ],
            options={
                'abstract': False,
            },
            bases=(models.Model, corehq.warehouse.models.shared.WarehouseTable, corehq.warehouse.etl.CustomSQLETLMixin),
        ),
        migrations.CreateModel(
            name='FormStagingTable',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('form_id', models.CharField(max_length=255, unique=True)),
                ('domain', models.CharField(default=None, max_length=255)),
                ('app_id', models.CharField(max_length=255, null=True)),
                ('xmlns', models.CharField(default=None, max_length=255)),
                ('user_id', models.CharField(max_length=255, null=True)),
                ('received_on', models.DateTimeField(db_index=True)),
                ('deleted_on', models.DateTimeField(null=True)),
                ('edited_on', models.DateTimeField(null=True)),
                ('build_id', models.CharField(max_length=255, null=True)),
                ('state', models.PositiveSmallIntegerField(choices=[(1, b'normal'), (2, b'archived'), (4, b'deprecated'), (8, b'duplicate'), (16, b'error'), (32, b'submission_error'), (64, b'deleted')], default=1)),
            ],
            options={
                'abstract': False,
            },
            bases=(models.Model, corehq.warehouse.models.shared.WarehouseTable, corehq.warehouse.etl.CouchToDjangoETLMixin),
        ),
        migrations.CreateModel(
            name='SyncLogStagingTable',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('sync_log_id', models.CharField(max_length=255)),
                ('sync_date', models.DateTimeField(null=True)),
                ('domain', models.CharField(max_length=255, null=True)),
                ('user_id', models.CharField(max_length=255, null=True)),
                ('build_id', models.CharField(max_length=255, null=True)),
                ('duration', models.IntegerField(null=True)),
            ],
            options={
                'abstract': False,
            },
            bases=(models.Model, corehq.warehouse.models.shared.WarehouseTable, corehq.warehouse.etl.CouchToDjangoETLMixin),
        ),
        migrations.AddField(
            model_name='domaindim',
            name='deleted',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='domainstagingtable',
            name='domain',
            field=models.CharField(default=None, max_length=100),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='groupdim',
            name='deleted',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='locationdim',
            name='deleted',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='userdim',
            name='deleted',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='userdim',
            name='doc_type',
            field=models.CharField(default=None, max_length=100),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='usergroupdim',
            name='deleted',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='userlocationdim',
            name='deleted',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='userstagingtable',
            name='domain',
            field=models.CharField(default=None, max_length=100),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='domaindim',
            name='creating_user_id',
            field=models.CharField(max_length=255, null=True),
        ),
        migrations.AlterField(
            model_name='domaindim',
            name='domain_created_on',
            field=models.DateTimeField(null=True),
        ),
        migrations.AlterField(
            model_name='domaindim',
            name='domain_last_modified',
            field=models.DateTimeField(null=True),
        ),
        migrations.AlterField(
            model_name='domaindim',
            name='first_domain_for_user',
            field=models.NullBooleanField(),
        ),
        migrations.AlterField(
            model_name='domaindim',
            name='hr_name',
            field=models.CharField(max_length=255, null=True),
        ),
        migrations.AlterField(
            model_name='domaindim',
            name='location_restriction_for_users',
            field=models.NullBooleanField(),
        ),
        migrations.AlterField(
            model_name='domaindim',
            name='project_type',
            field=models.CharField(max_length=255, null=True),
        ),
        migrations.AlterField(
            model_name='domaindim',
            name='use_sql_backend',
            field=models.NullBooleanField(),
        ),
        migrations.AlterField(
            model_name='domainstagingtable',
            name='domain_last_modified',
            field=models.DateTimeField(null=True),
        ),
        migrations.AlterField(
            model_name='userdim',
            name='email',
            field=models.CharField(max_length=255, null=True),
        ),
        migrations.AlterField(
            model_name='userdim',
            name='first_name',
            field=models.CharField(max_length=30, null=True),
        ),
        migrations.AlterField(
            model_name='userdim',
            name='is_active',
            field=models.NullBooleanField(),
        ),
        migrations.AlterField(
            model_name='userdim',
            name='is_staff',
            field=models.NullBooleanField(),
        ),
        migrations.AlterField(
            model_name='userdim',
            name='is_superuser',
            field=models.NullBooleanField(),
        ),
        migrations.AlterField(
            model_name='userdim',
            name='last_login',
            field=models.DateTimeField(null=True),
        ),
        migrations.AlterField(
            model_name='userdim',
            name='last_name',
            field=models.CharField(max_length=30, null=True),
        ),
        migrations.AddField(
            model_name='formfact',
            name='domain_dim',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='warehouse.DomainDim'),
        ),
        migrations.AddField(
            model_name='formfact',
            name='user_dim',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='warehouse.UserDim'),
        ),
        migrations.AddField(
            model_name='applicationstatusfact',
            name='user_dim',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='warehouse.UserDim'),
        ),
    ]
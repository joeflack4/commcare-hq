from base64 import b64decode
import bz2
from datetime import datetime
import logging

from celery.schedules import crontab
from celery.task import periodic_task, task

from corehq import toggles
from corehq.motech.dhis2.dbaccessors import get_dhis2_connection, get_dataset_maps
from corehq.motech.dhis2.api import JsonApiRequest
from corehq.motech.dhis2.models import JsonApiLog
from corehq.motech.dhis2.utils import fetch_dhis2_id_display_names
from dimagi.utils.couch import get_redis_client
from toggle.shortcuts import find_domains_with_toggle_enabled


EXPIRE_TIME = 60 * 60 * 24


@task(queue='background_queue')
def send_datasets(domain_name, send_now=False, send_date=None):
    """
    Sends a data set of data values in the following format:

    {
      "dataSet": "dataSetID",
      "completeDate": "date",
      "period": "period",
      "orgUnit": "orgUnitID",
      "attributeOptionCombo", "aocID",
      "dataValues": [
        { "dataElement": "dataElementID", "categoryOptionCombo": "cocID", "value": "1", "comment": "comment1" },
        { "dataElement": "dataElementID", "categoryOptionCombo": "cocID", "value": "2", "comment": "comment2" },
        { "dataElement": "dataElementID", "categoryOptionCombo": "cocID", "value": "3", "comment": "comment3" }
      ]
    }

    See DHIS2 API docs for more details: https://docs.dhis2.org/master/en/developer/html/webapi_data_values.html

    """
    if not send_date:
        send_date = datetime.today()
    dhis2_conn = get_dhis2_connection(domain_name)
    dataset_maps = get_dataset_maps(domain_name)
    if not dhis2_conn or not dataset_maps:
        return  # Nothing to do
    api = JsonApiRequest(
        dhis2_conn.server_url,
        dhis2_conn.username,
        bz2.decompress(b64decode(dhis2_conn.password)),
        domain_name=domain_name,
    )
    endpoint = 'dataValueSets'
    for dataset_map in dataset_maps:
        if send_now or dataset_map.should_send_on_date(send_date):
            try:
                dataset = dataset_map.get_dataset(send_date)
            except Exception as err:
                domain_log_level = getattr(dhis2_conn, 'log_level', logging.INFO)
                log_level = logging.ERROR
                if log_level >= domain_log_level:
                    JsonApiLog.log(
                        log_level,
                        api,
                        str(err),
                        response_status=None,
                        response_body=None,
                        method_func=api.post,
                        request_url=api.get_request_url(endpoint),
                    )
            else:
                api.post(endpoint, dataset)


@periodic_task(
    run_every=crontab(minute=3, hour=3),
    queue='background_queue'
)
def send_datasets_for_all_domains():
    for domain_name in find_domains_with_toggle_enabled(toggles.DHIS2_INTEGRATION):
        send_datasets(domain_name)


@task(queue='background_queue')
def refresh_dhis2_name_cache(domain_name):
    dhis2_conn = get_dhis2_connection(domain_name)
    api = JsonApiRequest(
        dhis2_conn.server_url,
        dhis2_conn.username,
        bz2.decompress(b64decode(dhis2_conn.password)),
        domain_name=domain_name,
    )
    data_sets = fetch_dhis2_id_display_names(api)
    modified = datetime.utcnow()
    cache = get_redis_client()
    key = domain_name + '_dhis2_id_display_names'
    cache.set(key, {
        'modified_at': modified,
        'data_sets': data_sets,
    })
    cache.expire(key, EXPIRE_TIME)

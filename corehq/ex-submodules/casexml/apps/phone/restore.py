from __future__ import absolute_import

import logging
import os
import shutil
import tempfile
from io import FileIO
from cStringIO import StringIO
from uuid import uuid4
from distutils.version import LooseVersion
from datetime import datetime, timedelta
from wsgiref.util import FileWrapper
from xml.etree import cElementTree as ElementTree

import six
from celery.exceptions import TimeoutError
from celery.result import AsyncResult
from couchdbkit import ResourceNotFound
from django.http import HttpResponse, StreamingHttpResponse
from django.conf import settings

from casexml.apps.phone.data_providers import get_element_providers, get_async_providers
from casexml.apps.phone.exceptions import (
    MissingSyncLog, InvalidSyncLogException, SyncLogUserMismatch,
    BadStateException, RestoreException, DateOpenedBugException,
)
from casexml.apps.phone.restore_caching import AsyncRestoreTaskIdCache, RestorePayloadPathCache
from casexml.apps.phone.tasks import get_async_restore_payload, ASYNC_RESTORE_SENT
from corehq.toggles import EXTENSION_CASES_SYNC_ENABLED, LIVEQUERY_SYNC, ICDS_LIVEQUERY, NAMESPACE_USER
from corehq.util.datadog.utils import bucket_value
from corehq.util.timer import TimingContext
from corehq.util.datadog.gauges import datadog_counter
from dimagi.utils.decorators.memoized import memoized
from dimagi.utils.parsing import json_format_datetime
from casexml.apps.phone.models import (
    get_properly_wrapped_sync_log,
    LOG_FORMAT_LIVEQUERY,
    OTARestoreUser,
    SimplifiedSyncLog,
    SyncLog,
)
from dimagi.utils.couch.database import get_db
from casexml.apps.phone import xml as xml_util
from couchforms.openrosa_response import (
    ResponseNature,
    get_simple_response_xml,
    get_response_element,
)
from casexml.apps.case.xml import check_version, V1
from casexml.apps.phone.checksum import CaseStateHash
from casexml.apps.phone.const import (
    INITIAL_SYNC_CACHE_TIMEOUT,
    INITIAL_SYNC_CACHE_THRESHOLD,
    INITIAL_ASYNC_TIMEOUT_THRESHOLD,
    ASYNC_RETRY_AFTER,
    CLEAN_OWNERS,
    LIVEQUERY,
)
from casexml.apps.phone.xml import get_sync_element, get_progress_element
from corehq.blobs import get_blob_db
from corehq.blobs.exceptions import NotFound


logger = logging.getLogger(__name__)

DEFAULT_CASE_SYNC = CLEAN_OWNERS


def stream_response(payload, headers=None, status=200):
    try:
        response = StreamingHttpResponse(
            FileWrapper(payload),
            content_type="text/xml; charset=utf-8",
            status=status
        )
        if headers:
            for header, value in headers.items():
                response[header] = value
        return response
    except IOError as e:
        return HttpResponse(e, status=500)


class StockSettings(object):

    def __init__(self, section_to_consumption_types=None, consumption_config=None,
                 default_product_list=None, force_consumption_case_filter=None,
                 sync_consumption_ledger=False):
        """
        section_to_consumption_types should be a dict of stock section-ids to corresponding
        consumption section-ids. any stock sections not found in the dict will not have
        any consumption data set in the restore.

        force_consumption_case_filter allows you to force sending consumption data even if
        empty for a given CaseStub (id + type)
        """
        self.section_to_consumption_types = section_to_consumption_types or {}
        self.consumption_config = consumption_config
        self.default_product_list = default_product_list or []
        self.force_consumption_case_filter = force_consumption_case_filter or (lambda stub: False)
        self.sync_consumption_ledger = sync_consumption_ledger


class RestoreContent(object):
    start_tag_template = (
        b'<OpenRosaResponse xmlns="http://openrosa.org/http/response"%(items)s>'
        b'<message nature="%(nature)s">Successfully restored account %(username)s!</message>'
    )
    items_template = b' items="%s"'
    closing_tag = b'</OpenRosaResponse>'

    def __init__(self, username=None, items=False):
        self.username = username
        self.items = items
        self.num_items = 0

    def __enter__(self):
        self.response_body = tempfile.TemporaryFile('w+b')
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.response_body.close()

    def append(self, xml_element):
        self.num_items += 1
        if isinstance(xml_element, six.binary_type):
            self.response_body.write(xml_element)
        else:
            self.response_body.write(xml_util.tostring(xml_element))

    def extend(self, iterable):
        for element in iterable:
            self.append(element)

    def _write_to_file(self, fileobj):
        # Add 1 to num_items to account for message element
        items = (self.items_template % (self.num_items + 1)) if self.items else b''
        fileobj.write(self.start_tag_template % {
            b"items": items,
            b"username": self.username.encode("utf8"),
            b"nature": ResponseNature.OTA_RESTORE_SUCCESS.encode("utf8"),
        })

        self.response_body.seek(0)
        shutil.copyfileobj(self.response_body, fileobj)

        fileobj.write(self.closing_tag)

    def get_fileobj(self):
        fileobj = tempfile.TemporaryFile('w+b')
        try:
            self._write_to_file(fileobj)
            fileobj.seek(0)
            return fileobj
        except:
            fileobj.close()
            raise


class RestoreResponse(object):

    def __init__(self, fileobj):
        self.fileobj = fileobj

    def as_file(self):
        return self.fileobj

    def as_string(self):
        """Get content as utf8-encoded bytes

        NOTE: This method is only used in tests.
        Cannot be called more than once, and `self.as_file()` will
        return a closed file after this is called.
        """
        with self.fileobj:
            return self.fileobj.read()

    def get_http_response(self):
        self.fileobj.seek(0, os.SEEK_END)
        headers = {'Content-Length': self.fileobj.tell()}
        self.fileobj.seek(0)
        return stream_response(self.fileobj, headers)


class AsyncRestoreResponse(object):

    def __init__(self, task, username):
        self.task = task
        self.username = username

        task_info = self.task.info if self.task.info and isinstance(self.task.info, dict) else {}
        self.progress = {
            'done': task_info.get('done', 0),
            'total': task_info.get('total', 0),
            'retry_after': task_info.get('retry-after', ASYNC_RETRY_AFTER),
        }

    def compile_response(self):
        root = get_response_element(
            message="Asynchronous restore under way for {}".format(self.username),
            nature=ResponseNature.OTA_RESTORE_PENDING
        )
        sync_tag = get_sync_element()
        sync_tag.append(get_progress_element(**self.progress))
        root.append(sync_tag)

        return ElementTree.tostring(root, encoding='utf-8')

    def get_http_response(self):
        headers = {"Retry-After": self.progress['retry_after']}
        response = stream_response(
            StringIO(self.compile_response()),
            status=202,
            headers=headers,
        )
        return response


class CachedResponse(object):

    def __init__(self, name):
        self.name = name

    @classmethod
    def save_for_later(cls, fileobj, timeout):
        """Save restore response for later

        :param fileobj: A file-like object.
        :param timeout: Minimum content expiration in seconds.
        :returns: A new `CachedResponse` pointing to the saved content.
        """
        name = 'restore-response-{}.xml'.format(uuid4().hex)
        get_blob_db().put(NoClose(fileobj), name, timeout=max(timeout // 60, 60))
        return cls(name)

    def __nonzero__(self):
        try:
            return bool(self.as_file())
        except NotFound:
            return False

    def as_string(self):
        with self.as_file() as fileobj:
            return fileobj.read()

    def as_file(self):
        try:
            value = self._fileobj
        except AttributeError:
            value = get_blob_db().get(self.name) if self.name else None
            self._fileobj = value
        return value

    def get_http_response(self):
        headers = {'Content-Length': get_blob_db().size(self.name)}
        return stream_response(self.as_file(), headers)


class RestoreParams(object):
    """
    Lightweight class that just handles grouping the possible attributes of a restore together.

    This is just for user-defined settings that can be configured via the URL.

    :param sync_log_id:         ID of the previous restore
    :param version:             The version of the restore format
    :param state_hash:          The case state hash string to use to verify the state of the phone
    :param include_item_count:  Set to `True` to include the item count in the response
    :param device_id:           The Device id of the device restoring
    """

    def __init__(self,
            sync_log_id='',
            version=V1,
            state_hash='',
            include_item_count=False,
            device_id=None,
            app=None,
            openrosa_version=None):
        self.sync_log_id = sync_log_id
        self.version = version
        self.state_hash = state_hash
        self.include_item_count = include_item_count
        self.app = app
        self.device_id = device_id
        self.openrosa_version = (LooseVersion(openrosa_version)
            if isinstance(openrosa_version, basestring) else openrosa_version)

    @property
    def app_id(self):
        return self.app._id if self.app else None


class RestoreCacheSettings(object):
    """
    Settings related to restore caching. These only apply if doing an initial restore and
    are not used if `RestoreParams.sync_log_id` is set.

    :param force_cache:     Set to `True` to force the response to be cached.
    :param cache_timeout:   Override the default cache timeout of 1 hour.
    :param overwrite_cache: Ignore any previously cached value and re-generate the restore response.
    """

    def __init__(self, force_cache=False, cache_timeout=None, overwrite_cache=False):
        self.force_cache = force_cache
        self.cache_timeout = cache_timeout if cache_timeout is not None else INITIAL_SYNC_CACHE_TIMEOUT
        self.overwrite_cache = overwrite_cache


class RestoreState(object):
    """
    The RestoreState object can be passed around to multiple restore data providers.

    This allows the providers to set values on the state, for either logging or performance
    reasons.
    """

    def __init__(self, project, restore_user, params, async=False,
                 overwrite_cache=False, case_sync=None):
        if not project or not project.name:
            raise Exception('you are not allowed to make a RestoreState without a domain!')

        self.project = project
        self.domain = project.name

        self.restore_user = restore_user
        self.params = params
        self.provider_log = {}  # individual data providers can log stuff here
        # get set in the start_sync() function
        self.start_time = None
        self.duration = None
        self.current_sync_log = None
        self.async = async
        self.overwrite_cache = overwrite_cache
        self._last_sync_log = Ellipsis

        if case_sync is None:
            username = self.restore_user.username
            if LIVEQUERY_SYNC.enabled(self.domain):
                case_sync = LIVEQUERY
            elif self.domain == 'icds-cas' and ICDS_LIVEQUERY.enabled(username, namespace=NAMESPACE_USER):
                case_sync = LIVEQUERY
            else:
                case_sync = DEFAULT_CASE_SYNC
        if case_sync not in [LIVEQUERY, CLEAN_OWNERS]:
            raise ValueError("unknown case sync algorithm: %s" % case_sync)
        self._case_sync = case_sync
        self.is_livequery = case_sync == LIVEQUERY

    def validate_state(self):
        check_version(self.params.version)
        if self.last_sync_log:
            if (self._case_sync == CLEAN_OWNERS and
                    self.last_sync_log.log_format == LOG_FORMAT_LIVEQUERY):
                raise RestoreException("clean_owners sync after livequery sync")
            if self.params.state_hash:
                parsed_hash = CaseStateHash.parse(self.params.state_hash)
                computed_hash = self.last_sync_log.get_state_hash()
                if computed_hash != parsed_hash:
                    # log state error on the sync log
                    self.last_sync_log.had_state_error = True
                    self.last_sync_log.error_date = datetime.utcnow()
                    self.last_sync_log.error_hash = str(parsed_hash)
                    self.last_sync_log.save()

                    raise BadStateException(
                        server_hash=computed_hash,
                        phone_hash=parsed_hash,
                        case_ids=self.last_sync_log.get_footprint_of_cases_on_phone()
                    )

    @property
    def last_sync_log(self):
        if self._last_sync_log is Ellipsis:
            if self.params.sync_log_id:
                try:
                    sync_log = get_properly_wrapped_sync_log(self.params.sync_log_id)
                    if settings.SERVER_ENVIRONMENT == "production":
                        self._check_for_date_opened_bug(sync_log)
                except ResourceNotFound:
                    # if we are in loose mode, return an HTTP 412 so that the phone will
                    # just force a fresh sync
                    raise MissingSyncLog('No sync log with ID {} found'.format(self.params.sync_log_id))
                if sync_log.doc_type != 'SyncLog':
                    raise InvalidSyncLogException('Bad sync log doc type for {}'.format(self.params.sync_log_id))
                elif sync_log.user_id != self.restore_user.user_id:
                    raise SyncLogUserMismatch('Sync log {} does not match user id {} (was {})'.format(
                        self.params.sync_log_id, self.restore_user.user_id, sync_log.user_id
                    ))

                # convert to the right type if necessary
                if not isinstance(sync_log, SimplifiedSyncLog):
                    # this call can fail with an IncompatibleSyncLogType error
                    sync_log = SimplifiedSyncLog.from_other_format(sync_log)
                self._last_sync_log = sync_log
            else:
                self._last_sync_log = None
        return self._last_sync_log

    def _check_for_date_opened_bug(self, sync_log):
        introduced_date = datetime(2016, 7, 19, 19, 15)
        reverted_date = datetime(2016, 7, 20, 9, 15)  # date bug was reverted on HQ
        resolved_date = datetime(2016, 7, 21, 0, 0)  # approximate date this fix was deployed

        if introduced_date < sync_log.date < reverted_date:
            raise DateOpenedBugException(self.restore_user, sync_log._id)

        # if the last synclog was before the time we pushed out this resolution,
        # we also need to check that they don't have a bad sync
        if reverted_date <= sync_log.date < resolved_date:
            synclogs = SyncLog.view(
                "phone/sync_logs_by_user",
                reduce=True,
                startkey=[sync_log.user_id, json_format_datetime(introduced_date), None],
                endkey=[sync_log.user_id, json_format_datetime(reverted_date), {}],
            ).first()
            if synclogs and synclogs.get('value') != 0:
                raise DateOpenedBugException(self.restore_user, sync_log._id)

    @property
    def is_initial(self):
        return self.last_sync_log is None

    @property
    def version(self):
        return self.params.version

    @property
    @memoized
    def owner_ids(self):
        return set(self.restore_user.get_owner_ids())

    @property
    @memoized
    def stock_settings(self):
        if self.project and self.project.commtrack_settings:
            return self.project.commtrack_settings.get_ota_restore_settings()
        else:
            return StockSettings()

    @property
    def is_first_extension_sync(self):
        extension_toggle_enabled = EXTENSION_CASES_SYNC_ENABLED.enabled(self.domain)
        try:
            return extension_toggle_enabled and not self.last_sync_log.extensions_checked
        except AttributeError:
            return extension_toggle_enabled

    def start_sync(self):
        self.start_time = datetime.utcnow()
        self.current_sync_log = self._new_sync_log()

    def finish_sync(self):
        self.duration = datetime.utcnow() - self.start_time
        self.current_sync_log.duration = self.duration.seconds
        self.current_sync_log.save()

    def _new_sync_log(self):
        previous_log_id = None if self.is_initial else self.last_sync_log._id
        previous_log_rev = None if self.is_initial else self.last_sync_log._rev
        last_seq = str(get_db().info()["update_seq"])
        new_synclog = SimplifiedSyncLog(
            _id=SyncLog.get_db().server.next_uuid(),
            domain=self.restore_user.domain,
            build_id=self.params.app_id,
            user_id=self.restore_user.user_id,
            last_seq=last_seq,
            owner_ids_on_phone=set(self.owner_ids),
            date=datetime.utcnow(),
            previous_log_id=previous_log_id,
            previous_log_rev=previous_log_rev,
            extensions_checked=True,
        )
        if self.is_livequery:
            new_synclog.log_format = LOG_FORMAT_LIVEQUERY
        return new_synclog

    @property
    @memoized
    def loadtest_factor(self):
        return self.restore_user.loadtest_factor


class RestoreConfig(object):
    """
    A collection of attributes associated with an OTA restore

    :param project:         The domain object. An instance of `Domain`.
    :param restore_user:    The restore user requesting the restore
    :param params:          The RestoreParams associated with this (see above).
    :param cache_settings:  The RestoreCacheSettings associated with this (see above).
    :param async:           Whether to get the restore response using a celery task
    :param case_sync:       Case sync algorithm (None -> default).
    """

    def __init__(self, project=None, restore_user=None, params=None,
                 cache_settings=None, async=False, case_sync=None):
        assert isinstance(restore_user, OTARestoreUser)
        self.project = project
        self.domain = project.name if project else ''
        self.restore_user = restore_user
        self.params = params or RestoreParams()
        self.cache_settings = cache_settings or RestoreCacheSettings()
        self.async = async

        self.restore_state = RestoreState(
            self.project,
            self.restore_user,
            self.params, async,
            self.cache_settings.overwrite_cache,
            case_sync=case_sync,
        )

        self.force_cache = self.cache_settings.force_cache
        self.cache_timeout = self.cache_settings.cache_timeout
        self.overwrite_cache = self.cache_settings.overwrite_cache

        self.timing_context = TimingContext('restore-{}-{}'.format(self.domain, self.restore_user.username))

    @property
    @memoized
    def sync_log(self):
        return self.restore_state.last_sync_log

    @property
    def async_restore_task_id_cache(self):
        return AsyncRestoreTaskIdCache(
            domain=self.domain,
            user_id=self.restore_user.user_id,
            sync_log_id=self.sync_log._id if self.sync_log else '',
            device_id=self.params.device_id,
        )

    @property
    def restore_payload_path_cache(self):
        return RestorePayloadPathCache(
            domain=self.domain,
            user_id=self.restore_user.user_id,
            sync_log_id=self.sync_log._id if self.sync_log else '',
            device_id=self.params.device_id,
        )

    @property
    def initial_restore_payload_path_cache(self):
        return RestorePayloadPathCache(
            domain=self.domain,
            user_id=self.restore_user.user_id,
            sync_log_id='',
            device_id=self.params.device_id,
        )

    def get_response(self):
        async = self.async
        try:
            with self.timing_context:
                payload = self.get_payload()
            response = payload.get_http_response()
        except RestoreException as e:
            logging.exception("%s error during restore submitted by %s: %s" %
                              (type(e).__name__, self.restore_user.username, str(e)))
            async = False
            response = get_simple_response_xml(
                e.message,
                ResponseNature.OTA_RESTORE_ERROR
            )
            response = HttpResponse(response, content_type="text/xml; charset=utf-8",
                                    status=412)  # precondition failed
        if not async:
            self._record_timing(response.status_code)
        return response

    def get_payload(self):
        self.validate()
        self.delete_initial_cached_payload_if_necessary()
        self.delete_cached_payload_if_necessary()

        cached_response = self.get_cached_response()
        tags = [
            u'domain:{}'.format(self.domain),
            u'is_initial:{}'.format(not bool(self.sync_log)),
        ]
        if cached_response:
            datadog_counter('commcare.restores.cache_hits.count', tags=tags)
            return cached_response
        datadog_counter('commcare.restores.cache_misses.count', tags=tags)

        # Start new sync
        if self.async:
            response = self._get_asynchronous_payload()
        else:
            response = self.generate_payload()

        return response

    def validate(self):
        try:
            self.restore_state.validate_state()
        except InvalidSyncLogException as e:
            # This exception will get caught by the view and a 412 will be returned to the phone for resync
            raise RestoreException(e)

    def get_cached_response(self):
        if self.overwrite_cache:
            return None

        cache_payload_path = self.restore_payload_path_cache.get_value()

        return CachedResponse(cache_payload_path)

    def generate_payload(self, async_task=None):
        if async_task:
            self.timing_context.stop("wait_for_task_to_start")
        self.restore_state.start_sync()
        fileobj = self._generate_restore_response(async_task=async_task)
        try:
            self.restore_state.finish_sync()
            cached_response = self.set_cached_payload_if_necessary(
                fileobj, self.restore_state.duration, async_task)
            if async_task:
                fileobj.close()
                assert cached_response is not None
                response = cached_response
                self.timing_context.stop()  # root timer
                self._record_timing('async')
            else:
                fileobj.seek(0)
                response = RestoreResponse(fileobj)
        except:
            fileobj.close()
            raise
        return response

    def _get_asynchronous_payload(self):
        new_task = False
        # fetch the task from celery
        task_id = self.async_restore_task_id_cache.get_value()
        task = AsyncResult(task_id)
        task_exists = task.status == ASYNC_RESTORE_SENT

        if not task_exists:
            # start a new task
            # NOTE this starts a nested timer (wait_for_task_to_start),
            # which will be stopped by self.generate_payload(async_task)
            # in the asynchronous task. It is expected that
            # get_async_restore_payload.delay(self) will serialize this
            # RestoreConfig and it's associated TimingContext before it
            # returns, and thereby fork the timing context. The timing
            # context associated with this side of the fork will not be
            # recorded since it is async (see self.get_response).
            with self.timing_context("wait_for_task_to_start"):
                task = get_async_restore_payload.delay(self)
            new_task = True
            # store the task id in cache
            self.async_restore_task_id_cache.set_value(task.id)
        try:
            response = task.get(timeout=self._get_task_timeout(new_task))
        except TimeoutError:
            # return a 202 with progress
            response = AsyncRestoreResponse(task, self.restore_user.username)

        return response

    def _get_task_timeout(self, new_task):
        # if this is a new task, wait for INITIAL_ASYNC_TIMEOUT in case
        # this restore completes quickly. otherwise, only wait 1 second for
        # a response.
        return INITIAL_ASYNC_TIMEOUT_THRESHOLD if new_task else 1

    def _generate_restore_response(self, async_task=None):
        """
        :returns: A file-like object containing response content.
        """
        username = self.restore_user.username
        count_items = self.params.include_item_count
        with RestoreContent(username, count_items) as content:
            for provider in get_element_providers(self.timing_context):
                with self.timing_context(provider.__class__.__name__):
                    content.extend(provider.get_elements(self.restore_state))

            for provider in get_async_providers(self.timing_context, async_task):
                with self.timing_context(provider.__class__.__name__):
                    provider.extend_response(self.restore_state, content)

            return content.get_fileobj()

    def set_cached_payload_if_necessary(self, fileobj, duration, async):
        # on initial sync, only cache if the duration was longer than the threshold
        is_long_restore = duration > timedelta(seconds=INITIAL_SYNC_CACHE_THRESHOLD)

        if async or self.force_cache or is_long_restore or self.sync_log:
            response = CachedResponse.save_for_later(fileobj, self.cache_timeout)
            self.restore_payload_path_cache.set_value(response.name, self.cache_timeout)
            return response
        return None

    def delete_cached_payload_if_necessary(self):
        if self.overwrite_cache and self.restore_payload_path_cache.get_value():
            self.restore_payload_path_cache.invalidate()

    def delete_initial_cached_payload_if_necessary(self):
        if self.sync_log:
            # Restores are usually cached by there sync token
            # but initial restores don't have a sync token,
            # so they're indistinguishable from each other.
            # Once a user syncs with a sync token, we're sure their initial sync is stale,
            # so delete it to avoid a stale payload if they (say) wipe the phone and sync again
            self.initial_restore_payload_path_cache.invalidate()

    def _record_timing(self, status):
        timing = self.timing_context
        assert timing.is_finished()
        duration = timing.duration if timing is not None else -1
        device_id = self.params.device_id
        if duration > 20 or status == 412:
            if status == 412:
                # use last sync log since there is no current sync log
                sync_log_id = self.params.sync_log_id or 'N/A'
            else:
                sync_log = self.restore_state.current_sync_log
                sync_log_id = sync_log._id if sync_log else 'N/A'
            log = logging.getLogger(__name__)
            log.info(
                "restore %s: user=%s device=%s domain=%s status=%s duration=%.3f",
                sync_log_id,
                self.restore_user.username,
                device_id,
                self.domain,
                status,
                duration,
            )
        is_webapps = device_id and device_id.startswith("WebAppsLogin")
        tags = [
            u'status_code:{}'.format(status),
            u'device_type:{}'.format('webapps' if is_webapps else 'other'),
        ]
        env = settings.SERVER_ENVIRONMENT
        if (env, self.domain) in settings.RESTORE_TIMING_DOMAINS:
            tags.append(u'domain:{}'.format(self.domain))
        if timing is not None:
            timer_buckets = (5, 20, 60, 120)
            for timer in timing.to_list(exclude_root=True):
                if timer.name in RESTORE_SEGMENTS:
                    segment = RESTORE_SEGMENTS[timer.name]
                    bucket = bucket_value(timer.duration, timer_buckets, 's')
                    datadog_counter(
                        'commcare.restores.{}'.format(segment),
                        tags=tags + ['duration:%s' % bucket],
                    )
            tags.append('duration:%s' % bucket_value(timing.duration, timer_buckets, 's'))
        datadog_counter('commcare.restores.count', tags=tags)


RESTORE_SEGMENTS = {
    "wait_for_task_to_start": "waiting",
    "FixtureElementProvider": "fixtures",
    "CasePayloadProvider": "cases",
}


class NoClose:
    """HACK file object with no-op `close()` to avoid close by S3Transfer

    https://github.com/boto/s3transfer/issues/80
    """

    def __init__(self, fileobj):
        self.fileobj = fileobj

    def __getattr__(self, name):
        return getattr(self.fileobj, name)

    def close(self):
        pass

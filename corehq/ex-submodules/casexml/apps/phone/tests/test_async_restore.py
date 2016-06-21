import mock
from django.test import TestCase, SimpleTestCase
from corehq.apps.app_manager.tests import TestXmlMixin

from celery.exceptions import TimeoutError
from celery.result import AsyncResult

from casexml.apps.case.xml import V2
from casexml.apps.case.mock import CaseFactory
from casexml.apps.case.tests.util import (
    delete_all_cases,
    delete_all_sync_logs,
 )
from corehq.apps.domain.models import Domain
from casexml.apps.phone.restore import (
    RestoreConfig,
    RestoreParams,
    AsyncRestoreResponse,
    FileRestoreResponse,
    restore_cache_key,
)
from casexml.apps.phone.const import(
    ASYNC_RESTORE_CACHE_KEY_PREFIX,
    ASYNC_RETRY_AFTER,
)
from casexml.apps.phone.tests.utils import create_restore_user
from corehq.apps.receiverwrapper.auth import AuthContext
from corehq.apps.users.dbaccessors.all_commcare_users import delete_all_users
from corehq.util.test_utils import flag_enabled


class AsyncRestoreTest(TestCase):
    dependent_apps = [
        'auditcare',
        'django_digest',
        'casexml.apps.phone',
        'casexml.apps.stock',
        'corehq.couchapps',
        'corehq.form_processor',
        'corehq.sql_accessors',
        'corehq.sql_proxy_accessors',
        'corehq.apps.domain',
        'corehq.apps.hqcase',
        'corehq.apps.products',
        'corehq.apps.reminders',
        'corehq.apps.sms',
        'corehq.apps.smsforms',
        'corehq.apps.notifications',
        'phonelog',
        'corehq.apps.domain',
    ]

    @classmethod
    def setUpClass(cls):
        super(AsyncRestoreTest, cls).setUpClass()
        delete_all_cases()
        delete_all_sync_logs()
        delete_all_users()
        cls.domain = 'dummy-project'
        cls.project = Domain(name=cls.domain)
        cls.project.save()
        cls.user = create_restore_user(domain=cls.domain)

    @classmethod
    def tearDownClass(cls):
        cls.project.delete()
        delete_all_cases()
        delete_all_sync_logs()
        delete_all_users()
        super(AsyncRestoreTest, cls).tearDownClass()

    def _restore_config(self, async=True, sync_log_id=''):
        restore_config = RestoreConfig(
            project=self.project,
            restore_user=self.user,
            params=RestoreParams(sync_log_id=sync_log_id, version=V2),
            async=async
        )
        self.addCleanup(restore_config.cache.clear)
        return restore_config

    @mock.patch('casexml.apps.phone.restore.get_async_restore_payload')
    def test_regular_restore_doesnt_start_task(self, task):
        """
        when the feature flag is off, the celery task does not get called
        """
        self._restore_config(async=False).get_payload()
        self.assertFalse(task.delay.called)

    @mock.patch('casexml.apps.phone.restore.get_async_restore_payload')
    def test_first_async_restore_kicks_off_task(self, task):
        delay = mock.MagicMock()
        delay.id = 'random_task_id'
        task.delay.return_value = delay

        self._restore_config(async=True).get_payload()
        self.assertTrue(task.delay.called)

    @mock.patch('casexml.apps.phone.restore.get_async_restore_payload')
    def test_restore_then_sync_on_same_synclog_returns_async_restore_response(self, task):
        delay = mock.MagicMock()
        delay.id = 'random_task_id'
        delay.get = mock.MagicMock(side_effect=TimeoutError())  # task not finished
        task.delay.return_value = delay

        restore_config = self._restore_config(async=True)
        initial_payload = restore_config.get_payload()
        self.assertTrue(isinstance(initial_payload, AsyncRestoreResponse))

        subsequent_restore = self._restore_config(async=True)
        subsequent_payload = subsequent_restore.get_payload()
        self.assertTrue(isinstance(subsequent_payload, AsyncRestoreResponse))

    def test_subsequent_syncs_when_job_complete(self):
        # First sync, return a timout. Ensure that the async_task_id gets set
        cache_id = restore_cache_key(ASYNC_RESTORE_CACHE_KEY_PREFIX, self.user.user_id)
        with mock.patch('casexml.apps.phone.restore.get_async_restore_payload') as task:
            delay = mock.MagicMock()
            delay.id = 'random_task_id'
            delay.get = mock.MagicMock(side_effect=TimeoutError())  # task not finished
            task.delay.return_value = delay

            restore_config = self._restore_config(async=True)
            initial_payload = restore_config.get_payload()
            self.assertIsNotNone(restore_config.cache.get(cache_id))
            self.assertTrue(isinstance(initial_payload, AsyncRestoreResponse))
            # new synclog should not have been created
            self.assertIsNone(restore_config.restore_state.current_sync_log)

        # Second sync, don't timeout (can't use AsyncResult in tests, so mock
        # the return value). Ensure that the synclog is updated properly
        with mock.patch.object(AsyncResult, 'get', mock.MagicMock(return_value=FileRestoreResponse())):
            subsequent_restore = self._restore_config(async=True)
            self.assertIsNotNone(restore_config.cache.get(cache_id))
            subsequent_payload = subsequent_restore.get_payload()
            self.assertIsNone(restore_config.cache.get(cache_id))
            self.assertTrue(isinstance(subsequent_payload, FileRestoreResponse))
            # a new synclog should not have been created
            self.assertIsNone(subsequent_restore.restore_state.current_sync_log)

    @flag_enabled('ASYNC_RESTORE')
    def test_restore_in_progress_form_submitted_kills_old_jobs(self):
        """If the user submits a form somehow while a job is running, the job should be terminated
        """
        cache_id = restore_cache_key(ASYNC_RESTORE_CACHE_KEY_PREFIX, self.user.user_id)
        fake_task_id = 'fake-task-id'
        restore_config = self._restore_config(async=True)
        # pretend we have a task running
        restore_config.cache.set(cache_id, fake_task_id)
        correct_user_factory = CaseFactory(
            domain=self.domain,
            form_extras={
                'auth_context': AuthContext(
                    authenticated=True,
                    domain=self.domain,
                    user_id=self.user.user_id
                ),
            }
        )
        other_user_factory = CaseFactory(
            domain=self.domain,
            form_extras={
                'auth_context': AuthContext(
                    authenticated=True,
                    domain=self.domain,
                    user_id='other_user'
                ),
            }
        )
        with mock.patch('corehq.form_processor.submission_post.revoke_celery_task') as revoke:
            # with a different user in the same domain, task doesn't get killed
            other_user_factory.create_case()
            self.assertFalse(revoke.called)
            self.assertEqual(restore_config.cache.get(cache_id), fake_task_id)

            # task gets killed when the user submits a form
            correct_user_factory.create_case()
            revoke.assert_called_with(fake_task_id)
            self.assertIsNone(restore_config.cache.get(cache_id))


class TestAsyncRestoreResponse(TestXmlMixin, SimpleTestCase):
    def setUp(self):
        self.task = mock.MagicMock()
        self.task.info = {'done': 25, 'total': 100}

        self.response = AsyncRestoreResponse(self.task)

    def test_response(self):
        expected = """
        <OpenRosaResponse xmlns="http://openrosa.org/http/response">
            <Sync xmlns="http://commcarehq.org/sync">
                <progress total="{total}" done="{done}" retry-after="{retry_after}"/>
            </Sync>
        </OpenRosaResponse>
        """.format(
            total=self.task.info['total'],
            done=self.task.info['done'],
            retry_after=ASYNC_RETRY_AFTER,
        )
        self.assertXmlEqual(self.response.compile_response(), expected)

    def test_html_response(self):
        http_response = self.response.get_http_response()
        self.assertEqual(http_response.status_code, 202)
        self.assertTrue(http_response.has_header('Retry-After'))
        self.assertEqual(http_response['retry-after'], str(ASYNC_RETRY_AFTER))
        self.assertXmlEqual(list(http_response.streaming_content)[0], self.response.compile_response())

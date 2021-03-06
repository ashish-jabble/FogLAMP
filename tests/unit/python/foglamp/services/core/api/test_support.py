# -*- coding: utf-8 -*-

# FOGLAMP_BEGIN
# See: http://foglamp.readthedocs.io/
# FOGLAMP_END

import pathlib
from pathlib import PosixPath

from unittest.mock import patch, mock_open, Mock, MagicMock

from aiohttp import web
import pytest

from foglamp.services.core import routes
from foglamp.services.core.api import support
from foglamp.services.core.support import *

__author__ = "Ashish Jabble"
__copyright__ = "Copyright (c) 2018 OSIsoft, LLC"
__license__ = "Apache 2.0"
__version__ = "${VERSION}"


@pytest.allure.feature("unit")
@pytest.allure.story("api", "bundle-support")
class TestBundleSupport:

    @pytest.fixture
    def client(self, loop, test_client):
        app = web.Application(loop=loop)
        # fill the routes table
        routes.setup(app)
        return loop.run_until_complete(test_client(app))

    @pytest.fixture
    def support_bundles_dir_path(self):
        return pathlib.Path(__file__).parent

    @pytest.mark.parametrize("data, expected_content, expected_count", [
        (['support-180301-13-35-23.tar.gz', 'support-180301-13-13-13.tar.gz'], {'bundles': ['support-180301-13-35-23.tar.gz', 'support-180301-13-13-13.tar.gz']}, 2),
        (['support-180301-15-25-02.tar.gz', 'foglamp.txt'], {'bundles': ['support-180301-15-25-02.tar.gz']}, 1),
        (['foglamp.txt'], {'bundles': []}, 0),
        ([], {'bundles': []}, 0)
    ])
    async def test_get_support_bundle(self, client, support_bundles_dir_path, data, expected_content, expected_count):
        path = support_bundles_dir_path / 'support'
        with patch.object(support, '_get_support_dir', return_value=path):
            with patch('os.walk') as mockwalk:
                mockwalk.return_value = [(path, [], data)]
                resp = await client.get('/foglamp/support')
                assert 200 == resp.status
                res = await resp.text()
                jdict = json.loads(res)
                assert expected_count == len(jdict['bundles'])
                assert expected_content == jdict
            mockwalk.assert_called_once_with(path)

    async def test_get_support_bundle_by_name(self, client, support_bundles_dir_path):
        gz_filepath = Mock()
        gz_filepath.open = mock_open()
        gz_filepath.is_file.return_value = True
        gz_filepath.stat.return_value = MagicMock()
        gz_filepath.stat.st_size = 1024

        bundle_name = 'support-180301-13-35-23.tar.gz'

        filepath = Mock()
        filepath.name = bundle_name
        filepath.open = mock_open()
        filepath.with_name.return_value = gz_filepath

        with patch("aiohttp.web.FileResponse", return_value=web.FileResponse(path=filepath)) as f_res:
            path = support_bundles_dir_path / 'support'
            with patch.object(support, '_get_support_dir', return_value=path):
                with patch('os.path.isdir', return_value=True):
                    with patch('os.walk') as mockwalk:
                        mockwalk.return_value = [(path, [], [bundle_name])]
                        resp = await client.get('/foglamp/support/{}'.format(bundle_name))
                        assert 200 == resp.status
                        assert 'OK' == resp.reason
                mockwalk.assert_called_once_with(path)
                args, kwargs = f_res.call_args
                assert {'path': PosixPath(pathlib.Path(path) / str(bundle_name))} == kwargs
                assert 1 == f_res.call_count

    @pytest.mark.parametrize("data, request_bundle_name", [
        (['support-180301-13-35-23.tar.gz'], 'xsupport-180301-01-15-13.tar.gz'),
        ([], 'support-180301-13-13-13.tar.gz')
    ])
    async def test_get_support_bundle_by_name_not_found(self, client, support_bundles_dir_path, data, request_bundle_name):
        path = support_bundles_dir_path / 'support'
        with patch.object(support, '_get_support_dir', return_value=path):
            with patch('os.path.isdir', return_value=True):
                with patch('os.walk') as mockwalk:
                    mockwalk.return_value = [(path, [], data)]
                    resp = await client.get('/foglamp/support/{}'.format(request_bundle_name))
                    assert 404 == resp.status
                    assert '{} not found'.format(request_bundle_name) == resp.reason
            mockwalk.assert_called_once_with(path)

    async def test_get_support_bundle_by_name_bad_request(self, client):
        resp = await client.get('/foglamp/support/support-180301-13-35-23.tar')
        assert 400 == resp.status
        assert 'Bundle file extension is invalid' == resp.reason

    async def test_get_support_bundle_by_name_no_dir(self, client, support_bundles_dir_path):
        path = support_bundles_dir_path / 'invalid'
        with patch.object(support, '_get_support_dir', return_value=path):
            with patch('os.path.isdir', return_value=False) as mockisdir:
                resp = await client.get('/foglamp/support/bla.tar.gz')
                assert 404 == resp.status
                assert 'Support bundle directory does not exist' == resp.reason
            mockisdir.assert_called_once_with(path)

    async def test_create_support_bundle(self, client):
        async def mock_build():
            return 'support-180301-13-35-23.tar.gz'

        with patch.object(SupportBuilder, "__init__", return_value=None):
            with patch.object(SupportBuilder, "build", return_value=mock_build()):
                resp = await client.post('/foglamp/support')
                res = await resp.text()
                jdict = json.loads(res)
                assert 200 == resp.status
                assert {"bundle created": "support-180301-13-35-23.tar.gz"} == jdict

    async def test_create_support_bundle_exception(self, client):
        with patch.object(SupportBuilder, "__init__", return_value=None):
            with patch.object(SupportBuilder, "build", side_effect=RuntimeError("blah")):
                resp = await client.post('/foglamp/support')
                assert 500 == resp.status
                assert "Support bundle could not be created. blah" == resp.reason

    async def test_get_syslog_entries_all_ok(self, client):
        def mock_syslog():
            return """
        echo "Mar 19 14:00:53 nerd51-ThinkPad FogLAMP[18809] INFO: server: foglamp.services.core.server: start core
        Mar 19 14:00:53 nerd51-ThinkPad FogLAMP[18809] INFO: server: foglamp.services.core.server: Management API started on http://0.0.0.0:38311
        Mar 19 14:00:53 nerd51-ThinkPad FogLAMP[18809] INFO: server: foglamp.services.core.server: start storage, from directory /home/asinha/Development/FogLAMP/scripts
        Mar 19 14:00:54 nerd51-ThinkPad FogLAMP[18809] INFO: service_registry: foglamp.services.core.service_registry.service_registry: Registered service instance id=479a90ec-0d1d-4845-b2c5-f1d9ce72ac8e: <FogLAMP Storage, type=Storage, protocol=http, address=localhost, service port=33395, management port=45952, status=1>
        Mar 19 14:00:58 nerd51-ThinkPad FogLAMP[18809] INFO: server: foglamp.services.core.server: start scheduler
        Mar 19 14:00:58 nerd51-ThinkPad FogLAMP Storage[18809]: Registered configuration category STORAGE, registration id 3db674a7-9569-4950-a328-1204834fba7e
        Mar 19 14:00:58 nerd51-ThinkPad FogLAMP[18809] INFO: scheduler: foglamp.services.core.scheduler.scheduler: Starting Scheduler: Management port received is 38311
        Mar 19 14:00:58 nerd51-ThinkPad FogLAMP[18809] INFO: scheduler: foglamp.services.core.scheduler.scheduler: Scheduled task for schedule 'purge' to start at 2018-03-19 15:00:58.912532
        Mar 19 14:00:58 nerd51-ThinkPad FogLAMP[18809] INFO: scheduler: foglamp.services.core.scheduler.scheduler: Scheduled task for schedule 'stats collection' to start at 2018-03-19 14:01:13.912532
        Mar 19 14:00:58 nerd51-ThinkPad FogLAMP[18809] INFO: scheduler: foglamp.services.core.scheduler.scheduler: Scheduled task for schedule 'certificate checker' to start at 2018-03-19 15:05:00"
        """

        with patch.object(support, "__GET_SYSLOG_CMD_TEMPLATE", mock_syslog()):
            with patch.object(support, "__GET_SYSLOG_TOTAL_MATCHED_LINES", """echo "10" """):
                resp = await client.get('/foglamp/syslog')
                res = await resp.text()
                jdict = json.loads(res)
                assert 200 == resp.status
                assert 10 == jdict['count']
                assert 'INFO' in jdict['logs'][0]
                assert 'FogLAMP' in jdict['logs'][0]
                assert 'FogLAMP Storage' in jdict['logs'][5]

    async def test_get_syslog_entries_all_with_level_error(self, client):
        def mock_syslog():
            return """
            echo "Sep 12 13:31:41 nerd-034 FogLAMP[9241] ERROR: sending_process: sending_process_PI: cannot complete the sending operation"
            """

        with patch.object(support, "__GET_SYSLOG_CMD_WITH_ERROR_TEMPLATE", mock_syslog()):
            with patch.object(support, "__GET_SYSLOG_ERROR_MATCHED_LINES", """echo "1" """):
                resp = await client.get('/foglamp/syslog?level=error')
                res = await resp.text()
                jdict = json.loads(res)
                assert 200 == resp.status
                assert 1 == jdict['count']
                assert 'ERROR' in jdict['logs'][0]

    async def test_get_syslog_entries_all_with_level_warning(self, client):
        def mock_syslog():
            return """
            echo "Sep 12 14:31:36 nerd-034 FogLAMP Storage[8683]: SQLite3 storage plugin raising error: UNIQUE constraint failed: readings.read_key
            Sep 12 17:42:23 nerd-034 FogLAMP[16637] WARNING: server: foglamp.services.core.server: A FogLAMP PID file has been found: [/home/foglamp/Development/FogLAMP/data/var/run/foglamp.core.pid] found, ignoring it."
            """
        with patch.object(support, "__GET_SYSLOG_CMD_WITH_WARNING_TEMPLATE", mock_syslog()):
            with patch.object(support, "__GET_SYSLOG_WARNING_MATCHED_LINES", """echo "2" """):
                resp = await client.get('/foglamp/syslog?level=warning')
                res = await resp.text()
                jdict = json.loads(res)
                assert 200 == resp.status
                assert 2 == jdict['count']
                assert 'error' in jdict['logs'][0]
                assert 'WARNING' in jdict['logs'][1]

    async def test_get_syslog_entries_from_storage(self, client):
        def mock_syslog():
            return """
            echo "Sep 12 14:31:41 nerd-034 FogLAMP Storage[8874]: Starting service...
            Sep 12 14:46:36 nerd-034 FogLAMP Storage[8683]: SQLite3 storage plugin raising error: UNIQUE constraint failed: readings.read_key
            Sep 12 14:56:41 nerd-034 FogLAMP Storage[8979]: warning No directory found"
            """
        with patch.object(support, "__GET_SYSLOG_CMD_TEMPLATE", mock_syslog()):
            with patch.object(support, "__GET_SYSLOG_TOTAL_MATCHED_LINES", """echo "3" """):
                resp = await client.get('/foglamp/syslog?source=Storage')
                res = await resp.text()
                jdict = json.loads(res)
                assert 200 == resp.status
                assert 3 == jdict['count']
                assert 'FogLAMP Storage' in jdict['logs'][0]
                assert 'error' in jdict['logs'][1]
                assert 'warning' in jdict['logs'][2]

    async def test_get_syslog_entries_from_storage_with_level_warning(self, client):
        def mock_syslog():
            return """
            echo "Sep 12 14:31:36 nerd-034 FogLAMP Storage[8683]: SQLite3 storage plugin raising error: UNIQUE constraint failed: readings.read_key
            Sep 12 14:46:41 nerd-034 FogLAMP Storage[8979]: warning No directory found"
            """
        with patch.object(support, "__GET_SYSLOG_CMD_WITH_WARNING_TEMPLATE", mock_syslog()):
            with patch.object(support, "__GET_SYSLOG_WARNING_MATCHED_LINES", """echo "3" """):
                resp = await client.get('/foglamp/syslog?source=storage&level=warning')
                res = await resp.text()
                jdict = json.loads(res)
                assert 200 == resp.status
                assert 3 == jdict['count']
                assert 'FogLAMP Storage' in jdict['logs'][0]
                assert 'error' in jdict['logs'][0]
                assert 'warning' in jdict['logs'][1]

    @pytest.mark.parametrize("param, message", [
        ("__DEFAULT_LIMIT", "Limit must be a positive integer"),
        ("__DEFAULT_OFFSET", "Offset must be a positive integer OR Zero"),
        ("__DEFAULT_LOG_SOURCE", "garbage is not a valid source")
    ])
    async def test_get_syslog_entries_exception(self, client, param, message):
        with patch.object(support, param, "garbage"):
            resp = await client.get('/foglamp/syslog')
            assert 400 == resp.status
            assert message == resp.reason

    async def test_get_syslog_entries_cmd_exception(self, client):
        msg = 'Internal Server Error'
        with patch.object(subprocess, "Popen", side_effect=Exception(msg)):
            resp = await client.get('/foglamp/syslog')
            assert 500 == resp.status
            assert msg == resp.reason

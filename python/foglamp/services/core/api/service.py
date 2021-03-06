# -*- coding: utf-8 -*-

# FOGLAMP_BEGIN
# See: http://foglamp.readthedocs.io/
# FOGLAMP_END
import os
import datetime
import uuid
import platform
import json
from aiohttp import web

from typing import Dict
from foglamp.common import utils
from foglamp.common import logger
from foglamp.common.service_record import ServiceRecord
from foglamp.common.storage_client.payload_builder import PayloadBuilder
from foglamp.common.storage_client.exceptions import StorageServerError
from foglamp.common.configuration_manager import ConfigurationManager
from foglamp.services.core import server
from foglamp.services.core import connect
from foglamp.services.core.api import utils as apiutils
from foglamp.services.core.scheduler.entities import StartUpSchedule
from foglamp.services.core.service_registry.service_registry import ServiceRegistry
from foglamp.services.core.service_registry import exceptions as service_registry_exceptions
from foglamp.common.common import _FOGLAMP_ROOT
from foglamp.services.core.api.plugins import common
from foglamp.services.core.api.plugins import install
from foglamp.services.core.api.plugins.exceptions import *


__author__ = "Mark Riddoch, Ashwin Gopalakrishnan, Amarendra K Sinha"
__copyright__ = "Copyright (c) 2018 OSIsoft, LLC"
__license__ = "Apache 2.0"
__version__ = "${VERSION}"

_help = """
    -------------------------------------------------------------------------------
    | GET POST            | /foglamp/service                                      |
    | GET                 | /foglamp/service/available                            |
    | GET                 | /foglamp/service/installed                            |
    -------------------------------------------------------------------------------
"""

_logger = logger.setup()

#################################
#  Service
#################################


def get_service_records():
    sr_list = list()
    for service_record in ServiceRegistry.all():
        sr_list.append(
            {
                'name': service_record._name,
                'type': service_record._type,
                'address': service_record._address,
                'management_port': service_record._management_port,
                'service_port': service_record._port,
                'protocol': service_record._protocol,
                'status': ServiceRecord.Status(int(service_record._status)).name.lower()
            })
    recs = {'services': sr_list}
    return recs


async def get_health(request):
    """
    Args:
        request:

    Returns:
            health of all registered services

    :Example:
            curl -X GET http://localhost:8081/foglamp/service
    """
    response = get_service_records()
    return web.json_response(response)


async def delete_service(request):
    """ Delete an existing service

    :Example:
        curl -X DELETE http://localhost:8081/foglamp/service/<svc name>
    """
    try:
        svc = request.match_info.get('service_name', None)
        storage = connect.get_storage_async()

        result = await get_schedule(storage, svc)
        if result['count'] == 0:
            return web.HTTPNotFound(reason='{} service does not exist.'.format(svc))

        config_mgr = ConfigurationManager(storage)

        # In case of notification service, if notifications exists, then deletion is not allowed
        if 'notification' in result['rows'][0]['process_name']:
            notf_children = await config_mgr.get_category_child(category_name="Notifications")
            children = [x['key'] for x in notf_children]
            if len(notf_children) > 0:
                return web.HTTPBadRequest(reason='Notification service `{}` can not be deleted, as {} notification instances exist.'.format(svc, children))

        # First disable the schedule
        svc_schedule = result['rows'][0]
        sch_id = uuid.UUID(svc_schedule['id'])
        if svc_schedule['enabled'].lower() == 't':
            await server.Server.scheduler.disable_schedule(sch_id)

        # Delete all configuration for the service name
        await config_mgr.delete_category_and_children_recursively(svc)

        # Remove from registry as it has been already shutdown via disable_schedule() and since
        # we intend to delete the schedule also, there is no use of its Service registry entry
        try:
            services = ServiceRegistry.get(name=svc)
            ServiceRegistry.remove_from_registry(services[0]._id)
        except service_registry_exceptions.DoesNotExist:
            pass

        # Delete schedule
        await server.Server.scheduler.delete_schedule(sch_id)
    except Exception as ex:
        raise web.HTTPInternalServerError(reason=ex)
    else:
        return web.json_response({'result': 'Service {} deleted successfully.'.format(svc)})


async def add_service(request):
    """
    Create a new service to run a specific plugin

    :Example:
             curl -X POST http://localhost:8081/foglamp/service -d '{"name": "DHT 11", "plugin": "dht11", "type": "south", "enabled": true}'
             curl -sX POST http://localhost:8081/foglamp/service -d '{"name": "Sine", "plugin": "sinusoid", "type": "south", "enabled": true, "config": {"dataPointsPerSec": {"value": "10"}}}' | jq
             curl -X POST http://localhost:8081/foglamp/service -d '{"name": "NotificationServer", "type": "notification", "enabled": true}' | jq

             curl -sX POST http://localhost:8081/foglamp/service?action=install -d '{"format":"repository", "name": "foglamp-service-notification"}'
             curl -sX POST http://localhost:8081/foglamp/service?action=install -d '{"format":"repository", "name": "foglamp-service-notification", "version":"1.6.0"}'
    """

    try:
        data = await request.json()
        if not isinstance(data, dict):
            raise ValueError('Data payload must be a valid JSON')

        name = data.get('name', None)
        plugin = data.get('plugin', None)
        service_type = data.get('type', None)
        enabled = data.get('enabled', None)
        config = data.get('config', None)

        if name is None:
            raise web.HTTPBadRequest(reason='Missing name property in payload.')
        if 'action' in request.query and request.query['action'] != '':
            if request.query['action'] == 'install':
                file_format = data.get('format', None)
                if file_format is None:
                    raise ValueError("format param is required")
                if file_format not in ["repository"]:
                    raise ValueError("Invalid format. Must be 'repository'")
                version = data.get('version', None)
                if version:
                    delimiter = '.'
                    if str(version).count(delimiter) != 2:
                        raise ValueError('Service semantic version is incorrect; it should be like X.Y.Z')

                services, log_path = common.fetch_available_packages("service")
                if name not in services:
                    raise KeyError('{} service is not available for the given repository or already installed'.format(name))

                _platform = platform.platform()
                pkg_mgt = 'yum' if 'centos' in _platform or 'redhat' in _platform else 'apt'
                code, msg = await install.install_package_from_repo(name, pkg_mgt, version)
                if code != 0:
                    raise ValueError(msg)

                message = "{} is successfully installed".format(name)
                return web.json_response({'message': message})
            else:
                raise web.HTTPBadRequest(reason='{} is not a valid action'.format(request.query['action']))
        if utils.check_reserved(name) is False:
            raise web.HTTPBadRequest(reason='Invalid name property in payload.')
        if utils.check_foglamp_reserved(name) is False:
            raise web.HTTPBadRequest(reason="'{}' is reserved for FogLAMP and can not be used as service name!".format(name))
        if service_type is None:
            raise web.HTTPBadRequest(reason='Missing type property in payload.')

        service_type = str(service_type).lower()
        if service_type == 'north':
            raise web.HTTPNotAcceptable(reason='north type is not supported for the time being.')
        if service_type not in ['south', 'notification']:
            raise web.HTTPBadRequest(reason='Only south and notification type are supported.')
        if plugin is None and service_type == 'south':
            raise web.HTTPBadRequest(reason='Missing plugin property for type south in payload.')
        if plugin and utils.check_reserved(plugin) is False:
            raise web.HTTPBadRequest(reason='Invalid plugin property in payload.')

        if enabled is not None:
            if enabled not in ['true', 'false', True, False]:
                raise web.HTTPBadRequest(reason='Only "true", "false", true, false'
                                                ' are allowed for value of enabled.')
        is_enabled = True if ((type(enabled) is str and enabled.lower() in ['true']) or (
            (type(enabled) is bool and enabled is True))) else False

        # Check if a valid plugin has been provided
        plugin_module_path, plugin_config, process_name, script = "", {}, "", ""
        if service_type == 'south':
            # "plugin_module_path" is fixed by design. It is MANDATORY to keep the plugin in the exactly similar named
            # folder, within the plugin_module_path.
            # if multiple plugin with same name are found, then python plugin import will be tried first
            plugin_module_path = "{}/python/foglamp/plugins/{}/{}".format(_FOGLAMP_ROOT, service_type, plugin)
            try:
                plugin_info = common.load_and_fetch_python_plugin_info(plugin_module_path, plugin, service_type)
                plugin_config = plugin_info['config']
                if not plugin_config:
                    _logger.exception("Plugin %s import problem from path %s", plugin, plugin_module_path)
                    raise web.HTTPNotFound(reason='Plugin "{}" import problem from path "{}".'.format(plugin, plugin_module_path))
                process_name = 'south_c'
                script = '["services/south_c"]'
            except FileNotFoundError as ex:
                # Checking for C-type plugins
                plugin_config = load_c_plugin(plugin, service_type)
                if not plugin_config:
                    _logger.exception("Plugin %s import problem from path %s. %s", plugin, plugin_module_path, str(ex))
                    raise web.HTTPNotFound(reason='Plugin "{}" import problem from path "{}".'.format(plugin, plugin_module_path))

                process_name = 'south_c'
                script = '["services/south_c"]'
            except TypeError as ex:
                _logger.exception(str(ex))
                raise web.HTTPBadRequest(reason=str(ex))
            except Exception as ex:
                _logger.exception("Failed to fetch plugin configuration. %s", str(ex))
                raise web.HTTPInternalServerError(reason='Failed to fetch plugin configuration')
        elif service_type == 'notification':
            process_name = 'notification_c'
            script = '["services/notification_c"]'

        storage = connect.get_storage_async()
        config_mgr = ConfigurationManager(storage)

        # Check  whether category name already exists
        category_info = await config_mgr.get_category_all_items(category_name=name)
        if category_info is not None:
            raise web.HTTPBadRequest(reason="The '{}' category already exists".format(name))

        # Check that the schedule name is not already registered
        count = await check_schedules(storage, name)
        if count != 0:
            raise web.HTTPBadRequest(reason='A service with this name already exists.')

        # Check that the process name is not already registered
        count = await check_scheduled_processes(storage, process_name)
        if count == 0:
            # Now first create the scheduled process entry for the new service
            payload = PayloadBuilder().INSERT(name=process_name, script=script).payload()
            try:
                res = await storage.insert_into_tbl("scheduled_processes", payload)
            except StorageServerError as ex:
                _logger.exception("Failed to create scheduled process. %s", ex.error)
                raise web.HTTPInternalServerError(reason='Failed to create service.')
            except Exception as ex:
                _logger.exception("Failed to create scheduled process. %s", str(ex))
                raise web.HTTPInternalServerError(reason='Failed to create service.')

        # check that notification service is not already registered, right now notification service LIMIT to 1
        if service_type == 'notification':
            res = await check_notification_schedule(storage)
            for ps in res['rows']:
                if 'notification_c' in ps['process_name']:
                    raise web.HTTPBadRequest(reason='A Notification service schedule already exists.')
        elif service_type == 'south':
            try:
                # Create a configuration category from the configuration defined in the plugin
                category_desc = plugin_config['plugin']['description']
                await config_mgr.create_category(category_name=name,
                                                 category_description=category_desc,
                                                 category_value=plugin_config,
                                                 keep_original_items=True)
                # Create the parent category for all South services
                await config_mgr.create_category("South", {}, "South microservices", True)
                await config_mgr.create_child_category("South", [name])

                # If config is in POST data, then update the value for each config item
                if config is not None:
                    if not isinstance(config, dict):
                        raise ValueError('Config must be a JSON object')
                    for k, v in config.items():
                        await config_mgr.set_category_item_value_entry(name, k, v['value'])

            except Exception as ex:
                await config_mgr.delete_category_and_children_recursively(name)
                _logger.exception("Failed to create plugin configuration. %s", str(ex))
                raise web.HTTPInternalServerError(reason='Failed to create plugin configuration.')

        # If all successful then lastly add a schedule to run the new service at startup
        try:
            schedule = StartUpSchedule()
            schedule.name = name
            schedule.process_name = process_name
            schedule.repeat = datetime.timedelta(0)
            schedule.exclusive = True
            #  if "enabled" is supplied, it gets activated in save_schedule() via is_enabled flag
            schedule.enabled = False

            # Save schedule
            await server.Server.scheduler.save_schedule(schedule, is_enabled)
            schedule = await server.Server.scheduler.get_schedule_by_name(name)
        except StorageServerError as ex:
            await config_mgr.delete_category_and_children_recursively(name)
            _logger.exception("Failed to create schedule. %s", ex.error)
            raise web.HTTPInternalServerError(reason='Failed to create service.')
        except Exception as ex:
            await config_mgr.delete_category_and_children_recursively(name)
            _logger.exception("Failed to create service. %s", str(ex))
            raise web.HTTPInternalServerError(reason='Failed to create service.')

    except ValueError as e:
        raise web.HTTPBadRequest(reason=str(e))
    except KeyError as ex:
        raise web.HTTPNotFound(reason=str(ex))
    else:
        return web.json_response({'name': name, 'id': str(schedule.schedule_id)})


def load_c_plugin(plugin: str, service_type: str) -> Dict:
    try:
        plugin_info = apiutils.get_plugin_info(plugin, dir=service_type)
        if plugin_info['type'] != service_type:
            msg = "Plugin of {} type is not supported".format(plugin_info['type'])
            raise TypeError(msg)
        plugin_config = plugin_info['config']
    except Exception:
        # Now looking for hybrid plugins if exists
        plugin_info = common.load_and_fetch_c_hybrid_plugin_info(plugin, True)
        if plugin_info:
            plugin_config = plugin_info['config']
    return plugin_config


async def check_scheduled_processes(storage, process_name):
    payload = PayloadBuilder().SELECT("name").WHERE(['name', '=', process_name]).payload()
    result = await storage.query_tbl_with_payload('scheduled_processes', payload)
    return result['count']


async def check_schedules(storage, schedule_name):
    payload = PayloadBuilder().SELECT("schedule_name").WHERE(['schedule_name', '=', schedule_name]).payload()
    result = await storage.query_tbl_with_payload('schedules', payload)
    return result['count']


async def get_schedule(storage, schedule_name):
    payload = PayloadBuilder().SELECT(["id", "enabled"]).WHERE(['schedule_name', '=', schedule_name]).payload()
    result = await storage.query_tbl_with_payload('schedules', payload)
    return result


async def check_notification_schedule(storage):
    payload = PayloadBuilder().SELECT("process_name").payload()
    result = await storage.query_tbl_with_payload('schedules', payload)
    return result


async def get_available(request: web.Request) -> web.Response:
    """ get list of a available services via package management i.e apt or yum

        :Example:
            curl -X GET http://localhost:8081/foglamp/service/available
    """
    try:
        services, log_path = common.fetch_available_packages("service")
    except PackageError as e:
        msg = "Fetch available service package request failed"
        raise web.HTTPBadRequest(body=json.dumps({"message": msg, "link": str(e)}), reason=msg)
    except Exception as ex:
        raise web.HTTPInternalServerError(reason=ex)

    return web.json_response({"services": services, "link": log_path})


async def get_installed(request: web.Request) -> web.Response:
    """ get list of a installed services

        :Example:
            curl -X GET http://localhost:8081/foglamp/service/installed
    """
    services = []
    svc_prefix = 'foglamp.services.'
    for root, dirs, files in os.walk(_FOGLAMP_ROOT + "/" + "services"):
        for f in files:
            if f.startswith(svc_prefix):
                services.append(f.split(svc_prefix)[-1])

    return web.json_response({"services": services})

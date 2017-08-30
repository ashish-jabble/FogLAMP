# -*- coding: utf-8 -*-

# FOGLAMP_BEGIN
# See: http://foglamp.readthedocs.io/
# FOGLAMP_END

"""FogLAMP device server"""

import asyncio
import signal
import asyncpg

from foglamp.device import coap
from foglamp.device.ingest import Ingest

__author__ = "Terris Linenbach"
__copyright__ = "Copyright (c) 2017 OSIsoft, LLC"
__license__ = "Apache 2.0"
__version__ = "${VERSION}"

pool = None

async def _stop(loop):
    """Stops the device server"""
    await Ingest.stop()

    for task in asyncio.Task.all_tasks():
        task.cancel()

    loop.stop()

async def get_pool():
    # Create a DB connection pool
    global pool
    if pool is None:
        pool = await asyncpg.create_pool(database='foglamp')
    return pool

def start():
    """Starts the device server"""
    loop = asyncio.get_event_loop()

    # Register signal handlers
    # Registering SIGTERM causes an error at shutdown. See
    # https://github.com/python/asyncio/issues/396
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(
            signal_name,
            lambda: asyncio.ensure_future(_stop(loop)))

    asyncio.ensure_future(Ingest.start())
    asyncio.ensure_future(coap.start())

    loop.run_forever()

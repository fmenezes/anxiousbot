import asyncio
import sys

import uvloop


def run_uv_loop(run_fn, *args, **kwargs):
    if sys.version_info >= (3, 11):
        with asyncio.Runner(loop_factory=uvloop.new_event_loop) as runner:
            return runner.run(run_fn(*args, **kwargs))
    else:
        uvloop.install()
        return asyncio.run(run_fn(*args, **kwargs))

import asyncio
import argparse
import random
import time
import socket
from hubtraf.user import User
from hubtraf.auth.dummy import login_dummy
from functools import partial
from collections import Counter


async def simulate_user(hub_url, username, password, delay_seconds, code_execute_seconds, json):
    await asyncio.sleep(delay_seconds)
    async with User(username, hub_url, partial(login_dummy, password=password)) as u:
        if json:
            u.logger = 'jupyter-telemetry'
        try:
            if not await u.login():
                return 'login'
            if not await u.ensure_server_simulate():
                return 'start-server'
            if not await u.start_kernel():
                return 'start-kernel'
            if not await u.assert_code_output("5 * 4", "20", 5, code_execute_seconds):
                return 'run-code'
            return 'completed'
        finally:
            if u.state == User.States.KERNEL_STARTED:
                await u.stop_kernel()
                await u.stop_server()


async def run(args):
    # FIXME: Pass in individual arguments, not argparse object
    awaits = []
    for i in range(args.user_count):
        awaits.append(simulate_user(
            args.hub_url,
            f'{args.user_prefix}-' + str(i),
            'hello',
            int(random.uniform(0, args.user_session_max_start_delay)),
            int(random.uniform(args.user_session_min_runtime, args.user_session_max_runtime)),
            args.json
        ))

    outputs = await asyncio.gather(*awaits)
    print(Counter(outputs))

def main():
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        'hub_url',
        help='Hub URL to send traffic to (without a trailing /)'
    )
    argparser.add_argument(
        'user_count',
        type=int,
        help='Number of users to simulate'
    )
    argparser.add_argument(
        '--user-prefix',
        default=socket.gethostname(),
        help='Prefix to use when generating user names'
    )
    argparser.add_argument(
        '--user-session-min-runtime',
        default=60,
        type=int,
        help='Min seconds user is active for'
    )
    argparser.add_argument(
        '--user-session-max-runtime',
        default=300,
        type=int,
        help='Max seconds user is active for'
    )
    argparser.add_argument(
        '--user-session-max-start-delay',
        default=60,
        type=int,
        help='Max seconds by which all users should have logged in'
    )
    argparser.add_argument(
        '--json',
        action='store_true',
        help='True if output should be JSON formatted'
    )
    args = argparser.parse_args()

    loop = asyncio.get_event_loop()
    loop.run_until_complete(run(args))


if __name__ == '__main__':
    main()
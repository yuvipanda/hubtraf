import asyncio
import structlog
import argparse
import random
import time
import socket
from hubtraf.user import User, OperationError
from hubtraf.auth.dummy import login_dummy
from functools import partial


async def simulate_user(
        hub_url, username, password, delay_seconds,
        exec_seconds, code_output=None, port=None):
    if code_output is None:
        code_output = ("5 * 4", "20")
    code, output = code_output
    await asyncio.sleep(delay_seconds)
    async with User(
            username, hub_url, partial(login_dummy, password=password),
            port=port) as u:
        try:
            await u.login()
            await u.ensure_server()
            await u.start_kernel()
            await u.assert_code_output(code, output, 5, exec_seconds)
        except OperationError:
            pass
        finally:
            try:
                if u.state == User.States.KERNEL_STARTED:
                    await u.stop_kernel()
            except OperationError:
                # We'll try to sto the server anyway
                pass
            try:
                if u.state == User.States.SERVER_STARTED:
                    await u.stop_server()
            except OperationError:
                # Nothing to do
                pass

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
        '--port',
        default=None,
        type=int,
        help='Port for jupyterhub server'
    )
    argparser.add_argument(
        '--json',
        action='store_true',
        help='True if output should be JSON formatted'
    )
    argparser.add_argument(
        '--code',
        default="5 * 4",
        type=str,
        help='Code for users to execute'
    )
    argparser.add_argument(
        '--output',
        default="20",
        type=str,
        help='Expected result of `--code`'
    )
    args = argparser.parse_args()

    processors=[structlog.processors.TimeStamper(fmt="ISO")]

    if args.json:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(processors=processors)

    awaits = []
    for i in range(args.user_count):
        awaits.append(simulate_user(
            args.hub_url,
            f'{args.user_prefix}-' + str(i),
            'hello',
            int(random.uniform(0, args.user_session_max_start_delay)),
            int(random.uniform(args.user_session_min_runtime, args.user_session_max_runtime)),
            code_output=(args.code, args.output),
            port=args.port
        ))
    loop = asyncio.get_event_loop()
    loop.run_until_complete(asyncio.gather(*awaits))
    
if __name__ == '__main__':
    main()

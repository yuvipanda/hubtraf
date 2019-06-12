import structlog
import asyncio
import argparse
import random
import time
import socket
import sys
import yaml
from hubtraf.user import User, OperationError
from hubtraf.auth.dummy import login_dummy
from hubtraf.auth.keycloak import login_keycloak
from functools import partial

def load_code_and_output(config):
    if config and 'notebook' in config:
        code = config['notebook']['code']
        output = config['notebook']['assert_output']
        return code, output
    else:
        return '5 * 4', '20'

async def simulate_user(hub_url, username, password, delay_seconds, code_execute_seconds, debug=False, config=None):
    await asyncio.sleep(delay_seconds)
    async with User(username, hub_url, partial(login_keycloak, password=password), debug=debug, config=config) as u:
        code, output = load_code_and_output(config)
        try:
            await u.login()
            await u.start_server()
            await u.ensure_server()
            await u.start_kernel()
            await u.assert_code_output(code, output, 5, code_execute_seconds)
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

def read_notebook_code_from_file(config):
    notebook = config.get('notebook', None)
    if notebook and 'code_file' in notebook:
        with open(notebook['code_file'], 'r') as file:
            code = file.read()
            config['notebook']['code'] = code
    return config

def verify_config(config):
    if 'hub' in config:
        if 'group' not in config['hub']:
            return False
        if 'instance_type' not in config['hub']:
            return False
        if 'image' not in config['hub']:
            return False
    else:
        return False
    
    if 'notebook' in config:
        if 'assert_output' not in config['notebook']:
            return False
        if 'code' not in config['notebook']:
            return False
    return True

def main():
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        '--debug',
        action='store_true',
        help='True if enable showing debug info of the http request')
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
    argparser.add_argument(
        '--config',
        help='Load yaml config file'
    )
    args = argparser.parse_args()

    processors=[structlog.processors.TimeStamper(fmt="ISO")]

    if args.json:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(processors=processors)

    print(args.config)
    config=None
    if args.config:
        with open(args.config, 'r') as stream:
            try:
                config = yaml.safe_load(stream)
            except yaml.YAMLError as exc:
                sys.exit(1)
            if 'notebook' in config and 'code_file' in config['notebook']:
                config = read_notebook_code_from_file(config)
            if not verify_config(config):
                sys.exit(1)

    awaits = []
    for i in range(args.user_count):
        awaits.append(simulate_user(
            args.hub_url,
            f'{args.user_prefix}-' + str(i),
            'hello',
            int(random.uniform(0, args.user_session_max_start_delay)),
            int(random.uniform(args.user_session_min_runtime, args.user_session_max_runtime)),
            debug=args.debug,
            config=config
        ))
    loop = asyncio.get_event_loop()
    loop.run_until_complete(asyncio.gather(*awaits))
    
if __name__ == '__main__':
    main()
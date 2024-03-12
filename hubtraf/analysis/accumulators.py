"""
Streamz Accumulators for use with processed hubtraf data
"""


def count_in_progress(state, event):
    """
    Count in-progress actions.

    Returns current state as each new produced event,
    so we can see state change over time
    """
    action = event['action']
    phase = event['phase']

    if phase == 'start':
        state[action] = state.get(action, 0) + 1
    elif phase == 'complete':
        state[action] = state[action] - 1
    elif phase.startswith('fail'):
        # Using startswith because some events use 'failure' vs 'failed'
        state[action] = state[action] - 1
        state[f'{action}.failed'] = state.get(f'{action}.failed', 0) + 1
    state['timestamp'] = event['timestamp']

    return state, state

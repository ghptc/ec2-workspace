#!/usr/bin/env python3
"""Validate authenticated cvar replies; never print server replies or credentials."""
import re
import sys


def validate(text, fs_game, capacity, empty=False):
    text = re.sub(r'\^[0-9]', '', text)
    expected = {'sv_pure': '1', 'sv_autoupdate': '0', 'bot_enable': '1',
                'bot_fill_limit': capacity, 'fs_game': fs_game, 'sv_maxclients': capacity}
    for key, value in expected.items():
        matches = re.findall(r'"' + re.escape(key) + r'" is: "([^"\r\n]*)"', text)
        if not matches or any(v != value for v in matches):
            raise ValueError('Effective runtime setting mismatch: ' + key)
    states = re.findall(r'BOT_STATUS enabled=(\d+) state=([\w-]+) humans=(\d+) connecting=(\d+) bots=(\d+) ready=(\d+) pure=(\d+) limit=(\d+)', text)
    if not states:
        raise ValueError('Missing native bot status')
    enabled, state, humans, connecting, bots, ready, pure, limit = states[-1]
    if enabled != '1' or pure != '1' or limit != capacity or state != 'active' or ready != '1':
        raise ValueError('Native bot policy is not ready')
    if empty and (int(humans) or int(connecting) or int(bots) != int(capacity) or ready != '1'):
        raise ValueError('Packaged bot population is not ready')
    if int(bots) + int(humans) + int(connecting) > int(capacity):
        raise ValueError('Native bot capacity exceeded')


if __name__ == '__main__':
    try:
        validate(sys.stdin.read(), *sys.argv[1:])
    except ValueError as exc:
        sys.exit(str(exc))

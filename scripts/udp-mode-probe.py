#!/usr/bin/env python3
"""Run on an independent observer host, via a pinned authenticated SSH command.
No RCON password or Docker access is needed. One bounded UDP query, no retries.
"""
import argparse
import ipaddress
import json
import re
import socket


def query(host, operation):
    ipaddress.IPv4Address(host)
    if operation != 'preflight' and not re.fullmatch(r'[0-9a-f]{32}', operation):
        raise ValueError('Invalid operation ID')
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as channel:
        channel.settimeout(5)
        channel.sendto(b'\xff'*4 + b'getstatus\n', (host, 28960))
        data, peer = channel.recvfrom(65535)
    if peer != (host, 28960) or not data.startswith(b'\xff'*4+b'statusResponse\n'):
        raise ValueError('Invalid server response')
    fields = data.split(b'\n')[1].split(b'\\')
    values = {k.decode(): v.decode() for k,v in zip(fields[1::2], fields[2::2])}
    return {'operation': operation, 'external': True,
            **{key: values.get(key) for key in ('fs_game','g_gametype','sv_pure','mapname')}}


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('host'); parser.add_argument('operation')
    args=parser.parse_args()
    print(json.dumps(query(args.host,args.operation)))

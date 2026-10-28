#!/usr/bin/env python3
"""Disposable local Compose transaction qualification; NO production activation.

Uses static UDP fixture executables, not licensed games or qualification records.
Production defaults remain fixed. Only this test subclass selects owned names.
No image builds, pulls, Git operations or downloads occur during transitions.
"""
import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import uuid
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('controller',ROOT/'scripts/mode-controller.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.load_runtime()
project='c4-mode-test-'+uuid.uuid4().hex[:10]
root=Path(tempfile.mkdtemp(prefix=project+'-'))
state=root/'state';state.mkdir();home=root/'home';home.mkdir()
(root/'bridge').mkdir()
listener=socket.socket(socket.AF_UNIX,socket.SOCK_SEQPACKET)
listener.bind(str(root/'bridge/control.sock'));listener.listen(1);listener.settimeout(3)
(home/'private.cfg').write_text('private-fixture-original')
for part in ('main','zone'):(root/part).mkdir()


def command(args):
    result=subprocess.run(args,text=True,capture_output=True,timeout=120)
    if result.returncode:raise RuntimeError(f'{args[0:2]} failed; private fixture evidence: {root}')
    return result.stdout

endpoint=command(['docker','context','inspect','--format','{{.Endpoints.docker.Host}}']).strip()
assert endpoint=='unix:///var/run/docker.sock','Only the local Unix Docker context is allowed'
assert not os.environ.get('DOCKER_HOST') and not os.environ.get('DOCKER_CONTEXT'),'No Docker endpoint overrides permitted'
for port in (28960,28962):
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as probe:probe.bind(('0.0.0.0',port))
base=command(['docker','image','inspect','python:3.12-slim','--format','{{.Id}}']).strip()
records={};created_images=[];configs=[];checks={};public=io.StringIO()
(root/'runtime').mkdir()
common=root/'common-fixture.sh'
common.write_text((ROOT/'scripts/common.sh').read_text().replace('/opt/services/cod4',str(root/'runtime')))

def apply_config(value):
    body='set -euo pipefail; source "$1"; remote() { "$@"; }; environment=production; project=$2; service=cod4; work=$3; apply_runtime'
    m.run(['bash','-c',body,'compose-fixture',str(common),project,str(root/'runtime')],payload=json.dumps(value))

def compose(path):return ['docker','compose','-p',project,'-f',str(path)]

def inspect(name):return json.loads(command(['docker','inspect',name]))[0]

try:
    # Preparation only. The switching methods below never invoke a builder.
    for mode,fail in (('promod',False),('zombies',False),('broken',True)):
        stage=root/mode;stage.mkdir()
        command(['gcc','-static','-O2',f'-DFAIL_START={int(fail)}',str(ROOT/'tests/mode_fixture.c'),'-o',str(stage/'fixture')])
        selected='zombies' if mode=='broken' else mode
        labels={'org.opencontainers.image.revision':'0'*40,'org.opencontainers.image.source':'test-only',
            'io.cod4.assets.lock':'0'*64,'io.cod4.bot-warfare.revision':'none','io.cod4.config.revision':'0'*40,
            'io.cod4.config.hash':'0'*64,'io.cod4.mode':selected,'io.cod4.fs-game':m.MODES[selected][0],
            'io.cod4.startup-map':'mp_crash','io.cod4.maps':'mp_crash','io.cod4.maxclients':'12',
            'io.cod4.disposable-fixture':project}
        dockerfile=f'FROM {base}\nCOPY fixture {m.runtime.EXECUTABLE}\nWORKDIR {m.runtime.ARTIFACT_ROOT}\nUSER 1000:1000\n'
        dockerfile+='LABEL '+' '.join(k+'='+json.dumps(v) for k,v in labels.items())+'\n'
        (stage/'Dockerfile').write_text(dockerfile)
        env={**os.environ,'DOCKER_BUILDKIT':'0'}
        built=subprocess.run(['docker','build','--pull=false','--network=none','-q',str(stage)],env=env,text=True,capture_output=True,timeout=120)
        (stage/'build.log').write_text(built.stdout+'\n'+built.stderr)
        assert built.returncode==0,f'Local fixture build failed: {root}'
        image=built.stdout.strip().splitlines()[-1];created_images.append(image)
        records[mode]={'image':image,'labels':labels}
    sentinel=project+'-homolog'
    config={'name':project,'services':{'cod4':{'container_name':project+'-production','image':records['promod']['image'],
        'entrypoint':[m.runtime.EXECUTABLE],'working_dir':m.runtime.ARTIFACT_ROOT,'read_only':True,
        'environment':{'PRIVATE_CANARY':'fixture-$private'},
        'volumes':[{'type':'bind','source':str(root/'main'),'target':'/home/user/cod4/main','read_only':True},
                   {'type':'bind','source':str(root/'zone'),'target':'/home/user/cod4/zone','read_only':True},
                   {'type':'bind','source':str(home),'target':m.runtime.PERSISTENT_HOME},
                   {'type':'bind','source':str(root/'bridge'),'target':'/run/cod4-mode-bridge','read_only':True}],
        'labels':{'io.cod4.disposable-fixture':project},
        'ports':[{'target':28960,'published':'28960','protocol':'udp'}],
        'command':['+set','fs_homepath',m.runtime.PERSISTENT_HOME,'+exec','private.cfg','+map','mp_crash']}}}
    m.runtime.adapt(config['services']['cod4'],records['promod']['image'],'promod','0'*64,*m.runtime.startup_values(records['promod']['labels']))
    initial=root/'initial.json';initial.write_text(json.dumps(config));configs.append(initial)
    apply_config(config)
    command(['docker','run','-d','--name',sentinel,'--label','io.cod4.disposable-fixture='+project,
        '--read-only','-p','28962:28960/udp','--entrypoint',m.runtime.EXECUTABLE,records['promod']['image']])
    sentinel_before=inspect(sentinel)

    class Fixture(m.Controller):
        container=project+'-production';private_home=home;readiness_timeout=3
        def __init__(self):super().__init__(state);self.project=project;self.current_config=copy.deepcopy(config)
        def snapshot(self):return self.validate_snapshot(copy.deepcopy(self.current_config))
        def apply(self,value):
            self.current_config=copy.deepcopy(value)
            path=root/('apply-'+uuid.uuid4().hex+'.json');path.write_text(json.dumps(value));configs.append(path)
            apply_config(value)
        def external(self,record,operation):
            # Separate network namespace traverses the published host UDP port.
            code="""import socket,json
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.settimeout(3);s.connect(('host.docker.internal',28960));s.send(b'\\xff'*4+b'getstatus\\n');data=s.recv(65535).split(b'\\n')[1].split(b'\\\\');print(json.dumps({k.decode():v.decode() for k,v in zip(data[1::2],data[2::2])}))"""
            result=json.loads(command(['docker','run','--rm','--read-only','--add-host','host.docker.internal:host-gateway',base,'python3','-c',code]))
            result.update(external=True,operation=operation);return result
    controller=Fixture()
    real_trusted=m.trusted
    def fixture_trust(path,directory=False):
        # Only ownership policy is substituted for this /tmp test namespace.
        # Production root ownership remains separately enforced and tested.
        if Path(path).is_relative_to(root):return Path(path)
        return real_trusted(path,directory=directory)
    qualified={key:records[key] for key in ('promod','zombies')}
    with patch.object(m,'qualification',side_effect=lambda registry:qualified),patch.object(m,'trusted',side_effect=fixture_trust),contextlib.redirect_stdout(public):
        controller.verify(config,'promod',{},'initial')
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as udp:
            udp.sendto(b'peer-probe',('127.0.0.1',28960))
        peer,_=listener.accept()
        with peer:
            import struct
            credentials=struct.unpack('3i',peer.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
            checks['kernel_peer_is_container_engine']=credentials[0]==controller.inspect()['State']['Pid']
            spec=importlib.util.spec_from_file_location('bridge_peer_test',ROOT/'scripts/mode-bridge.py')
            bridge=importlib.util.module_from_spec(spec);spec.loader.exec_module(bridge);bridge.c=m
            checks['peer_executable_and_cgroup_identity']=bridge.process_matches(credentials[0],controller.inspect()['Id'])
        controller.transition('zombies',{})
        checks['promod_to_zombies']=controller.query('127.0.0.1')['fs_game']==m.MODES['zombies'][0]
        controller.transition('promod',{})
        checks['zombies_to_promod']=controller.query('127.0.0.1')['fs_game']==m.MODES['promod'][0]
        baseline=copy.deepcopy(controller.current_config)
        qualified['zombies']=records['broken']
        try:controller.transition('zombies',{})
        except RuntimeError as exc:checks['failed_health_exact_rollback']='exact previous runtime restored' in str(exc)
        else:checks['failed_health_exact_rollback']=False
        checks['exact_image_rollback']=controller.inspect()['Image']==records['promod']['image']
        checks['private_bytes_rollback']=(home/'private.cfg').read_text()=='private-fixture-original'
        checks['exact_runtime_rollback']=controller.current_config==baseline
        checks['private_mounts_environment_ports']=('PRIVATE_CANARY=fixture-$private' in controller.inspect()['Config']['Env']) and all(controller.current_config['services']['cod4'][k]==config['services']['cod4'][k] for k in ('volumes','environment','ports'))
        checks['external_udp_after_rollback']=controller.external({},'rollback')['fs_game']==m.MODES['promod'][0]
    checks['homolog_isolation']=inspect(sentinel)['Id']==sentinel_before['Id'] and inspect(sentinel)['State']['Pid']==sentinel_before['State']['Pid']
    checks['no_private_canary_in_public_status']='fixture-$private' not in public.getvalue()
    (root/'public-journal.log').write_text(public.getvalue())
finally:
    listener.close()
    # Cleanup is bounded to names and images created by this invocation.
    for name in (project+'-production',project+'-homolog'):
        result=subprocess.run(['docker','inspect',name],text=True,capture_output=True)
        if result.returncode==0:
            data=json.loads(result.stdout)[0]
            assert data['Config']['Labels'].get('io.cod4.disposable-fixture')==project
            subprocess.run(['docker','rm','-f',name],capture_output=True)
    if configs:subprocess.run(compose(configs[0])+['down','--remove-orphans'],capture_output=True)
    for image in created_images:subprocess.run(['docker','image','rm',image],capture_output=True)
(root/'results.json').write_text(json.dumps({'evidence':str(root),'checks':checks,'real_game_qualification':False},indent=2)+'\n')
print(json.dumps({'evidence':str(root),'passed':sum(checks.values()),'failed':[k for k,v in checks.items() if not v]},indent=2))
assert len(checks)==12 and all(checks.values())

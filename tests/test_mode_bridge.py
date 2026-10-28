"""Bridge authentication, framing, host leases and durable-job boundaries.

All filesystem/process/socket fixtures are disposable. No Docker/SSH is invoked.
"""
import copy
import importlib.util
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch
from test_mode_controller import m, Fake, OLD, NEW

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('bridge',ROOT/'scripts/mode-bridge.py')
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b);b.c=m
OP='a'*32

def inspection():
    return {'Id':'b'*64,'Name':'/cod4-production','Path':m.runtime.EXECUTABLE,
        'State':{'Pid':os.getpid(),'Running':True},
        'Config':{'Labels':{'io.cod4.rcon-mode-bridge':'C4M1'}},
        'Mounts':[{'Type':'bind','Source':str(b.SOCKET.parent),'Destination':str(b.SOCKET.parent),'RW':False}]}

class BridgeSecurity(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.state=Path(self.tmp.name);self.patch=patch.object(m,'STATE',self.state);self.patch.start();self.addCleanup(self.patch.stop)

    def test_peer_requires_production_pid_identity_and_readonly_endpoint(self):
        good=inspection()
        with patch.object(b,'process_matches',return_value=True):
            self.assertTrue(b.peer_matches((os.getpid(),1000,1000),good))
            for key,value in [('Name','/cod4-homolog'),('Path','/bin/sh'),('Id','bad')]:
                self.assertFalse(b.peer_matches((os.getpid(),1000,1000),{**good,key:value}))
            for state in ({'Pid':os.getpid()+1,'Running':True},{'Pid':os.getpid(),'Running':False}):
                self.assertFalse(b.peer_matches((os.getpid(),1000,1000),{**good,'State':state}))
            bad=copy.deepcopy(good);bad['Mounts'][0]['RW']=True
            self.assertFalse(b.peer_matches((os.getpid(),1000,1000),bad))
        with patch.object(b,'process_matches',return_value=False):
            self.assertFalse(b.peer_matches((os.getpid(),1000,1000),good))

    def exchange(self,payload,authorized=True,enabled=True):
        client,server=socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET)
        with client,server:
            client.send(payload);bridge=b.Bridge();bridge.inspection=inspection()
            with patch.object(b,'process_matches',return_value=authorized),patch.object(b,'registry',return_value={'rcon_bridge_enabled':enabled}),patch.object(m,'qualification'),patch.object(b,'policy',side_effect=None if enabled else ValueError('disabled')),patch.object(bridge,'spawn') as spawn:
                bridge.handle(server)
                if spawn.called:return spawn.call_args
                return client.recv(512)

    def test_valid_kernel_authenticated_request_and_status(self):
        call=self.exchange(f'C4M1 switch {OP} zombies'.encode())
        self.assertEqual(call.args[:2],(OP,'zombies'))
        self.assertEqual(call.args[3][0],os.getpid())
        self.assertEqual(self.exchange(b'C4M1 status'),b'C4M1 idle none none idle')

    def test_unrelated_process_or_disabled_policy_never_spawns(self):
        self.assertIn(b'denied',self.exchange(f'C4M1 switch {OP} zombies'.encode(),authorized=False))
        self.assertIn(b'disabled',self.exchange(f'C4M1 switch {OP} zombies'.encode(),enabled=False))

    def test_invalid_truncated_injected_or_extra_requests_never_spawn(self):
        bad=[b'',b'{}',f'C4M1 switch {OP} hardcore'.encode(),f'C4M1 switch {OP} promod;quit'.encode(),
             f'C4M1 switch {OP} promod extra'.encode(),f'C4M1 switch {OP} promod\0extra'.encode(),
             f'C4M1 switch {OP} promod\n'.encode(),b'x'*300,b'C4M1 switch ../escape zombies']
        for value in bad:
            with self.subTest(value=value):self.assertIn(b'invalid',self.exchange(value))

    def test_explicit_activation_and_image_bound_evidence_required(self):
        records={mode:{'image':image,'labels':{'io.cod4.rcon-mode-bridge':'C4M1'}} for mode,image in [('promod',OLD),('zombies',NEW)]}
        rules={'modes':records,'rcon_bridge_enabled':True}
        for gate in ('rcon_security_review','rcon_activation_approval'):
            rules[gate]={'images':{mode:r['image'] for mode,r in records.items()}}
        with patch.object(m,'qualification'),patch.object(m,'evidence'):
            b.policy(rules)
            with self.assertRaises(ValueError):b.policy({**rules,'rcon_bridge_enabled':False})
            changed=copy.deepcopy(rules);changed['rcon_activation_approval']['images']['zombies']=OLD
            with self.assertRaises(ValueError):b.policy(changed)
            changed=copy.deepcopy(rules);changed['modes']['promod']['labels']={}
            with self.assertRaises(ValueError):b.policy(changed)

    def test_pending_and_failed_are_honest_status_codes(self):
        client,server=socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET)
        with client,server:
            for code in ('submitted','failed','rolled_back','accepted'):
                b.response(server,code,OP,'zombies','pending')
                self.assertIn((' '+code+' ').encode(),client.recv(512))

    def test_shared_host_lock_and_orphan_marker_fail_closed(self):
        import fcntl
        lock=self.state/'lease';lock.touch();guard=self.state/'orphan'
        bridge=b.Bridge()
        with patch.object(m,'DEPLOY_LOCK',lock),patch.object(m,'DEPLOY_GUARD',guard),patch.object(m,'trusted',side_effect=lambda p,**kw:p):
            with lock.open('r') as owned:
                fcntl.flock(owned,fcntl.LOCK_EX|fcntl.LOCK_NB)
                self.assertIsNone(bridge.lock())
            guard.write_text('interrupted-workstation')
            self.assertIsNone(bridge.lock())
            guard.unlink();lease=bridge.lock();self.assertIsNotNone(lease);lease.close()

    def test_failed_recovery_is_not_retried_automatically(self):
        m.atomic(self.state/'active.json',{'phase':'recovery_required','operation':OP,'target_mode':'zombies'})
        bridge=b.Bridge()
        with patch.object(bridge,'lock',return_value=None),patch.object(bridge,'spawn') as spawn:
            bridge.recover();spawn.assert_not_called()

    def test_untrusted_controller_is_not_executed_or_loaded_from_cache(self):
        self.assertIsNone(b.__dict__.get('untrusted_code_executed'))
        with self.assertRaises(ValueError):b.load_controller()

    def test_missing_recovery_evidence_records_blocked_terminal_state(self):
        tx={'operation':OP,'previous_mode':'promod','target_mode':'zombies','previous_image':OLD,'phase':'pending'}
        m.atomic(self.state/'active.json',tx)
        with patch.object(m,'rollback_qualification',side_effect=ValueError('revoked')):
            with self.assertRaises(RuntimeError):m.Controller(self.state).recover({})
        self.assertEqual(json.loads((self.state/'active.json').read_text())['phase'],'recovery_required')

    def test_accepted_host_job_survives_engine_socket_closure_and_replay_is_rejected(self):
        records={'promod':{'image':OLD},'zombies':{'image':NEW}}
        class Engine(Fake):
            stopped=False
            def inspect(self):return {'Id':'b'*64,'Image':self.config['services']['cod4']['image'],'State':{'Pid':os.getpid(),'Running':not self.stopped}}
        controller=Engine(self.state)
        client,server=socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET)
        received=[]
        def engine():
            try: received.append(client.recv(512));controller.stopped=True
            finally: client.close()
        thread=threading.Thread(target=engine);thread.start()
        with patch.object(b,'registry',return_value={}),patch.object(b,'policy'),patch.object(b,'peer_matches',return_value=True),patch.object(m,'Controller',return_value=controller),patch.object(m,'qualification',return_value=records):
            b.worker(OP,'zombies',os.getpid(),'b'*64,server.detach(),-1)
        thread.join(timeout=3);self.assertFalse(thread.is_alive());self.assertIn(b'accepted',received[0]);m.LOCK_FD=None
        self.assertEqual(controller.config['services']['cod4']['image'],NEW)
        self.assertEqual(json.loads((self.state/'active.json').read_text())['phase'],'success')
        client,server=socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET)
        with client:
            with patch.object(b,'registry',return_value={}),patch.object(b,'policy'),patch.object(b,'peer_matches',return_value=True),patch.object(m,'Controller',return_value=controller):
                b.worker(OP,'zombies',os.getpid(),'b'*64,server.detach(),-1)
            self.assertIn(b'replay',client.recv(512))
        self.assertEqual(len(controller.applied),1);m.LOCK_FD=None

class DeploymentLeaseLifetime(unittest.TestCase):
    def test_workstation_eof_keeps_guard_after_advisory_unlock(self):
        import subprocess
        text=(ROOT/'scripts/common.sh').read_text()
        body=text.split("coproc MODE_LEASE { remote bash -c '\n",1)[1].split("\n' mode-deployment-lease; }",1)[0]
        for release in (b'',b'hold\n',b'release\n'):
            with self.subTest(release=release),tempfile.TemporaryDirectory() as d:
                directory=Path(d);lock=directory/'lock';guard=directory/'guard';lock.touch();lock.chmod(0o644)
                script=body.replace('/opt/services/cod4/.production-transition.lock',str(lock)).replace('/opt/services/cod4/.production-deployment.json',str(guard))
                script=script.replace('== 0 &&',f'== {os.getuid()} &&')
                process=subprocess.Popen(['bash','-c',script],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                try:
                    self.assertEqual(process.stdout.readline(),b'locked\n')
                    if release:process.stdin.write(release);process.stdin.flush()
                    process.stdin.close();self.assertEqual(process.wait(timeout=3),0,process.stderr.read())
                    self.assertEqual(guard.exists(),release!=b'release\n')
                    with patch.object(m,'DEPLOY_LOCK',lock),patch.object(m,'DEPLOY_GUARD',guard),patch.object(m,'trusted',side_effect=lambda p,**kw:p):
                        acquired=b.Bridge().lock()
                        self.assertEqual(acquired is None,guard.exists())
                        if acquired:acquired.close()
                finally:
                    if process.poll() is None:process.kill();process.wait()
                    process.stdout.close();process.stderr.close()

class InheritedLease(unittest.TestCase):
    def test_worker_death_does_not_release_an_inflight_child_lease(self):
        import fcntl,subprocess,sys,time
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);lock=root/'lock';ready=root/'ready';lock.touch()
            code='''import importlib.util,sys,fcntl
from pathlib import Path
spec=importlib.util.spec_from_file_location("controller",Path(sys.argv[1])/"mode-controller.py")
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
with open(sys.argv[2],"r") as lock:
 fcntl.flock(lock,fcntl.LOCK_EX);m.LOCK_FD=lock.fileno()
 m.run([sys.executable,"-c","import sys,time;from pathlib import Path;Path(sys.argv[1]).write_text('ready');time.sleep(1)",sys.argv[3]])
'''
            worker=subprocess.Popen([sys.executable,'-c',code,str(ROOT/'scripts'),str(lock),str(ready)])
            try:
                deadline=time.monotonic()+3
                while not ready.exists() and time.monotonic()<deadline:time.sleep(.01)
                self.assertTrue(ready.exists())
                worker.kill();worker.wait(timeout=2)
                with lock.open('r') as contender:
                    with self.assertRaises(BlockingIOError):fcntl.flock(contender,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    time.sleep(1.1)
                    fcntl.flock(contender,fcntl.LOCK_EX|fcntl.LOCK_NB)
            finally:
                if worker.poll() is None:worker.kill();worker.wait()

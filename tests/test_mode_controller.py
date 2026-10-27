"""Host controller transaction tests; no Docker, SSH, or live services."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('controller', ROOT/'scripts/mode-controller.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.load_runtime()
OLD = 'sha256:' + '1'*64
NEW = 'sha256:' + '2'*64


def baseline():
    return {'name': 'cod4-production', 'networks': {'default': {'name': 'production'}},
            'services': {'cod4': {'container_name': 'cod4-production', 'image': OLD,
            'entrypoint': [m.runtime.EXECUTABLE], 'working_dir': m.runtime.ARTIFACT_ROOT,
            'command': ['+set', 'fs_game', 'mods/pml220', '+set', 'fs_homepath', m.runtime.PERSISTENT_HOME,
                        '+exec', 'server.cfg', '+map_rotate'], 'read_only': True,
            'environment': {'PRIVATE': 'fixture-$secret'},
            'volumes': [{'target': t, 'source': '/private/'+str(i)} for i, t in enumerate((
                '/home/user/cod4/main', '/home/user/cod4/zone', m.runtime.PERSISTENT_HOME))],
            'networks': {'default': None},
            'ports': [{'protocol': 'udp', 'published': '28960', 'target': 28960}]}}}


class Fake(m.Controller):
    def __init__(self, state, fail_target=False, fail_rollback=False):
        super().__init__(state); self.config=baseline(); self.applied=[]
        self.fail_target=fail_target; self.fail_rollback=fail_rollback
    def snapshot(self): return copy.deepcopy(self.config)
    def inspect(self): return {'Image': self.config['services']['cod4']['image']}
    def image(self, record, mode):
        return {'io.cod4.config.hash': 'fixture'}, (m.MODES[mode][0], 'mp_crash', 'mp_crash', '12')
    def backup_private(self, config, operation): pass
    def restore_private(self, config, operation): self.restored = True
    def apply(self, config):
        self.applied.append(copy.deepcopy(config)); self.config=copy.deepcopy(config)
    def verify(self, config, mode, record, operation):
        if operation == 'preflight': return
        if mode == 'zombies' and self.fail_target: raise ValueError('UDP timeout')
        if mode == 'promod' and self.fail_rollback: raise ValueError('rollback timeout')


class Transactions(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.state=Path(self.tmp.name)
        self.records={'promod': {'image': OLD}, 'zombies': {'image': NEW}}
        self.qual=patch.object(m, 'qualification', return_value=self.records); self.qual.start(); self.addCleanup(self.qual.stop)
    def test_success_retains_private_config_and_durable_snapshot(self):
        c=Fake(self.state); c.transition('zombies', {})
        tx=json.loads((self.state/'active.json').read_text()); self.assertEqual(tx['phase'], 'success')
        saved=json.loads((self.state/(tx['operation']+'-previous.json')).read_text())
        self.assertEqual(saved, baseline()); self.assertEqual(len(c.applied), 1)
        candidate=c.applied[0]['services']['cod4']; original=baseline()['services']['cod4']
        for key in ('volumes', 'environment', 'networks', 'ports', 'read_only'):
            self.assertEqual(candidate[key], original[key])
        self.assertEqual(candidate['image'], NEW)
        self.assertIn('server.cfg', candidate['command'])
        self.assertEqual((self.state/'active.json').stat().st_mode & 0o777, 0o600)
    def test_mocked_promod_zombies_promod_round_trip(self):
        c=Fake(self.state); c.transition('zombies', {}); c.transition('promod', {})
        self.assertEqual([x['services']['cod4']['image'] for x in c.applied],[NEW,OLD])
        for config in c.applied:
            self.assertEqual(config['services']['cod4']['environment'],baseline()['services']['cod4']['environment'])
        self.assertEqual(json.loads((self.state/'active.json').read_text())['phase'],'success')
    def test_failed_target_restores_exact_baseline(self):
        c=Fake(self.state, fail_target=True)
        with self.assertRaisesRegex(RuntimeError, 'exact previous runtime restored'): c.transition('zombies', {})
        self.assertEqual(c.applied[1], baseline()); self.assertEqual(len(c.applied), 2)
        self.assertEqual(json.loads((self.state/'active.json').read_text())['phase'], 'rolled_back')
    def test_failed_rollback_blocks_followup(self):
        c=Fake(self.state, fail_target=True, fail_rollback=True)
        with self.assertRaisesRegex(RuntimeError, 'operator recovery'): c.transition('zombies', {})
        with self.assertRaisesRegex(ValueError, 'Unfinished'): c.transition('promod', {})
        self.assertEqual(len(c.applied), 2)
        self.assertEqual(json.loads((self.state/'active.json').read_text())['phase'], 'recovery_required')
    def test_interrupted_transaction_blocks_new_apply(self):
        m.atomic(self.state/'active.json', {'phase':'pending'})
        c=Fake(self.state)
        with self.assertRaisesRegex(ValueError, 'Unfinished'): c.transition('zombies', {})
        self.assertFalse(c.applied)
    def test_allowlist_rejects_shell_paths_and_other_modes(self):
        for value in ('zombies;quit','../promod','hardcore','Zombies','', '$(id)'):
            c=Fake(self.state)
            with self.assertRaises(ValueError): c.transition(value, {})
            self.assertFalse(c.applied)
    def test_unqualified_rollback_rejected(self):
        self.records['promod']['image']='sha256:'+'3'*64
        c=Fake(self.state)
        with self.assertRaisesRegex(ValueError, 'rollback target'): c.transition('zombies', {})
        self.assertFalse(c.applied)


class Authorization(unittest.TestCase):
    def test_disabled_controller(self):
        with self.assertRaisesRegex(ValueError, 'disabled'): m.qualification({'enabled':False})
    def test_both_modes_mandatory(self):
        with patch.object(m, 'evidence'):
            with self.assertRaisesRegex(ValueError, 'Both'):
                m.qualification({'enabled':True,'authorization_tests':{},'rollback_tests':{},'modes':{}})
    def test_real_client_qualification_required(self):
        records={name:{'image': OLD if name == 'promod' else NEW, 'qualified':True,'evidence':{gate:{'image': OLD if name == 'promod' else NEW} for gate in ('independent_review','mandatory_ci','operator_approval','gameplay')}} for name in m.MODES}
        with patch.object(m, 'evidence'):
            with self.assertRaisesRegex(ValueError, 'actual-client'):
                m.qualification({'enabled':True,'authorization_tests':{},'rollback_tests':{},'modes':records})
    def test_cli_denies_nonroot_before_docker(self):
        with patch.object(m.os, 'geteuid', return_value=1000), patch.object(m.sys, 'argv', ['mode-controller.py','switch','zombies']), patch.object(m,'run') as run:
            with self.assertRaises(SystemExit): m.main()
            run.assert_not_called()
    def test_untrusted_and_symlinked_evidence_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            target=Path(d)/'evidence';target.write_text('fixture')
            with self.assertRaises(ValueError): m.trusted(target)
            link=Path(d)/'link';link.symlink_to(target)
            with self.assertRaises(ValueError):m.trusted(link)
    def test_udp_verification_checks_purity_and_map(self):
        good={'fs_game':'mods/btd_alpha_001','g_gametype':'war','sv_pure':'1','mapname':'mp_crash'}
        m.Controller.status_values(good,'zombies')
        for key in good:
            with self.assertRaises(ValueError):m.Controller.status_values({**good,key:''},'zombies')

if __name__ == '__main__': unittest.main()

class Concurrency(unittest.TestCase):
    def test_host_lock_rejects_second_operator_before_registry_or_apply(self):
        import fcntl
        with tempfile.TemporaryDirectory() as d:
            state=Path(d)
            with (state/'transition.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with patch.object(m,'STATE',state), patch.object(m,'DEPLOY_LOCK',state/'transition.lock'), patch.object(m.os,'geteuid',return_value=0), patch.object(m,'trusted', side_effect=lambda path, **kwargs:path), patch.object(m.sys,'argv',['controller','switch','zombies']), patch.object(m,'primitive') as apply:
                    with self.assertRaises(SystemExit) as error: m.main()
                    self.assertEqual(error.exception.code,2)
                    apply.assert_not_called()

class DockerVerification(unittest.TestCase):
    def setUp(self):
        self.config=baseline()
        self.original={'Image':OLD,'State':{'Running':True},
            'Config':{'Cmd':self.config['services']['cod4']['command'],
                      'Entrypoint':[m.runtime.EXECUTABLE], 'WorkingDir':m.runtime.ARTIFACT_ROOT,
                      'Env':['PRIVATE=fixture'], 'Labels':{}},
            'HostConfig':{'ReadonlyRootfs':True,'PortBindings':{'28960/udp':[{'HostPort':'28960'}]}},
            'Mounts':[{'Source':'/private/home','Destination':m.runtime.PERSISTENT_HOME,'RW':True}],
            'NetworkSettings':{'Networks':{'production':{}}}}
        self.status={'fs_game':'mods/pml220','g_gametype':'sd','sv_pure':'1','mapname':'mp_crash'}
    def verify(self, observed):
        c=m.Controller(); c.current=copy.deepcopy(self.original)
        with patch.object(c,'inspect',return_value=observed), patch.object(c,'query',return_value=self.status), patch.object(c,'external',return_value=self.status):
            c.verify(self.config,'promod',{},'fixture')
    def test_exact_image_and_private_runtime_pass(self): self.verify(copy.deepcopy(self.original))
    def test_mount_inspection_order_is_not_runtime_drift(self):
        self.original['Mounts'].append({'Source':'/private/main','Destination':'/home/user/cod4/main','RW':False})
        observed=copy.deepcopy(self.original);observed['Mounts'].reverse()
        self.verify(observed)
    def test_wrong_image_environment_mounts_networks_ports_rejected(self):
        variants=[]
        for path,value in [(('Image',),NEW),(('State','Running'),False),
                (('Config','Env'),['PRIVATE=changed']),(('Config','Cmd'),['+map','mp_crash']),
                (('Mounts',),[]),(('NetworkSettings','Networks'),{'other':{}}),
                (('HostConfig','ReadonlyRootfs'),False),(('HostConfig','PortBindings'),{})]:
            observed=copy.deepcopy(self.original); node=observed
            for key in path[:-1]:node=node[key]
            node[path[-1]]=value;variants.append(observed)
        for observed in variants:
            with self.assertRaises(ValueError):self.verify(observed)
    def test_external_result_must_match_operation(self):
        c=m.Controller()
        with patch.object(m,'trusted'),patch.object(m,'run',return_value='{"external":true,"operation":"wrong"}'):
            with self.assertRaisesRegex(ValueError,'attestation'):c.external({},'expected')
    def test_external_failure_rolls_back_even_when_local_passes(self):
        with tempfile.TemporaryDirectory() as d:
            c=Fake(Path(d));c.fail_target=True
            records={'promod':{'image':OLD},'zombies':{'image':NEW}}
            with patch.object(m,'qualification',return_value=records):
                with self.assertRaises(RuntimeError):c.transition('zombies',{})
            journal=json.loads((Path(d)/'active.json').read_text())
            self.assertEqual([e['phase'] for e in journal['events']],['pending','verifying','rolling_back','rolled_back'])

class PrivateRollback(unittest.TestCase):
    def test_actual_private_bytes_and_links_are_restored(self):
        import tarfile
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); state=root/'state';state.mkdir();home=root/'home';home.mkdir()
            (home/'private.cfg').write_text('original-private-fixture')
            (home/'relative').symlink_to('private.cfg')
            operation='a'*32
            with tarfile.open(state/(operation+'-private.tar.gz'),'w:gz',dereference=False) as tar:
                tar.add(home,arcname='production/home')
            (home/'private.cfg').write_text('changed');(home/'extra').write_text('target-state')
            m.Controller(state).extract_home(home,operation)
            self.assertEqual((home/'private.cfg').read_text(),'original-private-fixture')
            self.assertEqual((home/'relative').readlink(),Path('private.cfg'))
            self.assertFalse((home/'extra').exists())
            failed=list(state.glob('*-failed-home-*'));self.assertEqual(len(failed),1)
            self.assertEqual((failed[0]/'private.cfg').read_text(),'changed')

    def test_archive_cannot_write_through_links_or_paths(self):
        import io,tarfile
        for unsafe in ('../escape','production/home/link/file','production/home/./link/file'):
            with self.subTest(path=unsafe),tempfile.TemporaryDirectory() as d:
                root=Path(d);state=root/'state';state.mkdir();home=root/'home';home.mkdir();outside=root/'outside';outside.mkdir()
                operation='b'*32
                with tarfile.open(state/(operation+'-private.tar.gz'),'w:gz') as tar:
                    link=tarfile.TarInfo('production/home/link');link.type=tarfile.SYMTYPE;link.linkname=str(outside);tar.addfile(link)
                    file=tarfile.TarInfo(unsafe);file.size=4;tar.addfile(file,io.BytesIO(b'evil'))
                with self.assertRaises(ValueError):m.Controller(state).extract_home(home,operation)
                self.assertFalse((outside/'file').exists());self.assertTrue(home.is_dir())

class Recovery(unittest.TestCase):
    def test_interrupted_apply_restores_only_previous_runtime(self):
        with tempfile.TemporaryDirectory() as d:
            state=Path(d);controller=Fake(state)
            original=controller.apply
            def interrupted(config):
                original(config)
                raise KeyboardInterrupt()
            controller.apply=interrupted
            records={'promod':{'image':OLD},'zombies':{'image':NEW}}
            with patch.object(m,'qualification',return_value=records):
                with self.assertRaises(KeyboardInterrupt):controller.transition('zombies',{})
                controller.apply=original
                with patch.object(m,'rollback_qualification',return_value=records['promod']): controller.recover({})
            self.assertEqual([v['services']['cod4']['image'] for v in controller.applied],[NEW,OLD])
            self.assertEqual(controller.config,baseline())
            self.assertEqual(json.loads((state/'active.json').read_text())['phase'],'rolled_back')

    def test_notification_failure_never_applies(self):
        with tempfile.TemporaryDirectory() as d:
            controller=Fake(Path(d));records={'promod':{'image':OLD},'zombies':{'image':NEW}}
            with patch.object(m,'qualification',return_value=records):
                controller.transition('zombies',{},on_ready=lambda tx:False)
            self.assertFalse(controller.applied)
            self.assertEqual(json.loads((Path(d)/'active.json').read_text())['phase'],'denied')

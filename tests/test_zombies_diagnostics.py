import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/zombies-diagnostics.py'
spec = importlib.util.spec_from_file_location('diagnostics', SCRIPT)
diagnostics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnostics)


class DiagnosticsTests(unittest.TestCase):
    def test_commands_and_credentials_cannot_escape_structural_filter(self):
        text = (b'2026-10-26T22:00:01.123456789Z cmd 17: "rcon password-SENTINEL CoD4 MP99.9 build 777"\n'
                b'serverCommand: 205: rcon password-SENTINEL build 777\n'
                b'rcon_password is: "password-SENTINEL"\n'
                b'authorization: Bearer password-SENTINEL\n'
                b'userinfo password-SENTINEL\n'
                b'http://user:password-SENTINEL@host.invalid/path?token=password-SENTINEL\n'
                b'CL_CGameNeedsServerCommand: a reliable command was cycled out\n'
                b'serverCommandNumber: 17\n')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            diagnostics.filter_stream(io.BytesIO(text))
        rendered = output.getvalue()
        self.assertNotIn('SENTINEL', rendered)
        self.assertNotIn('99.9', rendered)
        # Observer clock digits can coincidentally contain the canary number.
        # Inspect retained payload fields separately from generated timestamps.
        payload = [{k:v for k,v in json.loads(line).items() if k not in ('observed_utc','observer_monotonic_ns')} for line in rendered.splitlines()]
        self.assertNotIn('777', json.dumps(payload))
        entries = [json.loads(line) for line in rendered.splitlines()]
        self.assertEqual(entries[0]['dump_ring_slot'], '17')
        self.assertEqual(entries[0]['source_utc'], '2026-10-26T22:00:01.123456789Z')
        self.assertEqual(entries[1]['cgame_requested_sequence'], '205')
        self.assertEqual(entries[2]['diagnostic'], 'command_ring_cycled_out')
        self.assertEqual(entries[3]['requested_ring_index'], '17')
        self.assertEqual(entries[-1]['diagnostics_retained'], 4)

    def test_version_ack_and_download_extract_fields_without_names(self):
        self.assertEqual(diagnostics.extract('"version" is: "CoD4 MP21.1 win_mingw-x86"'),
                         [{'reported_version': '21.1'}])
        self.assertEqual(diagnostics.extract('Out of range reliableAcknowledge message from PRIVATE_PLAYER - reliableSequence is 440, reliableAcknowledge is 300'),
                         [{'reliable_sequence': 440, 'reliable_acknowledge': 300, 'diagnostic': 'out_of_range_ack'}])
        self.assertEqual(diagnostics.extract('clientDownload: 2 : writing position 1200 with 1200 bytes of 33000 bytes'),
                         [{'download_offset': 1200, 'download_block_bytes': 1200, 'download_total_bytes': 33000}])

    def test_chat_and_embedded_command_text_are_not_diagnostic_evidence(self):
        for line in ('player chat: ' + diagnostics.ERROR,
                     'chat: CoD4 MP99.9 build 777',
                     'say serverCommandNumber: 42',
                     'chat: Out of range reliableAcknowledge message from x - reliableSequence is 440, reliableAcknowledge is 300',
                     'chat: clientDownload: 2 : writing position 1200 with 1200 bytes of 33000 bytes',
                     'chat: SV_SendClientGameState() for x',
                     'chat: EXE_SERVERCOMMANDOVERFLOW'):
            self.assertEqual(diagnostics.extract(line), [], line)
        self.assertEqual(diagnostics.extract('Error: ' + diagnostics.ERROR),
                         [{'diagnostic': 'command_ring_cycled_out'}])

    def test_oversized_lines_are_discarded_without_parsing_fragments(self):
        payload = b'x' * 20000 + b'\nserverCommandNumber: 42\n'
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            diagnostics.filter_stream(io.BytesIO(payload))
        entries = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(entries[0]['requested_ring_index'], '42')
        self.assertEqual(entries[-1]['lines_seen'], 2)

    def test_process_snapshot_reads_only_maps_comm_and_stat(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / '123'; directory.mkdir()
            module = root / 'cod4x_021.dll'; module.write_bytes(b'module fixture')
            (directory / 'comm').write_text('iw3mp.exe\n')
            (directory / 'stat').write_text('123 (iw3mp.exe) ' + ' '.join(['0'] * 19 + ['999'] + ['0'] * 5))
            (directory / 'maps').write_text(f'001-002 r-xp 0000 08:01 123 {module}\n')
            # cmdline/environ/mem intentionally absent; successful collection proves no dependency.
            before = module.stat()
            result = diagnostics.snapshot(123, root)
            self.assertEqual(result['process_start_ticks'], '999')
            self.assertEqual(result['mapped_files'][0]['sha256'], diagnostics.digest(module))
            self.assertEqual(before.st_mtime_ns, module.stat().st_mtime_ns)
            (directory / 'comm').write_text('other.exe\n')
            with self.assertRaises(ValueError): diagnostics.snapshot(123, root)

    def test_checkpoint_import_only_appended_lines_and_rejects_rotation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); log = root / 'console.log'; checkpoint = root / 'checkpoint.json'
            log.write_bytes(b'serverCommandNumber: 1\n')
            result = subprocess.run([sys.executable, str(SCRIPT), 'checkpoint', '--file', str(log)], capture_output=True, check=True)
            checkpoint.write_bytes(result.stdout)
            with log.open('ab') as stream: stream.write(b'serverCommandNumber: 9\n')
            argv = [sys.executable, str(SCRIPT), 'console', '--file', str(log), '--checkpoint', str(checkpoint)]
            result = subprocess.run(argv, capture_output=True, check=True)
            entries = [json.loads(line) for line in result.stdout.splitlines()]
            self.assertEqual(entries[0]['requested_ring_index'], '9')
            self.assertEqual(len(entries), 2)
            log.rename(root / 'old.log'); log.write_bytes(b'serverCommandNumber: 2\n')
            result = subprocess.run(argv, capture_output=True)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stdout)['event'], 'collection_failed')

    def test_checkpoint_rejects_same_inode_rewrite_and_skips_partial_line(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); log = root / 'console.log'; checkpoint = root / 'checkpoint.json'
            log.write_bytes(b'cmd 17: "')
            inode = log.stat().st_ino
            checkpoint.write_bytes(subprocess.run([sys.executable, str(SCRIPT), 'checkpoint', '--file', str(log)],
                                                  capture_output=True, check=True).stdout)
            with log.open('ab') as stream:
                stream.write(b'serverCommandNumber: 8\nserverCommandNumber: 10\n')
            argv = [sys.executable, str(SCRIPT), 'console', '--file', str(log), '--checkpoint', str(checkpoint)]
            result = subprocess.run(argv, capture_output=True, check=True)
            entries = [json.loads(line) for line in result.stdout.splitlines()]
            self.assertEqual(entries[0]['requested_ring_index'], '10')
            self.assertEqual(len(entries), 2)
            self.assertTrue(entries[-1]['skipped_partial_line'])
            log.write_bytes(b'rewritten-prefix\nserverCommandNumber: 900\n')
            self.assertEqual(log.stat().st_ino, inode)
            result = subprocess.run(argv, capture_output=True)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stdout)['event'], 'collection_failed')

    def test_server_commands_are_read_only_pinned_and_raw_data_not_retained(self):
        responses = [subprocess.CompletedProcess([], 0, b'2026-10-26T22:00:00.000000000Z\n'),
                     subprocess.CompletedProcess([], 0, (('a' * 64) + ' sha256:' + ('b' * 64) + ' true\n').encode())]
        child = unittest.mock.Mock()
        child.stdout = io.BytesIO(b'2026-10-26T22:00:01Z rcon_password secret-SENTINEL\n2026-10-26T22:00:02Z EXE_SERVERCOMMANDOVERFLOW\n')
        child.wait.return_value = 0; child.poll.return_value = 0
        output = io.StringIO()
        with patch.object(sys, 'argv', [str(SCRIPT), 'server', '--since', '2026-10-26T22:00:00Z']), \
             patch.object(diagnostics.subprocess, 'run', side_effect=responses) as run, \
             patch.object(diagnostics.subprocess, 'Popen', return_value=child) as popen, \
             contextlib.redirect_stdout(output):
            diagnostics.main()
        commands = [call.args[0][-1] for call in run.call_args_list] + [popen.call_args.args[0][-1]]
        self.assertEqual(commands, ['date -u +%Y-%m-%dT%H:%M:%S.%NZ',
            "docker inspect --format '{{.Id}} {{.Image}} {{.State.Running}}' cod4-homolog",
            'docker logs --timestamps --since 2026-10-26T22:00:00Z --tail 2000 cod4-homolog'])
        self.assertNotIn('SENTINEL', output.getvalue())
        entries = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(entries[1]['image_id'], 'sha256:' + ('b' * 64))
        self.assertEqual(entries[2]['source_utc'], '2026-10-26T22:00:02Z')

    def test_packet_command_is_print_only_and_rejects_filter_injection(self):
        with patch.object(diagnostics.subprocess, 'Popen') as popen, \
             patch.object(diagnostics.subprocess, 'run') as run, \
             patch.object(sys, 'argv', [str(SCRIPT), 'packet-command', '--server-ip', '192.0.2.1']), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            diagnostics.main()
        run.assert_not_called(); popen.assert_not_called()
        self.assertIn('udp port 28962', output.getvalue())
        for forbidden in (' -A ', ' -X ', ' -w '): self.assertNotIn(forbidden, output.getvalue())
        result = subprocess.run([sys.executable, str(SCRIPT), 'packet-command', '--server-ip', '192.0.2.1; quit'], capture_output=True)
        self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__': unittest.main()

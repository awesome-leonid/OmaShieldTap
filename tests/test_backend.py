"""Isolated tests for the button-only, agent-facing CLI."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('remote_buttons', ROOT / 'remote_buttons.py')
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='remote-buttons-test-', dir=os.environ.get('TMPDIR'))
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.env = os.environ.copy()
        self.env.update(HOME=str(self.home), XDG_CONFIG_HOME=str(self.home / 'config'),
                        XDG_STATE_HOME=str(self.home / 'state'), XDG_DATA_HOME=str(self.home / 'data'))
        bin_dir = self.home / 'bin'
        bin_dir.mkdir()
        fake = bin_dir / 'hyprctl'
        fake.write_bytes((ROOT / 'tests/fixtures/hyprctl').read_bytes())
        fake.chmod(0o755)
        self.env['PATH'] = str(bin_dir) + os.pathsep + self.env['PATH']
        self.config = self.home / 'config/omarchy-remote-buttons/config.json'

    def cli(self, *args, success=True, source=None):
        if source is None:
            source = ROOT / 'remote_buttons.py'
        result = subprocess.run([sys.executable, str(source), *args],
                                env=self.env, text=True, capture_output=True, timeout=10)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
        data = json.loads(result.stdout)
        self.assertEqual(data['ok'], success)
        return data

    def test_schema_is_self_documenting_and_read_only(self):
        data = self.cli('schema')
        self.assertEqual(data['schema'], 1)
        self.assertEqual(data['cli'], 'omarchy-remote-buttons')
        self.assertIn('bind', data['commands'])
        self.assertIn('apply', data['commands'])
        self.assertEqual(set(data['action_kinds']), {'native', 'disabled', 'key', 'shortcut', 'command'})
        self.assertEqual(len(data['buttons']), 16)
        self.assertEqual(next(b for b in data['buttons'] if b['id'] == 'mic')['key'], 'XF86Search')
        self.assertFalse((self.home / 'config').exists())
        self.assertFalse((self.home / 'state').exists())

    def test_default_model_is_complete_and_native_except_center_and_mic(self):
        config = backend.default_config('shield-remote', 'NVIDIA SHIELD Remote')
        self.assertEqual(config['schema'], 1)
        self.assertEqual(config['revision'], 1)
        self.assertEqual(len(config['buttons']), 16)
        buttons = {b['id']: b for b in config['buttons']}
        self.assertEqual(buttons['center']['action'], {'kind': 'key', 'value': 'Return'})
        self.assertEqual(buttons['mic']['action'], {'kind': 'command', 'argv': ['omarchy-dictation', 'toggle']})
        self.assertTrue(all(b['action']['kind'] == 'native' for ident, b in buttons.items()
                            if ident not in ('center', 'mic')))
        self.assertEqual(buttons['center']['summary'], 'Enter')

    def test_validate_rejects_unsafe_or_malformed_models(self):
        import copy
        base = backend.default_config('shield-remote', 'Shield')
        self.assertEqual(backend.validate(base), base)
        changes = [
            ('keyboard', '../laptop'), ('keyboard', 'bad\nname'), ('keyboard', 'k' * 129), ('schema', True),
            ('revision', -1), ('remote_name', 'bad\x00name'), ('buttons', base['buttons'] * 5),
        ]
        for field, value in changes:
            with self.subTest(field=field, value=str(value)[:40]):
                config = copy.deepcopy(base)
                config[field] = value
                with self.assertRaises(backend.Error):
                    backend.validate(config)
        invalid_actions = [
            {'kind': 'command', 'argv': 'touch /tmp/no'},
            {'kind': 'command', 'argv': []}, {'kind': 'command', 'argv': ['bad\ncmd']},
            {'kind': 'key', 'value': 'Return; exec evil'},
            {'kind': 'shortcut', 'mods': 'SUPER;evil', 'key': 'E'},
            {'kind': 'native', 'argv': ['evil']}, {'kind': 'bogus'},
        ]
        for action in invalid_actions:
            with self.subTest(action=action):
                config = copy.deepcopy(base)
                config['buttons'][0]['action'] = action
                with self.assertRaises(backend.Error):
                    backend.validate(config)
        for field, value in [('id', 'bad/../id'), ('label', 'x' * 161), ('key', 'bad\nkey'),
                             ('summary', 'x' * 513), ('id', 'mic')]:
            config = copy.deepcopy(base)
            config['buttons'][0][field] = value
            with self.subTest(field=field), self.assertRaises(backend.Error):
                backend.validate(config)

    def test_read_only_commands_and_errors_are_machine_readable(self):
        self.assertEqual(self.cli('agent-guide')['cli'], 'omarchy-remote-buttons')
        devices = self.cli('devices')['keyboards']
        self.assertEqual(devices[0]['name'], 'shield-remote')
        self.assertEqual(self.cli('show', success=False)['error']['code'], 'not_configured')
        self.assertEqual(self.cli('bogus', success=False)['error']['code'], 'usage')
        self.assertFalse((self.home / 'config').exists())
        self.assertFalse((self.home / 'state').exists())
        self.config.parent.mkdir(parents=True)
        config = backend.default_config('shield-remote', 'Shield')
        self.config.write_text(json.dumps(config))
        self.assertEqual(self.cli('show')['config'], config)

    def test_transaction_publishes_config_only_after_reload(self):
        from unittest.mock import patch
        config = backend.default_config('shield-remote', 'Shield')
        with patch.dict(os.environ, self.env, clear=True):
            paths = backend.Paths()
            paths.hook.parent.mkdir(parents=True)
            paths.hook.write_text('-- my unrelated bindings\n')
            backend.transact(paths, lambda old: config)
            self.assertEqual(json.loads(paths.config.read_text()), config)
            self.assertEqual((self.home / 'config-at-reload').read_text(), 'MISSING\n')
            self.assertIn('-- my unrelated bindings', paths.hook.read_text())
            self.assertTrue(paths.wrapper.stat().st_mode & 0o111)
            self.assertTrue(paths.ownership.exists())

    def local_cli(self, *args, success=True):
        from contextlib import redirect_stdout
        from io import StringIO
        from unittest.mock import patch
        output = StringIO()
        with patch.dict(os.environ, self.env, clear=True), redirect_stdout(output):
            status = backend.main(list(args))
        self.assertEqual(status == 0, success, output.getvalue())
        return json.loads(output.getvalue())

    def test_setup_and_reassignment_are_single_commands_and_never_execute_actions(self):
        config = self.local_cli('setup', '--keyboard', 'shield-remote', '--name', 'My Shield')['config']
        self.assertEqual(config['revision'], 1)
        sentinel = self.home / 'must-not-exist'
        data = self.local_cli('bind', 'mic', '--command', json.dumps(['touch', str(sentinel)]),
                              '--label', 'Launch thing')['config']
        self.assertEqual(data['revision'], 2)
        button = next(b for b in data['buttons'] if b['id'] == 'mic')
        self.assertEqual(button['label'], 'Launch thing')
        self.assertEqual(button['action']['argv'], ['touch', str(sentinel)])
        self.assertFalse(sentinel.exists())
        data = self.local_cli('unbind', 'mic')['config']
        self.assertEqual(next(b for b in data['buttons'] if b['id'] == 'mic')['action'], {'kind': 'native'})
        self.assertEqual(self.local_cli('setup', '--keyboard', 'laptop-keyboard', success=False)['error']['code'], 'conflict')

    def test_builtins_shortcuts_disabled_and_optimistic_batch(self):
        self.local_cli('setup', '--keyboard', 'shield-remote')
        for name, expected in [('enter', {'kind': 'key', 'value': 'Return'}),
                               ('copy', {'kind': 'shortcut', 'mods': 'CTRL', 'key': 'C'}),
                               ('paste', {'kind': 'shortcut', 'mods': 'CTRL', 'key': 'V'}),
                               ('terminal', {'kind': 'command', 'argv': ['omarchy-launch-terminal']}),
                               ('dictation-toggle', {'kind': 'command', 'argv': ['omarchy-dictation', 'toggle']})]:
            data = self.local_cli('bind', 'center', '--action', name)['config']
            self.assertEqual(data['buttons'][0]['action'], expected)
        data = self.local_cli('bind', 'center', '--shortcut', 'CTRL + SHIFT + V')['config']
        self.assertEqual(data['buttons'][0]['action'], {'kind': 'shortcut', 'mods': 'CTRL + SHIFT', 'key': 'V'})
        data = self.local_cli('bind', 'center', '--disabled')['config']
        self.assertEqual(data['buttons'][0]['action'], {'kind': 'disabled'})
        data['buttons'][0]['action'] = {'kind': 'native'}
        result = self.local_cli('apply', '--json', json.dumps(data))['config']
        self.assertEqual(result['revision'], data['revision'] + 1)
        self.assertEqual(self.local_cli('apply', '--json', json.dumps(data), success=False)['error']['code'], 'conflict')

    def test_reload_failure_restores_bytes_permissions_and_unrelated_edits(self):
        self.local_cli('setup', '--keyboard', 'shield-remote')
        hook = self.home / 'config/hypr/bindings.lua'
        hook.write_text(hook.read_text() + '\n-- later unrelated edit\n')
        hook.chmod(0o640)
        files = [self.config, hook, self.home / 'config/hypr/remote-buttons.lua',
                 self.home / '.local/bin/omarchy-remote-buttons',
                 self.home / 'state/omarchy-remote-buttons/ownership.json']
        before = {p: (p.read_bytes(), p.stat().st_mode) for p in files}
        (self.home / 'config-error').touch()
        error = self.local_cli('bind', 'center', '--key', 'Escape', success=False)['error']
        self.assertEqual(error['code'], 'compositor')
        self.assertEqual({p: (p.read_bytes(), p.stat().st_mode) for p in files}, before)
        calls = [json.loads(line) for line in (self.home / 'hyprctl.calls').read_text().splitlines()]
        self.assertEqual(calls[-5:], [['reload'], ['configerrors'], ['-j', 'binds'], ['binds'], ['-j', 'binds']])
        self.assertEqual(list(self.home.rglob('.remote-buttons-*')), [])

    def test_reassignment_does_not_replace_unchanged_hook(self):
        self.cli('setup', '--keyboard', 'shield-remote')
        hook = self.home / 'config/hypr/bindings.lua'
        before = hook.stat()
        self.cli('bind', 'center', '--key', 'Tab')
        self.assertEqual((hook.stat().st_ino, hook.stat().st_mtime_ns),
                         (before.st_ino, before.st_mtime_ns))

    def test_setup_refuses_hook_edit_between_snapshot_and_render(self):
        from unittest.mock import patch
        hook = self.home / 'config/hypr/bindings.lua'
        hook.parent.mkdir(parents=True)
        hook.write_text('-- original\n')
        render = backend.render_lua

        def concurrent_edit(config, paths):
            hook.write_text('-- concurrent edit\n')
            return render(config, paths)

        with patch.object(backend, 'render_lua', side_effect=concurrent_edit):
            result = self.local_cli('setup', '--keyboard', 'shield-remote', success=False)
        self.assertEqual(result['error']['code'], 'file_conflict')
        self.assertEqual(hook.read_text(), '-- concurrent edit\n')
        self.assertFalse(self.config.exists())

    def test_rollback_preserves_external_replacement_of_published_lua(self):
        self.cli('setup', '--keyboard', 'shield-remote')
        original = self.config.read_bytes()
        oldmap = self.keymap_path()
        (self.home / 'replace-lua-on-reload').touch()
        (self.home / 'config-error').touch()
        result = self.cli('bind', 'center', '--key', 'Tab', success=False)
        self.assertEqual(result['error']['code'], 'rollback_conflict')
        self.assertIn('remote-buttons.lua', result['error']['message'])
        self.assertEqual((self.home / 'config/hypr/remote-buttons.lua').read_text(), '-- external replacement\n')
        self.assertEqual(self.config.read_bytes(), original)
        self.assertEqual(self.keymap_path(), oldmap)

    def test_retiring_old_map_rechecks_original_after_reload(self):
        self.cli('setup', '--keyboard', 'shield-remote')
        original = self.config.read_bytes()
        oldmap = self.keymap_path()
        (self.home / 'edit-old-map-on-reload').touch()
        error = self.cli('bind', 'center', '--key', 'Tab', success=False)['error']
        self.assertEqual(error['code'], 'file_conflict')
        self.assertEqual(self.config.read_bytes(), original)
        self.assertEqual(self.keymap_path(), oldmap)
        self.assertTrue(oldmap.read_text().endswith('// concurrent edit\n'))

    def test_publication_to_absent_path_does_not_clobber_late_creation(self):
        from unittest.mock import patch
        wrapper = self.home / '.local/bin/omarchy-remote-buttons'
        take_snapshot = backend.snapshot
        seen = 0

        def concurrent_create(path):
            nonlocal seen
            result = take_snapshot(path)
            if path == wrapper:
                seen += 1
                if seen == 3:  # Immediately after the per-file publish recheck.
                    wrapper.write_text('-- external creation\n')
            return result

        with patch.object(backend, 'snapshot', side_effect=concurrent_create):
            error = self.local_cli('setup', '--keyboard', 'shield-remote', success=False)['error']
        self.assertEqual(error['code'], 'file_conflict')
        self.assertEqual(wrapper.read_text(), '-- external creation\n')
        self.assertFalse(self.config.exists())

    def test_rollback_reports_successful_reload_with_stale_bindings_as_failure(self):
        self.cli('setup', '--keyboard', 'shield-remote')
        (self.home / 'config-error').touch()
        (self.home / 'ignore-rollback-reload').touch()
        error = self.cli('bind', 'center', '--key', 'Tab', success=False)['error']
        self.assertEqual(error['code'], 'rollback_failed')

    def test_show_rejects_symlinks_oversize_and_traversal(self):
        self.config.parent.mkdir(parents=True)
        target = self.home / 'target.json'
        target.write_text(json.dumps(backend.default_config('shield-remote', 'Shield')))
        self.config.symlink_to(target)
        self.assertEqual(self.cli('show', success=False)['error']['code'], 'invalid')
        self.config.unlink()
        self.config.write_bytes(b' ' * 262145)
        self.assertIn('size', self.cli('show', success=False)['error']['message'].lower())
        self.env['XDG_CONFIG_HOME'] = str(self.home / 'config/../config')
        self.assertIn('path', self.cli('show', success=False)['error']['message'].lower())

    def test_successful_reload_without_new_binding_generation_is_rejected(self):
        self.cli('setup', '--keyboard', 'shield-remote', '--acknowledge-single-key-bindings')
        before = self.config.read_bytes()
        (self.home / 'ignore-reload-once').touch()
        error = self.cli('bind', 'center', '--key', 'Tab', success=False)['error']
        self.assertEqual(error['code'], 'activation_failed')
        self.assertEqual(self.config.read_bytes(), before)
        self.assertEqual(self.keymap_path().name, 'remote-buttons-r1.xkb')

    def test_disabled_mapping_must_have_a_registered_consuming_binding(self):
        self.cli('setup', '--keyboard', 'shield-remote', '--acknowledge-single-key-bindings')
        (self.home / 'omit-disabled-once').touch()
        error = self.cli('bind', 'power', '--disabled', success=False)['error']
        self.assertEqual(error['code'], 'activation_failed')
        self.cli('bind', 'power', '--disabled')
        rows = json.loads((self.home / 'active-managed-binds.json').read_text())
        self.assertEqual(next(row for row in rows if row['key'] == 'F27')['dispatcher'], '__lua')

    def test_wrong_binding_flags_block_activation(self):
        (self.home / 'wrong-manager-flags-once').touch()
        error = self.cli('setup', '--keyboard', 'shield-remote', success=False)['error']
        self.assertEqual(error['code'], 'activation_failed')
        self.assertFalse(self.config.exists())

    def test_remove_refuses_to_commit_if_managed_bindings_remain_active(self):
        self.cli('setup', '--keyboard', 'shield-remote')
        (self.home / 'ignore-reload-once').touch()
        error = self.cli('remove', success=False)['error']
        self.assertEqual(error['code'], 'activation_failed')
        self.assertTrue(self.config.exists())

    def test_real_renderer_uses_compiled_per_device_reserved_symbols_not_global_unbind(self):
        self.cli('setup', '--keyboard', 'shield-remote')
        keymap = self.keymap_path()
        lua = (self.home / 'config/hypr/remote-buttons.lua').read_text()
        self.assertTrue(keymap.exists())
        compiled = subprocess.run(['xkbcli', 'compile-keymap', '--from-xkb', str(keymap)],
                                  env=self.env, text=True, capture_output=True, timeout=10)
        self.assertEqual(compiled.returncode, 0, compiled.stderr)
        self.assertRegex(compiled.stdout, r'key <I361>\s*\{[^}]*F13')
        self.assertRegex(compiled.stdout, r'key <I225>\s*\{[^}]*F14')
        self.assertRegex(compiled.stdout, r'key <UP>\s*\{[^}]*Up')
        self.assertIn('kb_file = ', lua)
        self.assertIn('resolve_binds_by_sym = true', lua)
        self.assertIn('device = { inclusive = true, list = { "shield-remote" } }', lua)
        self.assertIn('hl.bind("F13"', lua)
        self.assertNotIn('hl.unbind', lua)
        self.assertNotIn('o.rebind', lua)
        self.assertIn('send_key_state', lua)
        self.assertIn('timeout = 50', lua)
        self.assertIn(' run mic --revision 1', lua)
        self.cli('bind', 'power', '--disabled')
        lua = (self.home / 'config/hypr/remote-buttons.lua').read_text()
        self.assertIn('hl.bind("F27"', lua)
        self.assertNotIn('XF86PowerOff', lua)

    def test_conflicting_bindings_are_refused_without_overwriting_laptop_shortcuts(self):
        conflicts = [
            {'key': 'F13', 'keycode': 0}, {'key': 'F35', 'keycode': 0},
            {'key': '', 'keycode': 361}, {'key': 'code:225', 'keycode': 0},
            {'key': 'Any', 'catch_all': True}, {'key': '', 'keycode': 0},
            {'key': 'A & F14', 'keycode': 0},
        ]
        for bind in conflicts:
            with self.subTest(bind=bind):
                self.env['FAKE_BINDS'] = json.dumps([bind])
                error = self.cli('setup', '--keyboard', 'shield-remote', success=False)['error']
                self.assertEqual(error['code'], 'binding_conflict')
                self.assertFalse(self.config.exists())
                self.assertFalse((self.home / 'config/hypr/remote-buttons.lua').exists())
        self.env['FAKE_BINDS'] = json.dumps([{'key': 'XF86PowerOff', 'keycode': 0, 'modmask': 0}])
        self.cli('setup', '--keyboard', 'shield-remote', '--acknowledge-single-key-bindings')
        self.assertTrue(self.config.exists())

    def test_run_dispatcher_executes_only_verified_current_argv_without_shell(self):
        import time
        self.cli('setup', '--keyboard', 'shield-remote')
        target = self.home / 'pressed.json'
        payload = '; $(touch NEVER) && literal'
        argv = [sys.executable, '-c', 'import json,sys;open(sys.argv[1],"w").write(json.dumps(sys.argv[2:]))',
                str(target), payload]
        config = self.cli('bind', 'mic', '--command', json.dumps(argv))['config']
        self.assertFalse(target.exists())
        self.assertEqual(self.cli('run', 'mic', '--revision', '1', success=False)['error']['code'], 'conflict')
        self.assertFalse(target.exists())
        self.cli('run', 'mic', '--revision', str(config['revision']))
        for _ in range(100):
            if target.exists():
                break
            time.sleep(0.01)
        self.assertEqual(json.loads(target.read_text()), [payload])
        self.assertFalse((ROOT / 'NEVER').exists())
        self.cli('run', 'center', '--revision', str(config['revision']), success=False)

    def test_setup_preserves_remote_layout_options_and_rejects_custom_keymaps(self):
        device = dict(name='shield-remote', rules='', model='', layout='de', variant='', options='caps:swapescape')
        self.env['FAKE_DEVICE'] = json.dumps(device)
        config = self.cli('setup', '--keyboard', 'shield-remote')['config']
        self.assertEqual(config['routing'], {k: device[k] for k in ('rules', 'model', 'layout', 'variant', 'options')})
        keymap = self.keymap_path().read_text()
        self.assertRegex(keymap, r'key <CAPS>\s*\{[^}]*(?:Escape|0xff1b)')
        self.assertIn('German', keymap)
        self.env['FAKE_KB_FILE'] = '/custom/layout.xkb'
        before = self.config.read_bytes()
        self.assertIn('custom', self.cli('bind', 'center', '--key', 'Tab', success=False)['error']['message'].lower())
        self.assertEqual(self.config.read_bytes(), before)
        self.env.pop('FAKE_KB_FILE')
        custom = self.home / 'config/hypr/input.lua'
        custom.write_text('hl.device({name="other",kb_file="/custom/keymap"})\n')
        self.cli('bind', 'center', '--key', 'Tab', success=False)
        self.assertEqual(self.config.read_bytes(), before)

    def keymap_path(self):
        files = list((self.home / 'config/hypr').glob('remote-buttons*.xkb'))
        self.assertEqual(len(files), 1, files)
        return files[0]

    def test_routing_reassignment_changes_keymap_path_and_retires_old_only_after_success(self):
        self.cli('setup', '--keyboard', 'shield-remote')
        first = self.keymap_path()
        old = first.read_bytes()
        self.cli('bind', 'power', '--disabled')
        second = self.keymap_path()
        self.assertNotEqual(first, second)
        self.assertFalse(first.exists())
        self.assertNotEqual(second.read_bytes(), old)
        before = second.read_bytes()
        (self.home / 'fail-reload').touch()
        self.cli('bind', 'up', '--key', 'Tab', success=False)
        self.assertEqual(self.keymap_path(), second)
        self.assertEqual(second.read_bytes(), before)

    def test_remove_preserves_later_unrelated_edits_and_refuses_modified_owned_files(self):
        self.cli('setup', '--keyboard', 'shield-remote')
        lua = self.home / 'config/hypr/remote-buttons.lua'
        original = lua.read_bytes()
        lua.write_text('-- user changed this\n')
        self.cli('remove', success=False)
        self.assertTrue(self.config.exists())
        lua.write_bytes(original)
        hook = self.home / 'config/hypr/bindings.lua'
        hook.write_text(hook.read_text() + '-- keep my later binding\n')
        self.assertTrue(self.cli('remove')['removed'])
        self.assertEqual(hook.read_text(), '-- keep my later binding\n')
        self.assertFalse(self.config.exists())
        self.assertFalse(lua.exists())
        self.assertEqual(list(hook.parent.glob('remote-buttons*.xkb')), [])
        self.assertFalse((self.home / '.local/bin/omarchy-remote-buttons').exists())
        self.assertFalse((self.home / 'state/omarchy-remote-buttons/ownership.json').exists())
        self.cli('remove')

    def test_sigint_during_reload_rolls_back_and_returns_json(self):
        self.cli('setup', '--keyboard', 'shield-remote')
        files = [self.config, self.keymap_path(), self.home / 'config/hypr/remote-buttons.lua',
                 self.home / 'config/hypr/bindings.lua', self.home / '.local/bin/omarchy-remote-buttons',
                 self.home / 'state/omarchy-remote-buttons/ownership.json']
        before = {p: p.read_bytes() for p in files}
        (self.home / 'interrupt-reload').touch()
        self.assertEqual(self.cli('bind', 'center', '--key', 'Tab', success=False)['error']['code'], 'interrupted')
        self.assertEqual({p: p.read_bytes() for p in files}, before)
        self.assertEqual(self.keymap_path(), files[1])
        self.assertEqual(list(self.home.rglob('.remote-buttons-*')), [])

    def test_raw_code_recovery_crosschecks_text_and_requires_audited_single_key_scope(self):
        self.env['FAKE_BINDS'] = json.dumps([{'key': '', 'display_key': 'SUPER + SHIFT + code:217', 'modmask': 65}])
        self.cli('setup', '--keyboard', 'shield-remote', success=False)
        self.assertFalse(self.config.exists())
        self.cli('setup', '--keyboard', 'shield-remote', '--acknowledge-single-key-bindings')
        self.cli('remove')
        self.env['FAKE_BINDS'] = json.dumps([{'key': '', 'display_key': 'SUPER + SHIFT + code:225', 'modmask': 65}])
        error = self.cli('setup', '--keyboard', 'shield-remote', '--acknowledge-single-key-bindings', success=False)['error']
        self.assertEqual(error['code'], 'binding_conflict')
        self.env['FAKE_BINDS'] = json.dumps([{'key': 'A'}])
        self.env['FAKE_BINDS_TEXT'] = 'malformed serializer\n'
        self.cli('setup', '--keyboard', 'shield-remote', '--acknowledge-single-key-bindings', success=False)
        self.assertFalse(self.config.exists())

    def test_unknown_keysyms_and_malformed_ownership_fail_closed_as_json(self):
        self.cli('setup', '--keyboard', 'shield-remote')
        original = self.config.read_bytes()
        self.cli('bind', 'center', '--key', 'NotAnActualKeysym123', success=False)
        self.assertEqual(self.config.read_bytes(), original)
        state = self.home / 'state/omarchy-remote-buttons/ownership.json'
        data = json.loads(state.read_text())
        state.write_text(json.dumps(dict(data, files=1)))
        self.cli('bind', 'center', '--key', 'Tab', success=False)
        self.assertEqual(self.config.read_bytes(), original)

    def test_schema_explains_configuration_paths_actions_and_scope_without_an_agent_runtime(self):
        data = self.cli('agent-guide')
        self.assertIn('config_path', data)
        self.assertEqual(data['builtins'], backend.BUILTINS)
        self.assertIn('native chords', ' '.join(data['limitations']))
        self.assertIn('--acknowledge-single-key-bindings', ' '.join(data['examples']))
        self.assertIn('focused app', data['action_help']['shortcut'])
        self.assertIn('revision', data['apply_help'])

    def test_schema_distinguishes_normal_press_path_from_direct_dispatcher_invocation(self):
        data = self.cli('schema')
        self.assertNotIn('only on an explicit physical press', data['action_help']['command'])
        self.assertIn('does not authenticate physical presses', data['action_help']['command'])

    def test_refresh_upgrades_verified_legacy_backend_without_changing_mappings(self):
        import re
        self.cli('setup', '--keyboard', 'shield-remote', '--name', 'Custom Shield')
        sentinel = self.home / 'must-not-exist'
        config = self.cli('bind', 'mic', '--command', json.dumps(['touch', str(sentinel)]),
                          '--label', 'Custom label')['config']
        config = self.cli('bind', 'power', '--disabled')['config']
        hook = self.home / 'config/hypr/bindings.lua'
        hook.write_text('-- user binding\n' + hook.read_text())
        before = (hook.read_bytes(), hook.stat().st_ino)
        source = self.home / 'reviewed-plugin/remote_buttons.py'
        source.parent.mkdir()
        source.write_bytes((ROOT / 'remote_buttons.py').read_bytes())
        wrapper = self.home / '.local/bin/omarchy-remote-buttons'
        lua = hook.with_name('remote-buttons.lua')
        wrapper.write_bytes(b'#!/usr/bin/env python3\n# legacy wrapper fixture\n')
        lua.write_text(re.sub(r' \[r\d+:[0-9a-f]{16}\]', '', lua.read_text()))
        ownership = self.home / 'state/omarchy-remote-buttons/ownership.json'
        old_state = json.loads(ownership.read_text())
        old_state['files'].update(wrapper=backend.digest(wrapper.read_bytes()), lua=backend.digest(lua.read_bytes()))
        ownership.write_bytes(backend.packed(old_state))
        subprocess.run(['hyprctl', 'reload'], env=self.env, check=True, capture_output=True, timeout=10)
        oldmap = self.keymap_path()
        config['revision'] += 1
        self.assertEqual(self.cli('refresh', source=source)['config'], config)
        self.assertEqual(self.cli('show', source=wrapper)['config'], config)
        self.assertEqual(wrapper.read_bytes(), source.read_bytes())
        self.assertEqual((hook.read_bytes(), hook.stat().st_ino), before)
        self.assertFalse(oldmap.exists())
        self.assertFalse(sentinel.exists())
        self.assertIn('refresh', self.cli('schema')['commands'])

    def test_refresh_is_not_setup_and_requires_separate_source(self):
        self.assertEqual(self.cli('refresh', success=False)['error']['code'], 'not_configured')
        self.cli('setup', '--keyboard', 'shield-remote')
        wrapper = self.home / '.local/bin/omarchy-remote-buttons'
        self.assertEqual(self.cli('refresh', source=wrapper, success=False)['error']['code'], 'usage')
        self.assertEqual(self.cli('show')['config']['revision'], 1)

    def test_refresh_refuses_modified_owned_wrapper(self):
        self.cli('setup', '--keyboard', 'shield-remote')
        wrapper = self.home / '.local/bin/omarchy-remote-buttons'
        wrapper.write_text('-- changed outside controller\n')
        before = self.config.read_bytes()
        error = self.cli('refresh', success=False)['error']
        self.assertIn('Modified owned file: wrapper', error['message'])
        self.assertEqual(wrapper.read_text(), '-- changed outside controller\n')
        self.assertEqual(self.config.read_bytes(), before)

    def test_generated_lua_constructs_real_native_dispatchers_without_registering_or_executing(self):
        import shutil
        native = shutil.which('hyprctl')
        if not native or not os.environ.get('HYPRLAND_INSTANCE_SIGNATURE'):
            self.skipTest('Running Hyprland is required for constructor-only native verification')
        config = backend.default_config('shield-remote', 'Constructor fixture')
        from unittest.mock import patch
        with patch.dict(os.environ, self.env, clear=True):
            lua = backend.render_lua(config, backend.Paths())
        # Only dispatcher constructors are real. Device/bind/dispatch/timer are
        # private local stubs: this probe cannot register bindings or send input.
        probe = '''local count=0
local key_objects={}
local shim={dsp=hl.dsp, device=function() end,
 bind=function(key,action,options)
   count=count+1
   if type(action)=="function" then action() else assert(type(action)=="userdata") end
 end,
 dispatch=function(action)
   assert(type(action)=="userdata");key_objects[#key_objects+1]=action
 end,
 timer=function(callback,options)
   assert(options.timeout==50 and options.type=="oneshot");callback()
 end}
local env=setmetatable({hl=shim},{__index=_G})
local chunk,message=load(%s,"remote-buttons-constructor-test","t",env)
assert(chunk,message);chunk();print("REMOTE_BUTTONS_CONSTRUCTORS "..count)
assert(#key_objects==2);print("REMOTE_BUTTONS_NATIVE_KEY_OBJECTS "..#key_objects)
''' % json.dumps(lua, ensure_ascii=False)
        result = subprocess.run([native, 'repl', probe], text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('REMOTE_BUTTONS_CONSTRUCTORS 2', result.stdout, result.stdout + result.stderr)
        self.assertIn('REMOTE_BUTTONS_NATIVE_KEY_OBJECTS 2', result.stdout, result.stdout + result.stderr)

    def test_generated_loader_compiles_with_unicode_config_path(self):
        import shutil
        from unittest.mock import patch
        compiler = shutil.which('luac5.4') or shutil.which('luac')
        if not compiler:
            self.skipTest('Lua compiler required')
        with patch.dict(os.environ, dict(self.env, XDG_CONFIG_HOME=str(self.home / 'Élodie "松"')), clear=True):
            paths = backend.Paths()
        result = subprocess.run([compiler, '-p', '-'], input=paths.block, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Élodie', paths.block)

    def test_serialized_config_size_is_bounded_before_publication(self):
        import copy
        config = copy.deepcopy(backend.default_config('shield-remote', 'Shield'))
        for button in config['buttons']:
            button['label'] = 'x' * 160
            button['summary'] = 'x' * 512
            button['action'] = {'kind': 'command', 'argv': ['echo'] + ['x' * 4095] * 4}
        self.assertGreater(len(backend.packed(config)), 262144)
        with self.assertRaisesRegex(backend.Error, 'size'):
            backend.validate(config)

    def test_setup_rejects_oversized_generated_hook_before_publication(self):
        hook = self.home / 'config/hypr/bindings.lua'
        hook.parent.mkdir(parents=True)
        original = b'--' + b'x' * (262144 - 3) + b'\n'
        hook.write_bytes(original)
        error = self.cli('setup', '--keyboard', 'shield-remote', success=False)['error']
        self.assertEqual(error['code'], 'invalid')
        self.assertIn('size', error['message'].lower())
        self.assertEqual(hook.read_bytes(), original)
        calls = [json.loads(line) for line in (self.home / 'hyprctl.calls').read_text().splitlines()]
        self.assertNotIn(['reload'], calls)
        for path in (self.config, hook.with_name('remote-buttons.lua'),
                     self.home / '.local/bin/omarchy-remote-buttons',
                     self.home / 'state/omarchy-remote-buttons/ownership.json'):
            self.assertFalse(path.exists(), path)
        self.assertEqual(list(hook.parent.glob('remote-buttons*.xkb')), [])
        self.assertEqual(list(self.home.rglob('.remote-buttons-*')), [])

    def test_catalog_menu_matches_reported_xkb_symbol(self):
        menu = next(b for b in self.cli('schema')['buttons'] if b['id'] == 'menu')
        self.assertEqual((menu['key'], menu['keycode']), ('XF86MenuKB', 147))


if __name__ == '__main__':
    unittest.main()

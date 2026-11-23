#!/usr/bin/env python3
"""Plugin configuration CLI for device-scoped remote buttons. No background service."""
import argparse
import ctypes
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import signal
import stat
import subprocess
import sys
import tempfile
from contextlib import contextmanager

VERSION = '0.1.0'
PLUGIN_ID = 'leo.remote-buttons'
BINDING_PREFIX = 'Remote Buttons: '
BUILTINS = {
    'enter': {'kind': 'key', 'value': 'Return'},
    'copy': {'kind': 'shortcut', 'mods': 'CTRL', 'key': 'C'},
    'paste': {'kind': 'shortcut', 'mods': 'CTRL', 'key': 'V'},
    'terminal': {'kind': 'command', 'argv': ['omarchy-launch-terminal']},
    'dictation-toggle': {'kind': 'command', 'argv': ['omarchy-dictation', 'toggle']},
}
CATALOG = (
    ('center', 'Center / OK', 'XF86Select', 353),
    ('mic', 'Microphone', 'XF86Search', 217),
    ('up', 'Up', 'Up', 103),
    ('down', 'Down', 'Down', 108),
    ('left', 'Left', 'Left', 105),
    ('right', 'Right', 'Right', 106),
    ('home', 'Home', 'XF86HomePage', 172),
    ('back', 'Back', 'XF86Back', 158),
    ('menu', 'Menu', 'XF86MenuKB', 139),
    ('play_pause', 'Play / pause', 'XF86AudioPlay', 164),
    ('rewind', 'Rewind', 'XF86AudioRewind', 168),
    ('fast_forward', 'Fast forward', 'XF86AudioForward', 208),
    ('volume_up', 'Volume +', 'XF86AudioRaiseVolume', 115),
    ('volume_down', 'Volume −', 'XF86AudioLowerVolume', 114),
    ('power', 'Power', 'XF86PowerOff', 116),
    ('netflix', 'Netflix', 'XF86Video', 393),
)


def schema():
    return {'ok': True, 'schema': 1, 'cli': 'omarchy-remote-buttons', 'version': VERSION,
            'commands': ['setup', 'show', 'devices', 'schema', 'agent-guide', 'bind', 'unbind', 'apply', 'refresh', 'remove'],
            'action_kinds': ['native', 'disabled', 'key', 'shortcut', 'command'],
            'config_path': '${XDG_CONFIG_HOME:-$HOME/.config}/omarchy-remote-buttons/config.json',
            'builtins': BUILTINS, 'limits': {'buttons': 64, 'label': 160, 'summary': 512, 'file_bytes': 262144},
            'action_help': {'native': 'Leave the original physical button unchanged', 'disabled': 'Consume this remote button',
                            'key': '--key KEYSYM sends a down/up pair to the focused app',
                            'shortcut': '--shortcut "CTRL + SHIFT + V" targets the focused app, not compositor macros',
                            'command': '--command JSON_ARGV stores argv without running it. The compositor normally invokes '
                                       'the internal dispatcher on a mapped press; the CLI does not authenticate physical presses.',
                            'label': '--label TEXT changes the button display label'},
            'apply_help': 'apply --json CONFIG: use show.config with its current revision; commit increments revision',
            'refresh_help': 'python3 /path/to/reviewed/installed/plugin/remote_buttons.py refresh: '
                            'refresh owned backend files and increment revision without changing mappings',
            'limitations': ['One configured remote; verified Shield source-button catalog only.',
                            'Desktop bindings must have one nonmodifier key: arbitrary native chords are unsupported '
                            'and public compositor metadata cannot certify them. Audit before acknowledging setup.',
                            'Custom kb_file configurations are unsupported and refused. No background service or agent runtime.'],
            'buttons': [{'id': ident, 'label': label, 'key': key, 'keycode': code + 8}
                        for ident, label, key, code in CATALOG],
            'examples': ['omarchy-remote-buttons setup --keyboard nvidia-shield-remote --acknowledge-single-key-bindings',
                         'omarchy-remote-buttons show',
                         'omarchy-remote-buttons bind center --key Return',
                         'omarchy-remote-buttons bind mic --command \'["omarchy-dictation","toggle"]\' --label "Toggle dictation"']}


def default_config(keyboard, name):
    buttons = []
    for ident, label, key, _ in CATALOG:
        action = {'kind': 'native'}
        summary = f'Native ({key})'
        if ident == 'center':
            action, summary = {'kind': 'key', 'value': 'Return'}, 'Enter'
        elif ident == 'mic':
            action = {'kind': 'command', 'argv': ['omarchy-dictation', 'toggle']}
            summary = 'Toggle dictation'
        buttons.append(dict(id=ident, label=label, key=key, action=action, summary=summary))
    return dict(schema=1, revision=1, keyboard=keyboard, remote_name=name, buttons=buttons)


class Error(Exception):
    def __init__(self, message, code='invalid'):
        super().__init__(message)
        self.code = code


def require(condition, message):
    if not condition:
        raise Error(message)


def text(value, limit, pattern=None):
    require(isinstance(value, str) and 0 < len(value) <= limit
            and not any(ord(c) < 32 or ord(c) == 127 for c in value), 'Invalid text')
    if pattern:
        require(re.fullmatch(pattern, value) is not None, 'Invalid identifier or key')
    return value


def validate_action(action):
    require(isinstance(action, dict), 'Action must be an object')
    fields = {'native': set(), 'disabled': set(), 'key': {'value'},
              'shortcut': {'mods', 'key'}, 'command': {'argv'}}
    kind = action.get('kind')
    require(isinstance(kind, str) and kind in fields, 'Unknown action kind')
    require(set(action) == fields[kind] | {'kind'}, 'Unexpected action fields')
    if kind == 'command':
        argv = action['argv']
        require(isinstance(argv, list) and 1 <= len(argv) <= 64, 'Command requires argv array')
        for arg in argv:
            if arg == '':
                continue
            text(arg, 4096)
        require(isinstance(argv[0], str) and bool(argv[0]), 'Empty executable')
        require(sum(len(a) for a in argv) <= 16384, 'Command too large')
    elif kind in ('key', 'shortcut'):
        key = text(action['value' if kind == 'key' else 'key'], 80, r'[A-Za-z0-9_]+')
        lib = ctypes.CDLL('libxkbcommon.so.0')
        lib.xkb_keysym_from_name.argtypes = [ctypes.c_char_p, ctypes.c_int]
        lib.xkb_keysym_from_name.restype = ctypes.c_uint
        require(bool(lib.xkb_keysym_from_name(key.encode(), 0)), 'Unknown keysym: ' + key)
        if kind == 'shortcut':
            mods = text(action['mods'], 80).split(' + ')
            require(len(mods) == len(set(mods)) and all(m in ('SUPER', 'CTRL', 'ALT', 'SHIFT')
                    for m in mods), 'Invalid modifiers; use CTRL + SHIFT')
    return action


def validate(config):
    require(isinstance(config, dict), 'Config must be an object')
    require(set(config) <= {'schema', 'revision', 'keyboard', 'remote_name', 'buttons', 'routing', 'binding_scope'}, 'Unknown config fields')
    require('binding_scope' not in config or config['binding_scope'] == 'audited-single-key', 'Unsupported binding scope')
    if 'routing' in config:
        routing = config['routing']
        require(isinstance(routing, dict) and set(routing) == {'rules', 'model', 'layout', 'variant', 'options'},
                'Invalid routing metadata')
        for value in routing.values():
            if value != '':
                text(value, 512, r'[A-Za-z0-9_:+,()\-]+')
    require(type(config.get('schema')) is int and config['schema'] == 1, 'Unsupported schema')
    require(type(config.get('revision')) is int and 1 <= config['revision'] < 2**53, 'Invalid revision')
    text(config.get('keyboard'), 128, r'[a-z0-9][a-z0-9_-]*')
    text(config.get('remote_name'), 160)
    buttons = config.get('buttons')
    require(isinstance(buttons, list) and 1 <= len(buttons) <= 64, 'Expected 1..64 buttons')
    ids, keys = set(), set()
    for button in buttons:
        require(isinstance(button, dict) and set(button) == {'id', 'label', 'key', 'action', 'summary'},
                'Invalid button fields')
        ident = text(button['id'], 64, r'[a-z][a-z0-9_]*')
        key = text(button['key'], 80, r'[A-Za-z0-9_]+')
        require(ident not in ids and key not in keys, 'Duplicate button id/key')
        ids.add(ident)
        keys.add(key)
        text(button['label'], 160)
        text(button['summary'], 512)
        validate_action(button['action'])
    require(len(packed(config)) <= 262144, 'Configuration exceeds size limit')
    return config


class Paths:
    def __init__(self):
        home = Path(os.environ['HOME'])
        self.config_root = Path(os.environ.get('XDG_CONFIG_HOME', home / '.config'))
        self.state_root = Path(os.environ.get('XDG_STATE_HOME', home / '.local/state'))
        self.config = self.config_root / 'omarchy-remote-buttons/config.json'
        self.lua = self.config_root / 'hypr/remote-buttons.lua'
        self.keymap = self.config_root / 'hypr/remote-buttons-r1.xkb'
        self.hook = self.config_root / 'hypr/bindings.lua'
        self.wrapper = home / '.local/bin/omarchy-remote-buttons'
        self.ownership = self.state_root / 'omarchy-remote-buttons/ownership.json'
        self.lock = self.ownership.with_name('lock')
        self.managed = {'config': self.config, 'lua': self.lua, 'keymap': self.keymap, 'wrapper': self.wrapper}
        self.block = ('\n-- BEGIN leo.remote-buttons (managed)\n'
                      + 'dofile(' + quote(str(self.lua)) + ')\n'
                      + '-- END leo.remote-buttons (managed)\n')

    def revision(self, number):
        self.keymap = self.lua.with_name(f'remote-buttons-r{number}.xkb')
        self.managed['keymap'] = self.keymap


def safe_path(path):
    text(str(path), 4096)
    require(path.is_absolute() and '..' not in path.parts, 'Unsafe path')
    for parent in (path, *path.parents):
        require(not parent.is_symlink(), 'Symlink path refused: ' + str(parent))


def snapshot(path):
    """Capture bytes, identity and permissions from one opened file."""
    safe_path(path)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid(), 'Not an owned regular file')
        require(before.st_size <= 262144, 'File exceeds size limit')
        content = stream.read(262145)
        after = os.fstat(fd)
        require(len(content) <= 262144, 'File exceeds size limit')
        if (before.st_ctime_ns, before.st_mtime_ns, before.st_size) != (after.st_ctime_ns, after.st_mtime_ns, len(content)):
            raise Error('File changed while reading: ' + str(path), 'file_conflict')
    # ctime is last: a rename changes it, so compare the remaining fields
    # when checking a published file against the staged inode.
    return (content, stat.S_IMODE(after.st_mode), after.st_dev, after.st_ino, after.st_mtime_ns, after.st_ctime_ns)


def read_bytes(path):
    saved = snapshot(path)
    return saved[0] if saved is not None else None


def digest(content):
    return hashlib.sha256(content).hexdigest()


def packed(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True) + '\n').encode()


def stage(path, content, mode=0o600):
    safe_path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix='.remote-buttons-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, mode)
        return Path(name)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise


@contextmanager
def locked(paths):
    safe_path(paths.lock)
    paths.lock.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(paths.lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Error('Another assignment is in progress', 'busy') from None
        yield
    finally:
        os.close(fd)


class Xkb:
    """Small typed libxkbcommon adapter; no subprocess compiler or downloads."""
    def __init__(self):
        self.lib = ctypes.CDLL('libxkbcommon.so.0')
        pointer, uint = ctypes.c_void_p, ctypes.c_uint
        signatures = {
            'context_new': ([uint], pointer), 'context_unref': ([pointer], None),
            'keymap_new_from_names': ([pointer, pointer, uint], pointer),
            'keymap_new_from_string': ([pointer, ctypes.c_char_p, uint, uint], pointer),
            'keymap_get_as_string': ([pointer, uint], pointer), 'keymap_unref': ([pointer], None),
            'keymap_key_get_name': ([pointer, uint], ctypes.c_char_p),
        }
        for name, (args, result) in signatures.items():
            func = getattr(self.lib, 'xkb_' + name)
            func.argtypes, func.restype = args, result
        self.context = self.lib.xkb_context_new(0)
        require(bool(self.context), 'Cannot create XKB context')

    def compile(self, source):
        keymap = self.lib.xkb_keymap_new_from_string(self.context, source.encode(), 2, 0)
        require(bool(keymap), 'Generated XKB keymap failed compilation')
        try:
            return self.serialize(keymap)
        finally:
            self.lib.xkb_keymap_unref(keymap)

    def serialize(self, keymap):
        data = self.lib.xkb_keymap_get_as_string(keymap, 2)
        require(bool(data), 'Cannot serialize keymap')
        try:
            return ctypes.string_at(data).decode()
        finally:
            libc = ctypes.CDLL(None)
            libc.free.argtypes = [ctypes.c_void_p]
            libc.free(data)

    def close(self):
        self.lib.xkb_context_unref(self.context)


def routes(config):
    catalog = {ident: (index, key, code + 8) for index, (ident, _, key, code) in enumerate(CATALOG)}
    result = []
    for button in config['buttons']:
        if button['action']['kind'] == 'native':
            continue
        require(button['id'] in catalog, 'Only catalog source buttons can currently be assigned')
        index, key, code = catalog[button['id']]
        require(button['key'] == key, 'Source key differs from verified catalog')
        result.append((button, 'F' + str(13 + index), code))
    return result


def render_keymap(config):
    routing = config.get('routing', {})
    fields = ('rules', 'model', 'layout', 'variant', 'options')
    class Names(ctypes.Structure):
        _fields_ = [(field, ctypes.c_char_p) for field in fields]
    names = Names(*(routing.get(f, 'us' if f == 'layout' else '').encode() for f in fields))
    xkb = Xkb()
    base = None
    try:
        base = xkb.lib.xkb_keymap_new_from_names(xkb.context, ctypes.byref(names), 0)
        require(bool(base), 'Cannot compile current remote layout/options')
        source = xkb.serialize(base)
        for _, reserved, code in routes(config):
            name = xkb.lib.xkb_keymap_key_get_name(base, code)
            require(bool(name), 'Source keycode absent from current keymap')
            pattern = r'key\s+<' + re.escape(name.decode()) + r'>\s*\{.*?\};'
            replacement = 'key <' + name.decode() + '> { type="ONE_LEVEL", symbols[Group1]=[ ' + reserved + ' ] };'
            source, count = re.subn(pattern, replacement, source, count=1, flags=re.S)
            require(count == 1, 'Cannot locate source key in compiled keymap')
        return xkb.compile(source)
    finally:
        if base:
            xkb.lib.xkb_keymap_unref(base)
        xkb.close()


def quote(value):
    return json.dumps(value, ensure_ascii=False)


def binding_generation(config):
    return f" [r{config['revision']}:{digest(packed(config))[:16]}]"


def render_lua(config, paths):
    lines = ['-- Managed by omarchy-remote-buttons; no global unbinds.',
             'hl.device({ name = ' + quote(config['keyboard']) + ', kb_file = ' + quote(str(paths.keymap))
             + ', resolve_binds_by_sym = true })',
             'local function send_once(mods, key)',
             '  return function()',
             '    hl.dispatch(hl.dsp.send_key_state({ mods = mods, key = key, state = "down" }))',
             '    hl.timer(function()',
             '      hl.dispatch(hl.dsp.send_key_state({ mods = mods, key = key, state = "up" }))',
             '    end, { timeout = 50, type = "oneshot" })',
             '  end', 'end']
    generation = binding_generation(config)
    for button, reserved, _ in routes(config):
        action = button['action']
        if action['kind'] == 'disabled':
            callback = 'function() end'
        elif action['kind'] == 'command':
            command = shlex.join([str(paths.wrapper), 'run', button['id'], '--revision', str(config['revision'])])
            callback = 'hl.dsp.exec_cmd(' + quote(command) + ')'
        else:
            key = action.get('value', action.get('key'))
            callback = 'send_once(' + quote(action.get('mods', '')) + ', ' + quote(key) + ')'
        options = ('{ device = { inclusive = true, list = { ' + quote(config['keyboard']) + ' } }, '
                   + 'ignore_mods = true, submap_universal = true, description = '
                   + quote(BINDING_PREFIX + button['id'] + generation) + ' }')
        lines.append('hl.bind(' + quote(reserved) + ', ' + callback + ', ' + options + ')')
    return '\n'.join(lines) + '\n'


def verify_owned(paths, originals=None):
    originals = {} if originals is None else originals

    def capture(path):
        originals[path] = saved = snapshot(path)
        return saved[0] if saved is not None else None

    raw = capture(paths.ownership)
    if raw is None:
        require(all(capture(p) is None for p in paths.managed.values()), 'Unowned managed files exist')
        require('leo.remote-buttons' not in (capture(paths.hook) or b'').decode(), 'Unowned loader block')
        return None
    config_raw = capture(paths.config)
    if config_raw is None:
        raise Error('Missing owned config')
    config = validate(json.loads(config_raw))
    paths.revision(config['revision'])
    state = json.loads(raw)
    require(isinstance(state, dict) and set(state) == {'files', 'block'}, 'Invalid ownership state')
    require(isinstance(state['files'], dict) and set(state['files']) == set(paths.managed), 'Invalid ownership file ids')
    require(all(isinstance(v, str) and re.fullmatch(r'[0-9a-f]{64}', v) for v in state['files'].values()),
            'Malformed ownership checksum')
    require(state['block'] == paths.block, 'Changed loader ownership')
    for ident, path in paths.managed.items():
        content = config_raw if path == paths.config else capture(path)
        require(content is not None and digest(content) == state['files'][ident], 'Modified owned file: ' + ident)
    hook = (capture(paths.hook) or b'').decode()
    require(hook.count(paths.block) == 1 and hook.count('-- BEGIN leo.remote-buttons') == 1
            and hook.count('-- END leo.remote-buttons') == 1, 'Modified loader block')
    return config


def binding_snapshot():
    first = json.loads(hypr('-j', 'binds'))
    human = hypr('binds')
    last = json.loads(hypr('-j', 'binds'))
    require(isinstance(first, list) and first == last and len(first) <= 8192, 'Bindings changed during inspection')
    fields = ('modmask', 'submap', 'key', 'keycode', 'catchall', 'description', 'dispatcher', 'arg')
    blocks = re.findall(r'(?m)^bind[^\n]*\n(?:\t[^\n]*\n)+\n', human)
    require(''.join(blocks).rstrip('\n') == human.rstrip('\n') and len(first) == len(blocks),
            'Unsupported compositor binding serialization')
    for binding, block in zip(first, blocks):
        require(isinstance(binding, dict) and type(binding.get('keycode')) is int, 'Invalid binding metadata')
        pairs = [line[1:].split(': ', 1) for line in block.splitlines()[1:-1]]
        require(all(len(p) == 2 for p in pairs) and tuple(p[0] for p in pairs) == fields, 'Ambiguous binding fields')
        row = dict(pairs)
        for field in fields:
            value = binding.get('catch_all' if field == 'catchall' else field)
            if field == 'key' and not value:
                continue
            require((str(value).lower() if isinstance(value, bool) else str(value)) == row[field],
                    'Inconsistent compositor binding snapshot')
        binding['key'] = row['key']
    return first


def binding_identities(config, lua=None):
    if config is None:
        return set()
    generation = binding_generation(config)
    identities = set()
    for button, symbol, _ in routes(config):
        base = BINDING_PREFIX + button['id']
        new = base + generation
        # Installed v0.1.0 Lua had unversioned descriptions. Only allow an
        # unversioned row if it appears in the verified, owned Lua snapshot.
        description = new
        if lua is not None and ('description = ' + quote(base)).encode() in lua:
            description = base
        identities.add((symbol, description))
    return identities


def is_managed_binding(binding):
    false_flags = ('locked', 'mouse', 'release', 'repeat', 'longPress', 'non_consuming',
                   'auto_consuming', 'catch_all', 'allow_input_capture')
    return (binding.get('dispatcher') == '__lua'
            and re.fullmatch(r'[1-9][0-9]*', str(binding.get('arg', ''))) is not None
            and binding.get('has_description') is True
            and binding.get('submap_universal') == 'true' and binding.get('submap') == ''
            and binding.get('keycode') == 0 and binding.get('modmask') == 0
            and all(binding.get(flag) is False for flag in false_flags))


def inspect_bindings(config, owned, *, verify_active=False):
    remaining = owned.copy()
    codes = {code for _, _, code in routes(config)} if config else set()
    external = False
    for binding in binding_snapshot():
        key = str(binding.get('key', ''))
        description = str(binding.get('description', ''))
        identity = (key.upper(), description)
        if identity in remaining and is_managed_binding(binding):
            remaining.remove(identity)
            continue
        if verify_active and description.startswith(BINDING_PREFIX):
            raise Error('Unexpected, stale, duplicate or malformed managed binding: ' + description[:160], 'activation_failed')
        if config is None:
            continue
        external = True
        physical = binding.get('keycode', 0)
        raw_codes = {int(v) for v in re.findall(r'(?<![A-Za-z0-9_])code:(\d+)(?![A-Za-z0-9_])', key)}
        raw_codes.add(physical)
        if (binding.get('catch_all') or (not key and not physical)
                or re.search(r'\bF(?:1[3-9]|2\d|3[0-5])\b', key, re.I)
                or raw_codes & codes or '&' in key or binding.get('keysyms') or binding.get('keycodes')):
            raise Error('Unsafe existing binding (including opaque multikey): ' +
                        str(binding.get('description') or key or physical)[:160]
                        + '; no laptop bindings were changed', 'binding_conflict')
    if verify_active and remaining:
        raise Error('Missing active managed binding(s): ' + ', '.join(sorted(key for key, _ in remaining)), 'activation_failed')
    require(not external or (config is not None and config.get('binding_scope') == 'audited-single-key'),
            'Compositor metadata hides native chords. Audit single-nonmodifier-key bindings, then setup with '
            '--acknowledge-single-key-bindings. Arbitrary native chords are unsupported.')


def check_custom_keymaps(paths):
    current = json.loads(hypr('-j', 'getoption', 'input:kb_file')).get('str')
    require(current in ('', '[[EMPTY]]'), 'Unsupported custom global kb_file; refusing to replace keymap')
    files = list(paths.hook.parent.rglob('*.lua'))
    require(len(files) <= 128, 'Too many Lua files to inspect for custom keymaps')
    for path in files:
        if path == paths.lua:
            continue
        require(not re.search(rb'\bkb_file\b', read_bytes(path) or b''),
                'Unsupported custom kb_file reference: ' + str(path))


def transact(paths, change, remove=False):
    with locked(paths):
        originals = {}
        previous = verify_owned(paths, originals)
        previous_lua = originals[paths.lua][0] if previous else None
        previous_bindings = binding_identities(previous, previous_lua)
        hook = originals[paths.hook][0].decode() if originals[paths.hook] else ''
        oldmap = None
        if remove:
            if previous is None:
                return None
            config = None
            candidates = {path: None for path in (*paths.managed.values(), paths.ownership)}
            candidates[paths.hook] = hook.replace(paths.block, '', 1).encode()
            activate, commit = (paths.hook,), (*paths.managed.values(), paths.ownership)
        else:
            config = validate(change(json.loads(json.dumps(previous))))
            oldmap = paths.keymap if previous else None
            paths.revision(config['revision'])
            if paths.keymap not in originals:
                originals[paths.keymap] = snapshot(paths.keymap)
                require(originals[paths.keymap] is None, 'Unowned revision keymap exists')
            inspect_bindings(config, previous_bindings)
            check_custom_keymaps(paths)
            if previous is None:
                hook += paths.block
            candidates = {paths.lua: render_lua(config, paths).encode(), paths.keymap: render_keymap(config).encode(),
                          paths.hook: hook.encode(), paths.wrapper: Path(__file__).read_bytes(), paths.config: packed(config)}
            state = {'files': {ident: digest(candidates[path]) for ident, path in paths.managed.items()}, 'block': paths.block}
            candidates[paths.ownership] = packed(state)
            activate, commit = (paths.keymap, paths.lua, paths.wrapper, paths.hook), (paths.config, paths.ownership)
        require(all(content is None or len(content) <= 262144 for content in candidates.values()),
                'Generated file exceeds size limit')
        if oldmap is not None and oldmap != paths.keymap:
            candidates[oldmap] = None
            commit += (oldmap,)
        candidates = {path: content for path, content in candidates.items()
                      if content != (originals[path][0] if originals[path] else None)}
        staged, published = {}, {}
        reload_attempted = False

        def recheck(path, expected):
            try:
                unchanged = snapshot(path) == expected
            except (Error, OSError):
                unchanged = False
            if not unchanged:
                raise Error('File changed during update: ' + str(path), 'file_conflict')

        def matches_publish(path, expected):
            current = snapshot(path)
            return current is None if expected is None else current is not None and current[:-1] == expected[:-1]

        def publish(path):
            if path not in candidates:
                return
            expected = snapshot(staged[path]) if path in staged else None
            # Record successful changes before delivering an interrupt to the CLI.
            mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT})
            try:
                original = originals[path]
                recheck(path, original)
                if expected is None:
                    path.unlink()
                elif original is None:
                    # Same-directory link publishes atomically without clobbering
                    # a path created after the recheck.
                    try:
                        os.link(staged[path], path)
                    except FileExistsError as error:
                        raise Error('File created during update: ' + str(path), 'file_conflict') from error
                else:
                    os.replace(staged[path], path)
                published[path] = expected
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, mask)

        try:
            for path, content in candidates.items():
                if content is not None:
                    mode = originals[path][1] & 0o777 if originals[path] else (0o755 if path == paths.wrapper else 0o600)
                    staged[path] = stage(path, content, mode)
            for path, original in originals.items():
                recheck(path, original)
            for path in activate:
                publish(path)
            reload_attempted = True
            hypr('reload')
            errors = hypr('configerrors').strip()
            if errors:
                raise Error('Compositor rejected assignment: ' + errors[:512], 'compositor')
            inspect_bindings(config, binding_identities(config), verify_active=True)
            for path in commit:
                publish(path)
            for path, original in originals.items():
                if path not in published:
                    recheck(path, original)
                elif not matches_publish(path, published[path]):
                    raise Error('Published file changed during update: ' + str(path), 'file_conflict')
            return config
        except BaseException as cause:
            conflicts, failures = [], []
            for path, expected in reversed(published.items()):
                try:
                    original = originals[path]
                    restored = stage(path, original[0], original[1]) if original else None
                    try:
                        try:
                            matches = matches_publish(path, expected)
                        except (Error, OSError):
                            matches = False
                        if not matches:
                            conflicts.append(str(path))
                        elif restored is None:
                            path.unlink()
                        elif expected is None:
                            try:
                                os.link(restored, path)
                            except FileExistsError:
                                conflicts.append(str(path))
                        else:
                            os.replace(restored, path)
                    finally:
                        if restored is not None:
                            restored.unlink(missing_ok=True)
                except (Error, OSError) as error:
                    failures.append(f'{path}: {error}')
            if conflicts:
                details = '; other rollback errors: ' + ', '.join(failures) if failures else ''
                raise Error('Rollback preserved concurrent changes at ' + ', '.join(conflicts)
                            + details + f'; rollback reload skipped; original error: {cause}', 'rollback_conflict') from cause
            if failures:
                raise Error('Rollback could not restore ' + ', '.join(failures)
                            + f'; rollback reload skipped; original error: {cause}', 'rollback_failed') from cause
            if reload_attempted:
                try:
                    hypr('reload')
                    if hypr('configerrors').strip():
                        raise Error('Compositor rejected rollback configuration')
                    inspect_bindings(None, previous_bindings, verify_active=True)
                except (Error, OSError, ValueError, subprocess.SubprocessError) as error:
                    raise Error(f'Rollback reload could not be verified: {error}; original error: {cause}',
                                'rollback_failed') from error
            raise
        finally:
            for path in staged.values():
                path.unlink(missing_ok=True)


def read_config(paths):
    content = read_bytes(paths.config)
    if content is None:
        raise Error('Run omarchy-remote-buttons setup --keyboard NAME first', 'not_configured')
    return validate(json.loads(content))


def hypr(*args):
    result = subprocess.run(['hyprctl', *args], text=True, capture_output=True, timeout=15)
    if result.returncode:
        raise Error('hyprctl failed: ' + (result.stderr or result.stdout)[:512], 'compositor')
    return result.stdout


def summary(action):
    kind = action['kind']
    if kind == 'key':
        return 'Enter' if action['value'] == 'Return' else action['value']
    if kind == 'shortcut':
        return action['mods'] + ' + ' + action['key']
    if kind == 'command':
        return ' '.join(action['argv'])[:512]
    return 'Disabled' if kind == 'disabled' else 'Native'


def edit(args, previous):
    if args.command == 'setup':
        if previous is not None:
            raise Error('Already configured; use bind/apply or remove first', 'conflict')
        config = validate(default_config(args.keyboard, args.name))
        if args.acknowledge_single_key_bindings:
            config['binding_scope'] = 'audited-single-key'
        devices = json.loads(hypr('-j', 'devices'))['keyboards']
        device = next((d for d in devices if d['name'] == args.keyboard), None)
        require(device is not None, 'Keyboard is not present; inspect devices')
        config['routing'] = {field: device.get(field, 'us' if field == 'layout' else '')
                             for field in ('rules', 'model', 'layout', 'variant', 'options')}
        return validate(config)
    if previous is None:
        raise Error('Run setup first', 'not_configured')
    if args.command == 'refresh':
        previous['revision'] += 1
        return previous
    if args.command == 'apply':
        require(len(args.json.encode()) <= 262144, 'Batch exceeds size limit')
        config = validate(json.loads(args.json))
        if config['revision'] != previous['revision']:
            raise Error('Stale revision; read show and retry', 'conflict')
        require(config['keyboard'] == previous['keyboard'], 'Remove before changing keyboard')
        require(config.get('routing') == previous.get('routing'), 'Remove/setup before changing routing')
        config['revision'] += 1
        return config
    button = next((b for b in previous['buttons'] if b['id'] == args.button), None)
    if button is None:
        raise Error('Unknown button; inspect schema/show')
    if args.command == 'unbind':
        action = {'kind': 'native'}
    elif args.action:
        action = json.loads(json.dumps(BUILTINS[args.action]))
    elif args.key is not None:
        action = {'kind': 'key', 'value': args.key}
    elif args.shortcut is not None:
        parts = [p.strip() for p in args.shortcut.split('+')]
        require(len(parts) >= 2, 'Shortcut needs modifiers + key')
        action = {'kind': 'shortcut', 'mods': ' + '.join(p.upper() for p in parts[:-1]), 'key': parts[-1]}
    elif args.argv is not None:
        action = {'kind': 'command', 'argv': json.loads(args.argv)}
    else:
        action = {'kind': 'disabled'}
    validate_action(action)
    button['action'] = action
    button['summary'] = 'Native (' + button['key'] + ')' if action['kind'] == 'native' else summary(action)
    if getattr(args, 'label', None) is not None:
        button['label'] = args.label
    previous['revision'] += 1
    return previous


def run_action(paths, button_id, revision):
    with locked(paths):
        config = verify_owned(paths)
        require(config is not None, 'Not configured')
        if config['revision'] != revision:
            raise Error('Stale assignment revision; retry after update completes', 'conflict')
        button = next((b for b in config['buttons'] if b['id'] == button_id), None)
        require(button is not None and button['action']['kind'] == 'command', 'Not a command assignment')
        child = subprocess.Popen(button['action']['argv'], stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 close_fds=True, start_new_session=True)
        return {'ok': True, 'started_pid': child.pid}


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Error(message, 'usage')


def main(argv=None):
    try:
        parser = Parser(prog='omarchy-remote-buttons', description=__doc__)
        parser.add_argument('--version', action='version', version=VERSION)
        commands = parser.add_subparsers(dest='command', required=True)
        for command in ('schema', 'agent-guide', 'show', 'devices'):
            commands.add_parser(command)
        setup = commands.add_parser('setup', help='Install default Shield mappings for one keyboard')
        setup.add_argument('--keyboard', required=True)
        setup.add_argument('--name', default='NVIDIA SHIELD Remote')
        setup.add_argument('--acknowledge-single-key-bindings', action='store_true',
                           help='Confirm desktop bindings were audited: no multi-nonmodifier native chords')
        bind = commands.add_parser('bind', help='Assign one button without running its action')
        bind.add_argument('button')
        bind.add_argument('--label')
        actions = bind.add_mutually_exclusive_group(required=True)
        actions.add_argument('--key')
        actions.add_argument('--shortcut')
        actions.add_argument('--command', dest='argv', help='JSON argv array, never a shell string')
        actions.add_argument('--disabled', action='store_true')
        actions.add_argument('--action', choices=sorted(BUILTINS))
        apply = commands.add_parser('apply', help='Update configuration with matching current revision')
        apply.add_argument('--json', required=True)
        unbind = commands.add_parser('unbind', help='Restore a button to native behavior')
        unbind.add_argument('button')
        commands.add_parser('remove', help='Remove only unchanged owned integration; preserve unrelated edits')
        commands.add_parser('refresh', help='Run from reviewed plugin source to refresh the owned backend without resetting mappings')
        run = commands.add_parser('run', help='Internal argv dispatcher; does not authenticate the event origin')
        run.add_argument('button')
        run.add_argument('--revision', type=int, required=True)
        args = parser.parse_args(argv)
        if args.command in ('schema', 'agent-guide'):
            output = schema()
        elif args.command == 'devices':
            output = {'ok': True, 'keyboards': json.loads(hypr('-j', 'devices'))['keyboards']}
        elif args.command == 'remove':
            transact(Paths(), lambda old: None, remove=True)
            output = {'ok': True, 'removed': True}
        elif args.command == 'run':
            output = run_action(Paths(), args.button, args.revision)
        elif args.command == 'show':
            output = {'ok': True, 'config': read_config(Paths())}
        else:
            paths = Paths()
            if args.command == 'refresh' and Path(__file__).resolve() == paths.wrapper.resolve():
                raise Error('Run refresh from reviewed installed plugin source, not the generated wrapper', 'usage')
            output = {'ok': True, 'config': transact(paths, lambda old: edit(args, old))}
        print(json.dumps(output, ensure_ascii=False))
        return 0
    except (Error, OSError, ValueError, subprocess.SubprocessError, KeyboardInterrupt) as error:
        code = 'interrupted' if isinstance(error, KeyboardInterrupt) else getattr(error, 'code', 'io')
        print(json.dumps({'ok': False, 'error': {'code': code,
                                               'message': str(error)}}))
        return 1


if __name__ == '__main__':
    sys.exit(main())

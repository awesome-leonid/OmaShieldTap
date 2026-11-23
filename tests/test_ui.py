"""Read-only UI checks. Native fixtures use private HOME/XDG and hidden windows."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from typing import Any

from remote_buttons import default_config, packed, validate

ROOT = Path(__file__).resolve().parents[1]


class ModelTests(unittest.TestCase):
    def js(self, program, raw: str | None = None):
        self.assertTrue((ROOT / "Model.js").exists(), "Read-only model is not implemented")
        result = subprocess.run(["node", "-e", "const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');const M={};vm.createContext(M);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),M);" + program, str(ROOT / "Model.js")], input=raw, capture_output=True, encoding='utf-8', timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_parser_matches_backend_code_point_limits(self):
        config: dict[str, Any] = default_config('nvidia-shield-remote', 'R' + '🔋' * 159)
        config['buttons'][0].update(label='L' + '🚀' * 159, summary='S' + '🚀' * 511,
                                    action={'kind': 'command', 'argv': ['true', 'A' + '🚀' * 4095]})
        self.js(r'''
const raw=fs.readFileSync(0,'utf8');
const parsed=M.parseConfig(raw);
assert.equal(parsed.ok,true,'backend-valid astral fields must render');
const config=JSON.parse(raw), button=config.buttons[0];
assert.equal(parsed.value.remote_name,config.remote_name);
assert.equal(parsed.value.buttons[0].label,button.label);
assert.equal(parsed.value.buttons[0].summary,button.summary);
for (const [name,obj] of [['remote_name',config],['label',button],['summary',button],[1,button.action.argv]]) {
 const original=obj[name];
 obj[name]+='🚀';
 assert.equal(M.parseConfig(JSON.stringify(config)).ok,false,'one extra code point in '+name);
 obj[name]=original;
}
''', raw=packed(validate(config)).decode())

    def test_all_mapping_kinds_are_display_only_and_extra_routing_is_ignored(self):
        self.js(r'''
const actions=[{kind:'native'},{kind:'disabled'},{kind:'key',value:'Return'},
 {kind:'shortcut',mods:'SUPER',key:'E'},{kind:'command',argv:['touch','/must-not-exist']}];
const raw={schema:1,revision:1,keyboard:'nvidia-shield-remote',remote_name:'<b>Remote</b>',
 buttons:Array.from({length:16},(_,i)=>({id:'button-'+i,label:'Button '+i,key:'XF86Select',
 action:actions[i%5],summary:i===0?'Native (XF86Select)':'<img src="https://invalid/">',routing:{ignored:true}})),routing:{ignored:true}};
const parsed=M.parseConfig(JSON.stringify(raw));
assert.equal(parsed.ok,true);
assert.equal(parsed.value.buttons.length,16);
assert.equal(parsed.value.remote_name,raw.remote_name);
assert.equal(parsed.value.buttons[4].kind,'command');
assert.equal(parsed.value.buttons[4].summary,raw.buttons[4].summary);
assert.equal(parsed.value.buttons[4].action,undefined);
assert.equal(parsed.value.routing,undefined);
assert.equal(typeof M.execute,'undefined');
assert.equal(M.tooltip('<b>remote</b> & x').includes('<'),false);
assert.equal(M.tooltip('<b>remote</b>').includes('>'),false);
''')

    def test_detail_tooltip_preserves_maximum_valid_fields_and_neutralizes_each(self):
        self.js(r'''
const label='<'+ 'L'.repeat(158) +'>';
const summary='<'+ 'S'.repeat(510) +'>';
const key='K'.repeat(128), source='Source key: '+key;
const raw={schema:1,revision:1,keyboard:'remote',remote_name:'Remote',buttons:[
 {id:'center',label,key,summary,action:{kind:'command',argv:['true']}}]};
assert.equal(M.parseConfig(JSON.stringify(raw)).ok,true);
assert.equal(typeof M.detailTooltip,'function','bounded composite detail helper is available');
const detail=M.detailTooltip(label,summary,source);
assert.equal(detail,M.tooltip(label)+'\n'+M.tooltip(summary)+'\n'+M.tooltip(source));
assert.equal(detail.split('\n')[1].length,512);
assert.ok(detail.endsWith(source),'full source key survives a maximum-length summary');
assert.ok(!/[<>]/.test(detail));
assert.ok(M.detailTooltip('x'.repeat(2000),'y'.repeat(2000),'z'.repeat(2000)).length<=1538);
assert.equal(M.tooltip('x'.repeat(513)).length,512,'shared tooltip cap remains');
''')

    def test_tooltip_caps_code_points_without_splitting_astral_text(self):
        self.js(r'''
const summary='<'+ 'S'.repeat(510) +'🚀';
const safe='‹'+ 'S'.repeat(510) +'🚀';
assert.equal(M.tooltip(summary),safe,'retain all 512 code points');
assert.equal(M.tooltip(summary+'x'),safe,'clip after the full surrogate pair');
assert.equal(M.detailTooltip('Name',summary,'Source key: Return'),
             'Name\n'+safe+'\nSource key: Return');
''')

    def test_single_line_assignment_preserves_original_hover_summary(self):
        self.js(r'''
const summary='First\r\n  second\tthird\nlast\u2028next\u2029end';
assert.equal(typeof M.singleLine,'function','visible assignment normalization is available');
assert.equal(M.singleLine(summary),'First second third last next end');
assert.equal(M.detailTooltip('Name',summary,'Source key: Return'),'Name\n'+summary+'\nSource key: Return');
''')

    def test_schema_bounds_duplicates_and_unsafe_objects_are_rejected(self):
        self.js(r'''
const b={id:'center',label:'Center / OK',key:'XF86Select',action:{kind:'key',value:'Return'},summary:'Enter'};
const c={schema:1,revision:1,keyboard:'nvidia-shield-remote',remote_name:'Remote',buttons:[b]};
const parse=c=>M.parseConfig(JSON.stringify(c));
for(const bad of ['', '{', 'null','[]','x'.repeat(262145)]) assert.equal(M.parseConfig(bad).ok,false);
for(const bad of [{...c,schema:2},{...c,revision:1.5},{...c,revision:-1},{...c,buttons:{}},
 {...c,buttons:Array(65).fill(b)},{...c,buttons:[b,b]},{...c,keyboard:'../other/config'},
 {...c,keyboard:'remote\n'},{...c,remote_name:42},{...c,buttons:[{...b,id:'bad\n'}]},
 {...c,buttons:[{...b,label:'x'.repeat(161)}]},{...c,buttons:[{...b,summary:'x'.repeat(513)}]},
 {...c,buttons:[{...b,action:null}]},{...c,buttons:[{...b,action:{kind:'unknown'}}]},
 {...c,buttons:[{...b,action:{kind:'command',argv:[42]}}]},
 {...c,buttons:[{...b,action:{kind:'shortcut',mods:42,key:'E'}}]},
 {...c,buttons:[{...b,key:'Return\n'}]}]) assert.equal(parse(bad).ok,false,JSON.stringify(bad).slice(0,120));
assert.equal(parse({...c,buttons:[]}).ok,true);
assert.equal(parse({...c,buttons:Array.from({length:64},(_,i)=>({...b,id:'b-'+i}))}).ok,true);
''')


class NativeUiTests(unittest.TestCase):
    def test_native_read_only_view_watches_replacements_errors_and_live_fallback(self):
        self.native_view(False)

    def test_initial_missing_config_shows_setup_guidance_and_recovers(self):
        self.native_view(True)

    def native_view(self, initial_missing):
        import time
        self.assertTrue((ROOT / "Panel.qml").exists(), "Native assignment panel is not implemented")
        if not Path('/usr/bin/qs').exists() or not os.environ.get('WAYLAND_DISPLAY'):
            self.skipTest('Installed Quickshell and Wayland are required; all fixture windows remain hidden')
        scratch = Path(tempfile.gettempdir())
        with tempfile.TemporaryDirectory(prefix='buttons-ui-', dir=scratch) as folder:
            work = Path(folder)
            for name in ('Commons', 'Ui'):
                (work / name).symlink_to(Path('/usr/share/omarchy/shell') / name, target_is_directory=True)
            plugin = work / 'plugin'
            plugin.mkdir()
            for name in ('Panel.qml', 'Model.js'):
                shutil.copy2(ROOT / name, plugin / name)
            shutil.copytree(ROOT / 'i18n', plugin / 'i18n')
            shutil.copy2(ROOT / 'tests/qml/Smoke.qml', work / 'shell.qml')
            env = os.environ.copy()
            for name in ('HOME', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_STATE_HOME', 'XDG_CACHE_HOME'):
                target = work / name.lower()
                target.mkdir()
                env[name] = str(target)
            language = work / 'language'
            language.write_text('de\n')
            env.update(QT_QPA_PLATFORM='wayland', QT_QUICK_BACKEND='software', OMARCHY_PATH='/usr/share/omarchy', OMARCHY_LANGUAGE_FILE=str(language), REMOTE_BUTTONS_INITIAL_MISSING='1' if initial_missing else '')
            config = Path(env['XDG_CONFIG_HOME']) / 'omarchy-remote-buttons/config.json'
            ids = ('center', 'mic', 'up', 'down', 'left', 'right', 'home', 'back', 'menu',
                   'play_pause', 'rewind', 'fast_forward', 'volume_up', 'volume_down', 'power', 'netflix')
            raw = {'schema':1, 'revision':1, 'keyboard':'nvidia-shield-remote', 'remote_name':'<b>Remote</b>',
                   'buttons':[{'id':ids[i], 'label':'<img src="https://invalid/">' if i == 0 else 'Button '+str(i),
                               'key':'XF86Select', 'action':{'kind':('native','disabled','key','shortcut','command')[i % 5], **({} if i % 5 < 2 else {'value':'Return'} if i % 5 == 2 else {'mods':'SUPER','key':'E'} if i % 5 == 3 else {'argv':['touch',str(work / 'ACTION_EXECUTED')]})},
                               'summary':'Enter' if i == 0 else 'Assignment '+str(i)} for i in range(16)]}
            raw['buttons'][2]['summary'] = 'First\r\n  second\tthird\nlast\u2028next\u2029end'
            raw['buttons'][4].update(label='<' + '🚀' * 158 + '>', summary='<' + 'S' * 510 + '🚀', key='K' * 128)
            if not initial_missing:
                config.parent.mkdir()
                config.write_text(json.dumps(raw))
            def replace(value):
                temp = config.with_suffix('.new')
                temp.write_text(value)
                temp.replace(config)
            log = work / 'native.log'
            with log.open('w') as output:
                proc = subprocess.Popen(['/usr/bin/qs', '--no-color', '-p', str(work / 'shell.qml')], env=env, stdout=output, stderr=subprocess.STDOUT, text=True)
                def wait(marker):
                    deadline = time.monotonic() + 8
                    while time.monotonic() < deadline:
                        text = log.read_text()
                        if marker in text:
                            return
                        if proc.poll() is not None:
                            self.fail(text)
                        time.sleep(.03)
                    self.fail('Timeout waiting for '+marker+'\n'+log.read_text())
                try:
                    if initial_missing:
                        wait('UI_INITIAL_MISSING')
                        config.parent.mkdir()
                        replace(json.dumps(raw))
                    wait('UI_READY')
                    raw['revision'] = 2
                    raw['buttons'][0]['summary'] = 'Changed by agent'
                    replace(json.dumps(raw))
                    wait('UI_UPDATED')
                    raw['revision'] = 3
                    raw['routing'] = {'ignored':True}
                    replace(json.dumps(raw))
                    language.write_text('da\n')
                    wait('UI_UNCHANGED')
                    replace('{invalid')
                    wait('UI_INVALID')
                    config.unlink()
                    wait('UI_MISSING')
                    replace(json.dumps(raw))
                    wait('UI_RECOVERED')
                    self.assertEqual(proc.wait(timeout=5), 0, log.read_text())
                finally:
                    if proc.poll() is None:
                        proc.kill()
                        proc.wait()
            text = log.read_text()
            self.assertNotRegex(text, r'ReferenceError|TypeError|SyntaxError|UI_ASSERT|Unable to assign|Cannot assign|is not a type')
            self.assertFalse((work / 'ACTION_EXECUTED').exists(), text)
            self.assertEqual(json.loads(config.read_text()), raw, 'Rendering must never write the config')


class UiContractTests(unittest.TestCase):
    def test_bar_icon_is_remote_control_not_ribbon(self):
        source = (ROOT / 'Panel.qml').read_text()
        bar = source[source.index('Ui.BarIconButton {'):]
        icon = re.search(r'text: "([^"]+)"', bar)
        assert icon is not None
        self.assertEqual(icon.group(1), '\U000f0454')

    def test_native_fixture_disarms_secondary_surfaces_before_opening(self):
        fixture = (ROOT / 'tests/qml/Smoke.qml').read_text()
        self.assertIn('variants.model = []', fixture)
        self.assertLess(fixture.index('variants.model = []'), fixture.index('widget.open()'))
        self.assertIn('backingWindowVisible', fixture)
        self.assertIn('variants.instances.length === 0', fixture)

    def test_native_identity_plaintext_catalog_and_no_execution_surface(self):
        self.assertTrue((ROOT / 'manifest.json').exists(), 'Plugin manifest missing')
        manifest = json.loads((ROOT / 'manifest.json').read_text())
        self.assertEqual({k:manifest[k] for k in ('schemaVersion','id','author','version','license')},
                         {'schemaVersion':1,'id':'leo.remote-buttons','author':'Leo','version':'0.1.0','license':'MIT'})
        self.assertEqual(manifest['entryPoints'], {'barWidget':'Panel.qml'})
        self.assertEqual(manifest['barWidget']['schema'], [])
        source = (ROOT / 'Panel.qml').read_text()
        self.assertEqual(len(re.findall(r'\bText\s*\{', source)), source.count('textFormat: Text.PlainText'))
        self.assertRegex(source, r'tooltipText:\s*Model\.tooltip\(')
        self.assertIn('Commons.Translations', source)
        self.assertIn('Ui.KeyboardPanel', source)
        for forbidden in ('Process {','execDetached','startDetached','XMLHttpRequest','Qt.openUrlExternally','setText(', 'setData(', 'writeAdapter(', 'busy:', 'Ui.Dropdown', 'Ui.ToggleSwitch'):
            self.assertNotIn(forbidden, source)
        catalog = json.loads((ROOT / 'i18n/en.json').read_text())
        self.assertFalse(set(re.findall(r'"((?:panel|error)\.[A-Za-z]+)"',source))-set(catalog))
        self.assertEqual(catalog['panel.agent'], 'Ask your agent to change a button')
        self.assertIn('omarchy-remote-buttons', catalog['panel.cli'])
        self.assertNotIn('Hermes', json.dumps(catalog))

    def test_first_run_notice_points_to_documented_audit_and_setup(self):
        catalog = json.loads((ROOT / 'i18n/en.json').read_text())
        notice = catalog['panel.setup']
        for guidance in ('README', 'Install', 'identify your remote', 'audit', 'one non-modifier key', 'setup'):
            self.assertIn(guidance, notice)
        self.assertNotIn('omarchy-remote-buttons', notice, 'the wrapper may not exist yet')
        self.assertNotIn('--acknowledge-single-key-bindings', notice, 'no blind acknowledgment')


if __name__ == "__main__":
    unittest.main()

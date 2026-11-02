import copy

from novel_h3.scene_contract_audit import audit_contract


def treatment(version='4.0'):
    return {
        'version': '1.0',
        'metadata': {'craft_version': version},
        'enhanced_sections': [{
            'id': 'S01',
            'text': 'Night on the riverbank.',
            'start_seconds': 0,
            'end_seconds': 10,
            'location': 'open riverbank, wooden boat, mooring stone',
            'time_of_day': 'night',
            'props': ['one wooden boat', 'one wine cup', 'one boat lantern'],
            'set_dressing': 'river, reeds and low mist; no table, no interior',
        }],
    }


def script():
    return {
        'version': '1.0',
        'sections': [{
            'id': 'S01',
            'text': 'Night on the riverbank.',
            'start_seconds': 0,
            'end_seconds': 10,
            'location': 'open riverbank, wooden boat, mooring stone',
            'time_of_day': 'night',
            'props': ['one wooden boat', 'one wine cup', 'one boat lantern'],
            'set_dressing': 'river, reeds and low mist; no table, no interior',
        }],
    }


def scene_plan():
    return {
        'version': '1.0',
        'scenes': [{
            'id': 'S01A',
            'type': 'generated',
            'description': 'Xu pours wine',
            'start_seconds': 0,
            'end_seconds': 10,
            'script_section_id': 'S01',
            'location': 'open riverbank, wooden boat, mooring stone',
            'time_of_day': 'night',
            'props': ['one wooden boat', 'one wine cup', 'one boat lantern'],
            'set_dressing': 'river, reeds and low mist; no table, no interior',
        }],
    }


def test_craft_v4_contract_passes_across_all_artifacts():
    report = audit_contract(treatment(), script(), scene_plan())
    assert report['status'] == 'pass', report['issues']
    assert report['skipped'] is False
    assert report['metrics']['scene_plan_scenes'] == 1


def test_missing_props_is_a_failure():
    data = treatment()
    data['enhanced_sections'][0]['props'] = []
    report = audit_contract(data)
    assert report['status'] == 'revise'
    assert any('needs a non-empty props list' in issue for issue in report['issues'])


def test_missing_location_on_scene_plan_is_a_failure():
    plan = scene_plan()
    plan['scenes'][0].pop('location')
    report = audit_contract(treatment(), script(), plan)
    assert report['status'] == 'revise'
    assert any('scene_plan S01A: scene contract is missing location' in issue
               for issue in report['issues'])


def test_unknown_script_section_is_a_failure():
    plan = scene_plan()
    plan['scenes'][0]['script_section_id'] = 'S99'
    report = audit_contract(treatment(), script(), plan)
    assert report['status'] == 'revise'
    assert any('S99' in issue for issue in report['issues'])


def test_legacy_treatment_is_skipped():
    report = audit_contract(treatment('2.1'))
    assert report['status'] == 'pass'
    assert report['skipped'] is True


def test_strict_flag_forces_legacy_audit():
    report = audit_contract(treatment('2.1'), strict=True)
    assert report['status'] == 'pass'  # fields are present
    assert report['skipped'] is False


def test_scene_contract_required_true_override():
    data = copy.deepcopy(treatment('2.1'))
    data['metadata']['scene_contract'] = True
    data['enhanced_sections'][0].pop('props')
    report = audit_contract(data)
    assert report['status'] == 'revise'
    assert any('props' in issue for issue in report['issues'])

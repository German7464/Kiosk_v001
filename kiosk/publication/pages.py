"""Stage 6 page objects and their versioned dependency contract."""
import re

PROFILES = ('tv-landscape', 'tv-portrait', 'kiosk-landscape', 'kiosk-portrait')
KINDS = ('dataset', 'block', 'layout', 'page', 'profile', 'assignment')
IDENTITY = re.compile(r'(dataset|block|layout|page|profile|assignment)-[0-9a-f]{32}\Z')
EVENT_ID = re.compile(r'[1-9][0-9]{0,9}\Z')


class PageError(ValueError):
    """A stable validation error without user data."""


def kind(identity):
    match = IDENTITY.fullmatch(identity) if isinstance(identity, str) else None
    if match:
        return match[1]
    if isinstance(identity, str) and EVENT_ID.fullmatch(identity) and int(identity) <= 2**31 - 1:
        return 'event'
    raise PageError('invalid_object_identity')


def _fields(value, names):
    if not isinstance(value, dict) or value.keys() != set(names.split()):
        raise PageError('invalid_page_fields')


def _integer(value, lower, upper):
    if type(value) is not int or not lower <= value <= upper:
        raise PageError('page_integer_out_of_range')
    return value


def _text(value, length):
    if not isinstance(value, str) or not value.strip() or len(value) > length or '\x00' in value:
        raise PageError('invalid_page_text')


def _reference(value, expected):
    if kind(value) != expected:
        raise PageError('incompatible_page_dependency')
    return value


def _references(values, expected, lower, upper):
    if not isinstance(values, list) or not lower <= len(values) <= upper:
        raise PageError('page_reference_limit')
    references = [_reference(value, expected) for value in values]
    if len(set(references)) != len(references):
        raise PageError('duplicate_page_reference')
    return references


def _selection(selection):
    _fields(selection, 'pages start_page transition_seconds')
    pages = _references(selection['pages'], 'page', 1, 32)
    if selection['start_page'] not in pages:
        raise PageError('invalid_start_page')
    _integer(selection['transition_seconds'], 5, 600)
    return pages


def validate(identity, value):
    """Validate one object and return the exact identities it must pin."""
    object_kind = kind(identity)
    if not isinstance(value, dict) or type(value.get('schema')) is not int or value['schema'] != 1:
        raise PageError('unsupported_page_schema')
    if object_kind == 'dataset':
        _fields(value, 'schema name module events')
        _text(value['name'], 120)
        if value['module'] != 'events':
            raise PageError('unsupported_page_module')
        return _references(value['events'], 'event', 0, 100)
    if object_kind == 'block':
        _fields(value, 'schema name dataset tags limit appearance')
        _text(value['name'], 120)
        if not isinstance(value['tags'], list) or len(value['tags']) > 32:
            raise PageError('invalid_block_tags')
        for tag in value['tags']:
            _text(tag, 128)
        if len(set(value['tags'])) != len(value['tags']):
            raise PageError('invalid_block_tags')
        _integer(value['limit'], 1, 100)
        if value['appearance'] not in ('cards', 'list'):
            raise PageError('invalid_block_appearance')
        return [_reference(value['dataset'], 'dataset')]
    if object_kind == 'layout':
        _fields(value, 'schema target columns rows placements')
        if value['target'] not in PROFILES:
            raise PageError('invalid_layout_target')
        columns, rows = _integer(value['columns'], 1, 24), _integer(value['rows'], 1, 24)
        placements = value['placements']
        if not isinstance(placements, list) or not 1 <= len(placements) <= 24:
            raise PageError('layout_placement_limit')
        occupied = set()
        blocks = []
        for placement in placements:
            _fields(placement, 'block x y w h')
            blocks.append(placement['block'])
            x, y = _integer(placement['x'], 0, columns - 1), _integer(placement['y'], 0, rows - 1)
            w, h = _integer(placement['w'], 1, columns - x), _integer(placement['h'], 1, rows - y)
            cells = {(column, row) for column in range(x, x + w) for row in range(y, y + h)}
            if cells & occupied:
                raise PageError('layout_overlap')
            occupied.update(cells)
        return _references(blocks, 'block', 1, 24)
    if object_kind == 'page':
        _fields(value, 'schema name order layouts fallback')
        _text(value['name'], 120)
        _integer(value['order'], 0, 10000)
        layouts, fallback = value['layouts'], value['fallback']
        if (not isinstance(layouts, dict) or not layouts or set(layouts) - set(PROFILES)
                or not isinstance(fallback, str) or fallback not in layouts):
            raise PageError('invalid_page_layouts')
        return _references(list(layouts.values()), 'layout', 1, 4)
    if object_kind == 'profile':
        _fields(value, 'schema name selection')
        _text(value['name'], 120)
        return _selection(value['selection'])
    if object_kind == 'assignment':
        _fields(value, 'schema device profile selection')
        _text(value['device'], 128)
        if value['profile'] is None:
            return _selection(value['selection'])
        if value['selection'] is not None:
            raise PageError('ambiguous_page_assignment')
        return [_reference(value['profile'], 'profile')]
    raise PageError('invalid_object_identity')


def validate_dependencies(identity, payload, dependencies):
    if set(validate(identity, payload)) != dependencies.keys():
        raise PageError('page_dependency_mismatch')


def validate_layout_targets(payload, layout_payloads):
    for target, identity in payload['layouts'].items():
        if layout_payloads[identity]['target'] != target:
            raise PageError('incompatible_layout_target')


def layout_for(page, layouts, target):
    """Reflow the designated default to nonoverlapping full-width rows."""
    if target not in PROFILES:
        raise PageError('invalid_layout_target')
    if target in page['layouts']:
        return layouts[page['layouts'][target]]
    default = layouts[page['layouts'][page['fallback']]]
    blocks = default['placements']
    return dict(schema=1, target=target, columns=1, rows=len(blocks),
                placements=[dict(block=item['block'], x=0, y=index, w=1, h=1)
                            for index, item in enumerate(blocks)])


def target_content(objects, device, target):
    """Project a frozen group revision to the data needed by one display.

    Keep dataset and block definitions keyed by their stable IDs. Client views
    must not receive the editor's authorship, device list or unrelated datasets.
    """
    assignments = [entry['payload'] for identity, entry in objects.items()
                   if identity.startswith('assignment-') and entry['payload']['device'] == device]
    if len(assignments) != 1:
        raise PageError('missing_or_duplicate_page_assignment')
    assignment = assignments[0]
    selection = (objects[assignment['profile']]['payload']['selection']
                 if assignment['profile'] is not None else assignment['selection'])
    projected = dict(schema=1, target=target, pages=[], blocks={}, datasets={},
                     start_page=selection['start_page'],
                     transition_seconds=selection['transition_seconds'])
    event_ids = set()
    for page_id in selection['pages']:
        entry = objects[page_id]
        page = entry['payload']
        layouts = {identity: objects[identity]['payload'] for identity in page['layouts'].values()}
        validate_layout_targets(page, layouts)
        layout = layout_for(page, layouts, target)
        projected['pages'].append(dict(id=page_id, version=entry['version'], name=page['name'],
                                       columns=layout['columns'], rows=layout['rows'],
                                       placements=layout['placements']))
        for placement in layout['placements']:
            block_id = placement['block']
            block = objects[block_id]
            projected['blocks'][block_id] = dict(block['payload'], version=block['version'])
            dataset_id = block['payload']['dataset']
            dataset = objects[dataset_id]
            projected['datasets'][dataset_id] = dict(dataset['payload'], version=dataset['version'])
            event_ids.update(dataset['payload']['events'])
    return projected, {identity: objects[identity] for identity in sorted(event_ids)}

"""Native Windows trusted-review publisher UI (no WebView, no generic signer).

The window shows the exact frozen draft/target facts, downloads and verifies the
complete candidate package, then makes one explicit Publish action. A browser or
remote page can never invoke signing: only this local controller holds the
review ticket and the DPAPI-protected key.
"""
from dataclasses import dataclass, field
from pathlib import Path
import argparse
import base64
import json
import re
import sys
import tempfile
from urllib.parse import quote, urlencode

from kiosk.display.delivery_capture import Capture
from kiosk.display.delivery_transport import Transport, TransportError
from kiosk.delivery.protocol import digest, encode, sha
from .publisher import LocalPublisher, Review, _is_page_document, native_token

CANDIDATE_PATH = '/editor/native/candidates/'
PAGE_OPEN_PATH = '/api/page/native/open'
PAGE_APPROVE_PATH = '/api/page/native/approve'
PAGE_PACKAGE_PATH = '/api/page/native/package/'
MAINTENANCE_PATHS = ('/api/page/native/',)
MAX_BUNDLE_BYTES = 65536


@dataclass(frozen=True)
class Candidate:
    identity: str
    document: dict
    ticket: Review
    folder: Path
    kind: str = 'events'
    packages: dict = None
    token: str = field(default=None, repr=False)
    maintenance_origin: str = None


def bundle(path):
    """Read one administrator authority/device bundle; never from a network page."""
    raw = Path(path).read_bytes()
    if len(raw) > MAX_BUNDLE_BYTES:
        raise ValueError('publisher_bundle_limit')
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError('publisher_bundle_refused')
    return value


def is_page_handoff(value):
    """Recognize a Maintenance page handoff without trusting or opening it."""
    from urllib.parse import urlsplit
    try:
        parsed = urlsplit(value.strip())
        return (parsed.scheme == 'kiosk' and parsed.netloc == 'roaming'
                and parsed.path == '/page')
    except (TypeError, ValueError, AttributeError):
        return False


class PublisherBridge:
    """Deterministic controller; the Tk window is a thin shell over these facts."""

    def __init__(self, publisher, transport, root, clock, *, maintenance_origin=None,
                 maintenance_ca=None, maintenance_factory=None):
        self.publisher, self.transport = publisher, transport
        self.root, self.clock = Path(root), clock
        self.maintenance_origin = maintenance_origin
        self.maintenance_ca = maintenance_ca
        self.maintenance_factory = maintenance_factory

    def status(self):
        try:
            facts = self.publisher.status(self.clock())
        except (OSError, ValueError):
            return None
        return facts

    def create(self):
        return self.publisher.create()

    def scope(self):
        return self.publisher.scope(self.clock())

    def import_authority(self, root_spki_base64, fingerprint, policy, chain, group_id, origin):
        import base64
        return self.publisher.install(base64.b64decode(root_spki_base64, validate=True),
                                      fingerprint, policy, chain, group_id, origin, self.clock())

    def device_request(self, group_id, origin, user_id):
        return self.publisher.public_request(group_id, origin, user_id, self.clock())

    def approve_login(self, token):
        """Native explicit login approval; the caller must have shown the context."""
        context = self.transport.json('/editor/native/challenge', authenticated=False,
                                      body={'token': token})['context']
        result = self.publisher.login(context, self.clock())
        self.transport.json('/editor/native/accept', authenticated=False,
                            body={'token': token, 'approval': result['approval'],
                                  'chain': result['chain']})
        return {'state': 'accepted', 'confirmation': context['id'][:8].upper(),
                'origin': context['origin'], 'summary': context['summary']}

    def authorize_device(self, request):
        """Same-user nondelegating child; explicit action on an authorized device."""
        bundle = self.publisher.authorize_own_device(request, self.clock())
        bundle['root_sha256'] = sha(base64.b64decode(bundle['root_spki']))
        return bundle

    def open(self, target):
        """Open a full kiosk:// link or an exact id; download and revalidate bytes."""
        identity = self._link_identity(target)
        document = self.transport.json(CANDIDATE_PATH + identity, authenticated=False)
        if _is_page_document(document):
            raise ValueError('publisher_page_requires_maintenance_ticket')
        plan = document.get('plan')
        if not isinstance(plan, dict) or plan.get('id') != identity:
            raise ValueError('publisher_candidate_refused')
        metadata = document.get('publication')
        folder = Path(tempfile.mkdtemp(prefix='publish-review-', dir=self.root))
        try:
            capture_root = folder / 'capture'
            capture_root.mkdir()
            package = Capture(capture_root).fetch(
                {'publication': metadata}, self.transport,
                path_prefix=CANDIDATE_PATH + identity)
            ticket = self.publisher.review(document, package.parent, self.clock())
            return Candidate(identity, document, ticket, folder)
        except BaseException:
            import shutil
            shutil.rmtree(folder, ignore_errors=True)
            raise

    def _page_link(self, target):
        """Strict kiosk://roaming/page fragment; origins must match this installation."""
        from urllib.parse import parse_qsl, urlsplit
        if not isinstance(target, str):
            raise ValueError('publisher_page_link_refused')
        parsed = urlsplit(target.strip())
        if (parsed.scheme != 'kiosk' or parsed.netloc != 'roaming'
                or parsed.path != '/page' or parsed.query):
            raise ValueError('publisher_page_link_refused')
        try:
            pairs = parse_qsl(parsed.fragment, keep_blank_values=True, strict_parsing=True)
        except ValueError:
            raise ValueError('publisher_page_link_refused') from None
        names = [name for name, _ in pairs]
        if len(names) != len(set(names)):
            raise ValueError('publisher_page_link_refused')
        fields = dict(pairs)
        if set(fields) != {'version', 'token', 'expires', 'content_origin',
                           'maintenance_origin'}:
            raise ValueError('publisher_page_link_refused')
        if fields['version'] != '1':
            raise ValueError('publisher_page_link_refused')
        if re.fullmatch('[0-9]{1,12}', fields['expires']) is None:
            raise ValueError('publisher_page_link_refused')
        if int(fields['expires']) <= self.clock():
            raise ValueError('publisher_page_link_expired')
        return dict(token=native_token(fields['token']),
                    content_origin=fields['content_origin'],
                    maintenance_origin=fields['maintenance_origin'])

    def _maintenance(self, token):
        """One token-bearing Maintenance transport; the token never enters a URL."""
        token = native_token(token)
        if self.maintenance_factory is not None:
            transport = self.maintenance_factory(token)
            if transport is None:
                raise ValueError('publisher_maintenance_origin_required')
            return transport
        if not self.maintenance_origin or not self.maintenance_ca:
            raise ValueError('publisher_maintenance_origin_required')
        return Transport({'origin': self.maintenance_origin, 'tls_ca_pem': self.maintenance_ca},
                         secret=token, paths=MAINTENANCE_PATHS)

    def open_page(self, target, *, confirm=False):
        """Explicit native open: signed ticket binding, bounded downloads, review.

        The page-review-open envelope authorizes the trusted Maintenance service to
        create a native-bound plan. No publication signature is made here.
        """
        if not confirm:
            raise ValueError('publisher_confirmation_required')
        ticket = self._page_link(target)
        scope = self.scope()
        if ticket['content_origin'] != scope['origin']:
            raise ValueError('publisher_content_origin_refused')
        if not self.maintenance_origin or ticket['maintenance_origin'] != self.maintenance_origin:
            raise ValueError('publisher_maintenance_origin_refused')
        opened = self.publisher.page_open_approval(
            ticket['token'], ticket['content_origin'], ticket['maintenance_origin'],
            self.clock())
        maintenance = self._maintenance(ticket['token'])
        response = maintenance.json(PAGE_OPEN_PATH, body=opened, authenticated=True)
        if (not isinstance(response, dict) or set(response) != {'version', 'document'}
                or response.get('version') != 1):
            raise ValueError('publisher_native_open_refused')
        document = self.publisher.validate_page_document(response['document'], self.clock())
        folder = Path(tempfile.mkdtemp(prefix='publish-pages-', dir=self.root))
        try:
            packages = {}
            for index, item in enumerate(document['targets']):
                capture_root = folder / ('target-%d' % index)
                capture_root.mkdir()
                packages[item['device_id']] = Capture(capture_root).fetch_pages(
                    {'metadata': item['metadata'],
                     'metadata_sha256': sha(encode(item['metadata'])),
                     'revision_sha256': document['plan']['revision_sha256'],
                     'device_id': item['device_id'],
                     'generation': document['plan']['id']},
                    maintenance, path_prefix=PAGE_PACKAGE_PATH + quote(item['device_id'], safe=''),
                    authenticated=True)
            reviewed = self.publisher.review_page(document, packages, self.clock())
            return Candidate(document['plan']['id'], document, reviewed, folder, 'pages',
                             packages, ticket['token'], self.maintenance_origin)
        except BaseException:
            import shutil
            shutil.rmtree(folder, ignore_errors=True)
            raise

    def _link_identity(self, target):
        from urllib.parse import parse_qsl, urlsplit
        if not isinstance(target, str):
            raise ValueError('publisher_link_refused')
        value = target.strip()
        if value.startswith('kiosk://'):
            parsed = urlsplit(value)
            if (parsed.scheme != 'kiosk' or parsed.netloc != 'roaming' or
                    parsed.path != '/publish' or parsed.query):
                raise ValueError('publisher_link_refused')
            params = dict(parse_qsl(parsed.fragment, keep_blank_values=True, strict_parsing=True))
            if set(params) != {'origin', 'plan'}:
                raise ValueError('publisher_link_refused')
            scope = self.scope()
            if params['origin'] != scope['origin']:
                raise ValueError('publisher_link_origin_refused')
            identity = params['plan']
        else:
            identity = value
        digest(identity)
        return identity

    def summarize(self, candidate):
        """Facts the operator must compare before the Publish button is enabled."""
        if candidate.kind == 'pages':
            return self._summarize_pages(candidate)
        document, plan = candidate.document, candidate.document['plan']
        from . import mapping
        data = mapping.derive(document['objects'], document.get('settings', {}),
                              document.get('content_version'))
        return {'candidate': candidate.identity,
                'confirmation': candidate.identity[:8].upper(),
                'user': plan['user_id'], 'device': plan['device_id'],
                'revision': data['content_version'],
                'events': [dict(id=item['id'], title=item['title'],
                                date=item['event_date'], tags=len(item['tag_ids']))
                           for item in data['events']],
                'tags': [item['name'] for item in data['tags']],
                'settings': data['settings'],
                'targets': [dict(device=item['device_id'], profile=item['profile_id'],
                                 revision=item['profile_version'], mode=item['mode'])
                            for item in plan['targets']],
                'package': plan['publication_sha256'],
                'expires': plan['expires']}

    def _summarize_pages(self, candidate):
        document, plan = candidate.document, candidate.document['plan']
        revision = document['revision']['plan']
        return {'candidate': candidate.identity,
                'confirmation': candidate.identity[:8].upper(),
                'user': plan['user_id'], 'device': plan['device_id'],
                'revision': plan['revision_sha256'],
                'targets': [{'device': item['device_id'], 'profile': item['profile_id'],
                             'revision': item['profile_version'], 'mode': item['mode'],
                             'projection': item['projection'],
                             'destination': item['destination'],
                             'renderer': item['renderer'],
                             'metadata': item['metadata_sha256']}
                            for item in plan['targets']],
                'included': [{'id': item['id'], 'version': item['version'],
                              'author': item['author']} for item in revision['included']],
                'excluded': [{'id': item['id'], 'version': item['version'],
                              'author': item['author'], 'reason': item['reason']}
                             for item in revision['excluded']],
                'expires': plan['expires']}

    def review_page(self, document, packages, *, token=None, maintenance_origin=None):
        """Explicit same-immutable review with independent per-target package bytes."""
        folder = Path(tempfile.mkdtemp(prefix='publish-pages-', dir=self.root))
        try:
            ticket = self.publisher.review_page(document, packages, self.clock())
            return Candidate(document['plan']['id'], document, ticket, folder,
                             'pages', dict(packages), token, maintenance_origin)
        except BaseException:
            import shutil
            shutil.rmtree(folder, ignore_errors=True)
            raise

    def publish(self, candidate):
        """Sign only this reviewed candidate, then submit the immutable approval.

        The signed approval is already durable; the local head advances only after
        the server accepts this exact approval.
        """
        result = self.publisher.publish(candidate.ticket, self.clock())
        response = self.transport.json('/editor/native/approve', authenticated=False,
                                       body={'id': candidate.identity, 'approval': result['approval'],
                                             'chain': result['chain']})
        if not isinstance(response, dict) or response.get('state') != 'approved':
            raise ValueError('publisher_approval_not_acknowledged')
        self.publisher.confirm_published(candidate.identity)
        return response

    def publish_page(self, candidate):
        """Sign exactly the reviewed v2 plan, then submit through Maintenance."""
        if candidate.kind != 'pages' or not candidate.token:
            raise ValueError('publisher_native_ticket_required')
        result = self.publisher.publish_page(
            candidate.ticket, self.clock(), token=candidate.token,
            maintenance_origin=candidate.maintenance_origin)
        return self._acknowledge_page(candidate.identity, result['approval'],
                                      result['chain'], candidate.token)

    def _acknowledge_page(self, identity, approval, chain, token):
        """Submit one exact v2 approval to the trusted Maintenance origin."""
        maintenance = self._maintenance(token)
        body = {'id': identity, 'approval': approval, 'chain': chain}
        try:
            response = maintenance.json(PAGE_APPROVE_PATH, body=body, authenticated=True)
        except TransportError as error:
            if error.status in (408, 425, 429):
                # Retryable: keep the exact durable approval for a later resend.
                raise
            if error.status in (400, 401, 403, 404, 409, 410, 422):
                # A definitive refusal can never become the same accepted plan.
                self.publisher.discard_pending(identity)
                code = 'publisher_page_review_changed' if error.status == 409 \
                    else 'publisher_approval_refused'
                raise ValueError(code) from None
            raise
        if (not isinstance(response, dict) or response.get('version') != 1
                or response.get('state') != 'approved'
                or not isinstance(response.get('distribution'), dict)):
            raise ValueError('publisher_approval_not_acknowledged')
        self.publisher.confirm_published(identity)
        return response

    def retry(self):
        """Resubmit the exact durable approval after a lost response; never re-signs."""
        pending = self.publisher.pending_approval()
        if not isinstance(pending, dict):
            raise ValueError('publisher_pending_approval_missing')
        if pending.get('kind') == 'pages':
            if not pending.get('token'):
                raise ValueError('publisher_native_ticket_required')
            return self._acknowledge_page(pending['id'], pending['approval'],
                                          pending['chain'], pending['token'])
        response = self.transport.json('/editor/native/approve', authenticated=False,
                                       body={'id': pending['id'], 'approval': pending['approval'],
                                             'chain': pending['chain']})
        if not isinstance(response, dict) or response.get('state') != 'approved':
            raise ValueError('publisher_approval_not_acknowledged')
        self.publisher.confirm_published(pending['id'])
        return response

    def discard(self, candidate):
        import shutil
        self.publisher.pending.clear()
        shutil.rmtree(candidate.folder, ignore_errors=True)


def main(argv=None):
    import sys
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        return _main(arguments)
    except SystemExit:
        raise
    except BaseException as error:
        import json
        if '--result' in arguments:
            index = arguments.index('--result')
            if index + 1 < len(arguments):
                path = Path(arguments[index + 1])
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({'result': 'error', 'error': type(error).__name__,
                                            'detail': str(error)[:300]}, sort_keys=True),
                                encoding='utf-8')
        return 1


def _main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path, help='Protected local publisher key directory')
    parser.add_argument('--origin', required=True, help='Exact https origin of the delivery server')
    parser.add_argument('--ca', required=True, type=Path, help='Public CA PEM used to verify that origin')
    parser.add_argument('--maintenance-origin',
                        help='Exact independently configured https Maintenance origin')
    parser.add_argument('--maintenance-ca', type=Path,
                        help='Public CA PEM used only to verify the Maintenance origin')
    parser.add_argument('--publisher-root', type=Path, help='Publisher root SPKI PEM for status display')
    parser.add_argument('--command', default='gui',
                        choices=('gui', 'status', 'identity', 'create-key', 'request-device', 'authorize-device',
                                 'import-bundle', 'recover-bundle', 'approve-login', 'publish', 'retry',
                                 'open-page', 'publish-page', 'discard-pending'),
                        help='Native operation; gui is the ordinary interactive window')
    parser.add_argument('--output', type=Path, help='Public device request/authorization output')
    parser.add_argument('--result', type=Path, help='Command result JSON for windowed CLI use')
    parser.add_argument('--request', type=Path, help='Incoming same-user add-device request')
    parser.add_argument('--token', help='Login or short-lived page ticket token from a kiosk:// link')
    parser.add_argument('--user', help='User identifier for a first-device add request')
    parser.add_argument('--group', help='Publisher group identifier for a first-device add request')
    parser.add_argument('--bundle', type=Path, help='Administrator authority bundle for import/recovery')
    parser.add_argument('--fingerprint', help='Root SHA-256 received through an independent channel')
    parser.add_argument('--replace', action='store_true', help='Explicit root recovery confirmation')
    parser.add_argument('--confirm', action='store_true', help='Explicit publication confirmation')
    parser.add_argument('link', nargs='?', help='Optional kiosk:// publication link from the browser')
    options = parser.parse_args(argv)
    import json
    import ssl
    import time
    from kiosk.publication.authority import origin as check_origin

    check_origin(options.origin)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_verify_locations(cafile=str(options.ca))
    pem = options.ca.read_text(encoding='ascii')
    maintenance_origin = maintenance_ca = None
    if options.maintenance_origin or options.maintenance_ca:
        if not (options.maintenance_origin and options.maintenance_ca):
            parser.error('--maintenance-origin and --maintenance-ca are required together')
        maintenance_origin = check_origin(options.maintenance_origin)
        maintenance_ca = options.maintenance_ca.read_text(encoding='ascii')
        maintenance_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        maintenance_context.minimum_version = ssl.TLSVersion.TLSv1_2
        maintenance_context.load_verify_locations(cafile=str(options.maintenance_ca))
    transport = Transport({'origin': options.origin, 'tls_ca_pem': pem},
                          paths=('/editor/native/',))
    publisher = LocalPublisher(options.root)
    bridge = PublisherBridge(publisher, transport, options.root,
                             lambda: int(time.time()),
                             maintenance_origin=maintenance_origin,
                             maintenance_ca=maintenance_ca)
    if options.command != 'gui':
        def emit(value):
            payload = json.dumps(value, sort_keys=True)
            if options.result:
                options.result.parent.mkdir(parents=True, exist_ok=True)
                options.result.write_text(payload, encoding='utf-8')
            try:
                print(payload, flush=True)
            except Exception:
                # PyInstaller --windowed has no console; the result file is authoritative.
                pass
        if options.command == 'status':
            facts = bridge.status()
            try:
                pending = publisher.pending_approval()
            except Exception:
                pending = None
            emit({'result': 'status', 'authority': facts,
                  'pending': None if pending is None else pending['id']})
            return 0
        if options.command == 'identity':
            from kiosk.display.cache import renderer_identity
            from kiosk.publication.renderer import ASSETS
            from kiosk.delivery.protocol import sha
            from kiosk.display import page_view
            page = page_view.renderer_pin()
            emit({'result': 'identity', 'renderer_build': renderer_identity(),
                  'js_sha256': sha((ASSETS / 'events.js').read_bytes()),
                  'css_sha256': sha((ASSETS / 'events.css').read_bytes()),
                  'page_renderer_build': page['build_id'],
                  'page_js_sha256': page['js_sha256'],
                  'page_css_sha256': page['css_sha256'],
                  'assets': str(ASSETS)})
            return 0
        if options.command == 'create-key':
            emit({'result': 'key_created', 'device_id': publisher.create()})
            return 0
        if options.command == 'request-device':
            try:
                facts = bridge.status()
            except Exception:
                facts = None
            group_id = options.group or (facts and facts['group_id'])
            user_id = options.user or (facts and facts['user_id'])
            if not group_id or not user_id:
                parser.error('--user and --group are required before authority is installed')
            request = bridge.device_request(group_id, options.origin, user_id)
            if options.output:
                options.output.parent.mkdir(parents=True, exist_ok=True)
                options.output.write_bytes(json.dumps(request, sort_keys=True).encode('utf-8'))
            emit({'result': 'device_request', 'device_id': request['request']['device_id'],
                  'user_id': request['request']['user_id'], 'output': str(options.output or '')})
            return 0
        if options.command == 'authorize-device':
            if options.request is None or options.output is None:
                parser.error('--request and --output are required')
            result = bridge.authorize_device(bundle(options.request))
            options.output.parent.mkdir(parents=True, exist_ok=True)
            options.output.write_bytes(json.dumps(result, sort_keys=True).encode('utf-8'))
            emit({'result': 'device_authorized', 'authorization': 'written',
                  'output': str(options.output)})
            return 0
        if options.command == 'approve-login':
            token = options.token
            if not token and options.link and options.link.startswith('kiosk://'):
                from urllib.parse import parse_qsl, urlsplit
                token = dict(parse_qsl(urlsplit(options.link).fragment)).get('token')
            if not token:
                parser.error('--token or a kiosk://roaming/login link is required')
            emit({'result': 'login', 'server': bridge.approve_login(token)})
            return 0
        if options.command in ('import-bundle', 'recover-bundle'):
            if options.bundle is None or not options.fingerprint:
                parser.error('--bundle and --fingerprint are required')
            value = bundle(options.bundle)
            fingerprint = options.fingerprint.replace(':', '').replace(' ', '').strip().lower()
            if options.command == 'recover-bundle':
                if not options.replace:
                    parser.error('--replace is required for explicit root recovery')
                publisher.recover(base64.b64decode(value['root_spki'], validate=True), fingerprint,
                                  value['policy'], value['chain'], value['group_id'],
                                  value['origin'], bridge.clock(), 'REPLACE')
            else:
                bridge.import_authority(value['root_spki'], fingerprint, value['policy'],
                                        value['chain'], value['group_id'], value['origin'])
            emit({'result': 'authority_installed', 'root_sha256': value.get('root_sha256'),
                  'recovery': options.command == 'recover-bundle'})
            return 0
        if options.command == 'retry':
            emit({'result': 'retry', 'server': bridge.retry()})
            return 0
        if options.command == 'discard-pending':
            pending = publisher.pending_approval()
            if not isinstance(pending, dict):
                raise ValueError('publisher_pending_approval_missing')
            publisher.discard_pending(pending['id'])
            emit({'result': 'discarded', 'id': pending['id']})
            return 0
        if options.command in ('open-page', 'publish-page'):
            if not options.confirm:
                emit({'result': 'confirmation_required',
                      'detail': 'Re-run with --confirm to authorize exactly this page ticket.'})
                return 2
            if options.link and options.link.strip().startswith('kiosk://'):
                target = options.link.strip()
            elif options.token:
                if maintenance_origin is None:
                    raise ValueError('publisher_maintenance_origin_required')
                target = 'kiosk://roaming/page#' + urlencode(
                    {'version': 1, 'token': options.token,
                     'expires': bridge.clock() + 600,
                     'content_origin': options.origin,
                     'maintenance_origin': maintenance_origin})
            else:
                parser.error('a kiosk://roaming/page link or --token is required')
            candidate = bridge.open_page(target, confirm=True)
            facts = bridge.summarize(candidate)
            emit({'result': 'reviewed', 'kind': 'pages', 'candidate': facts['candidate'],
                  'confirmation': facts['confirmation'], 'user': facts['user'],
                  'device': facts['device'], 'revision': facts['revision'],
                  'targets': facts['targets'], 'included': facts['included'],
                  'excluded': facts['excluded'], 'expires': facts['expires']})
            if options.command == 'open-page':
                bridge.discard(candidate)
                emit({'result': 'page_opened', 'candidate': facts['candidate']})
                return 0
            response = bridge.publish_page(candidate)
            emit({'result': 'published', 'kind': 'pages', 'server': response})
            return 0
        if not options.link:
            parser.error('a candidate link or id is required for publish')
        candidate = bridge.open(options.link)
        facts = bridge.summarize(candidate)
        emit({'result': 'reviewed', 'candidate': facts['candidate'],
              'confirmation': facts['confirmation'], 'user': facts['user'],
              'device': facts['device'], 'revision': facts['revision'],
              'events': facts['events'], 'targets': facts['targets'],
              'package': facts['package'], 'expires': facts['expires']})
        if not options.confirm:
            bridge.discard(candidate)
            emit({'result': 'confirmation_required',
                  'detail': 'Re-run with --confirm to sign exactly this reviewed candidate.'})
            return 2
        response = bridge.publish(candidate)
        emit({'result': 'published', 'server': response})
        return 0
    import tkinter as tk
    from tkinter import filedialog, messagebox, simpledialog

    window = tk.Tk()
    window.title('Kiosk publisher — local trusted review')
    status = tk.StringVar(value='No local publisher key')
    candidate_text = tk.StringVar()
    confirmed = tk.BooleanVar(value=False)
    frame = tk.Frame(window, padx=12, pady=12)
    frame.pack(fill='both', expand=True)
    tk.Label(frame, textvariable=status, justify='left').pack(anchor='w')
    tk.Label(frame, text='Candidate/page handoff link (kiosk://) or id').pack(anchor='w')
    tk.Entry(frame, textvariable=candidate_text, width=72).pack(anchor='w')
    summary = tk.Text(frame, width=88, height=22, state='disabled')
    summary.pack(pady=8)

    def refresh():
        facts = bridge.status()
        try:
            pending = publisher.pending_approval()
        except Exception:
            pending = None
        if facts:
            import datetime
            expiry = datetime.datetime.fromtimestamp(facts['expires'], datetime.timezone.utc)
            text = ('Local device ' + facts['device_id'] + '\nUser ' + facts['user_id']
                    + ' (' + facts['role'] + ') — group ' + facts['group_id'] + ' — '
                    + facts['origin'] + '\nAuthority expires ' + expiry.isoformat()
                    + ' — policy version ' + str(facts['policy_version']))
            if pending:
                text += ('\nA signed approval for ' + pending['id'][:8].upper()
                         + ' is stored and awaiting submission. Use Retry.')
            status.set(text)
        else:
            status.set('No usable local publisher key/authority. Create a key, then import an '
                       'administrator bundle.')
        retry_button.configure(state='normal' if pending else 'disabled')

    current = {}

    def show(text):
        summary.configure(state='normal')
        summary.delete('1.0', 'end')
        summary.insert('1.0', text)
        summary.configure(state='disabled')

    def load():
        try:
            candidate = bridge.open(candidate_text.get().strip())
            facts = bridge.summarize(candidate)
            current['candidate'], current['facts'] = candidate, facts
            lines = [f"Candidate {facts['confirmation']} — user {facts['user']} — "
                     f"device {facts['device'][:16]}… — revision {facts['revision']}",
                     f"Package {facts['package'][:32]}… — expires {facts['expires']}", '', 'Targets:']
            lines += [f"  {item['device']} — {item['profile']} v{item['revision']} — {item['mode']}"
                      for item in facts['targets']]
            lines += ['', 'Events:']
            lines += [f"  #{item['id']} {item['title']} ({item['date']}) tags={item['tags']}"
                      for item in facts['events']]
            lines += ['', 'Tags: ' + ', '.join(facts['tags']),
                      'Settings: ' + json.dumps(facts['settings'], ensure_ascii=False, sort_keys=True)]
            show('\n'.join(lines))
            confirmed.set(False)
        except Exception as error:
            show('Candidate refused: ' + str(error)[:200])

    def open_page():
        try:
            candidate = bridge.open_page(candidate_text.get().strip(), confirm=True)
            facts = bridge.summarize(candidate)
            current['candidate'], current['facts'] = candidate, facts
            lines = [f"Page plan {facts['confirmation']} — user {facts['user']} — "
                     f"publisher device {facts['device'][:16]}… — revision {facts['revision'][:24]}…",
                     f"Ticket expires {facts['expires']}", '', 'Targets:']
            lines += [f"  {item['device']} — {item['profile']} v{item['revision']} — {item['mode']}"
                      f" — {item['projection']} — {item['destination']} — renderer "
                      f"{item['renderer'][:16]}… — metadata {item['metadata'][:16]}…"
                      for item in facts['targets']]
            lines += ['', 'Included:']
            lines += [f"  {item['id']} v{item['version']} by {item['author']}"
                      for item in facts['included']]
            lines += ['', 'Excluded:']
            lines += [f"  {item['id']} v{item['version']} by {item['author']}"
                      f" — {item['reason']}" for item in facts['excluded']]
            show('\n'.join(lines))
            confirmed.set(False)
        except Exception as error:
            current.clear()
            show('Page ticket refused: ' + str(error)[:200])

    def publish():
        if not confirmed.get() or 'candidate' not in current:
            return messagebox.showwarning('Explicit confirmation required',
                                          'Compare the exact facts and confirm before signing.')
        try:
            if current['candidate'].kind == 'pages':
                response = bridge.publish_page(current['candidate'])
            else:
                response = bridge.publish(current['candidate'])
            distribution = response.get('distribution', {}) if isinstance(response, dict) else {}
            if distribution.get('state') == 'ready':
                message = ('Signed and distributed to ' + str(distribution.get('targets'))
                           + ' approved display(s).')
            else:
                message = ('Signed approval stored. Distribution pending: '
                           + str(distribution.get('error', 'unknown'))
                           + '. Retry from the browser session or after reconnecting.')
            messagebox.showinfo('Published', message)
            current.clear()
            refresh()
        except Exception as error:
            messagebox.showerror('Publish refused',
                                 'The signed approval is retained; use Retry after reconnecting. '
                                 + str(error)[:300])
            refresh()

    def discard_pending():
        try:
            pending = publisher.pending_approval()
            if not pending:
                return
            if not messagebox.askyesno(
                    'Discard signed approval',
                    'Discard the stored signed approval for ' + pending['id'][:8].upper()
                    + '? This cannot be recovered.'):
                return
            publisher.discard_pending(pending['id'])
            refresh()
        except Exception as error:
            messagebox.showerror('Discard refused', str(error)[:300])

    def retry():
        try:
            response = bridge.retry()
            distribution = response.get('distribution', {}) if isinstance(response, dict) else {}
            messagebox.showinfo('Retry submitted', 'Exact stored approval submitted; distribution '
                                + str(distribution.get('state', 'pending')) + '.')
            refresh()
        except Exception as error:
            messagebox.showerror('Retry failed', str(error)[:300])
            refresh()

    def create_key():
        try:
            bridge.create()
            refresh()
            messagebox.showinfo('Local key', 'Created a unique device-bound publisher key.')
        except Exception as error:
            messagebox.showerror('Key refused', str(error)[:300])

    def import_key(recovery=False):
        path = filedialog.askopenfilename(title='Administrator authority bundle',
                                          filetypes=[('JSON', '*.json')])
        if not path:
            return
        try:
            value = bundle(path)
            fingerprint = value.get('root_sha256', '')
            typed = simpledialog.askstring(
                'Authenticate the publisher pin',
                'Type the SHA-256 fingerprint received through an independent trusted channel.\n'
                'A bundle alone authenticates nothing.\n\nExpected: ' + fingerprint[:8] + '…',
                parent=window)
            if typed is None:
                return
            typed = typed.replace(':', '').replace(' ', '').strip().lower()
            confirmation = None
            if recovery:
                confirmation = simpledialog.askstring(
                    'Replace publisher root',
                    'Recovery replaces the pinned root and clears local ancestry.\n'
                    'Type REPLACE to continue.', parent=window)
            if recovery:
                bridge.publisher.recover(
                    base64.b64decode(value['root_spki'], validate=True), typed,
                    value['policy'], value['chain'], value['group_id'], value['origin'],
                    bridge.clock(), confirmation)
            else:
                bridge.import_authority(value['root_spki'], typed, value['policy'],
                                        value['chain'], value['group_id'], value['origin'])
            refresh()
            messagebox.showinfo('Authority', 'Publisher authority installed.')
        except Exception as error:
            messagebox.showerror('Import refused', str(error)[:300])

    def request_device():
        try:
            scope = bridge.scope()
            request = bridge.device_request(scope['group_id'], scope['origin'], scope['user_id'])
            path = filedialog.asksaveasfilename(title='Save device request', defaultextension='.json')
            if path:
                Path(path).write_text(json.dumps(request, sort_keys=True), encoding='utf-8')
        except Exception as error:
            messagebox.showerror('Request unavailable', str(error)[:300])

    def authorize_device():
        path = filedialog.askopenfilename(title='New device request from your other app',
                                          filetypes=[('JSON', '*.json')])
        if not path:
            return
        try:
            bundle_value = bridge.authorize_device(bundle(path))
            target = filedialog.asksaveasfilename(title='Save authorization bundle',
                                                  defaultextension='.json',
                                                  initialfile='kiosk-authority-bundle.json')
            if target:
                Path(target).write_text(json.dumps(bundle_value, sort_keys=True), encoding='utf-8')
                messagebox.showinfo('Device authorized',
                                    'Same-user nondelegating device bundle saved. Transfer it to '
                                    'that device once; it cannot authorize further devices.')
        except Exception as error:
            messagebox.showerror('Authorization refused', str(error)[:300])

    def register_link():
        if not getattr(sys, 'frozen', False):
            return messagebox.showinfo('Link registration',
                                       'Run the packaged publisher app to register its link handler.')
        try:
            from tools.register_publisher_link import register
            arguments = (f'--root "{options.root}" --origin {options.origin} '
                         f'--ca "{options.ca}"')
            if maintenance_origin and options.maintenance_ca:
                arguments += (f' --maintenance-origin {maintenance_origin}'
                              f' --maintenance-ca "{options.maintenance_ca}"')
            register(sys.executable, arguments)
            messagebox.showinfo('Link registration',
                                'Registered kiosk:// for this Windows user. Browser candidate '
                                'links now open this app; no administrator was required.')
        except Exception as error:
            messagebox.showerror('Link registration', str(error)[:300])

    def paste_link():
        try:
            candidate_text.set(window.clipboard_get().strip())
            if is_page_handoff(candidate_text.get()):
                show('Page handoff loaded. Press "Open page handoff (Maintenance)" to '
                     'authorize this exact ticket explicitly.')
            else:
                load()
        except Exception as error:
            messagebox.showerror('Clipboard', 'No usable link in the clipboard: ' + str(error)[:200])

    buttons = tk.Frame(frame)
    buttons.pack(anchor='w', pady=6)
    tk.Button(buttons, text='Create local key', command=create_key).pack(side='left')
    tk.Button(buttons, text='Import authority', command=import_key).pack(side='left')
    tk.Button(buttons, text='Recovery: replace root',
              command=lambda: import_key(True)).pack(side='left')
    tk.Button(buttons, text='Save device request', command=request_device).pack(side='left')
    tk.Button(buttons, text='Authorize own new device', command=authorize_device).pack(side='left')
    tk.Button(buttons, text='Register kiosk:// link (current user)', command=register_link).pack(side='left')
    tk.Button(buttons, text='Load candidate', command=load).pack(side='left')
    tk.Button(buttons, text='Open page handoff (Maintenance)',
              command=open_page).pack(side='left')
    tk.Button(buttons, text='Paste link from clipboard',
              command=lambda: paste_link()).pack(side='left')
    tk.Button(frame, text='Discard stored approval', command=discard_pending).pack(anchor='w')
    retry_button = tk.Button(frame, text='Retry stored approval', command=retry, state='disabled')
    retry_button.pack(anchor='w')
    tk.Checkbutton(frame, text='I compared this exact content, revision and target list',
                   variable=confirmed).pack(anchor='w')
    tk.Button(frame, text='Publish (sign exactly this candidate)', command=publish).pack(anchor='w', pady=6)
    refresh()
    if options.link:
        candidate_text.set(options.link.strip())
        if is_page_handoff(options.link):
            show('Page handoff loaded. Press "Open page handoff (Maintenance)" to authorize '
                 'this exact ticket explicitly.')
        else:
            load()
    window.mainloop()


if __name__ == '__main__':
    main()

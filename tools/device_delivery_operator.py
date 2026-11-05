"""External lab operator only; disposable admin credential never enters the APK."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlencode

from tools.check_device_delivery_lab import LabClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument('--pending', action='store_true')
    actions.add_argument('--approve-code')
    actions.add_argument('--publish-title')
    actions.add_argument('--revoke-device')
    args = parser.parse_args()
    client = LabClient(args.root)
    client.login()
    if args.pending or args.approve_code:
        pending = json.loads(client.call('/admin/devices/pending'))
        if args.pending:
            print(json.dumps(pending))
            return
        matches = [row for row in pending['requests'] if row['user_code'] == args.approve_code and row['state'] == 'pending']
        if len(matches) != 1:
            raise RuntimeError('Expected one pending request with the displayed phone code')
        row = matches[0]
        response = client.call('/admin/devices/' + row['request_id'] + '/decision',
                               body={'user_code': row['user_code'], 'binding_sha256': row['binding_sha256'], 'decision': 'approve'}, csrf=client.csrf())
        print(response.decode('utf-8'))
    elif args.revoke_device:
        print(client.call('/admin/devices/' + args.revoke_device + '/revoke', body={}, csrf=client.csrf()).decode('utf-8'))
    else:
        events = json.loads(client.call('/api/events'))['events']
        if len(events) != 1:
            raise RuntimeError('Expected one synthetic lab event; no other data is edited')
        event = events[0]
        form = {key: event.get(key) or '' for key in ('title', 'short_description', 'full_description', 'event_date', 'place', 'status', 'sort_order')}
        form['title'] = args.publish_title
        client.call('/admin/events/' + str(event['id']) + '/edit', 302, form=form, csrf=client.csrf())
        print('Synthetic lab event updated; automatic publisher assigns the revision.')


if __name__ == '__main__':
    main()

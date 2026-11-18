"""Local provider fixture retaining the actual wire and connection-local context."""

import json
import queue


class ProviderSocket:
    def __init__(self, reply):
        self.reply = reply
        self.responses = {}
        self.events = queue.Queue()
        self.wire = []
        self.closed = False

    def send(self, payload):
        wire = json.loads(payload)
        assert wire.pop('type') == 'response.create'
        assert 'stream' not in wire
        self.wire.append(wire)
        previous = wire.get('previous_response_id')
        if previous and previous not in self.responses:
            self.events.put({'type': 'error', 'error': {'code': 'previous_response_not_found'}})
            return
        context = self.responses.get(previous, []) + wire['input']
        result = self.reply({**wire, 'input': context})
        self.responses[result['id']] = context + result['output']
        self.events.put({'type': 'response.created', 'response': {'id': result['id']}})
        self.events.put({'type': 'response.completed', 'response': result})

    def recv(self, timeout):
        try:
            return json.dumps(self.events.get(timeout=timeout))
        except queue.Empty:
            raise TimeoutError from None

    def close(self):
        self.closed = True

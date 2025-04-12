"""Handlers for admin features"""

from model import Poll

import webapp2
from google.appengine.ext.ndb.query import Cursor
from google.appengine.api.datastore_errors import BadValueError
from google.appengine.api import taskqueue

class MigratePage(webapp2.RequestHandler):
    def post(self, pid):
        Poll.migrate(int(pid))

    def get(self, pid):
        taskqueue.add(queue_name='outbox', url='/migrate/{}'.format(pid))
        self.response.headers['Content-Type'] = 'text/plain'
        self.response.write('Migrate page\n')

class PollPage(webapp2.RequestHandler):
    def get(self, pid):
        try:
            pid = int(pid)
            poll = Poll.get_by_id(pid)
            if not poll:
                raise ValueError
        except ValueError:
            self.response.set_status(404)
            self.response.write('Invalid poll ID')
            return
        self.response.write(poll.render_html())

class PollsPage(webapp2.RequestHandler):
    def get(self):
        self.process_polls()

    def post(self):
        self.process_polls()

    def process_polls(self):
        try:
            cursor = Cursor.from_websafe_string(self.request.get('cursor'))
        except BadValueError:
            cursor = None

        try:
            limit = int(self.request.get('limit'))
            if limit <= 0:
                raise ValueError
        except (TypeError, ValueError):
            limit = 1000

        query = Poll.query().order(Poll.created)
        polls, next_cursor, has_more = query.fetch_page(limit, start_cursor=cursor, keys_only=True)

        for poll in polls:
            taskqueue.add(queue_name='outbox', url='/migrate/{}'.format(poll.id()))

        if not has_more:
            return

        more_url = '?cursor={}&limit={}'.format(next_cursor.to_websafe_string(), limit)
        self.response.write('<p><a href="{}">More</a></p>'.format(more_url))
        taskqueue.add(queue_name='outbox', url='/polls', params={'cursor': next_cursor.to_websafe_string(), 'limit': limit})

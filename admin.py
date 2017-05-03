"""Handlers for admin features"""

from model import Poll

import webapp2
from google.appengine.ext import ndb

class MigratePage(webapp2.RequestHandler):
    def get(self):
        self.response.headers['Content-Type'] = 'text/plain'
        self.response.write('Migrate page\n')

class PollPage(webapp2.RequestHandler):
    def get(self, pid):
        try:
            pid = int(pid)
            poll = Poll.get_by_id(pid)
            poll_text = poll.render_text()
        except:
            self.response.set_status(404)
            self.response.write('Invalid poll ID')
            return
        self.response.write('<p>' + poll_text.replace('\n', '<br>\n') + '</p>')

class PollsPage(webapp2.RequestHandler):
    def get(self):
        try:
            cursor = ndb.query.Cursor(urlsafe=self.request.get('cursor'))
        except:
            cursor = None

        try:
            limit = int(self.request.get('limit'))
            if limit <= 0:
                raise Exception
        except:
            limit = 100

        query = Poll.query().order(-Poll.created)
        polls, next_cursor, has_more = query.fetch_page(limit, start_cursor=cursor)

        for poll in polls:
            self.response.write(poll.render_html() + '\n\n<hr>\n\n')

        if not has_more:
            return

        more_url = '?cursor={}&limit={}'.format(next_cursor.urlsafe(), limit)
        self.response.write('<p><a href="{}">More</a></p>'.format(more_url))

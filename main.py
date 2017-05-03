"""Main CountMeIn Bot app"""

import logging
import warnings
import json

import util
import backend
from model import User, Respondent, Poll, Option
from secrets import BOT_TOKEN

import webapp2
from google.appengine.api import memcache
from google.appengine.runtime import apiproxy_errors
from urllib3.contrib.appengine import AppEnginePlatformWarning

warnings.simplefilter("ignore", AppEnginePlatformWarning)

class FrontPage(webapp2.RequestHandler):
    def get(self):
        self.response.headers['Content-Type'] = 'text/plain'
        self.response.write('CountMeIn Bot backend running...')

class MainPage(webapp2.RequestHandler):
    NEW_POLL = 'Let\'s create a new poll. First, send me the title.'
    PREMATURE_DONE = 'Sorry, a poll needs to have at least one option to work.'
    FIRST_OPTION = u'New poll: \'{}\'\n\nPlease send me the first answer option.'
    NEXT_OPTION = 'Good. Now send me another answer option, or /done to finish.'
    HELP = 'This bot will help you create polls where people can leave their names. ' + \
           'Use /start to create a poll here, then publish it to groups or send it to' + \
           'individual friends.\n\nSend /polls to manage your existing polls.'
    DONE = u'\U0001f44d' + ' Poll created. You can now publish it to a group or send it to ' + \
           'your friends in a private message. To do this, tap the button below or start ' + \
           'your message in any other chat with @countmeinbot and select one of your polls to send.'
    ERROR_OVER_QUOTA = 'Sorry, CountMeIn Bot is overloaded right now. Please try again later!'
    THUMB_URL = 'https://countmeinbot.appspot.com/thumb.jpg'

    update = None

    @staticmethod
    def deliver_poll(uid, poll):
        backend.send_message(0.5, chat_id=uid, text=poll.render_text(), parse_mode='HTML',
                             reply_markup=poll.build_admin_buttons())

    def post(self):
        logging.debug(self.request.body)
        self.update = backend.parse_update(self.request.body)

        if self.update.message:
            logging.info('Processing incoming message')
            self.handle_message()
        elif self.update.callback_query:
            logging.info('Processing incoming callback query')
            self.handle_callback_query()
        elif self.update.inline_query:
            logging.info('Processing incoming inline query')
            self.handle_inline_query()

    def handle_message(self):
        message = self.update.message

        User.populate_by_id(message.from_user.id,
                            first_name=message.from_user.first_name,
                            last_name=message.from_user.last_name,
                            username=message.from_user.username)

        if not message.text:
            return

        text = message.text
        uid = str(message.chat.id)
        responding_to = memcache.get(uid)

        if text.startswith('/start'):
            backend.send_message(chat_id=uid, text=self.NEW_POLL)
            memcache.set(uid, value='START', time=3600)

        elif text == '/done':
            if responding_to and responding_to.startswith('OPT '):
                poll_id = int(responding_to[4:])
                poll = Poll.get_by_id(poll_id)
                if poll.options:
                    backend.send_message(chat_id=uid, text=self.DONE)
                    self.deliver_poll(uid, poll)
                    memcache.delete(uid)
                else:
                    backend.send_message(chat_id=uid, text=self.PREMATURE_DONE)
            else:
                backend.send_message(chat_id=uid, text=self.HELP)

        elif text == '/polls':
            header = [util.make_html_bold('Your polls')]

            recent_polls = Poll.query(Poll.admin_uid == uid).order(-Poll.created).fetch(50)
            body = [u'{}. {}'.format(i, poll.generate_poll_summary_with_link()) for i, poll
                    in enumerate(recent_polls)]

            footer = ['Use /start to create a new poll.']

            output = u'\n\n'.join(header + body + footer)

            backend.send_message(chat_id=uid, text=output, parse_mode='HTML')
            memcache.delete(uid)

        elif text.startswith('/view_'):
            try:
                poll_id = int(text[6:])
                poll = Poll.get_by_id(poll_id)
                if poll.admin_uid != uid:
                    raise ValueError
                self.deliver_poll(uid, poll)
                memcache.delete(uid)
            except ValueError:
                backend.send_message(chat_id=uid, text=self.HELP)

        else:
            if not responding_to:
                backend.send_message(chat_id=uid, text=self.HELP)

            elif responding_to == 'START':
                new_poll_key = Poll.new(admin_uid=uid, title=text).put()
                poll_id = new_poll_key.id()
                bold_title = util.make_html_bold_first_line(text)
                backend.send_message(chat_id=uid, text=self.FIRST_OPTION.format(bold_title),
                                     parse_mode='HTML')
                memcache.set(uid, value='OPT {}'.format(poll_id), time=3600)

            elif responding_to.startswith('OPT '):
                poll_id = int(responding_to[4:])
                poll = Poll.get_by_id(poll_id)
                poll.options.append(Option(text))
                poll.put()
                if len(poll.options) < 10:
                    backend.send_message(chat_id=uid, text=self.NEXT_OPTION)
                else:
                    backend.send_message(chat_id=uid, text=self.DONE)
                    self.deliver_poll(uid, poll)
                    memcache.delete(uid)

            else:
                backend.send_message(chat_id=uid, text=self.HELP)
                memcache.delete(uid)

    def handle_callback_query(self):
        callback_query = self.update.callback_query

        extract_user_data = lambda user: (user.id, {'first_name': user.first_name,
                                                    'last_name': user.last_name,
                                                    'username': user.username})
        uid, user_profile = extract_user_data(callback_query.from_user)

        Respondent.populate_by_id(uid, **user_profile)

        imid = callback_query.inline_message_id
        chat_id = callback_query.message.chat.id if imid else None
        mid = callback_query.message.message_id if imid else None
        is_admin = not imid

        try:
            params = callback_query.data.split()
            poll_id = int(params[0])
            action = params[1]
        except (AttributeError, IndexError, ValueError):
            logging.warning('Invalid callback query data')
            self.answer_callback_query('Invalid data. This attempt will be logged!')
            return

        poll = Poll.get_by_id(poll_id)
        if not poll:
            backend.api_call('edit_message_reply_markup',
                             inline_message_id=imid, chat_id=chat_id, message_id=mid)
            self.answer_callback_query('Sorry, this poll has been deleted')
            return

        if action.isdigit():
            poll, status = Poll.toggle(poll_id, int(action), uid, user_profile)
            backend.api_call('edit_message_text',
                             inline_message_id=imid, chat_id=chat_id, message_id=mid,
                             text=poll.render_text(), parse_mode='HTML',
                             reply_markup=poll.build_vote_buttons(admin=is_admin))

        elif action == 'refresh' and is_admin:
            status = 'Results updated!'
            backend.api_call('edit_message_text', chat_id=chat_id, message_id=mid,
                             text=poll.render_text(), parse_mode='HTML',
                             reply_markup=poll.build_admin_buttons())

        elif action == 'vote' and is_admin:
            status = 'You may now vote!'
            backend.api_call('edit_message_reply_markup', chat_id=chat_id, message_id=mid,
                             reply_markup=poll.build_vote_buttons(admin=True))

        elif action == 'delete' and is_admin:
            poll.key.delete()
            status = 'Poll deleted!'
            backend.api_call('edit_message_reply_markup', chat_id=chat_id, message_id=mid)

        elif action == 'back' and is_admin:
            status = ''
            backend.api_call('edit_message_reply_markup', chat_id=chat_id, message_id=mid,
                             reply_markup=poll.build_admin_buttons())

        else:
            status = 'Invalid data. This attempt will be logged!'
            logging.warning('Invalid callback query data')

        self.answer_callback_query(status)

    def handle_inline_query(self):
        inline_query = self.update.inline_query

        text = inline_query.query.lower()

        uid = str(inline_query.from_user.id)
        query = Poll.query(Poll.admin_uid == uid,
                           Poll.title_short >= text, Poll.title_short < text + u'\ufffd')

        results = []
        polls = sorted(query.fetch(50), key=lambda poll: poll.created, reverse=True)
        for poll in polls:
            qr_id = str(poll.key.id())
            qr_title = poll.title
            qr_description = poll.generate_options_summary()
            content = {'message_text': poll.render_text(), 'parse_mode': 'HTML'}
            reply_markup = poll.build_vote_buttons()
            result = {'type': 'article', 'id': qr_id, 'title': qr_title,
                      'description': qr_description, 'input_message_content': content,
                      'reply_markup': reply_markup, 'thumb_url': self.THUMB_URL}
            results.append(result)

        self.answer_inline_query(results)

    def answer_callback_query(self, status):
        qid = self.update.callback_query.id
        self.write_request('answerCallbackQuery', callback_query_id=qid, text=status)

    def answer_inline_query(self, results):
        qid = self.update.inline_query.id
        self.write_request('answerInlineQuery', inline_query_id=qid, results=results, cache_time=0,
                           switch_pm_text='Create new poll', switch_pm_parameter='new')

    def write_request(self, method_name, **kwargs):
        request_data = kwargs.copy()
        request_data['method'] = method_name
        payload = json.dumps(request_data)

        self.response.headers['Content-Type'] = 'application/json'
        self.response.write(payload)

        logging.info('Request sent in response: ' + method_name)
        logging.debug(payload)

    def handle_exception(self, exception, debug):
        if isinstance(exception, apiproxy_errors.OverQuotaError):
            logging.warning(exception)

            if self.update.message:
                pass
            elif self.update.callback_query:
                self.answer_callback_query(self.ERROR_OVER_QUOTA)
            elif self.update.inline_query:
                pass

            return

        logging.exception(exception)
        self.abort(500)

APP = webapp2.WSGIApplication([
    webapp2.Route('/', FrontPage),
    webapp2.Route('/' + BOT_TOKEN, MainPage),
    webapp2.Route('/telegram/<method_name>', backend.TelegramPage),
    webapp2.Route('/migrate', 'admin.MigratePage'),
    webapp2.Route('/polls', 'admin.PollsPage'),
    webapp2.Route('/poll/<pid>', 'admin.PollPage'),
], debug=True)

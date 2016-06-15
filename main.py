import webapp2
import logging
import json
import telegram
from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from google.appengine.api import taskqueue, memcache
from google.appengine.ext import ndb
from collections import OrderedDict

from secrets import BOT_TOKEN
bot = telegram.Bot(token=BOT_TOKEN)

RECOGNISED_ERRORS = ['Message is not modified']
THUMB_URL = 'https://countmeinbot.appspot.com/thumb.jpg'

class User(ndb.Model):
    first_name = ndb.TextProperty()
    last_name = ndb.TextProperty()
    username = ndb.StringProperty(indexed=False)

    created = ndb.DateTimeProperty(auto_now_add=True)
    updated = ndb.DateTimeProperty(auto_now=True, indexed=False)

class Poll(ndb.Model):
    admin_uid = ndb.StringProperty()
    title = ndb.TextProperty()
    title_short = ndb.StringProperty()
    active = ndb.BooleanProperty(default=True)
    multi = ndb.BooleanProperty(default=True, indexed=False)

    options = ndb.PickleProperty(repeated=True)

    created = ndb.DateTimeProperty(auto_now_add=True)
    updated = ndb.DateTimeProperty(auto_now=True, indexed=False)

    def generate_options_summary(self):
        output = ''
        for option in self.options:
            output += option.title + ' / '
        return output.rstrip(' / ')

    def generate_respondents_summary(self):
        all_uids = []
        for option in self.options:
            all_uids += option.people.keys()
        num_respondents = len(set(all_uids))
        if num_respondents == 0:
            return 'Nobody responded'
        elif num_respondents == 1:
            return '1 person responded'
        else:
            return '{} people responded'.format(num_respondents)

    def generate_poll_summary_with_link(self):
        short_bold_title = make_html_bold(self.title.encode('utf-8')[:65])
        respondents_summary = self.generate_respondents_summary()
        link = '/view_{}'.format(self.key.id())
        return '{} {}.\n{}'.format(short_bold_title, respondents_summary, link)

    def render_text(self):
        output = make_html_bold(self.title) + '\n\n'
        for option in self.options:
            output += make_html_bold(option.title) + '\n'
            output += strip_html_symbols(option.generate_name_list()) + '\n\n'
        output += u'\U0001f465' + ' ' + self.generate_respondents_summary()
        return output

    def build_vote_buttons(self, admin=False):
        poll_id = self.key.id()
        options = self.options
        buttons = []
        for i in range(len(options)):
            data = '{} {}'.format(poll_id, i)
            button = InlineKeyboardButton(options[i].title, callback_data=data)
            buttons.append([button])
        if admin:
            back_data = '{} back'.format(poll_id)
            back_button = InlineKeyboardButton('Back', callback_data=back_data)
            buttons.append([back_button])
        return InlineKeyboardMarkup(buttons).to_dict()

    def build_admin_buttons(self):
        poll_id = self.key.id()
        publish_button = InlineKeyboardButton('Publish poll', switch_inline_query=self.title[:512])
        refresh_data = '{} refresh'.format(poll_id)
        refresh_button = InlineKeyboardButton('Update results', callback_data=refresh_data)
        vote_data = '{} vote'.format(poll_id)
        vote_button = InlineKeyboardButton('Vote', callback_data=vote_data)
        delete_data = '{} delete'.format(poll_id)
        delete_button = InlineKeyboardButton('Delete', callback_data=delete_data)
        buttons = [[publish_button], [refresh_button], [vote_button, delete_button]]
        return InlineKeyboardMarkup(buttons).to_dict()

class Option(object):
    def __init__(self, title, people=OrderedDict()):
        self.title = title
        self.people = people

    def toggle(self, uid, first_name, last_name):
        if self.people.get(uid):
            self.people.pop(uid, None)
            return 'Your name was removed from ' + self.title + '!'
        else:
            self.people[uid] = (first_name, last_name)
            return 'Your name was added to ' + self.title + '!'

    def generate_name_list(self):
        output = ''
        for (first_name, _) in self.people.values():
            output += first_name + '\n'
        return output.strip()

class FrontPage(webapp2.RequestHandler):
    def get(self):
        self.response.headers['Content-Type'] = 'text/plain'
        self.response.write('CountMeIn Bot backend running...')

class TelegramHandler(webapp2.RequestHandler):
    def handle_exception(self, exception, debug):
        if isinstance(exception, telegram.error.NetworkError):
            if str(exception) in RECOGNISED_ERRORS:
                logging.info(exception)
            else:
                logging.warning(exception)
                self.abort(500)
        else:
            logging.error(exception)

class SendMessagePage(TelegramHandler):
    def post(self):
        logging.debug(self.request.body)
        kwargs = json.loads(self.request.body)
        bot.sendMessage(**kwargs)
        logging.info('Message sent!')

class EditMessageTextPage(TelegramHandler):
    def post(self):
        logging.debug(self.request.body)
        kwargs = json.loads(self.request.body)
        bot.editMessageText(**kwargs)
        logging.info('Message text edited!')

class EditMessageReplyMarkupPage(TelegramHandler):
    def post(self):
        logging.debug(self.request.body)
        kwargs = json.loads(self.request.body)
        bot.editMessageReplyMarkup(**kwargs)
        logging.info('Message reply markup edited!')

class MainPage(webapp2.RequestHandler):
    NEW_POLL = 'Let\'s create a new poll. First, send me the title.'
    PREMATURE_DONE = 'Sorry, a poll needs to have at least one option to work.'
    FIRST_OPTION = 'New poll: \'{}\'\n\nPlease send me the first answer option.'
    NEXT_OPTION = 'Good. Now send me another answer option, or /done to finish.'
    HELP = 'This bot will help you create polls where people can leave their names. ' + \
           'Use /start to create a poll here, then publish it to groups or send it to' + \
           'individual friends.\n\nSend /polls to manage your existing polls.'
    DONE = u'\U0001f44d' + ' Poll created. You can now publish it to a group or send it to ' + \
           'your friends in a private message. To do this, tap the button below or start ' + \
           'your message in any other chat with @countmeinbot and select one of your polls to send.'

    def post(self):
        logging.debug(self.request.body)
        update = telegram.Update.de_json(json.loads(self.request.body))

        if update.message:
            logging.info('Processing incoming message')
            self.handle_message(update.message)
        elif update.callback_query:
            logging.info('Processing incoming callback query')
            self.handle_callback_query(update.callback_query)
        elif update.inline_query:
            logging.info('Processing incoming inline query')
            self.handle_inline_query(update.inline_query)

    def handle_message(self, message):
        u = message.from_user
        update_user(u.id, first_name=u.first_name, last_name=u.last_name, username=u.username)
        uid = str(message.chat.id)

        if not message.text:
            return

        raw_text = message.text
        text = raw_text.encode('utf-8')
        responding_to = memcache.get(uid)

        if text.startswith('/start'):
            send_message(chat_id=uid, text=self.NEW_POLL)
            memcache.set(uid, value='START', time=3600)

        elif text == '/done':
            if responding_to and responding_to.startswith('OPT '):
                poll_id = int(responding_to[4:])
                poll = get_poll(poll_id)
                option_count = len(poll.options)
                if option_count > 0:
                    send_message(chat_id=uid, text=self.DONE)
                    deliver_poll(uid, poll)
                    memcache.delete(uid)
                else:
                    send_message(chat_id=uid, text=self.PREMATURE_DONE)
            else:
                send_message(chat_id=uid, text=self.HELP)

        elif text == '/polls':
            output = make_html_bold('Your polls') + '\n\n'
            query = Poll.query(Poll.admin_uid == uid).order(-Poll.created)
            i = 0
            for poll in query.fetch(50):
                i += 1
                output += '{}. {}\n\n'.format(i, poll.generate_poll_summary_with_link())
            output += 'Use /start to create a new poll.'

            send_message(chat_id=uid, text=output, parse_mode='HTML')
            memcache.delete(uid)

        elif text.startswith('/view_'):
            try:
                poll_id = int(text[6:])
                poll = get_poll(poll_id)
                if poll.admin_uid != uid:
                    raise
                deliver_poll(uid, poll)
                memcache.delete(uid)
            except:
                send_message(chat_id=uid, text=self.HELP)

        else:
            if not responding_to:
                send_message(chat_id=uid, text=self.HELP)

            elif responding_to == 'START':
                new_poll = Poll(admin_uid=uid, title=text, title_short=text[:512].lower())
                poll_key = new_poll.put()
                poll_id = str(poll_key.id())
                bold_title = make_html_bold(text)
                send_message(chat_id=uid, text=self.FIRST_OPTION.format(bold_title),
                             parse_mode='HTML')
                memcache.set(uid, value='OPT ' + poll_id, time=3600)

            elif responding_to.startswith('OPT '):
                poll_id = int(responding_to[4:])
                poll = get_poll(poll_id)
                poll.options.append(Option(raw_text))
                poll.put()
                option_count = len(poll.options)
                if option_count < 10:
                    send_message(chat_id=uid, text=self.NEXT_OPTION)
                else:
                    send_message(chat_id=uid, text=self.DONE)
                    deliver_poll(uid, poll)
                    memcache.delete(uid)

            else:
                send_message(chat_id=uid, text=self.HELP)
                memcache.delete(uid)

    def handle_callback_query(self, callback_query):
        qid = callback_query.id
        data = callback_query.data

        uid = str(callback_query.from_user.id)
        first_name = callback_query.from_user.first_name
        last_name = callback_query.from_user.last_name

        imid = callback_query.inline_message_id
        if not imid:
            chat_id = callback_query.message.chat.id
            mid = callback_query.message.message_id

        try:
            params = data.split()
            poll_id = int(params[0])
            action = params[1]
        except:
            logging.warning('Invalid callback query data')
            self.answer_callback_query(qid, 'Invalid data. This attempt will be logged!')
            return

        poll = get_poll(poll_id)
        if not poll:
            if imid:
                edit_message_reply_markup(inline_message_id=imid)
            else:
                edit_message_reply_markup(chat_id=chat_id, message_id=mid)
            self.answer_callback_query(qid, 'Sorry, this poll has been deleted')
            return

        if action.isdigit():
            (poll, status) = toggle_poll(poll_id, int(action), uid, first_name, last_name)
            updated_text = poll.render_text()

            if imid:
                edit_message_text(inline_message_id=imid,
                                  text=updated_text, parse_mode='HTML',
                                  reply_markup=poll.build_vote_buttons())
            else:
                edit_message_text(chat_id=chat_id, message_id=mid,
                                  text=updated_text, parse_mode='HTML',
                                  reply_markup=poll.build_vote_buttons(admin=True))

        elif action == 'refresh' and not imid:
            status = 'Results updated!'
            updated_text = poll.render_text()
            edit_message_text(chat_id=chat_id, message_id=mid,
                              text=updated_text, parse_mode='HTML',
                              reply_markup=poll.build_admin_buttons())

        elif action == 'vote' and not imid:
            status = 'You may now vote!'
            edit_message_reply_markup(chat_id=chat_id, message_id=mid,
                                      reply_markup=poll.build_vote_buttons(admin=True))

        elif action == 'delete' and not imid:
            status = 'Poll deleted!'
            poll.key.delete()
            edit_message_reply_markup(chat_id=chat_id, message_id=mid)

        elif action == 'back' and not imid:
            status = ''
            edit_message_reply_markup(chat_id=chat_id, message_id=mid,
                                      reply_markup=poll.build_admin_buttons())

        else:
            logging.warning('Invalid callback query data')
            self.answer_callback_query(qid, 'Invalid data. This attempt will be logged!')
            return

        self.answer_callback_query(qid, status)

    def answer_callback_query(self, qid, status):
        payload = {'method': 'answerCallbackQuery', 'callback_query_id': qid, 'text': status}
        output = json.dumps(payload)
        self.response.headers['Content-Type'] = 'application/json'
        self.response.write(output)
        logging.info('Answered callback query!')
        logging.debug(output)

    def handle_inline_query(self, inline_query):
        qid = inline_query.id
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
                      'reply_markup': reply_markup, 'thumb_url': THUMB_URL}
            results.append(result)

        payload = {'method': 'answerInlineQuery', 'inline_query_id': qid, 'results': results,
                   'switch_pm_text': 'Create new poll', 'switch_pm_parameter': 'new',
                   'cache_time': 0}
        output = json.dumps(payload)
        self.response.headers['Content-Type'] = 'application/json'
        self.response.write(output)
        logging.info('Answered inline query!')
        logging.debug(output)

@ndb.transactional
def toggle_poll(poll_id, opt_id, uid, first_name, last_name):
    poll = get_poll(poll_id)
    if not poll:
        return (None, 'Sorry, this poll has been deleted')
    elif opt_id >= len(poll.options):
        return (None, 'Sorry, that\'s an invalid option')
    status = poll.options[opt_id].toggle(uid, first_name, last_name)
    poll.put()
    return (poll, status)

def get_poll(pid):
    key = ndb.Key('Poll', pid)
    return key.get()

def deliver_poll(uid, poll):
    send_message(0.5, chat_id=uid, text=poll.render_text(), parse_mode='HTML',
                 reply_markup=poll.build_admin_buttons())

def update_user(uid, **kwargs):
    key = ndb.Key('User', uid)
    user = key.get()
    if not user:
        user = User(id=uid)
    user.populate(**kwargs)
    user.put()

def send_message(countdown=0, **kwargs):
    payload = json.dumps(kwargs)
    taskqueue.add(queue_name='outbox', url='/sendMessage', payload=payload, countdown=countdown)
    logging.info('Message queued')
    logging.debug(payload)

def edit_message_text(**kwargs):
    payload = json.dumps(kwargs)
    taskqueue.add(queue_name='outbox', url='/editMessageText', payload=payload)
    logging.info('Message text edit queued')
    logging.debug(payload)

def edit_message_reply_markup(**kwargs):
    payload = json.dumps(kwargs)
    taskqueue.add(queue_name='outbox', url='/editMessageReplyMarkup', payload=payload)
    logging.info('Message reply markup edit queued')
    logging.debug(payload)

def strip_html_symbols(text):
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

def make_html_bold(text):
    return '<b>' + strip_html_symbols(text) + '</b>'

app = webapp2.WSGIApplication([
    ('/', FrontPage),
    ('/' + BOT_TOKEN, MainPage),
    ('/sendMessage', SendMessagePage),
    ('/editMessageText', EditMessageTextPage),
    ('/editMessageReplyMarkup', EditMessageReplyMarkupPage),
], debug=True)

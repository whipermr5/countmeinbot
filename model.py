"""Datastore entity models"""

from collections import OrderedDict

import util

from google.appengine.ext import ndb
from telegram import InlineKeyboardMarkup, InlineKeyboardButton

class User(ndb.Model):
    first_name = ndb.TextProperty()
    last_name = ndb.TextProperty()
    username = ndb.StringProperty(indexed=False)

    created = ndb.DateTimeProperty(auto_now_add=True)
    updated = ndb.DateTimeProperty(auto_now=True, indexed=False)

    @classmethod
    def populate_by_id(cls, id, **kwargs):  # pylint: disable=redefined-builtin, invalid-name
    # ignore warnings due to argument named "id" for consistency with similar ndb methods
        entity = cls.get_by_id(id) or cls(id=id)
        entity.populate(**kwargs)
        entity.put()

    def get_description(self):
        output = u'{}'.format(self.first_name)
        if self.last_name:
            output += u' {}'.format(self.last_name)
        if self.username:
            output += u' (@{})'.format(self.username)
        return output

class Respondent(User):
    username = ndb.StringProperty(indexed=True)
    updated = ndb.DateTimeProperty(auto_now=True, indexed=True)

class Poll(ndb.Model):
    admin_uid = ndb.StringProperty()
    title = ndb.TextProperty()
    title_short = ndb.StringProperty()
    active = ndb.BooleanProperty(default=True)
    multi = ndb.BooleanProperty(default=True, indexed=False)

    options = ndb.PickleProperty(repeated=True)

    created = ndb.DateTimeProperty(auto_now_add=True)
    updated = ndb.DateTimeProperty(auto_now=True, indexed=False)

    @classmethod
    def new(cls, admin_uid, title):
        title_short = util.uslice(title, 0, 512).lower()
        return cls(admin_uid=admin_uid, title=title, title_short=title_short)

    @staticmethod
    @ndb.transactional
    def toggle(poll_id, opt_id, uid, user_profile):
        poll = Poll.get_by_id(poll_id)
        if not poll:
            return None, 'Sorry, this poll has been deleted'
        if opt_id >= len(poll.options):
            return None, 'Sorry, that\'s an invalid option'
        status = poll.options[opt_id].toggle(uid, user_profile)
        poll.put()
        return poll, status

    def get_friendly_id(self):
        return util.uslice(self.title, 0, 512)

    def generate_options_summary(self):
        return u' / '.join([option.title for option in self.options])

    def generate_respondents_summary(self):
        all_uids_by_option = [option.people.keys() for option in self.options]
        all_uids = util.flatten(all_uids_by_option)
        num_respondents = len(set(all_uids))
        if num_respondents == 0:
            output = 'Nobody responded'
        elif num_respondents == 1:
            output = '1 person responded'
        else:
            output = '{} people responded'.format(num_respondents)
        return output

    def generate_poll_summary_with_link(self):
        short_bold_title = util.make_html_bold(util.uslice(self.title, 0, 65))
        respondents_summary = self.generate_respondents_summary()
        link = '/view_{}'.format(self.key.id())
        return u'{} {}.\n{}'.format(short_bold_title, respondents_summary, link)

    def render_text(self):
        header = [util.make_html_bold_first_line(self.title)]
        body = [option.render_text() for option in self.options]
        footer = [u'\U0001f465 ' + self.generate_respondents_summary()]
        return u'\n\n'.join(header + body + footer)

    def render_html(self):
        from datetime import timedelta

        user = User.get_by_id(int(self.admin_uid))
        user_description = user.get_description() if user else 'unknown ({})'.format(self.admin_uid)
        timestamp = (self.created + timedelta(hours=8)).strftime('%a, %d %b \'%y, %H:%M:%S')
        details = u' <small>by {} on {}</small>'.format(user_description, timestamp)

        text = self.render_text()
        idx = text.find('\n')
        text = (text[:idx] + details + text[idx:])

        return '<p>' + text.replace('\n', '<br>\n') + '</p>'

    def build_vote_buttons(self, admin=False):
        poll_id = self.key.id()
        buttons = []
        for i, option in enumerate(self.options):
            data = '{} {}'.format(poll_id, i)
            button = InlineKeyboardButton(option.title, callback_data=data)
            buttons.append([button])
        if admin:
            back_data = '{} back'.format(poll_id)
            back_button = InlineKeyboardButton('Back', callback_data=back_data)
            buttons.append([back_button])
        return InlineKeyboardMarkup(buttons).to_dict()

    def build_admin_buttons(self):
        poll_id = self.key.id()
        insert_key = self.get_friendly_id().encode('utf-8')
        publish_button = InlineKeyboardButton('Publish poll', switch_inline_query=insert_key)
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

    def toggle(self, uid, user_profile):
        uid = str(uid)
        if self.people.get(uid):
            self.people.pop(uid, None)
            action = u'removed from'
        else:
            self.people[uid] = user_profile['first_name'], user_profile['last_name']
            action = u'added to'
        return u'Your name was {} {}!'.format(action, self.title)

    def render_text(self):
        title = util.make_html_bold(self.title) + "|  Number of Votes: " + str(len(people))
        name_list = util.strip_html_symbols(self.generate_name_list())
        return title + '\n' + name_list

    def generate_name_list(self):
        return '\n'.join([first_name for first_name, _ in self.people.values()])

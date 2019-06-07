"""Handles all calls to Telegram Bot API"""

import logging
import json

from secrets import BOT_TOKEN

import webapp2
import telegram
from google.appengine.api import taskqueue

class TelegramPage(webapp2.RequestHandler):
    RECOGNISED_ERRORS = ['u\'Bad Request: message is not modified\'',
                         'u\'Bad Request: message to edit not found\'',
                         'u\'Bad Request: MESSAGE_ID_INVALID\'',
                         'Message is not modified: specified new message content and reply markup are exactly the same as a current content and reply markup of the message',
                         'Message to edit not found',
                         'Message_id_invalid']
    RECOGNISED_ERROR_URLFETCH = 'urlfetch.Fetch()'

    bot = telegram.Bot(token=BOT_TOKEN)

    def post(self, method_name):
        logging.debug(self.request.body)

        kwargs = json.loads(self.request.body)
        getattr(self.bot, method_name)(**kwargs)

        logging.info('Success!')

    def handle_exception(self, exception, debug):
        if isinstance(exception, telegram.error.NetworkError):
            if str(exception) in self.RECOGNISED_ERRORS:
                logging.info(exception)
                return

            logging.warning(exception)

        elif isinstance(exception, telegram.error.Unauthorized):
            logging.info(exception)
            return

        elif isinstance(exception, telegram.error.RetryAfter):
            logging.warning(exception)

        elif self.RECOGNISED_ERROR_URLFETCH in str(exception):
            logging.warning(exception)

        else:
            logging.error(exception)

        self.abort(500)

def parse_update(payload):
    return telegram.Update.de_json(json.loads(payload), None)

def api_call(method_name, countdown=0, **kwargs):
    payload = json.dumps(kwargs)
    taskqueue.add(queue_name='outbox', url='/telegram/' + method_name, payload=payload,
                  countdown=countdown)
    countdown_details = ' (countdown {}s)'.format(countdown) if countdown else ''
    logging.info('Request queued: ' + method_name + countdown_details)
    logging.debug(payload)

def send_message(countdown=0, **kwargs):
    return api_call('send_message', countdown=countdown, **kwargs)

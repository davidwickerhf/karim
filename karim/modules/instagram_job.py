from os import error
from instaclient.errors.common import BlockedAccountError, InvaildPasswordError, InvalidUserError, NotLoggedInError, RestrictedAccountError, SuspisciousLoginAttemptError, VerificationCodeNecessary
from telethon.client import buttons
from telethon.client.telegramclient import TelegramClient
from telethon.sessions.string import StringSession
from karim.classes.mq_bot import MQBot
from karim.classes.callbacks import ScrapeStates
from karim.classes.scraper import Scraper
from karim.classes.forwarder import Forwarder
from karim.classes.insta_session import InstaSession
from karim.classes.forwarder_markup import CreateMarkup
from karim.secrets import secrets
from karim.modules import sheet
from karim import instaclient_error_callback, queue, BOT_TOKEN
from karim.bot.texts import *

from telethon.tl.types import KeyboardButtonUrl
from telegram.inline.inlinekeyboardbutton import InlineKeyboardButton
from telegram.inline.inlinekeyboardmarkup import InlineKeyboardMarkup
from telegram import ParseMode
from rq.job import Job, Retry
from rq.registry import DeferredJobRegistry, FailedJobRegistry, StartedJobRegistry, FinishedJobRegistry
import time, random, string, redis, os
from datetime import datetime
from instaclient import InstaClient

SCRAPE = 'scrape'
CHECKSCRAPE = 'checkscrape'
DM = 'dm'
CHECKDM = 'checkdm'

def random_string():
    letters_and_digits = string.ascii_letters + string.digits
    result_str = ''.join((random.choice(letters_and_digits) for i in range(6)))
    return result_str


def check_job_queue(obj: Scraper or Forwarder, telegram_bot:MQBot):
    """
    Checks if any launch_scrape or launch_send_dm jobs are in the RQ Queue. If that's the case, sends a message to the user informing that another job is in the queue and that the newly requested job will be executed later.

    Args:
        obj (ScraperorForwarder): The object to get the `chat_id` from
        telegram_bot (MQbot): Bot to use to send messages
    """
    # Check if no other job is in queue
    registry = StartedJobRegistry(queue=queue)
    for job_id in registry.get_job_ids():
        if 'launch_scrape' in job_id:
            text = scrape_job_in_queue_text
            telegram_bot.send_message(chat_id=obj.chat_id, text=text)
        elif 'launch_send_dm' in job_id:
            text = dm_job_in_queue_text
            telegram_bot.send_message(chat_id=obj.chat_id, text=text)


def process_update_callback(obj: Scraper or Forwarder, message:str, message_id:int=None):
    """
    process_update_callback sends an update message to the user, to inform of the status of the current process. This method can be used as a callback in another method.

    Args:
        obj (ScraperorForwarder): Object to get the `chat_id` and `message_id` from.
        message (str): The text to send via message
        message_id (int, optional): If this argument is defined, then the method will try to edit the message matching the `message_id` of the `obj`. Defaults to None.
    """
    from karim import telegram_bot as bot
    if message_id:
        try:
            bot.edit_message_text(text=message, chat_id=obj.chat_id, message_id=obj.get_message_id(), parse_mode=ParseMode.HTML)
            return
        except: pass
    bot.send_message(obj.chat_id, text=message, parse_mode=ParseMode.HTML)
    return


# SCRAPE JOB HANDLER ----------------------------------------------------------------------------
def launch_scrape(target:str, scraper:Scraper, telegram_bot:MQBot):
    """
    Add scrape job to the Worker queue. 
    
    This method abstracts the process of enqueing scrape jobs. It enqueues a method which takes care of enqueing the scrape jobs and returning a response. This makes it possible to add the `queue_scrape()` method to the Worker queue, hence it allows for it to run in the background.

    Args:
        target (str): Username of the instagram user to scrape from
        scraper (Scraper): Scraper object used to initialize the scrape
        telegram_bot (MQbot): Bot to use to send messages
    """
    
    # Check if other jobs are in queue
    check_job_queue(scraper, telegram_bot)

    # COMPILE SCRAPE
    # Add scrape job
    identifier = random_string()
    scrape_id = '{}:{}:{}'.format(SCRAPE, target, identifier)
    job = Job.create(scrape_job, kwargs={'user': target, 'scraper': scraper}, id=scrape_id, timeout=3600, ttl=None, connection=queue.connection)
    queue.enqueue_job(job)
    # Add checker job
    checker_id = '{}:{}:{}'.format(CHECKSCRAPE, target, identifier)
    job = Job.create(send_dm_job, kwargs={'scrape_id': scrape_id, 'scraper': scraper}, id=checker_id, timeout=380, ttl=None, connection=queue.connection)
    queue.enqueue_job(job)

 
def scrape_job(user:str, scraper:Scraper):
    print('scrape_job()')
    try:
        instasession = InstaSession(scraper.chat_id, scraper.user_id, scraper.message_id)
        if instasession.get_creds():
            instaclient:InstaClient = InstaClient(host_type=InstaClient.WEB_SERVER, error_callback=instaclient_error_callback, debug=True)
            process_update_callback(scraper, logging_in_with_credentials_text, scraper.get_message_id())
            instaclient.login(instasession.username, instasession.password, check_user=False)
            time.sleep(1)
            process_update_callback(scraper, initiating_scrape_text.format(user, user))
            followers = instaclient.scrape_followers(user=user, discard_driver=True)
            return followers
        else:
            return None
    except Exception as error:
        raise error


def check_scrape_job(scrape_id:str, scraper:Scraper):
    from karim import telegram_bot as bot
    failed = FailedJobRegistry(queue=queue)

    if scrape_id in failed.get_job_ids():
        # job failed
        bot.send_message(scraper.get_user_id(), failed_scraping_ig_text)
        sheet.log(datetime.utcnow(), scraper.get_user_id(), action='FAILED SCRAPE')
        return False
    else:
        redis_url = os.getenv('REDISTOGO_URL', 'redis://localhost:6379')
        conn = redis.from_url(redis_url)
        job = Job.fetch(scrape_id, connection=conn)
        result = job.result

        # Save result in sheets
        sheet.add_scrape(scraper.get_target(), name=scraper.get_name(), scraped=result)
        sheet.log(datetime.utcnow(), scraper.get_user_id(), action='SUCCESSFUL SCRAPE')
        # Update user
        markup = InlineKeyboardMarkup([[InlineKeyboardButton(text='Google Sheets', url=sheet.get_sheet_url(1))]])
        bot.send_message(scraper.get_user_id(), finished_scrape_text, reply_markup=markup)
        return True


# SEND DM JOB HANDLER -------------------------------------------------------------------------
def launch_send_dm(targets:list, message:str, forwarder:Forwarder, telegram_bot:MQBot):
    """
    launch_send_dm Adds send DMs jobs to the Worker queue.

    This method abstracts the process of enqueing send_dm jobs. It enqueues a method which takes care of enqueing the send_dm jobs and returning a response. This makes it possible to add the `queue_send_dm()` method to the Worker queue, hence it allows for it to run in the background.

    Args:
        targets (list): List of instagram usernames
        message (str): Message to send to the users
        forwarder (Forwarder): Forwarder object used to initialize the operation
        telegram_bot (MQbot): Bot to use to send messages
    """
    
    # Check if no other job is in queue
    check_job_queue(forwarder, telegram_bot)

    # Enqueues jobs
    identifier = random_string()
    instasession = InstaSession(forwarder.chat_id, forwarder.user_id)
    instasession.get_creds()
    

    if instasession.username in targets:
        targets.remove(instasession.username)

    for index, target in enumerate(targets):
        if target != instasession.username:
            job = Job.create(send_dm_job, kwargs={'index': index, 'count': len(targets), 'user': target, 'message': message, 'forwarder': forwarder}, id='{}:{}:{}'.format(DM, target, identifier), timeout=380, ttl=None, connection=queue.connection)
            queue.enqueue_job(job)
            print('TELEBOT: Enequeued DM Job: ', target)
    # Enqueue check job
    job = Job.create(check_dm_job, kwargs={'identifier': identifier, 'forwarder': forwarder}, id='{}:{}'.format(CHECKDM, identifier), timeout=380, ttl=None, connection=queue.connection)
    queue.enqueue_job(job)


def send_dm_job(index:int, count:int, user:str, message:str, forwarder:Forwarder):
    print('TELEBOT: Send DM Job {} Initiated'.format(index+1))
    instasession = InstaSession(forwarder.chat_id, forwarder.user_id)
    process_update_callback(forwarder, processing_dm_job.format(index+1), forwarder.get_message_id())
    print('TELEBOT: Message: ', message)
    if instasession.get_creds():
        instaclient = InstaClient(host_type=InstaClient.WEB_SERVER, error_callback=instaclient_error_callback, debug=True)
        try:
            instaclient.login(instasession.username, instasession.password)
        except (InvaildPasswordError, InvalidUserError) as error:
            print('TELEBOT: IG Credentials Incorrect')
            process_update_callback(forwarder, incorrect_credentials_error.format(index), forwarder.get_message_id())
            remove_jobs()
            raise error

        try:
            instaclient.send_dm(user=user, message=message, discard_driver=True)
        except SuspisciousLoginAttemptError as error:
            print('TELEBOT: Suspicious Login Attempt')
            process_update_callback(forwarder, suspicious_login.format(index), forwarder.get_message_id())
            remove_jobs()
            raise error

        except VerificationCodeNecessary as error:
            print('TELEBOT: Verification Code Necessary. Turn it off')
            process_update_callback(forwarder, verification_necessary.format(index), forwarder.get_message_id())
            remove_jobs()
            raise error

        except RestrictedAccountError as error:
            print('TELEBOT: Account is restricted')
            process_update_callback(forwarder, restricted_account.format(index), forwarder.get_message_id())
            remove_jobs()
            raise error

        except BlockedAccountError as error:
            print('TELEBOT: Account is blocked')
            process_update_callback(forwarder, blocked_account.format(index), forwarder.get_message_id())
            remove_jobs()
            raise error
        
        if index < count-1:
            process_update_callback(forwarder, dm_job_complete_waiting.format(index+1), forwarder.get_message_id())
            print('TELEBOT: Sleeping 25->60 seconds')
            time.sleep(random.randrange(25, 60))
        else:
            print('TELEBOT: Finished running DM jobs...')
        return True
    else:
        raise NotLoggedInError()


def remove_jobs():
    queue.empty()
    print('TELEBOT: Queue Emptied')
    

def check_dm_job(identifier:str, forwarder:Forwarder):
    print('TELEBOT: Check DM Job Initiated')
    from karim import telegram_bot as bot
    failed = FailedJobRegistry(queue=queue)

    count = 0
    for id in failed.get_job_ids():
        if identifier in id and DM in id:
            count += 1

    bot.send_message(forwarder.get_user_id(), finished_sending_dm_text.format(count))
    return True
from instaclient.errors.common import InvaildPasswordError, InvalidSecurityCodeError, InvalidUserError, PrivateAccountError, SecurityCodeNecessary
from karim.bot.commands import *
from karim import instaclient

@run_async
@send_typing_action
def ig_login(update, context):
    if not check_auth(update, context):
        return ConversationHandler.END

    # Check IG status    
    instasession:InstaSession = InstaSession(update.effective_chat.id, update.effective_user.id)
    markup = CreateMarkup({Callbacks.CANCEL: 'Cancel'}).create_markup()
    message = update.effective_chat.send_message(text=checking_ig_status)
    instasession.set_message(message.message_id)
    result = instaclient.check_status()
    if result:
        # Account is already logged in
        context.bot.edit_message_text(text=user_logged_in_text, chat_id=instasession.chat_id, message_id=message.message_id)
        return ConversationHandler.END

    else:
        # Check if account is already registered
        response = instasession.get_creds()
        if response:
            # Creds Exist, attempt login
            try:
                instaclient.login(instasession.username, instasession.password)
            except SecurityCodeNecessary:
                # Creds are correct
                context.bot.edit_message_text(text=input_security_code_text, chat_id=instaclient.chat_id, message_id=instaclient.message_id, reply_markup=markup)
                return InstaStates.INPUT_SECURITY_CODE
            except (InvalidUserError, InvaildPasswordError):
                # Credentials incorrect, continue login procedure as normal
                pass

        # Request Username
        context.bot.edit_message_text(text=input_ig_username_text, chat_id=instasession.chat_id, message_id=message.message_id, reply_markup=markup)
        return InstaStates.INPUT_USERNAME

    
@run_async
@send_typing_action
def instagram_username(update, context):
    instasession:InstaSession = InstaSession.deserialize(Persistence.INSASESSION, update)
    if not instasession:
        return InstaStates.INPUT_USERNAME
    
    username = update.message.text 
    message = update.message.reply_text(text=checking_user_vadility_text)
    instasession.set_message(message.message_id)
    markup = CreateMarkup({Callbacks.CANCEL: 'Cancel'}).create_markup()
    # Verify User
    try:
        instaclient.is_valid_user(username)
    except InvalidUserError as error:
        context.bot.edit_message_text(text=invalid_user_text.format(error.username), chat_id=update.effective_chat.id, message_id=instasession.message_id, reply_markup=markup)
        instasession.set_message(message.message_id)
        return InstaStates.INPUT_USERNAME
    except PrivateAccountError as error:
        pass
    instasession.set_username(username)
    # Request Password
    context.bot.edit_message_text(text=input_password_text, chat_id=update.effective_chat.id, message_id=instasession.message_id, reply_markup=markup)
    return InstaStates.INPUT_PASSWORD


@run_async
@send_typing_action
def instagram_password(update, context):
    instasession:InstaSession = InstaSession.deserialize(Persistence.INSASESSION, update)
    if not instasession:
        return InstaStates.INPUT_PASSWORD

    markup = CreateMarkup({Callbacks.CANCEL: 'Cancel'}).create_markup()
    password = update.message.text
    instasession.set_password(password)
    message = update.effective_chat.send_message(text=attempting_login_text)
    instasession.set_message(message.message_id)
    # Attempt login
    try:
        instaclient.login(instasession.username, instasession.password, check_user=False)
    except InvaildPasswordError:
        context.bot.edit_message_text(text=invalid_password_text.format(instaclient.password), chat_id=instaclient.chat_id, message_id=instaclient.message_id, reply_markup=markup)
        return InstaStates.INPUT_PASSWORD
    except SecurityCodeNecessary:
        context.bot.edit_message_text(text=input_security_code_text, chat_id=instaclient.chat_id, message_id=instaclient.message_id, reply_markup=markup)
        return InstaStates.INPUT_SECURITY_CODE

    # Login Successful
    instasession.save_creds()
    context.bot.edit_message_text(text=login_successful_text, chat_id=instaclient.chat_id, message_id=instaclient.message_id)
    instasession.discard()
    return ConversationHandler.END


@run_async
@send_typing_action
def instagram_security_code(update, context):
    instasession:InstaSession = InstaSession.deserialize(Persistence.INSASESSION, update)
    if not instasession:
        return InstaStates.INPUT_SECURITY_CODE

    markup = CreateMarkup({Callbacks.CANCEL: 'Cancel'}).create_markup()
    code = update.message.text
    message = update.effective_chat.send_message(text=validating_code_text, reply_markup=markup)
    instasession.set_code(code)
    instasession.set_message(message.message_id)

    try:
        instaclient.input_security_code(code)
    except InvalidSecurityCodeError:
        context.bot.edit_message_text(text=invalid_security_code_text.format(code), chat_id=instaclient.chat_id, message_id=instaclient.message_id, reply_markup=markup)
        return InstaStates.INPUT_SECURITY_CODE

    # Login Successful
    instasession.save_creds()
    context.bot.edit_message_text(text=login_successful_text, chat_id=instaclient.chat_id, message_id=instaclient.message_id)
    instasession.discard()
    return ConversationHandler.END


@run_async
@send_typing_action
def cancel_instagram(update, context, instasession:InstaSession=None):
    if not instasession:
        instasession = InstaSession.deserialize(Persistence.INSASESSION, update)
        if not instasession:
            return

    try:
        update.callback_query.edit_message_text(text=cancelled_instagram_text)
    except:
        try:
            context.bot.edit_message_text(chat_id=instasession.chat_id, message_id=instasession.message_id, text=cancelled_instagram_text)
        except:
            update.effective_chat.send_message(text=cancelled_instagram_text)
    instasession.discard()
    return ConversationHandler.END

    
    






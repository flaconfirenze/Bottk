import logging
import aiohttp
import json
import os
from telegram import Update, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
)
from enum import Enum
import re
from fastapi import FastAPI, Request

# Define conversation states using Enum for better readability
class ConversationStates(Enum):
    MAIN_MENU = 0
    LOGIN_ND = 1
    LOGIN_PASSWORD = 2
    ND_FACT_INPUT = 3
    VOUCHER_ND_INPUT = 4
    VOUCHER_CODE_INPUT = 5
    GET_NCLI_INPUT = 6
    REGISTER_ND_INPUT = 7
    REGISTER_NCLI_INPUT = 8
    REGISTER_MOBILE_INPUT = 9
    REGISTER_EMAIL_INPUT = 10
    REGISTER_PASSWORD1_INPUT = 11
    REGISTER_PASSWORD2_INPUT = 12
    REGISTER_OTP_INPUT = 13
    VOUCHER_LTE_ND_INPUT = 14
    VOUCHER_LTE_CODE_INPUT = 15

# Configuration
API_URL = "https://mobile-pre.at.dz/api"
PAIEMENT_URL = "https://paiement.algerietelecom.dz/AndroidApp/dette_paiement.php"

# 🔒 Directly assign your Telegram Bot Token here
TOKEN = '7829306127:AAEAKk_hdrTVNn7ehzPEp7iAc_wcIYWqAgc'  # Replace with your actual Telegram Bot Token

# Logging configuration
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Regex patterns for input validation
PHONE_PATTERN = re.compile(r"^0\d{9}$")  # Algerian phone numbers starting with 0 followed by 9 digits
EMAIL_PATTERN = re.compile(r"^[\w\.-]+@[\w\.-]+\.\w+$")
VOUCHER_PATTERN = re.compile(r"^\d{16}$")
OTP_PATTERN = re.compile(r"^\d{6}$")

# Separate function to retrieve ncli
async def retrieve_ncli(nd: str) -> str:
    """
    Retrieves the ncli by making a POST request to the paiement URL.

    Args:
        nd (str): The phone number (nd) to retrieve the ncli for.

    Returns:
        str: The ncli retrieved from the response.
    """
    paiement_url = PAIEMENT_URL
    payload = f"ndco20={nd}&validerco20=Confirmer&nfactco20=&"

    headers = {
        "Authorization": "Basic VEdkNzJyOTozUjcjd2FiRHNfSGpDNzg3IQ==",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 10; M2004J19C MIUI/V12.0.4.0.QJCMIXM)",
        "Host": "paiement.algerietelecom.dz",
        "Connection": "Keep-Alive",
        "Accept-Encoding": "gzip",
    }

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(paiement_url, data=payload, headers=headers) as response:
                if response.status == 200:
                    text_response = await response.text()
                    # Remove BOM if present
                    clean_text = text_response.lstrip('\ufeff').strip()

                    try:
                        json_response = json.loads(clean_text)
                        logger.info("Successfully retrieved ncli.")

                        if json_response.get("succes") == 1:
                            ncli = json_response.get("ncli", "غير متوفر")
                            return ncli
                        else:
                            error_code = json_response.get("succes", "غير معروف")
                            logger.error(f"Failed to retrieve ncli. Error Code: {error_code}")
                            raise Exception(f"فشل في استرجاع رقم الزبون. رمز الخطأ: {error_code}")

                    except json.JSONDecodeError:
                        logger.error(f"Failed to parse JSON response: {clean_text}")
                        raise Exception("تلقى استجابة غير صالحة من الخادم.")
                else:
                    logger.error(f"Failed to retrieve ncli. Status Code: {response.status}")
                    raise Exception(f"فشل في استرجاع ncli. كود الحالة: {response.status}")
        except Exception as e:
            logger.error(f"Error during ncli retrieval: {str(e)}")
            raise

# Formatting functions
async def format_account_info(data: dict) -> str:
    """Formats account information for display."""
    return (
        "📊 معلومات الحساب:\n\n"
        f"👤 الاسم: {data.get('prenom', '')} {data.get('nom', '')}\n"
        f"📱 رقم الهاتف: {data.get('nd', '')}\n"
        f"🏠 العنوان: {data.get('adresse', '')}\n"
        f"📡 العرض: {data.get('offre', '')}\n"
        f"⚡ السرعة: {data.get('speed', '')} Mbps\n"
        f"💲 رصيدالهاتف: {data.get('credit', '0')} DA\n"
        f"💰 عدد الأيام المتبقية: {data.get('balance', '0')} يوم\n"
        f"📅 تاريخ الانتهاء: {data.get('dateexp', '')}\n"
        f"📞 الهاتف المحمول: {data.get('mobile', '')}\n"
        f"📧 البريد الإلكتروني: {data.get('email', '')}\n"
        f"🆔 رقم الزبون: {data.get('ncli', '')}\n"
        f"📊 الحالة: {data.get('status', '')}\n"
        f"💫 النوع: {data.get('type1', '')}"
    )

async def format_nd_fact_info(data: dict) -> str:
    """Formats ND Fact information for display in Arabic."""
    return (
        "📊 الفواتير الخاصة بكم:\n\n"
        f"📱 الرقم: {data.get('INFO', {}).get('nd', '')}\n"
        f"💲 المبلغ: {data.get('INFO', {}).get('credit', '0')} DA"
    )

async def format_voucher_response(response: dict) -> str:
    """Formats voucher response for display in Arabic."""
    code = response.get('code', '')
    message = response.get('message', '')
    if code == "0":
        return f"✅ تم شحن الرصيد بنجاح!\n🔢 الكود: {message}"
    else:
        return f"❌ فشل في شحن الرصيد.\nرمز الخطأ: {code}\nالرسالة: {message}"

async def format_ncli_response(ncli: str) -> str:
    """
    Formats the ncli for display.

    Args:
        ncli (str): The ncli retrieved.

    Returns:
        str: A formatted string to be sent to the user.
    """
    return f"🆔 رقم الزبون: {ncli}"  # Updated label

async def format_register_response(response: dict) -> str:
    """Formats the registration response for display in Arabic."""
    if response.get("code") in ["0", "1", "5"]:  # Assuming "5" indicates account created successfully
        return "✅ تم التسجيل بنجاح! يرجى إدخال رمز التحقق (OTP) الذي تلقيته لتأكيد التسجيل."
    else:
        message = response.get("message", "❌ فشل في التسجيل.")
        return f"❌ {message}"

async def format_confirm_register_response(response: dict) -> str:
    """
    Formats the confirmation registration response for display.

    Args:
        response (dict): The JSON response from the confirmRegister API.

    Returns:
        str: A formatted string message.
    """
    if response.get("meta_data", {}).get("original", {}).get("token"):
        return "✅ تم تأكيد التسجيل بنجاح! يمكنك الآن تسجيل الدخول باستخدام خيار تسجيل الدخول."
    else:
        message = response.get("message", "❌ فشل تأكيد التسجيل. يرجى المحاولة مرة أخرى.")
        return f"❌ {message}"

# Handler functions
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info("Received /start command.")
    welcome_message = (
        "👋 مرحبًا بك في بوت الجزائر تيليكوم!\n\n"
        "يرجى اختيار أحد الخيارات التالية:"
    )
    keyboard = [
        [InlineKeyboardButton("تسجيل", callback_data="register")],
        [InlineKeyboardButton("تسجيل الدخول", callback_data="login")],
        [InlineKeyboardButton("تحقق من الفواتير", callback_data="nd_fact")],
        [InlineKeyboardButton("شحن adsl عبر القسيمة", callback_data="recharge_voucher")],
        [InlineKeyboardButton("شحن LTE عبر القسيمة", callback_data="recharge_voucher_lte")],
        [InlineKeyboardButton("الحصول على رقم الزبون", callback_data="get_ncli")],

    ]
    await update.message.reply_text(welcome_message, reply_markup=InlineKeyboardMarkup(keyboard))
    return ConversationStates.MAIN_MENU.value

async def login_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info("Login option selected.")
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("يرجى إدخال رقم الهاتف الخاص بك:")
    return ConversationStates.LOGIN_ND.value

async def nd_fact_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info("Check Bills option selected.")
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("يرجى إدخال رقم الهاتف للتحقق من الفواتير:")
    return ConversationStates.ND_FACT_INPUT.value

async def recharge_voucher_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info("Recharge via Voucher option selected.")
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("يرجى إدخال رقم الهاتف:")
    return ConversationStates.VOUCHER_ND_INPUT.value

async def recharge_voucher_lte_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info("Recharge LTE via Voucher option selected.")
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("يرجى إدخال رقم الهاتف المحمول (ND):")
    return ConversationStates.VOUCHER_LTE_ND_INPUT.value

async def get_ncli_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info("Get Customer Number option selected.")
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("يرجى إدخال رقم الهاتف لاسترجاع رقم الزبون:")
    return ConversationStates.GET_NCLI_INPUT.value

async def register_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info("Register option selected.")
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("يرجى إدخال رقم الهاتف:")
    return ConversationStates.REGISTER_ND_INPUT.value

async def register_nd_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info("Received ND for registration.")
    nd = update.message.text.strip()

    if not nd.isdigit():
        await update.message.reply_text("⚠️ يرجى إدخال رقم هاتف صالح مكون من أرقام فقط.")
        return ConversationStates.REGISTER_ND_INPUT.value

    context.user_data['register_nd'] = nd
    await update.message.reply_text("يرجى إدخال رقم الزبون (NCLI):")
    return ConversationStates.REGISTER_NCLI_INPUT.value

async def register_ncli_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info("Received NCLI for registration.")
    ncli = update.message.text.strip()

    if not ncli.isdigit():
        await update.message.reply_text("⚠️ يرجى إدخال رقم الزبون (NCLI) صالح مكون من أرقام فقط.")
        return ConversationStates.REGISTER_NCLI_INPUT.value

    context.user_data['register_ncli'] = ncli
    await update.message.reply_text("يرجى إدخال رقم الهاتف المحمول:")
    return ConversationStates.REGISTER_MOBILE_INPUT.value

async def register_mobile_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info("Received mobile number for registration.")
    mobile = update.message.text.strip()

    if not PHONE_PATTERN.match(mobile):
        await update.message.reply_text("⚠️ يرجى إدخال رقم هاتف محمول صالح مكون من 10 أرقام ويبدأ بـ 0.")
        return ConversationStates.REGISTER_MOBILE_INPUT.value

    context.user_data['register_mobile'] = mobile
    await update.message.reply_text("يرجى إدخال عنوان البريد الإلكتروني:")
    return ConversationStates.REGISTER_EMAIL_INPUT.value

async def register_email_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info("Received email for registration.")
    email = update.message.text.strip()

    if not EMAIL_PATTERN.match(email):
        await update.message.reply_text("⚠️ يرجى إدخال عنوان بريد إلكتروني صالح.")
        return ConversationStates.REGISTER_EMAIL_INPUT.value

    context.user_data['register_email'] = email
    await update.message.reply_text("يرجى إدخال كلمة المرور (على الأقل 8 أحرف):")
    return ConversationStates.REGISTER_PASSWORD1_INPUT.value

async def register_password1_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info("Received first password input for registration.")
    password1 = update.message.text.strip()

    if len(password1) < 8:
        await update.message.reply_text("⚠️ يجب أن تكون كلمة المرور مكونة من 8 أحرف على الأقل.")
        return ConversationStates.REGISTER_PASSWORD1_INPUT.value

    context.user_data['register_password1'] = password1
    await update.message.reply_text("يرجى إعادة إدخال كلمة المرور للتأكيد:")
    return ConversationStates.REGISTER_PASSWORD2_INPUT.value

async def register_password2_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info("Received second password input for registration.")
    password2 = update.message.text.strip()
    password1 = context.user_data.get('register_password1')

    if password2 != password1:
        await update.message.reply_text("⚠️ كلمات المرور غير متطابقة. يرجى إعادة إدخال كلمة المرور:")
        return ConversationStates.REGISTER_PASSWORD1_INPUT.value

    # Gather all registration data
    registration_data = {
        "nd": context.user_data.get('register_nd'),
        "ncli": context.user_data.get('register_ncli'),
        "mobile": context.user_data.get('register_mobile'),
        "email": context.user_data.get('register_email'),
        "password1": password1,
        "password2": password2,
        "lang": "fr"
    }

    async with APIClient(API_URL, PAIEMENT_URL) as api_client:
        try:
            response = await api_client.register(registration_data)
            info_text = await format_register_response(response)

            if response.get("code") == "5":
                # Registration successful, prompt for OTP
                await update.message.reply_text(
                    "✅ تم إنشاء الحساب بنجاح! يرجى إدخال رمز التحقق (OTP) الذي تلقيته لتأكيد التسجيل:"
                )
                return ConversationStates.REGISTER_OTP_INPUT.value
            else:
                # Handle other response codes if necessary
                keyboard = [
                    [InlineKeyboardButton("العودة إلى القائمة الرئيسية", callback_data="main_menu")],
                ]
                await update.message.reply_text(
                    info_text,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return ConversationStates.MAIN_MENU.value
        except Exception as e:
            logger.error(f"Registration error: {str(e)}")
            await update.message.reply_text(
                "❌ حدث خطأ أثناء عملية التسجيل. يرجى المحاولة مرة أخرى لاحقًا."
            )
            return ConversationHandler.END

async def register_otp_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info("Received OTP for registration confirmation.")
    otp = update.message.text.strip()
    nd = context.user_data.get('register_nd')

    if not OTP_PATTERN.match(otp):
        await update.message.reply_text("⚠️ يرجى إدخال رمز التحقق (OTP) المكون من 6 أرقام:")
        return ConversationStates.REGISTER_OTP_INPUT.value

    async with APIClient(API_URL, PAIEMENT_URL) as api_client:
        try:
            confirmation_data = {
                "nd": nd,
                "otp": otp
            }
            response = await api_client.confirm_register(confirmation_data)
            info_text = await format_confirm_register_response(response)

            if response.get("meta_data", {}).get("original", {}).get("token"):
                # Save token and user info for the session
                token = response["meta_data"]["original"]["token"]
                user_info = response["data"]["original"]

                context.user_data['token'] = token
                context.user_data['user_info'] = user_info

                # Optionally, retrieve additional account info
                account_info = await api_client.get_account_info(token)
                context.user_data['account_info'] = account_info

                main_menu_text = (
                    "✅ تم تأكيد التسجيل بنجاح! يمكنك الآن تسجيل الدخول باستخدام خيار تسجيل الدخول."
                )
                keyboard = [
                    [InlineKeyboardButton("تسجيل الدخول", callback_data="login")],
                    [InlineKeyboardButton("العودة إلى القائمة الرئيسية", callback_data="main_menu")],
                ]
                await update.message.reply_text(
                    main_menu_text,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return ConversationStates.MAIN_MENU.value
            else:
                # Handle cases where token is not present
                error_message = response.get("message", "❌ فشل تأكيد التسجيل. يرجى التحقق من رمز التحقق (OTP) والمحاولة مرة أخرى.")
                await update.message.reply_text(
                    f"❌ {error_message}"
                )
                return ConversationStates.REGISTER_OTP_INPUT.value

        except Exception as e:
            logger.error(f"OTP confirmation error: {str(e)}")
            await update.message.reply_text(
                "❌ حدث خطأ أثناء تأكيد التسجيل. يرجى المحاولة مرة أخرى لاحقًا."
            )
            return ConversationHandler.END

async def login_nd_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info("Received ND for login.")
    nd = update.message.text.strip()

    if not nd.isdigit():
        await update.message.reply_text("⚠️ يرجى إدخال رقم هاتف صالح مكون من أرقام فقط.")
        return ConversationStates.LOGIN_ND.value

    context.user_data['nd'] = nd
    await update.message.reply_text("يرجى إدخال كلمة المرور:")
    return ConversationStates.LOGIN_PASSWORD.value

async def login_password_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info("Received password for login.")
    try:
        # Note: Telegram bots cannot delete user messages in private chats, so this might fail
        await update.message.delete()
    except Exception:
        pass

    nd = context.user_data.get('nd')
    password = update.message.text

    async with APIClient(API_URL, PAIEMENT_URL) as api_client:
        try:
            response = await api_client.login(nd, password)

            token = response.get("meta_data", {}).get("original", {}).get("token")
            if token:
                user_data = response["data"]["original"]
                context.user_data['token'] = token
                context.user_data['user_info'] = user_data

                # Retrieve account information upon successful login
                account_info = await api_client.get_account_info(token)
                context.user_data['account_info'] = account_info

                main_menu_text = (
                    "✅ تم تسجيل الدخول بنجاح!\n\n"
                    f"مرحبًا {user_data.get('prenom', '')} {user_data.get('nom', '')}\n"
                    "يرجى اختيار أحد الخيارات التالية:"
                )

                # Show only 'معلومات الحساب' and 'شحن LTE عبر القسيمة' buttons
                keyboard = [
                    [InlineKeyboardButton("معلومات الحساب", callback_data="account_info")],
                    [InlineKeyboardButton("تسجيل خروج", callback_data="logout")],
                ]

                await update.message.reply_text(
                    main_menu_text,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return ConversationStates.MAIN_MENU.value

            await update.message.reply_text(
                "❌ فشل تسجيل الدخول. يرجى التحقق من بيانات الدخول والمحاولة مرة أخرى."
            )
            return ConversationHandler.END

        except Exception as e:
            logger.error(f"Login error: {str(e)}")
            await update.message.reply_text(
                "❌ حدث خطأ أثناء تسجيل الدخول. يرجى المحاولة مرة أخرى لاحقًا."
            )
            return ConversationHandler.END

async def nd_fact_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info("Received input for bill checking.")
    nd = update.message.text.strip()

    if not nd.isdigit():
        await update.message.reply_text("⚠️ يرجى إدخال رقم هاتف صالح.")
        return ConversationStates.ND_FACT_INPUT.value

    async with APIClient(API_URL, PAIEMENT_URL) as api_client:
        try:
            response = await api_client.check_nd_fact(nd)
            info_text = await format_nd_fact_info(response)
            keyboard = [
                [InlineKeyboardButton("العودة إلى القائمة الرئيسية", callback_data="main_menu")],
            ]
            await update.message.reply_text(
                info_text,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return ConversationStates.MAIN_MENU.value
        except Exception as e:
            logger.error(f"Bill checking error: {str(e)}")
            await update.message.reply_text(
                "❌ حدث خطأ أثناء التحقق من الفواتير. يرجى المحاولة مرة أخرى لاحقًا."
            )
            return ConversationHandler.END

async def recharge_voucher_nd_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info("Received ND for voucher recharge.")
    nd = update.message.text.strip()

    if not nd.isdigit():
        await update.message.reply_text("⚠️ يرجى إدخال رقم هاتف صالح.")
        return ConversationStates.VOUCHER_ND_INPUT.value

    context.user_data['voucher_nd'] = nd
    await update.message.reply_text(
        "✅ تم تلقي رقم الهاتف بنجاح.\n\n"
        "يرجى إدخال رمز القسيمة يدويًا في الرسالة التالية."
    )
    return ConversationStates.VOUCHER_CODE_INPUT.value

async def recharge_voucher_code_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info("Received voucher code for recharge.")
    voucher = update.message.text.strip()
    nd = context.user_data.get('voucher_nd')

    if not VOUCHER_PATTERN.match(voucher):
        await update.message.reply_text("⚠️ يرجى إدخال رمز قسيمة صالح مكون من 16 رقمًا.")
        return ConversationStates.VOUCHER_CODE_INPUT.value

    async with APIClient(API_URL, PAIEMENT_URL) as api_client:
        try:
            # Step 1: Verify ND ADSL service
            check_adsl_response = await api_client.check_nd_fact(nd)

            if check_adsl_response.get('code') != "0":
                await update.message.reply_text(
                    f"❌ فشل التحقق من خدمة ADSL.\nرمز الخطأ: {check_adsl_response.get('code', 'غير معروف')}",
                )
                return ConversationStates.MAIN_MENU.value

            ncli = check_adsl_response.get('INFO', {}).get('ncli', '')
            if not ncli:
                await update.message.reply_text(
                    "❌ لم يتم العثور على رقم الزبون (ncli). يرجى التحقق من التفاصيل والمحاولة مرة أخرى."
                )
                return ConversationStates.MAIN_MENU.value

            # Use the voucher
            voucher_response = await api_client.use_voucher(nd=nd, ncli=ncli, voucher=voucher)

            # Format and send the response
            info_text = await format_voucher_response(voucher_response)
            keyboard = [
                [InlineKeyboardButton("العودة إلى القائمة الرئيسية", callback_data="main_menu")],
            ]
            await update.message.reply_text(
                info_text,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return ConversationStates.MAIN_MENU.value

        except Exception as e:
            logger.error(f"Voucher recharge error: {str(e)}")
            await update.message.reply_text(
                "❌ حدث خطأ أثناء الشحن عبر القسيمة. يرجى المحاولة مرة أخرى لاحقًا."
            )
            return ConversationHandler.END

async def recharge_voucher_lte_nd_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info("Received ND for LTE Voucher recharge.")
    nd = update.message.text.strip()

    if not nd.isdigit():
        await update.message.reply_text("⚠️ يرجى إدخال رقم هاتف صالح مكون من أرقام فقط.")
        return ConversationStates.VOUCHER_LTE_ND_INPUT.value

    context.user_data['voucher_lte_nd'] = nd
    await update.message.reply_text(
        "✅ تم تلقي رقم الهاتف بنجاح.\n\n"
        "يرجى إدخال رمز القسيمة LTE يدويًا في الرسالة التالية."
    )
    return ConversationStates.VOUCHER_LTE_CODE_INPUT.value

async def recharge_voucher_lte_code_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info("Received LTE voucher code for recharge.")
    voucher = update.message.text.strip()
    nd = context.user_data.get('voucher_lte_nd')

    if not VOUCHER_PATTERN.match(voucher):
        await update.message.reply_text("⚠️ يرجى إدخال رمز قسيمة صالح مكون من 16 رقمًا.")
        return ConversationStates.VOUCHER_LTE_CODE_INPUT.value

    async with APIClient(API_URL, PAIEMENT_URL) as api_client:
        try:
            # Step 1: Verify ND LTE service
            check_lte_response = await api_client.check_nd_lte(nd)

            if check_lte_response.get('code') != "0":
                await update.message.reply_text(
                    f"❌ فشل التحقق من خدمة LTE.\nرمز الخطأ: {check_lte_response.get('code', 'غير معروف')}",
                )
                return ConversationStates.MAIN_MENU.value

            ncli = check_lte_response.get('INFO', {}).get('ncli', '')
            if not ncli:
                await update.message.reply_text(
                    "❌ لم يتم العثور على رقم الزبون (ncli). يرجى التحقق من التفاصيل والمحاولة مرة أخرى."
                )
                return ConversationStates.MAIN_MENU.value

            # Use the LTE voucher
            voucher_lte_response = await api_client.use_voucher_lte(nd=nd, ncli=ncli, voucher=voucher, type1="4GLTE")

            # Log the full response for debugging
            logger.info(f"Voucher LTE Response: {voucher_lte_response}")

            # Adjust response handling based on actual API response
            code = voucher_lte_response.get('code', '')
            message = voucher_lte_response.get('message', '')

            # Determine success based on code and message
            if code == "0":
                info_text = f"✅ تم شحن خدمة LTE بنجاح!\n🔢 الكود: {message}"
            elif code.startswith("11"):
                info_text = f"✅ تم شحن خدمة LTE بنجاح!\n🔢 رمز المعاملة: {code}"
            else:
                info_text = f"❌ فشل في شحن خدمة LTE.\nرمز الخطأ: {code}\nالرسالة: {message}"

            keyboard = [
                [InlineKeyboardButton("العودة إلى القائمة الرئيسية", callback_data="main_menu")],
            ]
            await update.message.reply_text(
                info_text,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return ConversationStates.MAIN_MENU.value

        except Exception as e:
            logger.error(f"LTE Voucher recharge error: {str(e)}")
            await update.message.reply_text(
                "❌ حدث خطأ أثناء الشحن عبر القسيمة LTE. يرجى المحاولة مرة أخرى لاحقًا."
            )
            return ConversationHandler.END

async def get_ncli_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info("Received ND for retrieving ncli.")
    nd = update.message.text.strip()

    if not nd.isdigit():
        await update.message.reply_text("⚠️ يرجى إدخال رقم هاتف صالح مكون من أرقام فقط.")
        return ConversationStates.GET_NCLI_INPUT.value

    try:
        ncli = await retrieve_ncli(nd)
        # Display only the ncli to the user
        info_text = await format_ncli_response(ncli)
        keyboard = [
            [InlineKeyboardButton("العودة إلى القائمة الرئيسية", callback_data="main_menu")],
        ]
        await update.message.reply_text(
            info_text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return ConversationStates.MAIN_MENU.value

    except Exception as e:
        logger.error(f"Error retrieving ncli: {str(e)}")
        await update.message.reply_text(
            "❌ حدث خطأ أثناء استرجاع رقم الزبون. يرجى المحاولة مرة أخرى لاحقًا."
        )
        return ConversationHandler.END

async def account_info_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info("Account info callback triggered.")
    query = update.callback_query
    await query.answer()

    account_info = context.user_data.get('account_info')
    if account_info:
        info_text = await format_account_info(account_info)
        keyboard = [
            [InlineKeyboardButton("العودة إلى القائمة الرئيسية", callback_data="main_menu")],
        ]
        await query.message.edit_text(info_text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await query.message.reply_text("❌ لا توجد معلومات حساب متاحة.", reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("العودة إلى القائمة الرئيسية", callback_data="main_menu")]
            ]
        ))
    return ConversationStates.MAIN_MENU.value

async def check_speeds_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info("Check speeds callback triggered.")
    query = update.callback_query
    await query.answer()

    account_info = context.user_data.get('account_info')
    if account_info:
        speeds = account_info.get('listOffreDebit', '').split(',')

        speed_text = "🚀 الخيارات المتاحة للسرعة:\n\n"
        for speed in speeds:
            speed_text += f"• {speed.strip()} Mbps\n"

        keyboard = [
            [InlineKeyboardButton("العودة إلى القائمة الرئيسية", callback_data="main_menu")],
        ]
        await query.message.edit_text(speed_text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await query.message.reply_text("❌ لا توجد معلومات حساب متاحة.", reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("العودة إلى القائمة الرئيسية", callback_data="main_menu")]
            ]
        ))
    return ConversationStates.MAIN_MENU.value

async def nd_fact_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info("Check bills callback triggered.")
    query = update.callback_query
    await query.answer()

    # Check if the user is logged in
    if 'token' in context.user_data:
        nd = context.user_data.get('nd')
        async with APIClient(API_URL, PAIEMENT_URL) as api_client:
            try:
                response = await api_client.check_nd_fact(nd)
                info_text = await format_nd_fact_info(response)
                keyboard = [
                    [InlineKeyboardButton("العودة إلى القائمة الرئيسية", callback_data="main_menu")],
                ]
                await query.message.edit_text(
                    info_text,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except Exception as e:
                logger.error(f"Bill checking error: {str(e)}")
                await query.message.edit_text(
                    "❌ حدث خطأ أثناء التحقق من الفواتير. يرجى المحاولة مرة أخرى لاحقًا."
                )
    else:
        # If the user is not logged in, prompt for phone number
        await query.message.edit_text("يرجى إدخال رقم الهاتف للتحقق من الفواتير:")
        return ConversationStates.ND_FACT_INPUT.value
    return ConversationStates.MAIN_MENU.value

async def logout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info("Logout option selected.")
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.message.edit_text(
        "✅ تم تسجيل خروجك. أرسل /start لتسجيل الدخول مرة أخرى.",
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("العودة إلى القائمة الرئيسية", callback_data="main_menu")]
            ]
        )
    )
    return ConversationStates.MAIN_MENU.value

async def return_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Function to return to the main menu.
    """
    logger.info("Returning to main menu.")
    query = update.callback_query
    await query.answer()
    main_menu_text = (
        "👋 مرحبًا بك في بوت الجزائر تيليكوم!\n\n"
        "يرجى اختيار أحد الخيارات التالية:"
    )
    keyboard = [
        [InlineKeyboardButton("تسجيل", callback_data="register")],
        [InlineKeyboardButton("تسجيل الدخول", callback_data="login")],
        [InlineKeyboardButton("تحقق من الفواتير", callback_data="nd_fact")],
        [InlineKeyboardButton("شحن adsl عبر القسيمة", callback_data="recharge_voucher")],
        [InlineKeyboardButton("شحن LTE عبر القسيمة", callback_data="recharge_voucher_lte")],
        [InlineKeyboardButton("الحصول على رقم الزبون", callback_data="get_ncli")],

    ]
    await query.message.edit_text(main_menu_text, reply_markup=InlineKeyboardMarkup(keyboard))
    return ConversationStates.MAIN_MENU.value

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info("Cancel command received.")
    await update.message.reply_text(
        "❌ تم إلغاء العملية. أرسل /start للبدء مرة أخرى.",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("Help command received.")
    help_text = (
        "🔍 الأوامر المتاحة:\n\n"
        "/start - بدء التفاعل مع البوت\n"
        "/help - عرض رسالة المساعدة\n"
        "/cancel - إلغاء العملية الحالية\n"
    )
    await update.message.reply_text(help_text)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Error handler to prevent the bot from stopping due to unexpected exceptions.
    """
    logger.error(msg="استثناء غير متوقع:", exc_info=context.error)
    if isinstance(update, Update) and update.message:
        await update.message.reply_text("❌ حدث خطأ غير متوقع. يرجى المحاولة مرة أخرى لاحقًا.")

# APIClient class definition
class APIClient:
    def __init__(self, base_url, paiement_url):
        self.base_url = base_url
        self.paiement_url = paiement_url
        self.session = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def login(self, nd: str, password: str) -> dict:
        url = f"{self.base_url}/auth/login_new"

        payload = {
            "nd": nd,
            "password": password,
            "lang": "fr"
        }

        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "Dart/3.0 (dart:io)",
            "Accept-Encoding": "gzip"
        }

        try:
            async with self.session.post(url, json=payload, headers=headers) as response:
                if response.status == 200:
                    logger.info("✅ تسجيل الدخول ناجح")
                    return await response.json()
                else:
                    logger.error(f"❌ فشل تسجيل الدخول: {response.status}")
                    raise Exception(f"فشل تسجيل الدخول: {response.status}")
        except Exception as e:
            logger.error(f"❌ فشل طلب API: {str(e)}")
            raise

    async def register(self, registration_data: dict) -> dict:
        url = f"{self.base_url}/auth/register"

        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "Dart/3.0 (dart:io)",
            "Accept-Encoding": "gzip"
        }

        try:
            async with self.session.post(url, json=registration_data, headers=headers) as response:
                if response.status == 200:
                    logger.info("✅ عملية التسجيل تمت بنجاح")
                    return await response.json()
                else:
                    logger.error(f"❌ فشل عملية التسجيل: {response.status}")
                    raise Exception(f"فشل عملية التسجيل: {response.status}")
        except Exception as e:
            logger.error(f"❌ فشل طلب التسجيل: {str(e)}")
            raise

    async def confirm_register(self, confirmation_data: dict) -> dict:
        """
        Confirms registration by sending OTP.

        Args:
            confirmation_data (dict): Dictionary containing 'nd' and 'otp'.

        Returns:
            dict: Parsed JSON response from the API.
        """
        url = f"{self.base_url}/auth/confirmRegister"

        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "Dart/3.0 (dart:io)",
            "Accept-Encoding": "gzip"
        }

        try:
            async with self.session.post(url, json=confirmation_data, headers=headers) as response:
                if response.status == 200:
                    logger.info("✅ تأكيد التسجيل ناجح")
                    return await response.json()
                else:
                    logger.error(f"❌ فشل تأكيد التسجيل: {response.status}")
                    raise Exception(f"فشل تأكيد التسجيل: {response.status}")
        except Exception as e:
            logger.error(f"❌ فشل طلب تأكيد التسجيل: {str(e)}")
            raise

    async def get_account_info(self, token: str) -> dict:
        url = f"{self.base_url}/compte_augmentation_debit"

        headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": "Dart/3.0 (dart:io)",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }

        try:
            async with self.session.get(url, headers=headers) as response:
                if response.status == 200:
                    logger.info("✅ تم استرجاع معلومات الحساب بنجاح")
                    return await response.json()
                else:
                    logger.error(f"❌ فشل في الحصول على معلومات الحساب: {response.status}")
                    raise Exception(f"فشل في الحصول على معلومات الحساب: {response.status}")
        except Exception as e:
            logger.error(f"❌ فشل طلب معلومات الحساب: {str(e)}")
            raise

    async def check_nd_fact(self, nd: str) -> dict:
        url = f"{self.base_url}/epay/checkNdFact"

        payload = {
            "nd": nd,
            "nfact": "",
            "service": "Dus"
        }

        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "Dart/3.0 (dart:io)",
            "Accept-Encoding": "gzip"
        }

        try:
            async with self.session.post(url, json=payload, headers=headers) as response:
                if response.status == 200:
                    logger.info("✅ تم التحقق من ND Fact بنجاح")
                    return await response.json()
                else:
                    logger.error(f"❌ فشل في التحقق من ND Fact: {response.status}")
                    raise Exception(f"فشل في التحقق من ND Fact: {response.status}")
        except Exception as e:
            logger.error(f"❌ فشل طلب التحقق من ND Fact: {str(e)}")
            raise

    async def check_nd_lte(self, nd: str) -> dict:
        """
        Checks ND for LTE service.

        Args:
            nd (str): The phone number (nd) to check.

        Returns:
            dict: Parsed JSON response from the API.
        """
        url = f"{self.base_url}/epay/checkNdLte"

        payload = {
            "nd": nd
        }

        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "Dart/3.0 (dart:io)",
            "Accept-Encoding": "gzip"
        }

        try:
            async with self.session.post(url, json=payload, headers=headers) as response:
                if response.status == 200:
                    logger.info("✅ تم التحقق من ND LTE بنجاح")
                    return await response.json()
                else:
                    logger.error(f"❌ فشل في التحقق من ND LTE: {response.status}")
                    raise Exception(f"فشل في التحقق من ND LTE: {response.status}")
        except Exception as e:
            logger.error(f"❌ فشل طلب التحقق من ND LTE: {str(e)}")
            raise

    async def use_voucher_lte(self, nd: str, ncli: str, voucher: str, type1: str, ip: str = "0.0.0.0") -> dict:
        """
        Uses an LTE voucher to recharge.

        Args:
            nd (str): The phone number.
            ncli (str): The customer number.
            voucher (str): The voucher code.
            type1 (str): The type of service, e.g., "4GLTE".
            ip (str): The IP address. Defaults to "0.0.0.0".

        Returns:
            dict: Parsed JSON response from the API.
        """
        url = f"{self.base_url}/epay/voucherLte"

        payload = {
            "nd": nd,
            "ncli": ncli,
            "type": type1,
            "voucher": voucher,
            "ip": ip
        }

        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "Dart/3.0 (dart:io)",
            "Accept-Encoding": "gzip"
        }

        try:
            async with self.session.post(url, json=payload, headers=headers) as response:
                response_text = await response.text()
                logger.info(f"Voucher LTE Response Text: {response_text}")
                if response.status == 200:
                    logger.info("✅ تم استخدام القسيمة LTE بنجاح")
                    return await response.json()
                else:
                    logger.error(f"❌ فشل في استخدام القسيمة LTE: {response.status}")
                    raise Exception(f"فشل في استخدام القسيمة LTE: {response.status}")
        except Exception as e:
            logger.error(f"❌ فشل طلب استخدام القسيمة LTE: {str(e)}")
            raise

    async def use_voucher(self, nd: str, ncli: str, voucher: str, ip: str = "0.0.0.0") -> dict:
        """Uses a standard voucher to recharge the balance."""
        url = f"{self.base_url}/epay/voucherAdsl"

        payload = {
            "nd": nd,
            "ncli": ncli,
            "type": "FTTH",
            "voucher": voucher,
            "ip": ip
        }

        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "Dart/3.0 (dart:io)",
            "Accept-Encoding": "gzip"
        }

        try:
            async with self.session.post(url, json=payload, headers=headers) as response:
                if response.status == 200:
                    logger.info("✅ تم استخدام القسيمة بنجاح")
                    return await response.json()
                else:
                    logger.error(f"❌ فشل في استخدام القسيمة: {response.status}")
                    raise Exception(f"فشل في استخدام القسيمة: {response.status}")
        except Exception as e:
            logger.error(f"❌ فشل طلب استخدام القسيمة: {str(e)}")
            raise

# --- Webhook Setup for Cloudflare ---

# It is recommended to get the TOKEN from environment variables in production
# For example: TOKEN = os.environ["TELEGRAM_TOKEN"]
# You should also set WEBHOOK_URL as an environment variable on your Cloudflare worker
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")

# Initialize the bot application
logger.info("🔧 Initializing Bot Application...")
application = Application.builder().token(TOKEN).build()

# Add conversation handler
conv_handler = ConversationHandler(
    entry_points=[CommandHandler("start", start)],
    states={
        ConversationStates.MAIN_MENU.value: [
            CallbackQueryHandler(login_selected, pattern='^login$'),
            CallbackQueryHandler(nd_fact_selected, pattern='^nd_fact$'),
            CallbackQueryHandler(recharge_voucher_selected, pattern='^recharge_voucher$'),
            CallbackQueryHandler(recharge_voucher_lte_selected, pattern='^recharge_voucher_lte$'),
            CallbackQueryHandler(get_ncli_selected, pattern='^get_ncli$'),
            CallbackQueryHandler(register_selected, pattern='^register$'),
            CallbackQueryHandler(account_info_callback, pattern='^account_info$'),
            CallbackQueryHandler(check_speeds_callback, pattern='^check_speeds$'),
            CallbackQueryHandler(nd_fact_callback, pattern='^nd_fact$'),
            CallbackQueryHandler(logout_callback, pattern='^logout$'),
            CallbackQueryHandler(return_to_main_menu, pattern='^main_menu$'),
        ],
        ConversationStates.LOGIN_ND.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_nd_handler)],
        ConversationStates.LOGIN_PASSWORD.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_password_handler)],
        ConversationStates.ND_FACT_INPUT.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, nd_fact_input_handler)],
        ConversationStates.VOUCHER_ND_INPUT.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, recharge_voucher_nd_input_handler)],
        ConversationStates.VOUCHER_CODE_INPUT.value: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, recharge_voucher_code_input_handler),
        ],
        ConversationStates.GET_NCLI_INPUT.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_ncli_input_handler)],
        ConversationStates.REGISTER_ND_INPUT.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_nd_input_handler)],
        ConversationStates.REGISTER_NCLI_INPUT.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_ncli_input_handler)],
        ConversationStates.REGISTER_MOBILE_INPUT.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_mobile_input_handler)],
        ConversationStates.REGISTER_EMAIL_INPUT.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_email_input_handler)],
        ConversationStates.REGISTER_PASSWORD1_INPUT.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_password1_input_handler)],
        ConversationStates.REGISTER_PASSWORD2_INPUT.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_password2_input_handler)],
        ConversationStates.REGISTER_OTP_INPUT.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_otp_input_handler)],
        ConversationStates.VOUCHER_LTE_ND_INPUT.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, recharge_voucher_lte_nd_input_handler)],
        ConversationStates.VOUCHER_LTE_CODE_INPUT.value: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, recharge_voucher_lte_code_input_handler),
        ],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
    allow_reentry=True,
)

application.add_handler(conv_handler)
application.add_handler(CommandHandler("help", help_command))
application.add_error_handler(error_handler)

# FastAPI application, referenced by wrangler.toml as `main:_asgi_app`
_asgi_app = FastAPI()

@_asgi_app.post(f"/webhook/{TOKEN}")
async def webhook(request: Request):
    """Handle incoming Telegram updates."""
    logger.info("Received a webhook request.")
    try:
        data = await request.json()
        update = Update.de_json(data, application.bot)
        await application.process_update(update)
        logger.info("Webhook request processed successfully.")
        return {"status": "ok"}
    except json.JSONDecodeError:
        logger.error("Failed to decode JSON from webhook request.")
        return {"status": "bad request"}, 400
    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        return {"status": "internal server error"}, 500


@_asgi_app.get("/set_webhook")
async def set_webhook(request: Request):
    """
    Set the webhook for the bot. Call this once after deploying.
    You must set the WEBHOOK_URL environment variable in your Cloudflare worker settings.
    The URL for this endpoint will be https://<your-worker-url>/set_webhook
    """
    if WEBHOOK_URL:
        webhook_full_url = f"{WEBHOOK_URL}/webhook/{TOKEN}"
        await application.bot.set_webhook(url=webhook_full_url, allowed_updates=Update.ALL_TYPES)
        logger.info(f"Webhook set to {webhook_full_url}")
        return {"status": "webhook set", "url": webhook_full_url}
    else:
        logger.error("WEBHOOK_URL environment variable not set.")
        return {"status": "error", "message": "WEBHOOK_URL environment variable not set"}, 500

@_asgi_app.get("/")
async def root():
    return {"status": "Bot is running"}

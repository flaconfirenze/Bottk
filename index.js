/**
 * Cloudflare Worker for a Python Telegram Bot
 *
 * This script uses Pyodide to run a Python Telegram bot in a serverless environment.
 * It's designed to be triggered by a Telegram webhook.
 *
 * How it works:
 * 1. Telegram sends an update (new message, button click, etc.) as a JSON payload
 * to this worker's URL via an HTTP POST request.
 * 2. The worker initializes a Python environment using Pyodide.
 * 3. It loads necessary Python packages like 'requests'.
 * 4. It passes the Telegram update JSON and environment secrets (like BOT_TOKEN)
 * to the embedded Python script.
 * 5. The Python script processes the update, calls external APIs if needed, and
 * uses 'requests' to call the Telegram API to send a reply.
 * 6. The worker returns a 200 OK response to Telegram to acknowledge receipt of the update.
 */
import { Router } from 'itty-router';

// --- Pyodide Initialization ---
// We cache the Pyodide instance to avoid slow cold starts on every request.
let pyodideInstance;

async function loadPyodideInstance() {
  const { loadPyodide } = await import('pyodide');
  const pyodide = await loadPyodide({
    indexURL: 'https://cdn.jsdelivr.net/pyodide/v0.25.1/full/',
  });
  // Load the 'requests' library, which is essential for making HTTP calls in Python.
  await pyodide.loadPackage('requests');
  return pyodide;
}

async function getPyodide() {
  if (!pyodideInstance) {
    pyodideInstance = loadPyodideInstance();
  }
  return await pyodideInstance;
}

// --- Embedded Python Bot Script ---
function getPythonScript() {
  const pythonCode = `
import json
import requests
import os
from enum import Enum

# --- Configuration & Globals ---
API_URL = "https://mobile-pre.at.dz/api"
PAIEMENT_URL = "https://paiement.algerietelecom.dz/AndroidApp"

# This will be read from the worker's environment secrets
BOT_TOKEN = os.environ.get('BOT_TOKEN')

# --- Formatting Functions (Copied from your original script) ---
# These functions format the API responses into user-friendly messages.

def format_nd_fact_info(data: dict) -> str:
    info_data = data.get('INFO', {})
    if not info_data:
        return f"❌ فشل في الحصول على معلومات الرقم.\\nالرسالة: {data.get('message', 'خطأ غير معروف')}"
    return (
        "*📊 معلومات الرقم*\\n\\n"
        f"📱 *الرقم*: \`{info_data.get('nd', 'غير متوفر')}\`\\n"
        f"💰 *الرصيد*: \`{info_data.get('credit', '0')} DA\`"
    )

def format_ncli_response(ncli: str) -> str:
    return (
        "*✅ تم العثور على رقم الزبون*\\n\\n"
        f"🆔 *رقم الزبون (NCLI)*: \`{ncli}\`\\n\\n"
        "📝 _احفظ هذا الرقم لاستخدامه في عمليات التسجيل والشحن._"
    )

def format_voucher_response(response: dict) -> str:
    code = response.get('code', '')
    trans_info = response.get('TRANS')
    message = response.get('message', 'خطأ غير معروف')

    if str(code) == "0":
        if isinstance(trans_info, dict):
            transaction_num = trans_info.get('num_trans', 'غير متوفر')
            date_transaction = trans_info.get('date_transaction', 'غير متوفر')
            heure_transaction = trans_info.get('heure_transaction', 'غير متوفر')
            service = trans_info.get('service', 'غير متوفر')
            return (
                "✅ *تم شحن الرصيد بنجاح!*\\n"
                "*📊 معلومات العملية:*\\n\\n"
                f"🔢 *رقم العملية*: \`{transaction_num}\`\\n"
                f"📅 *التاريخ*: \`{date_transaction}\`\\n"
                f"⏱️ *الوقت*: \`{heure_transaction}\`\\n"
                f"⚙️ *الخدمة*: \`{service}\`"
            )
        else:
            return "✅ *تم شحن الرصيد بنجاح، ولكن بدون تفاصيل العملية.*"
    else:
        error_map = {"9": "رمز القسيمة غير صالح أو مستخدم."}
        specific_message = error_map.get(str(code), message)
        return f"❌ *فشل في شحن الرصيد.*\\n*رمز الخطأ*: \`{code}\`\\n*الرسالة*: {specific_message}"


# --- API Client Class (Refactored to use 'requests') ---
class APIClient:
    def __init__(self, base_url, paiement_url):
        self.base_url = base_url
        self.paiement_url = paiement_url
        self._default_mobile_headers = {
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "Dart/3.0 (dart:io)",
            "Accept-Encoding": "gzip",
            "Accept": "application/json",
        }
        self._default_paiement_headers = {
            "Authorization": "Basic VEdkNzJyOTozUjcjd2FiRHNfSGpDNzg3IQ==",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 10; M2004J19C MIUI/V12.0.4.0.QJCMIXM)",
            "Host": "paiement.algerietelecom.dz",
            "Connection": "Keep-Alive",
            "Accept-Encoding": "gzip",
        }

    def _request(self, method: str, url: str, **kwargs) -> tuple[int, dict | str]:
        try:
            response = requests.request(method, url, **kwargs, timeout=30)
            status_code = response.status_code
            try:
                json_response = response.json()
                return status_code, json_response
            except json.JSONDecodeError:
                text_response = response.text
                if status_code != 200:
                    return status_code, {"error": "Server returned non-JSON response", "details": text_response.strip()}
                return status_code, text_response.strip()
        except requests.RequestException as e:
            return 503, {"error": "Network connection failed", "details": str(e)}

    def check_nd_fact(self, nd: str) -> dict:
        url = f"{self.base_url}/epay/checkNdFact"
        payload = {"nd": nd, "nfact": "", "service": "Internet"}
        status, response_data = self._request("POST", url, json=payload, headers=self._default_mobile_headers)
        return response_data if isinstance(response_data, dict) else {"error": "API response error"}

    def check_nd_lte(self, nd: str) -> dict:
        url = f"{self.base_url}/epay/checkNdLte"
        payload = {"nd": nd}
        status, response_data = self._request("POST", url, json=payload, headers=self._default_mobile_headers)
        return response_data if isinstance(response_data, dict) else {"error": "API response error"}

    def use_voucher_lte(self, nd: str, ncli: str, voucher: str, type1: str, ip: str = "0.0.0.0") -> dict:
        url = f"{self.base_url}/epay/voucherLte"
        payload = {"nd": nd, "ncli": ncli, "type": type1, "voucher": voucher, "ip": ip}
        status, response_data = self._request("POST", url, json=payload, headers=self._default_mobile_headers)
        return response_data if isinstance(response_data, dict) else {"error": "API response error"}

    def retrieve_ncli(self, phone_number: str) -> dict:
        url = f"{self.paiement_url}/internet_recharge.php"
        payload = f"validerADSLco20=Confirmer&ndco20={phone_number}&"
        status, response_data = self._request("POST", url, data=payload, headers=self._default_paiement_headers)
        if status == 200 and isinstance(response_data, str):
            try:
                clean_text = response_data.lstrip('\\ufeff').strip()
                json_response = json.loads(clean_text)
                json_response['success'] = json_response.get("succes") == "1"
                return json_response
            except json.JSONDecodeError:
                return {"success": False, "error": "Invalid JSON response"}
        return {"success": False, "error": "API request failed"}

    def retrieve_ncli_4glte(self, phone_number: str) -> dict:
        url = f"{self.paiement_url}/voucher_internet.php"
        payload = f"dahabiaco20=Confirmer&nd_4gco20={phone_number}&"
        status, response_data = self._request("POST", url, data=payload, headers=self._default_paiement_headers)
        if status == 200 and isinstance(response_data, str):
            try:
                clean_text = response_data.lstrip('\\ufeff').strip()
                json_response = json.loads(clean_text)
                json_response['success'] = json_response.get("succes") == "1"
                return json_response
            except json.JSONDecodeError:
                return {"success": False, "error": "Invalid JSON response"}
        return {"success": False, "error": "API request failed"}

# --- Telegram API Helper Functions ---

def send_message(chat_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    requests.post(url, json=payload)

def edit_message_text(chat_id, message_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    requests.post(url, json=payload)

def answer_callback_query(callback_query_id):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
    payload = {"callback_query_id": callback_query_id}
    requests.post(url, json=payload)

# --- Bot Logic Handlers ---

def get_main_menu_keyboard():
    keyboard = [
        [
            {"text": "🧾 تحقق من الفواتير (ADSL/Fibre)", "callback_data": "nd_fact"},
            {"text": "🆔 NCLI (ADSL/Fibre)", "callback_data": "get_ncli"},
        ],
        [
            {"text": "📶 شحن (4G LTE) بالقسيمة", "callback_data": "recharge_voucher_lte"},
            {"text": "🆔 NCLI (4G LTE)", "callback_data": "get_ncli_4glte"},
        ],
        [
            {"text": "❓ مساعدة", "callback_data": "help_menu"}
        ]
    ]
    return {"inline_keyboard": keyboard}

def handle_start_command(chat_id, user_name):
    welcome_message = (
        f"👋 مرحبًا بك يا {user_name} في بوت خدمات الجزائر تيليكوم!\\n\\n"
        "هذه نسخة مبسطة تعمل في بيئة سحابية.\\n\\n"
        "*✨ الخدمات المتاحة حاليًا: ✨*\\n"
        "• التحقق من الفواتير والرصيد\\n"
        "• شحن الرصيد (4G LTE)\\n"
        "• استرجاع رقم الزبون (NCLI)\\n\\n"
        "📱 يرجى اختيار الخدمة المطلوبة:"
    )
    send_message(chat_id, welcome_message, get_main_menu_keyboard())

def handle_help_menu(chat_id, message_id):
    help_text = (
        "*❓ قائمة المساعدة ❓*\\n\\n"
        "هذا البوت يساعدك في الوصول إلى خدمات الجزائر تيليكوم:\\n\\n"
        "• *تحقق من الفواتير*: لعرض الرصيد لرقم ADSL/Fibre.\\n"
        "• *الحصول على NCLI*: استرجاع رقم الزبون لـ ADSL/Fibre أو 4G LTE.\\n"
        "• *شحن 4G LTE*: لشحن حساب 4G LTE باستخدام قسائم التعبئة.\\n\\n"
        "ℹ️ _ميزات تسجيل الدخول وإنشاء الحساب تتطلب بنية مختلفة وسيتم إضافتها لاحقًا._"
    )
    keyboard = {"inline_keyboard": [[{"text": "⬅️ العودة إلى القائمة الرئيسية", "callback_data": "main_menu"}]]}
    edit_message_text(chat_id, message_id, help_text, keyboard)

# --- Main Entry Point for the Worker ---
def main(update_data, state_data):
    if not BOT_TOKEN:
        return

    api_client = APIClient(API_URL, PAIEMENT_URL)

    if 'callback_query' in update_data:
        query = update_data['callback_query']
        callback_id = query['id']
        chat_id = query['message']['chat']['id']
        message_id = query['message']['message_id']
        data = query['data']

        answer_callback_query(callback_id)

        if data == 'main_menu':
            edit_message_text(chat_id, message_id, "🏠 *القائمة الرئيسية*\\n\\nاختر الخدمة المطلوبة:", get_main_menu_keyboard())
            state_data['step'] = None
        elif data == 'help_menu':
            handle_help_menu(chat_id, message_id)
            state_data['step'] = None
        elif data == 'nd_fact':
            edit_message_text(chat_id, message_id, "🧾 يرجى إدخال رقم الهاتف الثابت (ADSL/Fibre) للتحقق:")
            state_data['step'] = 'nd_fact_input'
        elif data == 'get_ncli':
            edit_message_text(chat_id, message_id, "🆔 يرجى إدخال رقم الهاتف الثابت (ADSL/Fibre) لاسترجاع رقم الزبون:")
            state_data['step'] = 'get_ncli_input'
        elif data == 'get_ncli_4glte':
            edit_message_text(chat_id, message_id, "🆔 يرجى إدخال رقم شريحة 4G LTE لاسترجاع رقم الزبون:")
            state_data['step'] = 'get_ncli_4glte_input'
        elif data == 'recharge_voucher_lte':
            edit_message_text(chat_id, message_id, "📶 يرجى إدخال رقم شريحة 4G LTE للشحن:")
            state_data['step'] = 'voucher_lte_nd_input'
        return

    if 'message' in update_data:
        message = update_data['message']
        chat_id = message['chat']['id']
        text = message.get('text', '')

        if text.startswith('/start'):
            user_name = message['from'].get('first_name', 'مستخدم')
            handle_start_command(chat_id, user_name)
            state_data['step'] = None
            return

        current_step = state_data.get('step')

        if current_step == 'nd_fact_input':
            send_message(chat_id, f"⏳ جار التحقق من معلومات الرقم \`{text}\`...")
            response = api_client.check_nd_fact(text)
            info_text = format_nd_fact_info(response)
            send_message(chat_id, info_text, get_main_menu_keyboard())
            state_data['step'] = None

        elif current_step == 'get_ncli_input':
            send_message(chat_id, f"⏳ جار استرجاع NCLI للرقم \`{text}\`...")
            response = api_client.retrieve_ncli(text)
            if response.get('success'):
                info_text = format_ncli_response(response.get('ncli', 'غير متوفر'))
            else:
                info_text = f"❌ {response.get('error', 'فشل في استرجاع رقم الزبون.')}"
            send_message(chat_id, info_text, get_main_menu_keyboard())
            state_data['step'] = None

        elif current_step == 'get_ncli_4glte_input':
            send_message(chat_id, f"⏳ جار استرجاع NCLI للرقم \`{text}\`...")
            response = api_client.retrieve_ncli_4glte(text)
            if response.get('success'):
                info_text = format_ncli_response(response.get('ncli', 'غير متوفر'))
            else:
                info_text = f"❌ {response.get('error', 'فشل في استرجاع رقم الزبون.')}"
            send_message(chat_id, info_text, get_main_menu_keyboard())
            state_data['step'] = None

        elif current_step == 'voucher_lte_nd_input':
            state_data['lte_nd'] = text
            send_message(chat_id, "🔢 يرجى إدخال رمز قسيمة LTE (16 رقم):")
            state_data['step'] = 'voucher_lte_code_input'

        elif current_step == 'voucher_lte_code_input':
            nd_lte = state_data.get('lte_nd')
            voucher_code = text
            if not nd_lte:
                send_message(chat_id, "❌ حدث خطأ. يرجى البدء من جديد.", get_main_menu_keyboard())
                state_data['step'] = None
                return

            send_message(chat_id, f"⏳ جار التحقق من رقم LTE \`{nd_lte}\` وشحن القسيمة...")
            check_response = api_client.check_nd_lte(nd_lte)
            if check_response and str(check_response.get('code')) == '0':
                ncli_lte = check_response.get('ncli')
                type1 = check_response.get('type1')
                if ncli_lte and type1:
                    recharge_response = api_client.use_voucher_lte(nd_lte, ncli_lte, voucher_code, type1)
                    info_text = format_voucher_response(recharge_response)
                else:
                    info_text = "❌ فشل التحقق من تفاصيل رقم LTE. لا يمكن المتابعة."
            else:
                info_text = f"❌ {check_response.get('message', 'فشل التحقق من رقم LTE.')}"

            send_message(chat_id, info_text, get_main_menu_keyboard())
            state_data['step'] = None
            state_data['lte_nd'] = None
`;
  return pythonCode;
}

// Initialize the router.
const router = Router();

// Telegram webhook endpoint.
router.post('/webhook', async (request, env) => {
  try {
    const pyodide = await getPyodide();
    const update = await request.json();

    // Set environment variables for the Python script.
    pyodide.globals.set('env', env);

    // Simple state (per request turn).
    pyodide.globals.set('state_data', new Map());
    pyodide.globals.set('update_data_json', JSON.stringify(update));

    const runnerScript = `
import json
import os
from js import env, update_data_json, state_data

# Make secrets from Cloudflare available as environment variables
for key, value in env.to_py().items():
    os.environ[key] = value

# Load the main bot script
${getPythonScript()}

# Get the update data from the JSON string passed by JavaScript
update_data = json.loads(update_data_json)

# Execute the main function
main(update_data, state_data)
    `;

    // Fire-and-forget the Python execution.
    pyodide.runPythonAsync(runnerScript).catch(e => console.error("Python script error:", e));

    // Acknowledge the webhook request immediately.
    return new Response('OK', { status: 200 });

  } catch (error) {
    console.error('Worker error:', error);
    return new Response(`Error: ${error.message}`, { status: 500 });
  }
});

// Health check.
router.get('/', () => new Response('Your Python Telegram Bot Worker is running!'));

// Catch-all.
router.all('*', () => new Response('Not Found.', { status: 404 }));

export default {
  async fetch(request, env, ctx) {
    return router.handle(request, env, ctx);
  },
};

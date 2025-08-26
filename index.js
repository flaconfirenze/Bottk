import { Telegraf, Scenes, session, Markup } from 'telegraf';
import axios from 'axios';
import { Router } from 'itty-router';

// --- Environment Variables ---
// It's crucial to set these in your Cloudflare Worker's settings
const TOKEN = env.TELEGRAM_TOKEN;
const WEBHOOK_URL = env.WEBHOOK_URL;

// --- API Configuration ---
const API_URL = "https://mobile-pre.at.dz/api";
const PAIEMENT_URL = "https://paiement.algerietelecom.dz/AndroidApp/dette_paiement.php";

// --- Input Validation Regex ---
const PHONE_PATTERN = /^0\d{9}$/;
const EMAIL_PATTERN = /^[\w\.-]+@[\w\.-]+\.\w+$/;
const VOUCHER_PATTERN = /^\d{16}$/;
const OTP_PATTERN = /^\d{6}$/;


// --- API Client Functions ---

const apiClient = axios.create({
    headers: {
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "Dart/3.0 (dart:io)",
        "Accept-Encoding": "gzip"
    }
});

async function retrieve_ncli(nd) {
    const payload = `ndco20=${nd}&validerco20=Confirmer&nfactco20=&`;
    const headers = {
        "Authorization": "Basic VEdkNzJyOTozUjcjd2FiRHNfSGpDNzg3IQ==",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 10; M2004J19C MIUI/V12.0.4.0.QJCMIXM)",
        "Host": "paiement.algerietelecom.dz",
        "Connection": "Keep-Alive",
        "Accept-Encoding": "gzip",
    };
    try {
        const response = await axios.post(PAIEMENT_URL, payload, { headers });
        // The response is not JSON, it's a weird text format. We need to parse it manually.
        // Assuming the response is JSON after cleaning
        const cleanText = response.data.replace(/^\uFEFF/, '').trim();
        const jsonResponse = JSON.parse(cleanText);

        if (jsonResponse.succes === 1) {
            return jsonResponse.ncli || "غير متوفر";
        } else {
            throw new Error(`فشل في استرجاع رقم الزبون. رمز الخطأ: ${jsonResponse.succes}`);
        }
    } catch (error) {
        console.error("NCLI retrieval error:", error.message);
        throw new Error("حدث خطأ أثناء استرجاع رقم الزبون.");
    }
}

// --- Formatting Functions ---

function formatAccountInfo(data) {
    return [
        "📊 معلومات الحساب:",
        `👤 الاسم: ${data.prenom || ''} ${data.nom || ''}`,
        `📱 رقم الهاتف: ${data.nd || ''}`,
        `🏠 العنوان: ${data.adresse || ''}`,
        `📡 العرض: ${data.offre || ''}`,
        `⚡ السرعة: ${data.speed || ''} Mbps`,
        `💲 رصيدالهاتف: ${data.credit || '0'} DA`,
        `💰 عدد الأيام المتبقية: ${data.balance || '0'} يوم`,
        `📅 تاريخ الانتهاء: ${data.dateexp || ''}`,
        `📞 الهاتف المحمول: ${data.mobile || ''}`,
        `📧 البريد الإلكتروني: ${data.email || ''}`,
        `🆔 رقم الزبون: ${data.ncli || ''}`,
        `📊 الحالة: ${data.status || ''}`,
        `💫 النوع: ${data.type1 || ''}`
    ].join('\n');
}

// ... other formatting functions can be translated similarly ...


// --- Bot Setup ---
const bot = new Telegraf(TOKEN);

// --- Conversation Scenes ---
// We use scenes to handle multi-step conversations, similar to ConversationHandler in python-telegram-bot

// Helper function to create a text prompt scene
const createTextPromptScene = (sceneId, promptMessage, nextSceneId, validationRegex = null, validationMessage = null) => {
    const scene = new Scenes.BaseScene(sceneId);
    scene.enter((ctx) => ctx.reply(promptMessage));
    scene.on('text', (ctx) => {
        const text = ctx.message.text.trim();
        if (validationRegex && !validationRegex.test(text)) {
            return ctx.reply(validationMessage || '⚠️ إدخال غير صالح. يرجى المحاولة مرة أخرى.');
        }
        ctx.scene.state[sceneId] = text; // Save data to scene state
        return ctx.scene.enter(nextSceneId, ctx.scene.state);
    });
    scene.use((ctx) => ctx.reply('يرجى إرسال نص فقط.'));
    return scene;
};


// Login Scene
const loginNdScene = createTextPromptScene('LOGIN_ND_SCENE', 'يرجى إدخال رقم الهاتف الخاص بك:', 'LOGIN_PASSWORD_SCENE');
const loginPasswordScene = new Scenes.BaseScene('LOGIN_PASSWORD_SCENE');
loginPasswordScene.enter((ctx) => ctx.reply('يرجى إدخال كلمة المرور:'));
loginPasswordScene.on('text', async (ctx) => {
    const password = ctx.message.text;
    const { LOGIN_ND_SCENE: nd } = ctx.scene.state;

    try {
        await ctx.deleteMessage(); // Try to delete password message
    } catch (e) { /* ignore */ }

    try {
        const response = await apiClient.post(`${API_URL}/auth/login_new`, { nd, password, lang: 'fr' });
        const token = response.data?.meta_data?.original?.token;

        if (token) {
            const accountInfo = await apiClient.get(`${API_URL}/compte_augmentation_debit`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            ctx.session.accountInfo = accountInfo.data;
            ctx.session.token = token;

            await ctx.reply('✅ تم تسجيل الدخول بنجاح!', Markup.inlineKeyboard([
                Markup.button.callback('معلومات الحساب', 'account_info'),
                Markup.button.callback('تسجيل خروج', 'logout')
            ]));
        } else {
            await ctx.reply('❌ فشل تسجيل الدخول. يرجى التحقق من بيانات الدخول والمحاولة مرة أخرى.');
        }
    } catch (error) {
        console.error('Login error:', error.message);
        await ctx.reply('❌ حدث خطأ أثناء تسجيل الدخول.');
    }

    return ctx.scene.leave();
});

// Get NCLI Scene
const getNcliScene = new Scenes.BaseScene('GET_NCLI_SCENE');
getNcliScene.enter((ctx) => ctx.reply('يرجى إدخال رقم الهاتف لاسترجاع رقم الزبون:'));
getNcliScene.on('text', async (ctx) => {
    const nd = ctx.message.text.trim();
    if (!/^\d+$/.test(nd)) {
        return ctx.reply('⚠️ يرجى إدخال رقم هاتف صالح.');
    }
    try {
        const ncli = await retrieve_ncli(nd);
        await ctx.reply(`🆔 رقم الزبون: ${ncli}`);
    } catch (error) {
        await ctx.reply(error.message);
    }
    return ctx.scene.leave();
});


// --- Staging and Registering Scenes ---
const stage = new Scenes.Stage([loginNdScene, loginPasswordScene, getNcliScene]);
bot.use(session());
bot.use(stage.middleware());


// --- Bot Commands and Actions ---

bot.start((ctx) => {
    ctx.reply('👋 مرحبًا بك في بوت الجزائر تيليكوم!\n\nيرجى اختيار أحد الخيارات التالية:', Markup.inlineKeyboard([
        // [Markup.button.callback("تسجيل", "register")], // Register scene not implemented yet
        [Markup.button.callback("تسجيل الدخول", "login")],
        // [Markup.button.callback("تحقق من الفواتير", "nd_fact")], // Not implemented yet
        // [Markup.button.callback("شحن adsl عبر القسيمة", "recharge_voucher")], // Not implemented yet
        // [Markup.button.callback("شحن LTE عبر القسيمة", "recharge_voucher_lte")], // Not implemented yet
        [Markup.button.callback("الحصول على رقم الزبون", "get_ncli")],
    ]));
});

bot.action('login', (ctx) => ctx.scene.enter('LOGIN_ND_SCENE'));
bot.action('get_ncli', (ctx) => ctx.scene.enter('GET_NCLI_SCENE'));

bot.action('account_info', (ctx) => {
    if (ctx.session.accountInfo) {
        ctx.editMessageText(formatAccountInfo(ctx.session.accountInfo), Markup.inlineKeyboard([
             Markup.button.callback("العودة إلى القائمة الرئيسية", "main_menu")
        ]));
    } else {
        ctx.reply('❌ لا توجد معلومات حساب متاحة. يرجى تسجيل الدخول أولاً.');
    }
});

bot.action('logout', (ctx) => {
    ctx.session = {}; // Clear session
    ctx.editMessageText('✅ تم تسجيل خروجك. أرسل /start للبدء مرة أخرى.');
});

bot.action('main_menu', (ctx) => {
     ctx.editMessageText('👋 مرحبًا بك في بوت الجزائر تيليكوم!\n\nيرجى اختيار أحد الخيارات التالية:', Markup.inlineKeyboard([
        // [Markup.button.callback("تسجيل", "register")],
        [Markup.button.callback("تسجيل الدخول", "login")],
        // [Markup.button.callback("تحقق من الفواتير", "nd_fact")],
        // [Markup.button.callback("شحن adsl عبر القسيمة", "recharge_voucher")],
        // [Markup.button.callback("شحن LTE عبر القسيمة", "recharge_voucher_lte")],
        [Markup.button.callback("الحصول على رقم الزبون", "get_ncli")],
    ]));
});

// --- Webhook Setup ---
const router = Router();

// This endpoint will be called by Telegram
router.post(`/${TOKEN}`, async (request) => {
    const update = await request.json();
    await bot.handleUpdate(update);
    return new Response('OK', { status: 200 });
});

// This endpoint is to set the webhook
router.get('/set_webhook', async () => {
    if (!WEBHOOK_URL || !TOKEN) {
        return new Response('Missing WEBHOOK_URL or TELEGRAM_TOKEN environment variables', { status: 500 });
    }
    const webhookFullUrl = `${WEBHOOK_URL}/${TOKEN}`;
    const success = await bot.telegram.setWebhook(webhookFullUrl);
    if (success) {
        return new Response(`Webhook set successfully to ${webhookFullUrl}`);
    } else {
        return new Response('Error setting webhook', { status: 500 });
    }
});

// A root endpoint to check if the worker is running
router.get('/', () => new Response('Bot is running'));

// Catch-all for any other request
router.all('*', () => new Response('Not Found', { status: 404 }));


// --- Cloudflare Worker Entrypoint ---
export default {
    async fetch(request, env, ctx) {
        // Make environment variables available globally for the bot
        globalThis.env = env;
        return router.handle(request);
    }
};

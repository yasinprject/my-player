import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from flask import Flask, request, render_template_string, Response
import os
import yt_dlp
import logging
import uuid
import requests

# ================= কনফিগারেশন =================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get('BOT_TOKEN', '')
HOST_URL = os.environ.get('HOST_URL', '').rstrip('/')

app = Flask(__name__)
bot = telebot.TeleBot(BOT_TOKEN)

video_cache = {}

# ================= এক্সট্রাক্টর =================
def extract_direct_url(video_url):
    ydl_opts = {
        'format': 'best',
        'quiet': True,
        'no_warnings': True,
        'simulate': True,
        'skip_download': True
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            return info.get('url') or (info['formats'][-1]['url'] if 'formats' in info else None)
    except Exception as e:
        logger.error(f"Extraction Error: {e}")
        return None

# ================= ওয়েব হুক ও প্রক্সি =================
@app.route('/' + BOT_TOKEN, methods=['POST'])
def getMessage():
    json_string = request.get_data().decode('utf-8')
    update = telebot.types.Update.de_json(json_string)
    bot.process_new_updates([update])
    return "!", 200

@app.route('/')
def webhook():
    bot.remove_webhook()
    success = bot.set_webhook(url=HOST_URL + '/' + BOT_TOKEN)
    return f"✅ Bot is running! Webhook Status: {success}"

@app.route('/stream')
def stream_video():
    vid_id = request.args.get('v')
    url = video_cache.get(vid_id)
    if not url: return "Link Expired", 404
    
    headers = {'User-Agent': 'Mozilla/5.0'}
    range_header = request.headers.get('Range')
    if range_header:
        headers['Range'] = range_header
        
    req = requests.get(url, headers=headers, stream=True, allow_redirects=True, verify=False)
    
    def generate():
        for chunk in req.iter_content(chunk_size=1024 * 512): # 512KB chunks for smooth playback
            if chunk: yield chunk

    resp = Response(generate(), status=req.status_code)
    for k, v in req.headers.items():
        if k.lower() in ['content-length', 'content-range', 'accept-ranges', 'content-type']:
            resp.headers[k] = v
    return resp

@app.route('/player')
def video_player():
    vid_id = request.args.get('v')
    if not video_cache.get(vid_id):
        return "<h2 style='color:white; text-align:center; font-family:sans-serif; margin-top:50px;'>❌ ভিডিও সেশন শেষ! বটে গিয়ে নতুন করে লিংক দিন।</h2>", 400
    
    proxy_url = f"{HOST_URL}/stream?v={vid_id}"

    # Native Player (সবচেয়ে ফাস্ট লোড হবে)
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>Telegram Player</title>
        <script src="https://telegram.org/js/telegram-web-app.js"></script>
        <style>
            body { margin: 0; background: #000; height: 100vh; display: flex; justify-content: center; align-items: center; overflow: hidden; }
            video { width: 100%; max-height: 100vh; outline: none; background: #000; }
        </style>
    </head>
    <body>
        <video id="vid" controls autoplay playsinline preload="auto">
            <source src="{{ proxy_url }}" type="video/mp4">
            Your browser does not support the video tag.
        </video>
        <script>
            window.Telegram.WebApp.expand();
            var v = document.getElementById('vid');
            v.play().catch(function(e) { console.log("Auto-play blocked"); });
        </script>
    </body>
    </html>
    """
    return render_template_string(html, proxy_url=proxy_url)

# ================= বট কমান্ড =================
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "🌍 **Universal Video Player Bot**\nনতুন কোনো ভিডিও লিংক দিন!")

@bot.message_handler(func=lambda message: True)
def process_url(message):
    url = message.text.strip()
    if not url.startswith("http"):
        bot.reply_to(message, "❌ সঠিক লিংক দিন।")
        return

    msg = bot.reply_to(message, "🔄 *লিংক বের করা হচ্ছে...*", parse_mode='Markdown')

    try:
        direct_url = extract_direct_url(url)
        if direct_url:
            vid_id = str(uuid.uuid4())[:8]
            video_cache[vid_id] = direct_url 
            
            player_link = f"{HOST_URL}/player?v={vid_id}"
            
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton(text="▶️ প্লে করুন", web_app=WebAppInfo(url=player_link)))
            
            bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id, text="✅ ভিডিও প্লে করতে নিচের বাটনে ক্লিক করুন।", reply_markup=markup)
        else:
            bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id, text="❌ লিংক বের করা যায়নি।")
    except Exception as e:
        bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id, text=f"❌ Error: {str(e)}")

if __name__ == "__main__":
    # threaded=True যুক্ত করা হয়েছে যাতে একসাথে একাধিক রিকোয়েস্ট প্রসেস করতে পারে
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)), threaded=True)

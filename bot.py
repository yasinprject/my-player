import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from flask import Flask, request, render_template_string, Response
import os
import yt_dlp
import logging
import uuid
import requests
import threading

# ================= কনফিগারেশন =================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get('BOT_TOKEN', '')
HOST_URL = os.environ.get('HOST_URL', '').rstrip('/')

app = Flask(__name__)
bot = telebot.TeleBot(BOT_TOKEN)

# মেমোরি ক্যাশ (লিংক সেভ রাখার জন্য)
video_cache = {}

# ================= এক্সট্রাক্টর (MP4 Forced) =================
def extract_direct_url(video_url):
    ydl_opts = {
        # সাইটকে বাধ্য করা হচ্ছে শুধুমাত্র ডিরেক্ট HTTP mp4 লিংক দেওয়ার জন্য (m3u8 ব্লক করা হলো)
        'format': 'best[ext=mp4][protocol^=http]/best[protocol^=http]/best',
        'quiet': True,
        'no_warnings': True,
        'simulate': True,
        'skip_download': True,
        'geo_bypass': True,
        'nocheckcertificate': True
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            url = info.get('url')
            if not url and 'formats' in info:
                # সবচেয়ে ভালো mp4 কোয়ালিটি ফিল্টার করা
                mp4_formats = [f for f in info['formats'] if f.get('ext') == 'mp4' and f.get('protocol', '').startswith('http')]
                if mp4_formats:
                    url = mp4_formats[-1].get('url')
                else:
                    url = info['formats'][-1].get('url')
            return url
    except Exception as e:
        logger.error(f"Extraction Error: {e}")
        return None

# ================= Webhook & Background Task =================
@app.route('/' + BOT_TOKEN, methods=['POST'])
def getMessage():
    json_string = request.get_data().decode('utf-8')
    update = telebot.types.Update.de_json(json_string)
    # টেলিগ্রাম যাতে ব্লক না হয় তাই ব্যাকগ্রাউন্ড থ্রেডে প্রসেস করা হচ্ছে
    threading.Thread(target=bot.process_new_updates, args=([update],)).start()
    return "OK", 200

@app.route('/')
def webhook():
    bot.remove_webhook()
    # drop_pending_updates=True দেওয়া হলো যাতে সার্ভার অফ থাকার সময়ের পুরোনো মেসেজগুলো জ্যাম না করে
    success = bot.set_webhook(url=HOST_URL + '/' + BOT_TOKEN, drop_pending_updates=True)
    return f"✅ Ultimate Telegram Player is Live! Webhook Status: {success}"

# ================= 🚀 Advanced Proxy Streaming =================
@app.route('/stream')
def stream_video():
    vid_id = request.args.get('v')
    url = video_cache.get(vid_id)
    
    if not url: 
        return "Video Session Expired", 404
    
    # ব্রাউজারের অরিজিনাল রিকোয়েস্ট হেডার্স
    req_headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': '*/*',
        'Connection': 'keep-alive'
    }
    
    # ভিডিও সামনে-পেছনে টানার (Seek) জন্য Range Header অত্যন্ত জরুরি
    if request.headers.get('Range'):
        req_headers['Range'] = request.headers.get('Range')
        
    try:
        r = requests.get(url, headers=req_headers, stream=True, verify=False, allow_redirects=True, timeout=10)
        
        def generate():
            # 1 MB চাংকে ডেটা স্ট্রিম করা হচ্ছে (বাফারিং এড়ানোর জন্য)
            for chunk in r.iter_content(chunk_size=1024 * 1024): 
                if chunk:
                    yield chunk

        resp = Response(generate(), status=r.status_code)
        
        # অরিজিনাল সার্ভারের সাইজ এবং রেঞ্জ ক্লায়েন্টকে পাস করা
        for k, v in r.headers.items():
            if k.lower() in ['content-length', 'content-range', 'accept-ranges', 'content-type']:
                resp.headers[k] = v
        return resp
        
    except Exception as e:
        logger.error(f"Proxy Error: {e}")
        return "Streaming Error", 500

# ================= Premium Web Player (Plyr) =================
@app.route('/player')
def video_player():
    vid_id = request.args.get('v')
    if not video_cache.get(vid_id):
        return "<h2 style='color:red; text-align:center; font-family:sans-serif; margin-top:50px;'>❌ ভিডিওর সেশন শেষ হয়ে গেছে! টেলিগ্রামে গিয়ে নতুন করে লিংক দিন।</h2>", 400
    
    proxy_url = f"{HOST_URL}/stream?v={vid_id}"

    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>Telegram Video Player</title>
        <!-- Plyr CSS -->
        <link rel="stylesheet" href="https://cdn.plyr.io/3.7.8/plyr.css" />
        <script src="https://telegram.org/js/telegram-web-app.js"></script>
        <style>
            body { margin: 0; padding: 0; background: #000; height: 100vh; display: flex; justify-content: center; align-items: center; overflow: hidden; }
            .container { width: 100%; max-width: 100vw; max-height: 100vh; }
            /* Hide Telegram Header for full immersion */
            :root { --plyr-color-main: #2481cc; }
        </style>
    </head>
    <body>
        <div class="container">
            <video id="player" playsinline controls preload="metadata">
                <source src="{{ proxy_url }}" type="video/mp4" />
            </video>
        </div>
        
        <!-- Plyr JS -->
        <script src="https://cdn.plyr.io/3.7.8/plyr.polyfilled.js"></script>
        <script>
            // Expand Telegram WebApp to fullscreen
            window.Telegram.WebApp.expand();
            window.Telegram.WebApp.ready();
            
            // Initialize Player
            const player = new Plyr('#player', {
                controls: ['play-large', 'play', 'progress', 'current-time', 'mute', 'volume', 'fullscreen'],
                autoplay: true,
                ratio: '16:9'
            });
            
            player.on('ready', () => {
                player.play().catch(() => console.log("Autoplay blocked by Telegram/Browser"));
            });
        </script>
    </body>
    </html>
    """
    return render_template_string(html, proxy_url=proxy_url)

# ================= বট কমান্ডস =================
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "🌍 **Ultimate Video Player Bot**\n\nযেকোনো সাইটের (xHamster, YouTube ইত্যাদি) ভিডিও লিংক আমাকে দিন। আমি নিখুঁতভাবে প্লে করে দেব!")

@bot.message_handler(func=lambda message: True)
def process_url(message):
    url = message.text.strip()
    if not url.startswith("http"):
        bot.reply_to(message, "❌ সঠিক ভিডিও লিংক দিন।")
        return

    msg = bot.reply_to(message, "🔄 *সার্ভার ভিডিও লিংক প্রসেস করছে...*", parse_mode='Markdown')

    try:
        direct_url = extract_direct_url(url)
        if direct_url:
            vid_id = str(uuid.uuid4())[:8]
            video_cache[vid_id] = direct_url 
            
            player_link = f"{HOST_URL}/player?v={vid_id}"
            
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton(text="▶️ প্লে করুন", web_app=WebAppInfo(url=player_link)))
            
            bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id, text="✅ ভিডিও প্রস্তুত! নিচের বাটনে ক্লিক করে প্লে করুন।", reply_markup=markup)
        else:
            bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id, text="❌ লিংক বের করা যায়নি। সাইটটির কড়া সিকিউরিটি থাকতে পারে।")
    except Exception as e:
        bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id, text=f"❌ Error: {str(e)}")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)), threaded=True)

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from flask import Flask, request, render_template_string, Response, stream_with_context
import os
import yt_dlp
import logging
import uuid
import threading
import requests

# ================= কনফিগারেশন =================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get('BOT_TOKEN', 'আপনার_বট_টোকেন')
HOST_URL = os.environ.get('HOST_URL', 'https://আপনার-ক্লাউড-লিংক.com').rstrip('/')

app = Flask(__name__)
bot = telebot.TeleBot(BOT_TOKEN)

video_cache = {}

# ================= ভিডিও লিংক এক্সট্রাক্টর =================
def extract_direct_url(video_url):
    ydl_opts = {
        # 'best[ext=mp4]' ব্যবহার করা হলো যাতে এটি সবসময় ডিরেক্ট mp4 ভিডিও বের করে
        'format': 'best[ext=mp4]/best', 
        'quiet': True,
        'no_warnings': True,
        'simulate': True,
        'skip_download': True
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            
            direct_url = info.get('url')
            if not direct_url and 'formats' in info and len(info['formats']) > 0:
                direct_url = info['formats'][-1].get('url')
                
            return direct_url
    except Exception as e:
        logger.error(f"Extraction Error: {e}")
        return None

# ================= FLASK ওয়েব পেজ, Webhook এবং PROXY =================

@app.route('/' + BOT_TOKEN, methods=['POST'])
def getMessage():
    json_string = request.get_data().decode('utf-8')
    update = telebot.types.Update.de_json(json_string)
    threading.Thread(target=bot.process_new_updates, args=([update],)).start()
    return "!", 200

@app.route('/')
def webhook():
    bot.remove_webhook()
    bot.set_webhook(url=HOST_URL + '/' + BOT_TOKEN)
    return "Bot is running & Webhook is Set!"

# 🟢 এটি হলো ম্যাজিক প্রক্সি! (যাতে IP Binding ব্লক করতে না পারে)
@app.route('/stream')
def stream_video():
    vid_id = request.args.get('v')
    url = video_cache.get(vid_id)
    if not url:
        return "Link Expired", 404
    
    # ব্রাউজারের মতো ভান করার জন্য হেডার
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://xhamster.com/'
    }
    
    # ভিডিও সামনে-পেছনে টানার (Seek) জন্য Range Header সাপোর্ট
    range_header = request.headers.get('Range', None)
    if range_header:
        headers['Range'] = range_header
        
    req = requests.get(url, stream=True, headers=headers, allow_redirects=True)
    
    response_headers = {
        'Content-Type': req.headers.get('Content-Type', 'video/mp4'),
        'Accept-Ranges': 'bytes'
    }
    if 'Content-Length' in req.headers:
        response_headers['Content-Length'] = req.headers['Content-Length']
    if 'Content-Range' in req.headers:
        response_headers['Content-Range'] = req.headers['Content-Range']

    def generate():
        try:
            for chunk in req.iter_content(chunk_size=1024 * 1024): # 1MB chunks
                if chunk:
                    yield chunk
        finally:
            req.close()

    return Response(stream_with_context(generate()), status=req.status_code, headers=response_headers)


@app.route('/player')
def video_player():
    vid_id = request.args.get('v')
    if not video_cache.get(vid_id):
        return "<h2 style='color:white; text-align:center; margin-top:50px;'>❌ সেশন শেষ!</h2>", 400
    
    # এখন আমরা মূল লিংকের বদলে আমাদের নিজস্ব প্রক্সি লিংকটি প্লেয়ারে দিচ্ছি
    proxy_url = f"{HOST_URL}/stream?v={vid_id}"

    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <meta name="referrer" content="no-referrer">
        <title>Telegram Web Player</title>
        <link href="https://vjs.zencdn.net/8.0.0/video-js.css" rel="stylesheet" />
        <script src="https://telegram.org/js/telegram-web-app.js"></script>
        <style>
            body { margin: 0; background: #000; display: flex; align-items: center; justify-content: center; height: 100vh; overflow: hidden;}
            .video-container { width: 100vw; height: 100vh; }
            .video-js { width: 100%; height: 100%; }
        </style>
    </head>
    <body>
        <div class="video-container">
            <video id="my-player" class="video-js vjs-default-skin" controls autoplay playsinline>
                <source src="{{ proxy_url }}" type="video/mp4">
            </video>
        </div>
        <script src="https://vjs.zencdn.net/8.0.0/video.min.js"></script>
        <script>
            window.Telegram.WebApp.expand();
            var player = videojs('my-player', {
                fluid: false,
                preload: 'auto'
            });
            player.ready(function() { 
                this.play().catch(function(error) {
                    console.log("Autoplay prevented.");
                });
            });
        </script>
    </body>
    </html>
    """
    return render_template_string(html, proxy_url=proxy_url)

# ================= টেলিগ্রাম বট হ্যান্ডলার =================
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "🌍 **Universal Video Player Bot**\n\nযেকোনো ওয়েবসাইটের ভিডিও লিংক আমাকে দিন।")

@bot.message_handler(func=lambda message: True)
def process_url(message):
    url = message.text.strip()
    if not url.startswith("http"):
        bot.reply_to(message, "❌ দয়া করে সঠিক ভিডিও লিংক দিন।")
        return

    msg = bot.reply_to(message, "🔄 *লিংক প্রসেস করা হচ্ছে, অপেক্ষা করুন...*", parse_mode='Markdown')

    try:
        direct_url = extract_direct_url(url)
        
        if direct_url:
            vid_id = str(uuid.uuid4())[:8]
            video_cache[vid_id] = direct_url 
            
            player_link = f"{HOST_URL}/player?v={vid_id}"
            
            markup = InlineKeyboardMarkup()
            web_app = WebAppInfo(url=player_link)
            btn = InlineKeyboardButton(text="▶️ সরাসরি প্লে করুন", web_app=web_app)
            markup.add(btn)
            
            bot.edit_message_text(
                chat_id=message.chat.id, 
                message_id=msg.message_id, 
                text="✅ ভিডিও প্রস্তুত! নিচের বাটনে ক্লিক করে প্লে করুন।",
                reply_markup=markup
            )
        else:
            bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id, text="❌ দুঃখিত, ভিডিও লিংক বের করা যায়নি।")
            
    except Exception as e:
        bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id, text=f"❌ Error: {str(e)}")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))

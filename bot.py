import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from flask import Flask, request, render_template_string
import os
import urllib.parse
import yt_dlp
import logging

# ================= কনফিগারেশন =================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment Variables
BOT_TOKEN = os.environ.get('BOT_TOKEN', 'আপনার_বট_টোকেন')
HOST_URL = os.environ.get('HOST_URL', 'https://আপনার-ক্লাউড-লিংক.com').rstrip('/')

app = Flask(__name__)
bot = telebot.TeleBot(BOT_TOKEN)

# ================= ভিডিও লিংক এক্সট্রাক্টর (yt-dlp) =================
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
            
            direct_url = info.get('url')
            if not direct_url and 'formats' in info and len(info['formats']) > 0:
                direct_url = info['formats'][-1].get('url')
                
            return direct_url
    except Exception as e:
        logger.error(f"Extraction Error: {e}")
        return None

# ================= FLASK ওয়েব পেজ ও Webhook =================

# এই লিংকে টেলিগ্রাম সার্ভার থেকে মেসেজ আসবে (Webhook)
@app.route('/' + BOT_TOKEN, methods=['POST'])
def getMessage():
    json_string = request.get_data().decode('utf-8')
    update = telebot.types.Update.de_json(json_string)
    bot.process_new_updates([update])
    return "!", 200

# মেইন পেজে গেলে Webhook সেট হয়ে যাবে
@app.route('/')
def webhook():
    bot.remove_webhook()
    bot.set_webhook(url=HOST_URL + '/' + BOT_TOKEN)
    return "Universal Telegram Player Bot is running & Webhook is Set!"

@app.route('/player')
def video_player():
    stream_url = request.args.get('url')
    if not stream_url:
        return "❌ ভিডিওর কোনো লিংক পাওয়া যায়নি!", 400
    
    video_type = "application/x-mpegURL" if ".m3u8" in stream_url else "video/mp4"

    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
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
                <source src="{{ stream_url }}" type="{{ video_type }}">
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
    return render_template_string(html, stream_url=stream_url, video_type=video_type)

# ================= টেলিগ্রাম বট হ্যান্ডলার =================
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "🌍 **Universal Video Player Bot**\n\nযেকোনো ওয়েবসাইটের ভিডিও লিংক আমাকে দিন। আমি সেটি টেলিগ্রামের ভেতরেই প্লে করার ব্যবস্থা করে দেব!")

@bot.message_handler(func=lambda message: True)
def process_url(message):
    url = message.text.strip()
    if not url.startswith("http"):
        bot.reply_to(message, "❌ দয়া করে সঠিক ভিডিও লিংক দিন।")
        return

    msg = bot.reply_to(message, "🔄 *সার্ভার লিংক প্রসেস করছে, অপেক্ষা করুন...*", parse_mode='Markdown')

    try:
        direct_url = extract_direct_url(url)
        
        if direct_url:
            encoded_url = urllib.parse.quote(direct_url, safe='')
            player_link = f"{HOST_URL}/player?url={encoded_url}"
            
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
            bot.edit_message_text(
                chat_id=message.chat.id, 
                message_id=msg.message_id, 
                text="❌ দুঃখিত, এই সাইটের ভিডিও লিংক বের করা যায়নি।"
            )
            
    except Exception as e:
        bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id, text=f"❌ Error: {str(e)}")

# ================= সার্ভার রান করা =================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from flask import Flask, request, render_template_string, Response, stream_with_context
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

# মেমোরি ক্যাশ 
video_cache = {}

# ================= 🚀 সুপার এক্সট্রাক্টর (YouTube/FB Bypass) =================
def extract_direct_url(video_url):
    ydl_opts = {
        # m3u8 ব্লক করে শুধুমাত্র সেরা কোয়ালিটির ডিরেক্ট MP4 ফাইল বের করার কমান্ড
        'format': 'best[protocol^=http][ext=mp4]/best[protocol^=http]/best',
        'quiet': True,
        'no_warnings': True,
        'simulate': True,
        'skip_download': True,
        'nocheckcertificate': True,
        # 🟢 YouTube/FB এর সিকিউরিটি বাইপাস করার জন্য অ্যান্ড্রয়েড ডিভাইস স্পুফিং
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web']
            }
        }
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            
            url = info.get('url')
            if not url and 'formats' in info:
                valid_formats = [f for f in info['formats'] if f.get('protocol', '').startswith('http')]
                if valid_formats:
                    url = valid_formats[-1].get('url')
            
            # সার্ভারের আসল হেডারগুলো (Cookies/User-Agent) সেভ করা হচ্ছে
            headers = info.get('http_headers', {})
            return url, headers
    except Exception as e:
        logger.error(f"Extraction Error: {e}")
        return None, None

# ================= Webhook Setup =================
@app.route('/' + BOT_TOKEN, methods=['POST'])
def getMessage():
    json_string = request.get_data().decode('utf-8')
    update = telebot.types.Update.de_json(json_string)
    threading.Thread(target=bot.process_new_updates, args=([update],)).start()
    return "OK", 200

@app.route('/')
def webhook():
    bot.remove_webhook()
    bot.set_webhook(url=HOST_URL + '/' + BOT_TOKEN, drop_pending_updates=True)
    return "✅ Masterpiece Player is Live!"

# ================= ⚡ বাফার-ফ্রি হাই-স্পিড প্রক্সি =================
@app.route('/stream')
def stream_video():
    vid_id = request.args.get('v')
    vid_data = video_cache.get(vid_id)
    
    if not vid_data: 
        return "Video Session Expired", 404
    
    url = vid_data['url']
    original_headers = vid_data['headers']
    
    # yt-dlp এর অরিজিনাল হেডারগুলো ব্যবহার করা হচ্ছে যাতে সাইট ব্লক না করে
    req_headers = {k: v for k, v in original_headers.items()}
    
    if request.headers.get('Range'):
        req_headers['Range'] = request.headers.get('Range')
        
    try:
        r = requests.get(url, headers=req_headers, stream=True, verify=False, allow_redirects=True, timeout=10)
        
        def generate():
            # ২৫৬ কেবি চাংক সাইজ - এটি ক্লাউড সার্ভারের জন্য সবচেয়ে স্মুথ বাফার-ফ্রি এক্সপেরিয়েন্স দেবে
            for chunk in r.iter_content(chunk_size=262144): 
                if chunk: yield chunk

        headers_to_pass = []
        for k, v in r.headers.items():
            if k.lower() in ['content-length', 'content-range', 'accept-ranges', 'content-type']:
                headers_to_pass.append((k, v))
                
        return Response(stream_with_context(generate()), status=r.status_code, headers=headers_to_pass)
        
    except Exception as e:
        logger.error(f"Proxy Error: {e}")
        return "Streaming Error", 500

# ================= Native HTML5 Player (Fastest) =================
@app.route('/player')
def video_player():
    vid_id = request.args.get('v')
    if not video_cache.get(vid_id):
        return "<h2 style='color:red; text-align:center; margin-top:50px;'>❌ সেশন শেষ! নতুন লিংক দিন।</h2>", 400
    
    proxy_url = f"{HOST_URL}/stream?v={vid_id}"

    # থার্ড-পার্টি প্লেয়ার বাদ দিয়ে নেটিভ প্লেয়ার দেওয়া হলো, যাতে কোনো ল্যাগ না করে
    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>Telegram Smart Player</title>
        <script src="https://telegram.org/js/telegram-web-app.js"></script>
        <style>
            body { margin: 0; padding: 0; background: #000; height: 100vh; display: flex; justify-content: center; align-items: center; overflow: hidden; }
            video { width: 100%; max-height: 100vh; outline: none; background: #000; }
        </style>
    </head>
    <body>
        <video id="video" controls playsinline preload="auto">
            <source src="{{ proxy_url }}" type="video/mp4">
        </video>
        <script>
            window.Telegram.WebApp.expand();
            window.Telegram.WebApp.ready();
            var video = document.getElementById('video');
            video.play().catch(e => console.log("Autoplay blocked"));
        </script>
    </body>
    </html>
    """
    return render_template_string(html, proxy_url=proxy_url)

# ================= বট কমান্ডস =================
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "🌍 **Ultimate Video Player Bot**\n\nYouTube, Facebook বা যেকোনো সাইটের ভিডিও লিংক দিন!")

@bot.message_handler(func=lambda message: True)
def process_url(message):
    url = message.text.strip()
    if not url.startswith("http"):
        bot.reply_to(message, "❌ সঠিক ভিডিও লিংক দিন।")
        return

    msg = bot.reply_to(message, "🔄 *সার্ভার হাই-কোয়ালিটি লিংক খুঁজছে...*", parse_mode='Markdown')

    try:
        extracted_url, headers = extract_direct_url(url)
        
        if extracted_url:
            vid_id = str(uuid.uuid4())[:8]
            video_cache[vid_id] = {'url': extracted_url, 'headers': headers}
            
            player_link = f"{HOST_URL}/player?v={vid_id}"
            
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton(text="▶️ প্লে করুন", web_app=WebAppInfo(url=player_link)))
            
            bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id, text="✅ ভিডিও প্রস্তুত! নিচের বাটনে ক্লিক করে প্লে করুন।", reply_markup=markup)
        else:
            bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id, text="❌ লিংক বের করা যায়নি। ভিডিওটি হয়তো প্রাইভেট অথবা সাইট ব্লক করেছে।")
    except Exception as e:
        bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id, text=f"❌ Error: {str(e)}")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)), threaded=True)

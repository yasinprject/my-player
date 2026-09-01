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

video_cache = {}

# ================= ইউনিভার্সাল এক্সট্রাক্টর =================
def extract_direct_url(video_url):
    ydl_opts = {
        'format': 'best',
        'quiet': True,
        'no_warnings': True,
        'simulate': True,
        'skip_download': True,
        'nocheckcertificate': True
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            url = info.get('url')
            if not url and 'formats' in info:
                url = info['formats'][-1].get('url')
            
            # ভিডিওটি m3u8 নাকি mp4 তা ডিটেক্ট করা হচ্ছে
            is_m3u8 = True if url and ('.m3u8' in url or info.get('protocol') == 'm3u8_native') else False
            return url, is_m3u8
    except Exception as e:
        logger.error(f"Extraction Error: {e}")
        return None, False

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
    return "✅ Ultimate Telegram Player is Live!"

# ================= 🚀 সুপার প্রক্সি সার্ভার =================
@app.route('/stream')
def stream_video():
    vid_id = request.args.get('v')
    vid_data = video_cache.get(vid_id)
    
    if not vid_data: 
        return "Video Session Expired", 404
    
    url = vid_data['url']
    
    req_headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://xhamster.com/'
    }
    
    if request.headers.get('Range'):
        req_headers['Range'] = request.headers.get('Range')
        
    try:
        r = requests.get(url, headers=req_headers, stream=True, verify=False, allow_redirects=True, timeout=15)
        
        def generate():
            # বাফারিং এড়াতে চাংক সাইজ ছোট (8KB) করা হয়েছে
            for chunk in r.iter_content(chunk_size=8192): 
                if chunk: yield chunk

        resp = Response(generate(), status=r.status_code)
        
        for k, v in r.headers.items():
            if k.lower() in ['content-length', 'content-range', 'accept-ranges', 'content-type']:
                resp.headers[k] = v
        return resp
        
    except Exception as e:
        logger.error(f"Proxy Error: {e}")
        return "Streaming Error", 500

# ================= HLS.js + HTML5 Smart Player =================
@app.route('/player')
def video_player():
    vid_id = request.args.get('v')
    vid_data = video_cache.get(vid_id)
    
    if not vid_data:
        return "<h2 style='color:red; text-align:center; margin-top:50px;'>❌ সেশন শেষ! নতুন লিংক দিন।</h2>", 400
    
    url = vid_data['url']
    is_m3u8 = vid_data['is_m3u8']
    
    # m3u8 হলে সরাসরি লিংক দেবো (HLS.js হ্যান্ডেল করবে), mp4 হলে প্রক্সি ব্যবহার করবো
    stream_url = url if is_m3u8 else f"{HOST_URL}/stream?v={vid_id}"

    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>Telegram Video Player</title>
        <script src="https://telegram.org/js/telegram-web-app.js"></script>
        <!-- HLS.js লাইব্রেরি যুক্ত করা হলো (m3u8 এর জন্য) -->
        <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
        <style>
            body { margin: 0; padding: 0; background: #000; height: 100vh; display: flex; justify-content: center; align-items: center; overflow: hidden; }
            video { width: 100%; max-height: 100vh; outline: none; background: #000; }
        </style>
    </head>
    <body>
        <video id="video" controls playsinline></video>
        <script>
            window.Telegram.WebApp.expand();
            window.Telegram.WebApp.ready();
            
            var video = document.getElementById('video');
            var source = "{{ stream_url }}";
            var is_m3u8 = "{{ is_m3u8 }}" === "True";

            if (is_m3u8 && Hls.isSupported()) {
                var hls = new Hls({
                    maxMaxBufferLength: 30,
                    startLevel: -1
                });
                hls.loadSource(source);
                hls.attachMedia(video);
                hls.on(Hls.Events.MANIFEST_PARSED, function() {
                    video.play().catch(e => console.log(e));
                });
            } 
            else if (video.canPlayType('application/vnd.apple.mpegurl')) {
                video.src = source;
                video.addEventListener('loadedmetadata', function() {
                    video.play().catch(e => console.log(e));
                });
            } 
            else {
                video.src = source;
                video.play().catch(e => console.log(e));
            }
        </script>
    </body>
    </html>
    """
    return render_template_string(html, stream_url=stream_url, is_m3u8=is_m3u8)

# ================= বট কমান্ডস =================
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "🌍 **Ultimate Video Player Bot**\n\nযেকোনো সাইটের ভিডিও লিংক দিন!")

@bot.message_handler(func=lambda message: True)
def process_url(message):
    url = message.text.strip()
    if not url.startswith("http"):
        bot.reply_to(message, "❌ সঠিক ভিডিও লিংক দিন।")
        return

    msg = bot.reply_to(message, "🔄 *সার্ভার লিংক প্রসেস করছে, দয়া করে অপেক্ষা করুন...*", parse_mode='Markdown')

    try:
        extracted_url, is_m3u8 = extract_direct_url(url)
        
        if extracted_url:
            vid_id = str(uuid.uuid4())[:8]
            video_cache[vid_id] = {'url': extracted_url, 'is_m3u8': is_m3u8}
            
            player_link = f"{HOST_URL}/player?v={vid_id}"
            
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton(text="▶️ সরাসরি প্লে করুন", web_app=WebAppInfo(url=player_link)))
            
            bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id, text="✅ ভিডিও প্রস্তুত! নিচের বাটনে ক্লিক করে প্লে করুন।", reply_markup=markup)
        else:
            bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id, text="❌ লিংক বের করা যায়নি। সাইটটির কড়া সিকিউরিটি থাকতে পারে।")
    except Exception as e:
        bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id, text=f"❌ Error: {str(e)}")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)), threaded=True)

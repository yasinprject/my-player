import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from flask import Flask, request, render_template_string, Response, stream_with_context
import os
import yt_dlp
import logging
import uuid
import requests
import threading
import base64
from urllib.parse import urljoin

# ================= কনফিগারেশন =================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get('BOT_TOKEN', 'আপনার_টোকেন_দিন')
HOST_URL = os.environ.get('HOST_URL', 'আপনার_ক্লাউড_লিংক').rstrip('/')

app = Flask(__name__)
bot = telebot.TeleBot(BOT_TOKEN)

# ভিডিও ক্যাশ (লিংক ও হেডার সেভ রাখার জন্য)
video_cache = {}

# ================= 🚀 আলটিমেট এক্সট্রাক্টর (IP/Bot Bypass) =================
def extract_direct_url(video_url):
    ydl_opts = {
        # MP4 কে অগ্রাধিকার দেওয়া হবে, না পেলে m3u8 নেওয়া হবে
        'format': 'best[ext=mp4]/best',
        'quiet': True,
        'no_warnings': True,
        'simulate': True,
        'skip_download': True,
        'nocheckcertificate': True,
        # YouTube/FB বাইপাস করার জন্য অ্যান্ড্রয়েড এবং ওয়েব স্পুফিং
        'extractor_args': {
            'youtube': {'player_client': ['android', 'web']}
        }
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            
            url = info.get('url')
            if not url and 'formats' in info:
                url = info['formats'][-1].get('url')
            
            headers = info.get('http_headers', {})
            
            # ভিডিওটি m3u8 কি না তা ডিটেক্ট করা
            protocol = info.get('protocol', '')
            is_m3u8 = True if 'm3u8' in protocol or (url and '.m3u8' in url.lower()) else False
            
            return url, headers, is_m3u8
    except Exception as e:
        logger.error(f"Extraction Error: {e}")
        return None, None, False

# ================= Webhook =================
@app.route('/' + BOT_TOKEN, methods=['POST'])
def getMessage():
    update = telebot.types.Update.de_json(request.get_data().decode('utf-8'))
    threading.Thread(target=bot.process_new_updates, args=([update],)).start()
    return "OK", 200

@app.route('/')
def webhook():
    bot.remove_webhook()
    bot.set_webhook(url=HOST_URL + '/' + BOT_TOKEN, drop_pending_updates=True)
    return "✅ Master Deep Proxy Server is Live!"

# ================= ⚡ Deep Proxy Server (ম্যাজিক এখানেই) =================
@app.route('/proxy')
def deep_proxy():
    vid_id = request.args.get('v')
    b64_url = request.args.get('u')
    
    if not b64_url or not video_cache.get(vid_id):
        return "Expired", 404
        
    # লিংক ডিকোড করা
    url = base64.urlsafe_b64decode(b64_url).decode('utf-8')
    vid_data = video_cache[vid_id]
    
    # অরিজিনাল সাইটের হেডার ব্যবহার করা (CORS ও IP Lock বাইপাস)
    req_headers = {k: v for k, v in vid_data['headers'].items()}
    if request.headers.get('Range'):
        req_headers['Range'] = request.headers.get('Range')
        
    try:
        r = requests.get(url, headers=req_headers, stream=True, verify=False, allow_redirects=True, timeout=15)
        content_type = r.headers.get('Content-Type', '')
        
        # 🟢 ম্যাজিক: যদি ফাইলটি m3u8 (প্লেলিস্ট) হয়, তবে এর ভেতরের সব লিংক হ্যাক করে প্রক্সিতে ডাইভার্ট করা হবে
        if 'mpegurl' in content_type or url.endswith('.m3u8') or 'm3u8' in url:
            new_lines = []
            for line in r.text.splitlines():
                line = line.strip()
                if not line: continue
                if line.startswith('#'):
                    new_lines.append(line)
                else:
                    # ভেতরের ভিডিও খণ্ডগুলোকে (TS) প্রক্সির মাধ্যমে পাস করানো
                    abs_url = urljoin(r.url, line)
                    encoded_ts = base64.urlsafe_b64encode(abs_url.encode()).decode('utf-8')
                    new_lines.append(f"{HOST_URL}/proxy?v={vid_id}&u={encoded_ts}")
            
            return Response('\n'.join(new_lines), mimetype='application/vnd.apple.mpegurl')
            
        # 🟢 আর যদি সাধারণ ভিডিও বা TS ফাইল হয়, তবে বাফার-ফ্রি স্ট্রিম করা হবে
        else:
            def generate():
                for chunk in r.iter_content(chunk_size=524288): # 512 KB Chunk
                    if chunk: yield chunk
                    
            headers_to_pass = {}
            for k, v in r.headers.items():
                if k.lower() in ['content-length', 'content-range', 'accept-ranges', 'content-type']:
                    headers_to_pass[k] = v
                    
            return Response(stream_with_context(generate()), status=r.status_code, headers=headers_to_pass)
            
    except Exception as e:
        logger.error(f"Proxy Error: {e}")
        return "Error", 500

# ================= 🎬 Smart Player =================
@app.route('/player')
def video_player():
    vid_id = request.args.get('v')
    vid_data = video_cache.get(vid_id)
    
    if not vid_data:
        return "<h2 style='color:red; text-align:center; margin-top:50px;'>❌ লিংক এক্সপায়ার হয়েছে! নতুন লিংক দিন।</h2>", 400
    
    is_m3u8 = vid_data['is_m3u8']
    encoded_main_url = base64.urlsafe_b64encode(vid_data['url'].encode()).decode('utf-8')
    proxy_url = f"{HOST_URL}/proxy?v={vid_id}&u={encoded_main_url}"

    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>Telegram Smart Player</title>
        <script src="https://telegram.org/js/telegram-web-app.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
        <style>
            body { margin: 0; padding: 0; background: #000; height: 100vh; display: flex; justify-content: center; align-items: center; overflow: hidden; }
            video { width: 100%; max-height: 100vh; outline: none; background: #000; }
        </style>
    </head>
    <body>
        <video id="video" controls playsinline preload="auto"></video>
        <script>
            window.Telegram.WebApp.expand();
            window.Telegram.WebApp.ready();
            
            var video = document.getElementById('video');
            var source = "{{ proxy_url }}";
            var is_m3u8 = "{{ is_m3u8 }}" === "True";

            if (is_m3u8 && Hls.isSupported()) {
                var hls = new Hls({ maxMaxBufferLength: 30 });
                hls.loadSource(source);
                hls.attachMedia(video);
                hls.on(Hls.Events.MANIFEST_PARSED, function() {
                    video.play().catch(e => console.log("Auto-play blocked"));
                });
            } else {
                video.src = source;
                video.play().catch(e => console.log("Auto-play blocked"));
            }
        </script>
    </body>
    </html>
    """
    return render_template_string(html, proxy_url=proxy_url, is_m3u8=is_m3u8)

# ================= বট কমান্ডস =================
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "🌍 **Ultimate Deep Proxy Bot**\n\nYouTube, FB, xHamster বা যেকোনো সাইটের লিংক দিন!")

@bot.message_handler(func=lambda message: True)
def process_url(message):
    url = message.text.strip()
    if not url.startswith("http"):
        bot.reply_to(message, "❌ সঠিক ভিডিও লিংক দিন।")
        return

    msg = bot.reply_to(message, "🔄 *সার্ভার ফাস্ট লিংক খুঁজছে, একটু সময় দিন...*", parse_mode='Markdown')

    try:
        extracted_url, headers, is_m3u8 = extract_direct_url(url)
        
        if extracted_url:
            vid_id = str(uuid.uuid4())[:8]
            video_cache[vid_id] = {'url': extracted_url, 'headers': headers, 'is_m3u8': is_m3u8}
            
            player_link = f"{HOST_URL}/player?v={vid_id}"
            
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton(text="▶️ প্লে করুন", web_app=WebAppInfo(url=player_link)))
            
            bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id, text="✅ ভিডিও প্রস্তুত! নিচের বাটনে ক্লিক করে প্লে করুন।", reply_markup=markup)
        else:
            bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id, text="❌ লিংক বের করা যায়নি। ভিডিওটি প্রাইভেট হতে পারে।")
    except Exception as e:
        bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id, text=f"❌ Error: {str(e)}")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)), threaded=True)

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

video_cache = {}

# ================= 🚀 স্মার্ট এক্সট্রাক্টর (MP4 Priority) =================
def extract_direct_url(video_url):
    ydl_opts = {
        'format': 'best',
        'quiet': True,
        'no_warnings': True,
        'simulate': True,
        'skip_download': True,
        'nocheckcertificate': True,
        # YouTube/FB এর সিকিউরিটি ভাঙার জন্য অ্যান্ড্রয়েড স্পুফিং
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web']
            }
        }
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            
            url = None
            is_m3u8 = False
            formats = info.get('formats', [])
            
            # প্রথমে সাইটের সার্ভার থেকে সবচেয়ে ভালো MP4 ফাইলটি খোঁজার চেষ্টা
            valid_mp4s = [f for f in formats if f.get('ext') == 'mp4' and 'm3u8' not in f.get('protocol', '') and 'dash' not in f.get('protocol', '')]
            if valid_mp4s:
                url = valid_mp4s[-1].get('url')  # সবচেয়ে হাই-কোয়ালিটি MP4
            
            # MP4 না পেলে ডিফল্ট লিংক নেওয়া হবে
            if not url:
                url = info.get('url') or (formats[-1].get('url') if formats else None)
            
            # লিংকটি m3u8 (HLS) কি না তা চেক করা হচ্ছে
            protocol = info.get('protocol', '')
            if 'm3u8' in protocol or (url and '.m3u8' in url.lower()):
                is_m3u8 = True
                
            headers = info.get('http_headers', {})
            return url, headers, is_m3u8
    except Exception as e:
        logger.error(f"Extraction Error: {e}")
        return None, None, False

# ================= Webhook =================
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
    return "✅ Smart Hybrid Player is Live!"

# ================= ⚡ বাফার-ফ্রি প্রক্সি (শুধু MP4 এর জন্য) =================
@app.route('/stream')
def stream_video():
    vid_id = request.args.get('v')
    vid_data = video_cache.get(vid_id)
    
    if not vid_data: 
        return "Video Session Expired", 404
    
    url = vid_data['url']
    req_headers = {k: v for k, v in vid_data['headers'].items()}
    
    if request.headers.get('Range'):
        req_headers['Range'] = request.headers.get('Range')
        
    try:
        r = requests.get(url, headers=req_headers, stream=True, verify=False, allow_redirects=True, timeout=10)
        
        def generate():
            for chunk in r.iter_content(chunk_size=262144): # 256KB Chunk for smooth streaming
                if chunk: yield chunk

        headers_to_pass = []
        for k, v in r.headers.items():
            if k.lower() in ['content-length', 'content-range', 'accept-ranges', 'content-type']:
                headers_to_pass.append((k, v))
                
        return Response(stream_with_context(generate()), status=r.status_code, headers=headers_to_pass)
        
    except Exception as e:
        logger.error(f"Proxy Error: {e}")
        return "Streaming Error", 500

# ================= 🎬 Hybrid Smart Player (HLS + MP4) =================
@app.route('/player')
def video_player():
    vid_id = request.args.get('v')
    vid_data = video_cache.get(vid_id)
    
    if not vid_data:
        return "<h2 style='color:red; text-align:center; font-family:sans-serif; margin-top:50px;'>❌ সেশন শেষ! টেলিগ্রামে গিয়ে নতুন লিংক দিন।</h2>", 400
    
    is_m3u8 = vid_data['is_m3u8']
    
    # যদি m3u8 হয়, সরাসরি অরিজিনাল লিংক প্লেয়ারে যাবে। আর mp4 হলে প্রক্সি হয়ে যাবে।
    stream_url = vid_data['url'] if is_m3u8 else f"{HOST_URL}/stream?v={vid_id}"

    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>Telegram Smart Player</title>
        <script src="https://telegram.org/js/telegram-web-app.js"></script>
        <!-- HLS.js লাইব্রেরি -->
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
            var source = "{{ stream_url }}";
            var is_m3u8 = "{{ is_m3u8 }}" === "True";

            // যদি ভিডিও m3u8 হয়, HLS.js দিয়ে ডিকোড করা হবে
            if (is_m3u8 && Hls.isSupported()) {
                var hls = new Hls({ maxMaxBufferLength: 30 });
                hls.loadSource(source);
                hls.attachMedia(video);
                hls.on(Hls.Events.MANIFEST_PARSED, function() {
                    video.play().catch(e => console.log("Autoplay blocked"));
                });
            } 
            // যদি Apple Device হয় অথবা ডিরেক্ট MP4 হয়
            else {
                video.src = source;
                video.play().catch(e => console.log("Autoplay blocked"));
            }
        </script>
    </body>
    </html>
    """
    return render_template_string(html, stream_url=stream_url, is_m3u8=is_m3u8)

# ================= বট কমান্ডস =================
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "🌍 **Ultimate Video Player Bot**\n\nYouTube, Facebook, xHamster বা যেকোনো সাইটের ভিডিও লিংক দিন!")

@bot.message_handler(func=lambda message: True)
def process_url(message):
    url = message.text.strip()
    if not url.startswith("http"):
        bot.reply_to(message, "❌ সঠিক ভিডিও লিংক দিন।")
        return

    msg = bot.reply_to(message, "🔄 *সার্ভার লিংক প্রসেস করছে...*", parse_mode='Markdown')

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
            bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id, text="❌ লিংক বের করা যায়নি।")
    except Exception as e:
        bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id, text=f"❌ Error: {str(e)}")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)), threaded=True)

"""
Vaultly yt-dlp microservice — Render.com free tier
"""
import os, json, subprocess, re
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# ── helpers ───────────────────────────────────────────────────────────────────

QUALITY_MAP = {
    'mp4_480':  {'format': 'best[height<=480][ext=mp4]/best[height<=480]/best', 'ext': 'mp4'},
    'mp4_720':  {'format': 'best[height<=720][ext=mp4]/best[height<=720]/best', 'ext': 'mp4'},
    'mp4_1080': {'format': 'best[height<=1080][ext=mp4]/best[height<=1080]/best', 'ext': 'mp4'},
    'mp4_4k':   {'format': 'best', 'ext': 'mp4'},
    'mp3_128':  {'format': 'bestaudio[ext=m4a]/bestaudio', 'ext': 'mp3', 'audio_only': True},
    'mp3_320':  {'format': 'bestaudio', 'ext': 'mp3', 'audio_only': True},
}

# Base yt-dlp flags that work without a JS runtime
BASE_FLAGS = [
    '--no-playlist',
    '--no-warnings',
    '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
]

def run_ytdlp(args, timeout=55):
    cmd = ['yt-dlp'] + args
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return r.stdout, r.stderr, r.returncode

# ── routes ────────────────────────────────────────────────────────────────────

@app.route('/', methods=['GET'])
def health():
    v = subprocess.run(['yt-dlp', '--version'], capture_output=True, text=True).stdout.strip()
    node = subprocess.run(['which', 'node'], capture_output=True, text=True).stdout.strip()
    return jsonify({'status': 'ok', 'ytdlp': v, 'node': node or 'not found'})

@app.route('/ping', methods=['GET'])
def ping():
    return jsonify({'pong': True})

@app.route('/debug', methods=['GET'])
def debug():
    url = request.args.get('url', 'https://youtu.be/dQw4w9WgXcQ')
    stdout, stderr, code = run_ytdlp(BASE_FLAGS + ['--dump-json', '--quiet', url])
    return jsonify({
        'code': code,
        'stdout': stdout[:400] if stdout else '',
        'stderr': stderr[:600] if stderr else '',
        'node': subprocess.run(['which', 'node'], capture_output=True, text=True).stdout.strip(),
        'ytdlp': subprocess.run(['yt-dlp', '--version'], capture_output=True, text=True).stdout.strip(),
    })

@app.route('/info', methods=['GET'])
def get_info():
    url = request.args.get('url', '').strip()
    if not url:
        return jsonify({'success': False, 'error': 'url param required'}), 400
    # Strip tracking params from YouTube share links
    url = re.sub(r'[?&]si=[^&]+', '', url)
    try:
        stdout, stderr, code = run_ytdlp(BASE_FLAGS + ['--dump-json', '--quiet', url])
        if code != 0 or not stdout.strip():
            return jsonify({'success': False, 'error': stderr[:200] or 'Could not fetch video info.'}), 400
        info = json.loads(stdout.strip().split('\n')[0])
        secs = info.get('duration', 0) or 0
        thumbnail = info.get('thumbnail') or (
            sorted(info.get('thumbnails', []), key=lambda t: t.get('width') or 0, reverse=True)[0].get('url')
            if info.get('thumbnails') else None
        )
        return jsonify({'success': True, 'data': {
            'title':     info.get('title', 'Media file'),
            'thumbnail': thumbnail,
            'duration':  f"{int(secs//60)}:{int(secs%60):02d}" if secs else None,
            'platform':  info.get('extractor_key', 'Unknown'),
            'url':       url,
        }})
    except subprocess.TimeoutExpired:
        return jsonify({'success': False, 'error': 'Timed out. Try again.'}), 504
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/download', methods=['GET'])
def get_download_url():
    url    = request.args.get('url', '').strip()
    fmt_id = request.args.get('format', 'mp4_480').strip()
    if not url:
        return jsonify({'success': False, 'error': 'url param required'}), 400
    url = re.sub(r'[?&]si=[^&]+', '', url)
    fmt = QUALITY_MAP.get(fmt_id, QUALITY_MAP['mp4_480'])
    try:
        stdout, stderr, code = run_ytdlp(BASE_FLAGS + [
            '--get-url', '--quiet', '-f', fmt['format'], url
        ])
        if code != 0 or not stdout.strip():
            # fallback to absolute best
            stdout, stderr, code = run_ytdlp(BASE_FLAGS + ['--get-url', '--quiet', '-f', 'best', url])
        urls = [u.strip() for u in stdout.strip().split('\n') if u.strip().startswith('http')]
        if not urls:
            return jsonify({'success': False, 'error': f'No stream found. yt-dlp: {stderr[:200]}'}), 404
        # get title for filename
        t_out, _, _ = run_ytdlp(BASE_FLAGS + ['--print', 'title', '--quiet', url])
        title = (t_out.strip().split('\n')[0] if t_out.strip() else 'vaultly_download')
        safe  = re.sub(r'[^\w\s-]', '', title).strip().replace(' ', '_')[:60]
        return jsonify({'success': True, 'downloadUrl': urls[0], 'filename': f"{safe}.{fmt['ext']}", 'allUrls': urls})
    except subprocess.TimeoutExpired:
        return jsonify({'success': False, 'error': 'Timed out. Try again.'}), 504
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

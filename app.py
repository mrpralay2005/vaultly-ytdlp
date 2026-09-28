"""
Vaultly yt-dlp microservice — Render.com free tier
Uses yt-dlp with iOS client to bypass YouTube bot detection on datacenter IPs.
"""
import os, json, subprocess, re
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

QUALITY_MAP = {
    'mp4_480':  {'format': 'best[height<=480]/best', 'ext': 'mp4'},
    'mp4_720':  {'format': 'best[height<=720]/best', 'ext': 'mp4'},
    'mp4_1080': {'format': 'best[height<=1080]/best', 'ext': 'mp4'},
    'mp4_4k':   {'format': 'best', 'ext': 'mp4'},
    'mp3_128':  {'format': 'bestaudio', 'ext': 'mp3', 'audio_only': True},
    'mp3_320':  {'format': 'bestaudio', 'ext': 'mp3', 'audio_only': True},
}

# Use iOS client — bypasses bot detection without cookies on datacenter IPs
BASE_FLAGS = [
    '--no-playlist',
    '--no-warnings',
    '--extractor-args', 'youtube:player_client=ios',
]

def run_ytdlp(args, timeout=55):
    cmd = ['yt-dlp'] + args
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return r.stdout, r.stderr, r.returncode

def clean_url(url):
    # Strip YouTube share tracking params
    return re.sub(r'[?&]si=[^&]+', '', url).rstrip('?&')

# ── routes ────────────────────────────────────────────────────────────────────

@app.route('/', methods=['GET'])
def health():
    v = subprocess.run(['yt-dlp', '--version'], capture_output=True, text=True).stdout.strip()
    return jsonify({'status': 'ok', 'ytdlp': v})

@app.route('/ping', methods=['GET'])
def ping():
    return jsonify({'pong': True})

@app.route('/debug', methods=['GET'])
def debug():
    url = request.args.get('url', 'https://youtu.be/dQw4w9WgXcQ')
    stdout, stderr, code = run_ytdlp(BASE_FLAGS + ['--dump-json', '--quiet', url])
    return jsonify({
        'code': code,
        'stdout': stdout[:300] if stdout else '',
        'stderr': stderr[:800] if stderr else '',
        'ytdlp': subprocess.run(['yt-dlp', '--version'], capture_output=True, text=True).stdout.strip(),
    })

@app.route('/info', methods=['GET'])
def get_info():
    url = clean_url(request.args.get('url', '').strip())
    if not url:
        return jsonify({'success': False, 'error': 'url param required'}), 400
    try:
        stdout, stderr, code = run_ytdlp(BASE_FLAGS + ['--dump-json', '--quiet', url])
        if code != 0 or not stdout.strip():
            return jsonify({'success': False, 'error': stderr[:300] or 'Could not fetch video info.'}), 400
        info = json.loads(stdout.strip().split('\n')[0])
        secs = info.get('duration', 0) or 0
        thumbs = info.get('thumbnails', [])
        thumbnail = (
            sorted(thumbs, key=lambda t: t.get('width') or 0, reverse=True)[0].get('url')
            if thumbs else info.get('thumbnail')
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
    url    = clean_url(request.args.get('url', '').strip())
    fmt_id = request.args.get('format', 'mp4_480').strip()
    if not url:
        return jsonify({'success': False, 'error': 'url param required'}), 400
    fmt = QUALITY_MAP.get(fmt_id, QUALITY_MAP['mp4_480'])
    try:
        stdout, stderr, code = run_ytdlp(BASE_FLAGS + [
            '--get-url', '--quiet', '-f', fmt['format'], url
        ])
        if code != 0 or not stdout.strip():
            stdout, stderr, code = run_ytdlp(BASE_FLAGS + ['--get-url', '--quiet', '-f', 'best', url])
        urls = [u.strip() for u in stdout.strip().split('\n') if u.strip().startswith('http')]
        if not urls:
            return jsonify({'success': False, 'error': f'No stream found: {stderr[:300]}'}), 404
        t_out, _, _ = run_ytdlp(BASE_FLAGS + ['--print', 'title', '--quiet', url])
        title = t_out.strip().split('\n')[0] if t_out.strip() else 'vaultly_download'
        safe  = re.sub(r'[^\w\s-]', '', title).strip().replace(' ', '_')[:60]
        return jsonify({'success': True, 'downloadUrl': urls[0], 'filename': f"{safe}.{fmt['ext']}", 'allUrls': urls})
    except subprocess.TimeoutExpired:
        return jsonify({'success': False, 'error': 'Timed out. Try again.'}), 504
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

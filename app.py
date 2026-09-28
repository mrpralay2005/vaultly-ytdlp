"""
Vaultly yt-dlp microservice
Runs on Render.com free tier — no rate limits, no API keys needed.
"""

import os, json, subprocess, re
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# Auto-update yt-dlp to latest on startup (prevents YouTube blocking old versions)
try:
    subprocess.run(['yt-dlp', '-U'], capture_output=True, timeout=30)
except Exception:
    pass

# ── helpers ───────────────────────────────────────────────────────────────────

QUALITY_MAP = {
    'mp4_480':  {'format': 'bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]/best[height<=480]', 'ext': 'mp4'},
    'mp4_720':  {'format': 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best[height<=720]', 'ext': 'mp4'},
    'mp4_1080': {'format': 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best[height<=1080]', 'ext': 'mp4'},
    'mp4_4k':   {'format': 'bestvideo[height<=2160][ext=mp4]+bestaudio[ext=m4a]/best[height<=2160]', 'ext': 'mp4'},
    'mp3_128':  {'format': 'bestaudio[ext=m4a]/bestaudio', 'ext': 'mp3', 'audio_only': True},
    'mp3_320':  {'format': 'bestaudio', 'ext': 'mp3', 'audio_only': True},
}

def run_ytdlp(args):
    """Run yt-dlp as subprocess and return (stdout, stderr, returncode)."""
    cmd = ['yt-dlp'] + args
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    return result.stdout, result.stderr, result.returncode


# ── routes ────────────────────────────────────────────────────────────────────

@app.route('/', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'service': 'vaultly-ytdlp'})

@app.route('/ping', methods=['GET'])
def ping():
    """Keep-alive endpoint — called by the frontend every 10 min."""
    return jsonify({'pong': True})


@app.route('/info', methods=['GET'])
def get_info():
    """
    GET /info?url=<video_url>
    Returns title, thumbnail, duration, platform.
    """
    url = request.args.get('url', '').strip()
    if not url:
        return jsonify({'success': False, 'error': 'url param required'}), 400

    try:
        stdout, stderr, code = run_ytdlp([
            '--dump-json', '--no-playlist',
            '--no-warnings', '--quiet',
            '--extractor-args', 'youtube:skip=dash,hls',
            '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            url
        ])
        if code != 0 or not stdout.strip():
            print('yt-dlp stderr:', stderr[:300])
            return jsonify({'success': False, 'error': 'Could not fetch video info. Check the URL.'}), 400

        info = json.loads(stdout.strip().split('\n')[0])
        duration_secs = info.get('duration', 0)
        mins = int(duration_secs // 60)
        secs = int(duration_secs % 60)

        # Pick best thumbnail
        thumbnails = info.get('thumbnails', [])
        thumbnail = None
        if thumbnails:
            # prefer highest resolution
            sorted_thumbs = sorted(thumbnails, key=lambda t: (t.get('width') or 0), reverse=True)
            thumbnail = sorted_thumbs[0].get('url')
        if not thumbnail:
            thumbnail = info.get('thumbnail')

        return jsonify({
            'success': True,
            'data': {
                'title':     info.get('title', 'Media file'),
                'thumbnail': thumbnail,
                'duration':  f"{mins}:{secs:02d}" if duration_secs else None,
                'platform':  info.get('extractor_key', 'Unknown'),
                'uploader':  info.get('uploader', ''),
                'url':       url,
            }
        })
    except subprocess.TimeoutExpired:
        return jsonify({'success': False, 'error': 'Request timed out. Try again.'}), 504
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/download', methods=['GET'])
def get_download_url():
    """
    GET /download?url=<video_url>&format=mp4_480
    Returns a direct stream URL the browser can download.
    """
    url      = request.args.get('url', '').strip()
    fmt_id   = request.args.get('format', 'mp4_480').strip()

    if not url:
        return jsonify({'success': False, 'error': 'url param required'}), 400

    fmt = QUALITY_MAP.get(fmt_id, QUALITY_MAP['mp4_480'])
    is_audio = fmt.get('audio_only', False)

    try:
        # Get the direct URL without downloading
        args = [
            '--get-url', '--no-playlist',
            '--no-warnings', '--quiet',
            '--extractor-args', 'youtube:skip=dash,hls',
            '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            '-f', fmt['format'],
            url
        ]
        stdout, stderr, code = run_ytdlp(args)

        if code != 0 or not stdout.strip():
            # fallback — try simpler format
            stdout, stderr, code = run_ytdlp([
                '--get-url', '--no-playlist',
                '--no-warnings', '--quiet',
                '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                '-f', 'best',
                url
            ])

        urls = [u.strip() for u in stdout.strip().split('\n') if u.strip().startswith('http')]
        if not urls:
            return jsonify({'success': False, 'error': 'No downloadable stream found.'}), 404

        # For merged video+audio, yt-dlp may return 2 URLs (video + audio)
        # We return the first (best video or audio-only)
        download_url = urls[0]

        # Get title for filename
        title_stdout, _, _ = run_ytdlp([
            '--print', 'title', '--no-playlist',
            '--no-warnings', '--quiet',
            url
        ])
        title = title_stdout.strip().split('\n')[0] if title_stdout.strip() else 'vaultly_download'
        # sanitise filename
        safe_title = re.sub(r'[^\w\s-]', '', title).strip().replace(' ', '_')[:60]
        filename = f"{safe_title}.{fmt['ext']}"

        return jsonify({
            'success':      True,
            'downloadUrl':  download_url,
            'filename':     filename,
            'allUrls':      urls,   # video + audio if separate
        })

    except subprocess.TimeoutExpired:
        return jsonify({'success': False, 'error': 'Request timed out. Try again.'}), 504
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

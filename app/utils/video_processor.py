import os, subprocess, json
from datetime import datetime, timezone


def get_video_info(filepath, ffprobe_path='ffprobe'):
    try:
        cmd = [ffprobe_path, '-v', 'quiet', '-print_format', 'json',
               '-show_streams', '-show_format', filepath]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return json.loads(result.stdout)
    except Exception as e:
        print(f'ffprobe error: {e}')
    return None


def generate_thumbnail(filepath, output_path, time_offset=None, size=(640, 360)):
    try:
        if time_offset is None:
            info = get_video_info(filepath)
            duration = float(info.get('format', {}).get('duration', 10)) if info else 10
            time_offset = max(1, duration * 0.1)
        cmd = ['ffmpeg', '-y', '-ss', str(time_offset), '-i', filepath,
               '-vframes', '1',
               '-vf', f'scale={size[0]}:{size[1]}:force_original_aspect_ratio=decrease,'
                      f'pad={size[0]}:{size[1]}:(ow-iw)/2:(oh-ih)/2:black',
               '-q:v', '2', output_path]
        result = subprocess.run(cmd, capture_output=True, timeout=60)
        return result.returncode == 0
    except Exception as e:
        print(f'Thumbnail error: {e}')
        return False


def generate_placeholder_thumbnail(output_path, size=(640, 360)):
    try:
        from PIL import Image, ImageDraw
        img = Image.new('RGB', size, (20, 20, 30))
        draw = ImageDraw.Draw(img)
        cx, cy = size[0]//2, size[1]//2
        draw.polygon([(cx-40,cy-50),(cx+60,cy),(cx-40,cy+50)], fill=(200,50,50))
        img.save(output_path, 'JPEG', quality=85)
        return True
    except Exception as e:
        print(f'Placeholder error: {e}')
        return False


def process_video(video, filepath, config):
    from app import db
    ffprobe_path = config.get('FFPROBE_PATH', 'ffprobe')
    thumbnail_folder = config['THUMBNAIL_FOLDER']
    info = get_video_info(filepath, ffprobe_path)
    if info:
        vs = next((s for s in info.get('streams', []) if s.get('codec_type') == 'video'), None)
        if vs:
            video.resolution = f"{vs.get('width',0)}x{vs.get('height',0)}"
        video.duration = int(float(info.get('format', {}).get('duration', 0)))
    video.format = os.path.splitext(filepath)[1].lstrip('.').upper()
    thumb_filename = f'{video.id}_thumb.jpg'
    thumb_path = os.path.join(thumbnail_folder, thumb_filename)
    ffmpeg_ok = True
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, timeout=5)
    except Exception:
        ffmpeg_ok = False
    if ffmpeg_ok and generate_thumbnail(filepath, thumb_path, size=config.get('THUMBNAIL_SIZE', (640,360))):
        video.thumbnail = thumb_filename
    elif generate_placeholder_thumbnail(thumb_path):
        video.thumbnail = thumb_filename
    video.status = 'published'
    video.published_at = datetime.now(timezone.utc)
    db.session.commit()
    return video

import os
import re
import secrets
import json
from pathlib import Path
from functools import wraps
from datetime import timedelta, datetime
from flask import Flask, render_template, request, send_file, redirect, url_for, session, flash, abort, jsonify
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash, generate_password_hash
from dotenv import load_dotenv

# 加载 .env 文件（override=True 确保 .env 配置优先于系统环境变量）
load_dotenv(override=True)

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', secrets.token_hex(16))

# 设置会话持久化时间为30天
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

# 从环境变量读取配置
CONFIG = {
    'SHARED_DIRECTORY': os.getenv('SHARED_DIRECTORY', r'D:\shared'),
    'USERNAME': os.getenv('USERNAME', 'admin'),
    'PASSWORD_HASH': generate_password_hash(os.getenv('PASSWORD', 'admin123')),
    'MAX_UPLOAD_SIZE': int(os.getenv('MAX_UPLOAD_SIZE', 500)) * 1024 * 1024,  # MB转字节
    'PORT': int(os.getenv('PORT', 5000)),
    'HOST': os.getenv('HOST', '0.0.0.0'),
    'DEBUG': os.getenv('DEBUG', 'True').lower() == 'true',
    'RECYCLE_BIN': '回收站',  # 回收站文件夹名称
    'RECYCLE_DAYS': 30  # 回收站保留天数
}

app.config['MAX_CONTENT_LENGTH'] = CONFIG['MAX_UPLOAD_SIZE']


def login_required(f):
    """登录验证装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function


def get_safe_path(relative_path):
    """获取安全的文件路径，防止路径遍历攻击"""
    base_path = Path(CONFIG['SHARED_DIRECTORY']).resolve()
    target_path = (base_path / relative_path).resolve()

    # 确保目标路径在共享目录内
    if not str(target_path).startswith(str(base_path)):
        abort(403)

    return target_path


def get_directory_contents(path):
    """获取目录内容"""
    items = []
    try:
        for item in sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            relative_path = item.relative_to(CONFIG['SHARED_DIRECTORY'])
            file_type = get_file_type(item.name) if item.is_file() else None
            items.append({
                'name': item.name,
                'is_dir': item.is_dir(),
                'size': item.stat().st_size if item.is_file() else 0,
                'path': str(relative_path).replace('\\', '/'),
                'file_type': file_type
            })
    except PermissionError:
        flash('没有权限访问此目录', 'error')
    return items


def format_size(size):
    """格式化文件大小"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"


def get_file_type(filename):
    """根据文件扩展名判断文件类型"""
    ext = Path(filename).suffix.lower()

    # 音频文件
    audio_exts = ['.mp3', '.wav', '.ogg', '.m4a', '.aac', '.flac', '.wma']
    if ext in audio_exts:
        return 'audio'

    # 视频文件
    video_exts = ['.mp4', '.webm', '.ogg', '.avi', '.mov', '.mkv', '.flv']
    if ext in video_exts:
        return 'video'

    # 图片文件
    image_exts = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg']
    if ext in image_exts:
        return 'image'

    # PDF文件
    if ext == '.pdf':
        return 'pdf'

    return 'other'


def safe_filename(filename):
    """
    安全的文件名处理，允许中文等Unicode字符
    只过滤真正危险的字符：路径分隔符和控制字符
    """
    # 移除路径分隔符和其他危险字符
    # 保留中文、英文、数字、常见符号
    dangerous_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|', '\0']

    for char in dangerous_chars:
        filename = filename.replace(char, '')

    # 移除控制字符
    filename = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', filename)

    # 去除首尾空格和点号
    filename = filename.strip('. ')

    # 如果文件名为空或只包含空格，返回默认名称
    if not filename:
        return 'unnamed'

    return filename


app.jinja_env.filters['format_size'] = format_size


# ============ 回收站相关函数 ============

def get_recycle_bin_path():
    """获取回收站路径"""
    return Path(CONFIG['SHARED_DIRECTORY']) / CONFIG['RECYCLE_BIN']


def get_metadata_file():
    """获取元数据文件路径"""
    return get_recycle_bin_path() / '.metadata.json'


def load_metadata():
    """加载回收站元数据"""
    metadata_file = get_metadata_file()
    if metadata_file.exists():
        try:
            with open(metadata_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_metadata(metadata):
    """保存回收站元数据"""
    metadata_file = get_metadata_file()
    try:
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"保存元数据失败: {e}")


def add_to_recycle_bin(item_path, original_path):
    """将文件/目录添加到回收站元数据"""
    import uuid
    import shutil

    recycle_bin = get_recycle_bin_path()

    # 确保回收站存在
    if not recycle_bin.exists():
        recycle_bin.mkdir(parents=True)

    # 生成唯一ID作为回收站中的文件名
    unique_id = str(uuid.uuid4())
    ext = item_path.suffix if item_path.is_file() else ''
    new_name = f"{unique_id}{ext}"

    # 移动到回收站
    dest_path = recycle_bin / new_name
    shutil.move(str(item_path), str(dest_path))

    # 更新元数据
    metadata = load_metadata()
    metadata[unique_id] = {
        'original_name': item_path.name,
        'original_path': str(original_path),
        'deleted_time': datetime.now().isoformat(),
        'is_dir': dest_path.is_dir(),
        'size': get_dir_size(dest_path) if dest_path.is_dir() else dest_path.stat().st_size
    }
    save_metadata(metadata)

    return unique_id


def get_dir_size(path):
    """递归计算目录大小"""
    total = 0
    try:
        for item in path.rglob('*'):
            if item.is_file():
                total += item.stat().st_size
    except Exception:
        pass
    return total


def clean_old_items():
    """清理超过指定天数的回收站项目"""
    metadata = load_metadata()
    recycle_bin = get_recycle_bin_path()
    current_time = datetime.now()

    items_to_remove = []

    for item_id, info in metadata.items():
        deleted_time = datetime.fromisoformat(info['deleted_time'])
        days_diff = (current_time - deleted_time).days

        if days_diff >= CONFIG['RECYCLE_DAYS']:
            # 永久删除
            ext = Path(info['original_name']).suffix if not info['is_dir'] else ''
            item_path = recycle_bin / f"{item_id}{ext}"

            if item_path.exists():
                try:
                    if item_path.is_file():
                        item_path.unlink()
                    else:
                        import shutil
                        shutil.rmtree(item_path)
                    items_to_remove.append(item_id)
                except Exception as e:
                    print(f"删除 {item_id} 失败: {e}")

    # 更新元数据
    for item_id in items_to_remove:
        del metadata[item_id]

    if items_to_remove:
        save_metadata(metadata)

    return len(items_to_remove)


@app.route('/login', methods=['GET', 'POST'])
def login():
    """登录页面"""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if username == CONFIG['USERNAME'] and check_password_hash(CONFIG['PASSWORD_HASH'], password):
            session.permanent = True  # 设置为持久会话
            session['logged_in'] = True
            next_page = request.args.get('next')
            return redirect(next_page or url_for('index'))
        else:
            flash('用户名或密码错误', 'error')

    return render_template('login.html')


@app.route('/logout')
def logout():
    """登出"""
    session.pop('logged_in', None)
    return redirect(url_for('login'))


@app.route('/')
@app.route('/browse/')
@app.route('/browse/<path:subpath>')
@login_required
def index(subpath=''):
    """浏览目录"""
    current_path = get_safe_path(subpath)

    if not current_path.exists():
        flash('路径不存在', 'error')
        return redirect(url_for('index'))

    if current_path.is_file():
        # 如果是文件，直接下载
        return send_file(current_path, as_attachment=True)

    # 获取目录内容
    items = get_directory_contents(current_path)

    # 构建面包屑导航
    breadcrumbs = []
    parts = Path(subpath).parts if subpath else []
    for i, part in enumerate(parts):
        breadcrumbs.append({
            'name': part,
            'path': '/'.join(parts[:i+1])
        })

    return render_template('index.html',
                         items=items,
                         current_path=subpath,
                         breadcrumbs=breadcrumbs)


@app.route('/download/<path:filepath>')
@login_required
def download(filepath):
    """下载文件"""
    file_path = get_safe_path(filepath)

    if not file_path.exists() or not file_path.is_file():
        abort(404)

    return send_file(file_path, as_attachment=True, download_name=file_path.name)


@app.route('/play/<path:filepath>')
@login_required
def play(filepath):
    """播放音频/视频文件"""
    file_path = get_safe_path(filepath)

    if not file_path.exists() or not file_path.is_file():
        abort(404)

    file_type = get_file_type(file_path.name)

    if file_type not in ['audio', 'video']:
        flash('此文件类型不支持在线播放', 'error')
        return redirect(url_for('index'))

    # 获取同一目录下的所有媒体文件
    parent_dir = file_path.parent
    playlist = []
    current_index = 0

    try:
        for idx, item in enumerate(sorted(parent_dir.iterdir(), key=lambda x: x.name.lower())):
            if item.is_file():
                item_type = get_file_type(item.name)
                if item_type == file_type:  # 只添加相同类型的文件（音频或视频）
                    relative_path = item.relative_to(CONFIG['SHARED_DIRECTORY'])
                    playlist.append({
                        'name': item.name,
                        'path': str(relative_path).replace('\\', '/')
                    })
                    if item == file_path:
                        current_index = len(playlist) - 1
    except PermissionError:
        pass

    return render_template('player.html',
                         filename=file_path.name,
                         filepath=filepath,
                         file_type=file_type,
                         playlist=playlist,
                         current_index=current_index)


@app.route('/view/<path:filepath>')
@login_required
def view(filepath):
    """查看图片文件"""
    file_path = get_safe_path(filepath)

    if not file_path.exists() or not file_path.is_file():
        abort(404)

    file_type = get_file_type(file_path.name)

    if file_type != 'image':
        flash('此文件类型不支持查看', 'error')
        return redirect(url_for('index'))

    # 获取同一目录下的所有图片文件
    parent_dir = file_path.parent
    playlist = []
    current_index = 0

    try:
        for idx, item in enumerate(sorted(parent_dir.iterdir(), key=lambda x: x.name.lower())):
            if item.is_file():
                item_type = get_file_type(item.name)
                if item_type == 'image':  # 只添加图片文件
                    relative_path = item.relative_to(CONFIG['SHARED_DIRECTORY'])
                    playlist.append({
                        'name': item.name,
                        'path': str(relative_path).replace('\\', '/')
                    })
                    if item == file_path:
                        current_index = len(playlist) - 1
    except PermissionError:
        pass

    return render_template('viewer.html',
                         filename=file_path.name,
                         filepath=filepath,
                         playlist=playlist,
                         current_index=current_index)


@app.route('/stream/<path:filepath>')
@login_required
def stream(filepath):
    """流式传输媒体文件"""
    file_path = get_safe_path(filepath)

    if not file_path.exists() or not file_path.is_file():
        abort(404)

    return send_file(file_path, as_attachment=False)


@app.route('/upload', methods=['POST'])
@login_required
def upload():
    """上传文件（兼容旧版，保留用于小文件）"""
    import time

    start_time = time.time()
    receive_start = time.time()

    if 'file' not in request.files:
        return jsonify({'success': False, 'message': '没有文件'}), 400

    file = request.files['file']
    target_path = request.form.get('path', '')

    if file.filename == '':
        return jsonify({'success': False, 'message': '未选择文件'}), 400

    # 安全的文件名
    filename = safe_filename(file.filename)

    # 目标目录
    target_dir = get_safe_path(target_path)
    if not target_dir.exists() or not target_dir.is_dir():
        return jsonify({'success': False, 'message': '目标目录不存在'}), 400

    # 保存文件
    save_path = target_dir / filename

    # 检查文件是否已存在
    if save_path.exists():
        return jsonify({'success': False, 'message': '文件已存在'}), 400

    try:
        # 使用流式保存，提高大文件上传性能
        # 使用更大的缓冲区（4MB）来加快写入速度
        CHUNK_SIZE = 4 * 1024 * 1024  # 4MB chunks，减少系统调用次数

        write_start = time.time()
        receive_time = write_start - receive_start

        bytes_written = 0
        with open(save_path, 'wb', buffering=CHUNK_SIZE) as f:
            while True:
                chunk = file.stream.read(CHUNK_SIZE)
                if not chunk:
                    break
                f.write(chunk)
                bytes_written += len(chunk)

        write_time = time.time() - write_start
        total_time = time.time() - start_time

        file_size_mb = bytes_written / 1024 / 1024

        # 打印诊断信息（使用flush=True确保立即输出）
        print(f"\n=== 上传性能诊断 ===", flush=True)
        print(f"文件: {filename}", flush=True)
        print(f"大小: {file_size_mb:.2f} MB", flush=True)
        print(f"接收耗时: {receive_time:.2f} 秒", flush=True)
        print(f"写入耗时: {write_time:.2f} 秒", flush=True)
        print(f"总耗时: {total_time:.2f} 秒", flush=True)
        print(f"写入速度: {file_size_mb / write_time if write_time > 0 else 0:.2f} MB/s", flush=True)
        print(f"==================\n", flush=True)

        return jsonify({
            'success': True,
            'message': f'文件 {filename} 上传成功',
            'diagnostics': {
                'fileSize': f'{file_size_mb:.2f} MB',
                'receiveTime': f'{receive_time:.2f}秒',
                'writeTime': f'{write_time:.2f}秒',
                'totalTime': f'{total_time:.2f}秒',
                'writeSpeed': f'{file_size_mb / write_time if write_time > 0 else 0:.2f} MB/s'
            }
        })
    except Exception as e:
        # 如果保存失败，删除部分写入的文件
        if save_path.exists():
            try:
                save_path.unlink()
            except:
                pass
        return jsonify({'success': False, 'message': f'上传失败: {str(e)}'}), 500




@app.route('/delete', methods=['POST'])
@login_required
def delete():
    """删除文件或目录（移动到回收站）"""
    filepath = request.form.get('path')
    if not filepath:
        return jsonify({'success': False, 'message': '未指定路径'}), 400

    target_path = get_safe_path(filepath)

    if not target_path.exists():
        return jsonify({'success': False, 'message': '文件或目录不存在'}), 404

    # 检查是否是回收站本身
    recycle_bin = get_recycle_bin_path()
    try:
        if target_path.resolve() == recycle_bin.resolve():
            return jsonify({'success': False, 'message': '不能删除回收站'}), 400
    except Exception:
        pass

    try:
        # 移动到回收站
        add_to_recycle_bin(target_path, filepath)
        item_type = '目录' if not target_path.exists() or target_path.is_dir() else '文件'
        message = f'{item_type} {target_path.name} 已移至回收站'

        return jsonify({'success': True, 'message': message})
    except Exception as e:
        return jsonify({'success': False, 'message': f'删除失败: {str(e)}'}), 500


@app.route('/mkdir', methods=['POST'])
@login_required
def mkdir():
    """创建目录"""
    dirname = request.form.get('dirname')
    current_path = request.form.get('path', '')

    if not dirname:
        return jsonify({'success': False, 'message': '未指定目录名'}), 400

    # 安全的目录名
    dirname = safe_filename(dirname)

    target_dir = get_safe_path(current_path)
    new_dir = target_dir / dirname

    if new_dir.exists():
        return jsonify({'success': False, 'message': '目录已存在'}), 400

    try:
        new_dir.mkdir(parents=True)
        return jsonify({'success': True, 'message': f'目录 {dirname} 创建成功'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'创建失败: {str(e)}'}), 500


@app.route('/rename', methods=['POST'])
@login_required
def rename():
    """重命名文件或目录"""
    filepath = request.form.get('path')
    new_name = request.form.get('new_name')

    if not filepath or not new_name:
        return jsonify({'success': False, 'message': '参数不完整'}), 400

    # 安全的文件名
    new_name = safe_filename(new_name)

    if not new_name:
        return jsonify({'success': False, 'message': '文件名不合法'}), 400

    target_path = get_safe_path(filepath)

    if not target_path.exists():
        return jsonify({'success': False, 'message': '文件或目录不存在'}), 404

    # 构建新路径
    new_path = target_path.parent / new_name

    # 检查新路径是否已存在
    if new_path.exists():
        return jsonify({'success': False, 'message': '目标名称已存在'}), 400

    try:
        target_path.rename(new_path)
        item_type = '目录' if new_path.is_dir() else '文件'
        return jsonify({'success': True, 'message': f'{item_type}已重命名为 {new_name}'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'重命名失败: {str(e)}'}), 500


@app.route('/api/folders', methods=['GET'])
@login_required
def get_folders():
    """获取指定路径下的所有文件夹"""
    path = request.args.get('path', '')

    try:
        current_path = get_safe_path(path)

        if not current_path.exists() or not current_path.is_dir():
            return jsonify({'success': False, 'message': '路径不存在或不是目录'}), 404

        # 获取所有子文件夹
        folders = []
        try:
            for item in sorted(current_path.iterdir(), key=lambda x: x.name.lower()):
                if item.is_dir():
                    relative_path = item.relative_to(CONFIG['SHARED_DIRECTORY'])
                    folders.append({
                        'name': item.name,
                        'path': str(relative_path).replace('\\', '/')
                    })
        except PermissionError:
            return jsonify({'success': False, 'message': '没有权限访问此目录'}), 403

        # 构建面包屑导航
        breadcrumbs = []
        if path:
            parts = Path(path).parts
            for i, part in enumerate(parts):
                breadcrumbs.append({
                    'name': part,
                    'path': '/'.join(parts[:i+1])
                })

        return jsonify({
            'success': True,
            'folders': folders,
            'breadcrumbs': breadcrumbs
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'获取文件夹列表失败: {str(e)}'}), 500


@app.route('/copy', methods=['POST'])
@login_required
def copy():
    """复制文件或目录"""
    import shutil

    source_path = request.form.get('source_path')
    dest_path = request.form.get('dest_path', '')

    if not source_path:
        return jsonify({'success': False, 'message': '未指定源路径'}), 400

    source = get_safe_path(source_path)
    dest_dir = get_safe_path(dest_path)

    if not source.exists():
        return jsonify({'success': False, 'message': '源文件或目录不存在'}), 404

    if not dest_dir.exists() or not dest_dir.is_dir():
        return jsonify({'success': False, 'message': '目标目录不存在'}), 400

    # 构建目标路径
    dest = dest_dir / source.name

    # 检查目标是否已存在
    if dest.exists():
        return jsonify({'success': False, 'message': f'{source.name} 在目标目录中已存在'}), 400

    # 检查是否尝试复制到自身或其子目录
    try:
        if source.is_dir() and dest.resolve().is_relative_to(source.resolve()):
            return jsonify({'success': False, 'message': '不能将目录复制到其自身或子目录中'}), 400
    except (ValueError, AttributeError):
        # Python 3.8 及以下版本不支持 is_relative_to，使用字符串比较
        if source.is_dir() and str(dest.resolve()).startswith(str(source.resolve())):
            return jsonify({'success': False, 'message': '不能将目录复制到其自身或子目录中'}), 400

    try:
        if source.is_file():
            shutil.copy2(source, dest)
            return jsonify({'success': True, 'message': f'文件 {source.name} 已复制'})
        else:
            shutil.copytree(source, dest)
            return jsonify({'success': True, 'message': f'目录 {source.name} 已复制'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'复制失败: {str(e)}'}), 500


@app.route('/move', methods=['POST'])
@login_required
def move():
    """移动文件或目录"""
    import shutil

    source_path = request.form.get('source_path')
    dest_path = request.form.get('dest_path', '')

    if not source_path:
        return jsonify({'success': False, 'message': '未指定源路径'}), 400

    source = get_safe_path(source_path)
    dest_dir = get_safe_path(dest_path)

    if not source.exists():
        return jsonify({'success': False, 'message': '源文件或目录不存在'}), 404

    if not dest_dir.exists() or not dest_dir.is_dir():
        return jsonify({'success': False, 'message': '目标目录不存在'}), 400

    # 构建目标路径
    dest = dest_dir / source.name

    # 检查目标是否已存在
    if dest.exists():
        return jsonify({'success': False, 'message': f'{source.name} 在目标目录中已存在'}), 400

    # 检查是否尝试移动到自身或其子目录
    try:
        if source.is_dir() and dest.resolve().is_relative_to(source.resolve()):
            return jsonify({'success': False, 'message': '不能将目录移动到其自身或子目录中'}), 400
    except (ValueError, AttributeError):
        # Python 3.8 及以下版本不支持 is_relative_to，使用字符串比较
        if source.is_dir() and str(dest.resolve()).startswith(str(source.resolve())):
            return jsonify({'success': False, 'message': '不能将目录移动到其自身或子目录中'}), 400

    try:
        shutil.move(str(source), str(dest))
        item_type = '目录' if dest.is_dir() else '文件'
        return jsonify({'success': True, 'message': f'{item_type} {source.name} 已移动'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'移动失败: {str(e)}'}), 500


@app.route('/recycle-bin')
@login_required
def recycle_bin():
    """回收站页面"""
    # 清理过期项目
    clean_old_items()

    # 加载元数据
    metadata = load_metadata()
    recycle_bin_path = get_recycle_bin_path()

    # 准备显示数据
    items = []
    for item_id, info in metadata.items():
        ext = Path(info['original_name']).suffix if not info['is_dir'] else ''
        item_path = recycle_bin_path / f"{item_id}{ext}"

        if item_path.exists():
            deleted_time = datetime.fromisoformat(info['deleted_time'])
            days_left = CONFIG['RECYCLE_DAYS'] - (datetime.now() - deleted_time).days

            items.append({
                'id': item_id,
                'name': info['original_name'],
                'original_path': info['original_path'],
                'is_dir': info['is_dir'],
                'size': info['size'],
                'deleted_time': deleted_time.strftime('%Y-%m-%d %H:%M:%S'),
                'days_left': max(0, days_left),
                'file_type': get_file_type(info['original_name']) if not info['is_dir'] else None
            })

    # 按删除时间排序（最新的在前面）
    items.sort(key=lambda x: x['deleted_time'], reverse=True)

    return render_template('recycle_bin.html', items=items)


@app.route('/restore', methods=['POST'])
@login_required
def restore():
    """恢复文件或目录"""
    item_id = request.form.get('item_id')
    if not item_id:
        return jsonify({'success': False, 'message': '未指定项目ID'}), 400

    metadata = load_metadata()
    if item_id not in metadata:
        return jsonify({'success': False, 'message': '项目不存在'}), 404

    info = metadata[item_id]
    recycle_bin_path = get_recycle_bin_path()

    # 获取回收站中的文件
    ext = Path(info['original_name']).suffix if not info['is_dir'] else ''
    item_path = recycle_bin_path / f"{item_id}{ext}"

    if not item_path.exists():
        return jsonify({'success': False, 'message': '文件不存在'}), 404

    try:
        # 恢复到原路径
        original_path = get_safe_path(info['original_path'])

        # 检查原路径是否已存在同名文件
        if original_path.exists():
            return jsonify({'success': False, 'message': f'原位置已存在同名{("目录" if info["is_dir"] else "文件")}'}), 400

        # 确保父目录存在
        original_path.parent.mkdir(parents=True, exist_ok=True)

        # 移动回原位置
        import shutil
        shutil.move(str(item_path), str(original_path))

        # 从元数据中移除
        del metadata[item_id]
        save_metadata(metadata)

        return jsonify({'success': True, 'message': f'{info["original_name"]} 已恢复'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'恢复失败: {str(e)}'}), 500


@app.route('/permanent-delete', methods=['POST'])
@login_required
def permanent_delete():
    """永久删除文件或目录"""
    item_id = request.form.get('item_id')
    if not item_id:
        return jsonify({'success': False, 'message': '未指定项目ID'}), 400

    metadata = load_metadata()
    if item_id not in metadata:
        return jsonify({'success': False, 'message': '项目不存在'}), 404

    info = metadata[item_id]
    recycle_bin_path = get_recycle_bin_path()

    # 获取回收站中的文件
    ext = Path(info['original_name']).suffix if not info['is_dir'] else ''
    item_path = recycle_bin_path / f"{item_id}{ext}"

    try:
        if item_path.exists():
            if item_path.is_file():
                item_path.unlink()
            else:
                import shutil
                shutil.rmtree(item_path)

        # 从元数据中移除
        del metadata[item_id]
        save_metadata(metadata)

        return jsonify({'success': True, 'message': f'{info["original_name"]} 已永久删除'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'删除失败: {str(e)}'}), 500


@app.route('/empty-recycle-bin', methods=['POST'])
@login_required
def empty_recycle_bin():
    """清空回收站"""
    metadata = load_metadata()
    recycle_bin_path = get_recycle_bin_path()

    deleted_count = 0

    try:
        for item_id, info in list(metadata.items()):
            ext = Path(info['original_name']).suffix if not info['is_dir'] else ''
            item_path = recycle_bin_path / f"{item_id}{ext}"

            if item_path.exists():
                try:
                    if item_path.is_file():
                        item_path.unlink()
                    else:
                        import shutil
                        shutil.rmtree(item_path)
                    deleted_count += 1
                except Exception as e:
                    print(f"删除 {item_id} 失败: {e}")

        # 清空元数据
        save_metadata({})

        return jsonify({'success': True, 'message': f'已清空回收站，共删除 {deleted_count} 个项目'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'清空失败: {str(e)}'}), 500


if __name__ == '__main__':
    # 确保共享目录存在
    shared_dir = Path(CONFIG['SHARED_DIRECTORY'])
    if not shared_dir.exists():
        shared_dir.mkdir(parents=True)
        print(f"已创建共享目录: {shared_dir}")

    print("=" * 50)
    print("           文件共享服务器")
    print("=" * 50)
    print(f"共享目录: {shared_dir}")
    print(f"用户名: {CONFIG['USERNAME']}")
    print(f"密码: {os.getenv('PASSWORD', 'admin123')}")
    print("\n访问地址:")
    print(f"  本机: http://127.0.0.1:{CONFIG['PORT']}")
    print(f"  局域网: http://<你的IP地址>:{CONFIG['PORT']}")
    print("\n按 Ctrl+C 停止服务器")
    print("=" * 50)
    print()

    app.run(host=CONFIG['HOST'], port=CONFIG['PORT'], debug=CONFIG['DEBUG'])

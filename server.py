from flask import Flask, request, send_from_directory, redirect, url_for
from flask_socketio import SocketIO, emit, join_room
import os
import json
import atexit
import bcrypt
from datetime import datetime
import uuid
import shutil
from flask import send_from_directory, redirect, url_for, request

app = Flask(__name__)
app.config['SECRET_KEY'] = 'wechat_clone_secret_key'
app.config['DEBUG'] = True

socketio = SocketIO(app, cors_allowed_origins="*")

# 获取当前文件所在目录的绝对路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 聊天历史文件路径
HISTORY_FILE = os.path.join(BASE_DIR, 'chat_history.json')
# 用户数据文件路径
USERS_FILE = os.path.join(BASE_DIR, 'users.json')
# 房间数据文件路径
ROOMS_FILE = os.path.join(BASE_DIR, 'rooms.json')

# 存储在线用户、聊天历史和用户数据
online_users = set()
chat_history = []
users = {}
# 存储房间信息 {room_id: {users: set(), creator: username}}
rooms = {}
# 存储在线用户的sid和用户名映射
sid_to_username = {}

# 加载用户数据
if os.path.exists(USERS_FILE):
    try:
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            users = json.load(f)
    except:
        users = {'users': {}}
else:
    users = {'users': {}}

# 加载房间数据
print(f"[DEBUG] Attempting to load rooms from {ROOMS_FILE}")
if os.path.exists(ROOMS_FILE):
    try:
        with open(ROOMS_FILE, 'r', encoding='utf-8') as f:
            rooms_data = json.load(f)
            print(f"[DEBUG] Loaded rooms data: {rooms_data}")
            # 转换users集合为set类型
            for room_id, room_info in rooms_data.items():
                rooms[room_id] = {
                    'users': set(room_info['users']),
                    'creator': room_info['creator']
                }
            print(f"[DEBUG] Successfully loaded {len(rooms)} rooms")
            print(f"[DEBUG] Rooms list: {list(rooms.keys())}")
    except Exception as e:
        print(f"[DEBUG] Error loading rooms: {str(e)}")
        rooms = {}
else:
    print(f"[DEBUG] Rooms file {ROOMS_FILE} does not exist")
    rooms = {}

# 保存用户数据到文件
def save_users():
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, ensure_ascii=False, indent=2)

# 保存房间数据到文件
def save_rooms():
    # 转换set为list以支持JSON序列化
    rooms_data = {}
    for room_id, room_info in rooms.items():
        rooms_data[room_id] = {
            'users': list(room_info['users']),
            'creator': room_info['creator']
        }
    # 添加详细调试信息
    print(f'[DEBUG] Attempting to save rooms: {list(rooms.keys())}')
    print(f'[DEBUG] Room data to save: {rooms_data}')
    try:
        with open(ROOMS_FILE, 'w', encoding='utf-8') as f:
            json.dump(rooms_data, f, ensure_ascii=False, indent=2)
        print(f'[DEBUG] Successfully saved rooms to {ROOMS_FILE}')
        # 验证保存后的数据
        with open(ROOMS_FILE, 'r', encoding='utf-8') as f:
            saved_rooms = json.load(f)
        print(f'[DEBUG] Verified saved rooms: {list(saved_rooms.keys())}')
        return True
    except Exception as e:
        print(f'[DEBUG] Error saving rooms: {str(e)}')
        return False
    # 验证保存结果
    if os.path.exists(ROOMS_FILE):
        file_size = os.path.getsize(ROOMS_FILE)
        print(f'[DEBUG] Rooms file size: {file_size} bytes')
    else:
        print(f'[DEBUG] Rooms file {ROOMS_FILE} does not exist after save')

# 加载聊天历史
if os.path.exists(HISTORY_FILE):
    try:
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            chat_history = json.load(f)
    except:
        chat_history = []

# 保存聊天历史到文件
def save_chat_history():
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(chat_history, f, ensure_ascii=False, indent=2)

# 改进的退出处理逻辑
# 只有在房间数据不为空时才保存
def exit_handler():
    print('[DEBUG] Running exit handler')
    save_chat_history()
    if rooms:
        print('[DEBUG] Rooms data is not empty, saving...')
        save_rooms()
    else:
        print('[DEBUG] Rooms data is empty, skipping save')# 注册程序退出时保存数据
atexit.register(exit_handler)
print('Registered exit handlers for saving data')

# 文件上传配置
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
# 确保上传目录存在
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# 允许的文件扩展名
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'mp3', 'mp4', 'exe', 'zip', '7z'}

# 检查文件扩展名是否允许
def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# 文件上传API
@app.route('/upload_file', methods=['POST'])
def upload_file():
    # 检查用户是否登录
    username = request.form.get('username')
    if not username or username not in users['users']:
        return {'success': False, 'message': '未登录或用户不存在'}

    # 检查房间是否存在
    room_id = request.form.get('room_id')
    if not room_id or room_id not in rooms:
        return {'success': False, 'message': '房间不存在'}

    # 检查是否有文件上传
    if 'file' not in request.files:
        return {'success': False, 'message': '没有文件被上传'}

    file = request.files['file']
    # 如果用户没有选择文件，浏览器也会发送一个空的file对象
    if file.filename == '':
        return {'success': False, 'message': '没有选择文件'}

    if file and allowed_file(file.filename):
        # 生成唯一的文件名，避免覆盖
        unique_filename = str(uuid.uuid4()) + '_' + file.filename
        file_path = os.path.join(UPLOAD_FOLDER, unique_filename)
        file.save(file_path)

        # 获取文件大小
        file_size = os.path.getsize(file_path)

        # 生成文件访问URL
        file_url = f'/uploads/{unique_filename}'

        # 准备文件消息数据
        timestamp = datetime.now().strftime('%H:%M')
        file_message = {
            'type': 'file',
            'file_name': file.filename,
            'file_url': file_url,
            'file_size': file_size,
            'sender': username,
            'time': timestamp
        }

        # 广播文件消息到房间
        print(f'[DEBUG] Broadcasting file message to room {room_id}: {file_message}')
        socketio.emit('message', file_message, room=room_id)
        # 同时将文件消息添加到聊天历史
        chat_history.append(file_message)
        if len(chat_history) > 100:
            chat_history.pop(0)
        save_chat_history()

        return {'success': True, 'message': '文件上传成功'}
    else:
        return {'success': False, 'message': '不允许的文件类型'}

# 提供上传文件的访问路由
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

# 登录页面路由
@app.route('/')
def login_page():
    return send_from_directory(os.getcwd(), 'login.html')

# 桌面版聊天页面路由（需要登录）
@app.route('/chat')
def chat_page():
    username = request.args.get('username')
    if not username or username not in users['users']:
        return redirect(url_for('login_page'))
    return send_from_directory(os.getcwd(), 'chat.html')

# 手机版聊天页面路由（需要登录）
@app.route('/mobile_chat')
def mobile_chat_page():
    username = request.args.get('username')
    if not username or username not in users['users']:
        return redirect(url_for('login_page'))
    return send_from_directory(os.getcwd(), 'mobile_chat.html')

# 登录API
@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return {'success': False, 'message': '用户名和密码不能为空'}

    if username not in users['users']:
        return {'success': False, 'message': '用户不存在'}

    # 验证密码
    stored_password = users['users'][username]['password'].encode('utf-8')
    if bcrypt.checkpw(password.encode('utf-8'), stored_password):
        # 登录成功
        return {'success': True, 'username': username, 'redirect_url': '/home?username=' + username}
    else:
        return {'success': False, 'message': '密码错误'}

# 注册API
@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return {'success': False, 'message': '用户名和密码不能为空'}

    if len(password) < 6:
        return {'success': False, 'message': '密码长度不能少于6位'}

    if username in users['users']:
        return {'success': False, 'message': '用户名已存在'}

    # 加密密码
    hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

    # 添加新用户
    users['users'][username] = {
        'password': hashed_password.decode('utf-8'),
        'registered_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }

    # 保存用户数据
    save_users()

    return {'success': True, 'message': '注册成功'}

# 检查房间是否存在API
@app.route('/check_room', methods=['POST'])
def check_room():
    data = request.get_json()
    room_id = data.get('room_id')

    if not room_id or not room_id.isdigit() or len(room_id) < 6:
        return {'exists': False, 'message': '房间号必须是6位或更多位数字'}

    # 检查房间是否存在
    exists = room_id in rooms
    print(f'Checking room {room_id}: exists={exists}')

    return {'exists': exists}

# 创建房间API
@app.route('/create_room', methods=['POST'])
def create_room():
    username = request.args.get('username')
    if not username or username not in users['users']:
        return {'success': False, 'message': '未登录或用户不存在'}

    data = request.get_json()
    room_id = data.get('room_id')

    if not room_id or not room_id.isdigit() or len(room_id) < 6:
        return {'success': False, 'message': '请输入6位或更多位数字房间号'}

    if room_id in rooms:
        return {'success': False, 'message': '房间已存在'}

    # 创建房间
    rooms[room_id] = {'users': set(), 'creator': username}
    print(f'[DEBUG] Room created: {room_id} by {username}')
    print(f'[DEBUG] Room data: {rooms[room_id]}')
    print(f'[DEBUG] Current rooms: {list(rooms.keys())}')
    # 保存房间数据
    save_result = save_rooms()
    print(f'[DEBUG] Save rooms result: {save_result}')
    # 验证保存后的数据
    if os.path.exists(ROOMS_FILE):
        with open(ROOMS_FILE, 'r', encoding='utf-8') as f:
            saved_rooms = json.load(f)
            print(f'[DEBUG] Saved rooms data after creation: {saved_rooms}')
    # 验证保存后的数据
    print(f'After save_rooms call, rooms dictionary: {rooms}')
    if os.path.exists(ROOMS_FILE):
        with open(ROOMS_FILE, 'r', encoding='utf-8') as f:
            saved_rooms = json.load(f)
            print(f'Saved rooms data: {saved_rooms}')

    return {'success': True, 'message': '房间创建成功'}

# 提供聊天历史（需要登录）
@app.route('/history')
def get_history():
    username = request.args.get('username')
    if not username or username not in users['users']:
        return {'success': False, 'message': '未登录或用户不存在'}
    return {'history': chat_history}

# 存储在线用户的sid和用户名映射
sid_to_username = {}

# WebSocket事件处理
@socketio.on('connect')
def handle_connect(auth):
    global online_users, sid_to_username
    # 从socketio获取sid
    sid = request.sid
    # 获取用户名和房间号（从查询参数中传递）
    username = request.args.get('username')
    room_id = request.args.get('roomId')
    print(f'Connection attempt from: {username} (sid: {sid}) room: {room_id}')

    # 验证用户是否已登录
    if not username or username not in users['users']:
        print(f'Unauthorized connection attempt: {sid}')
        # 拒绝连接
        return False

    # 存储用户的房间信息
    sid_to_username[sid] = {'username': username, 'room_id': room_id}

    # 处理房间
    if room_id:
        print(f'Attempting to join room: {room_id}')
        print(f'Existing rooms: {list(rooms.keys())}')
        # 检查房间是否存在
        if room_id not in rooms:
            # 房间不存在，发送错误消息
            system_message = {
                'message': f'房间 {room_id} 不存在，请先创建房间',
                'type': 'system',
                'sender': 'server',
                'time': datetime.now().strftime('%H:%M')
            }
            print(f'Sending error message: {system_message}')
            emit('message', system_message)
            # 拒绝加入不存在的房间
            return False
        # 房间存在，添加用户到房间
        rooms[room_id]['users'].add(username)
        print(f'User {username} joined room {room_id}')
        print(f'Users in room {room_id}: {rooms[room_id]["users"]}')
        # 加入SocketIO房间
        join_room(room_id)
        # 发送房间系统消息
        system_message = {
            'message': f'{username} 加入房间',
            'type': 'system',
            'sender': 'server',
            'time': datetime.now().strftime('%H:%M')
        }
        emit('message', system_message, room=room_id)
    else:
        # 没有房间号，添加到在线用户
        online_users.add(username)
        print(f'User connected: {username} (sid: {sid})')
        # 发送系统消息
        system_message = {
            'message': f'{username} 加入聊天',
            'type': 'system',
            'sender': 'server',
            'time': datetime.now().strftime('%H:%M')
        }
        emit('message', system_message, broadcast=True)

    # 向新连接的客户端发送聊天历史
    emit('chat_history', {'history': chat_history})

@socketio.on('disconnect')
def handle_disconnect():
    global online_users, sid_to_username, rooms
    # 从socketio获取sid
    sid = request.sid
    user_info = sid_to_username.get(sid)

    if user_info:
        username = user_info['username']
        room_id = user_info['room_id']
        del sid_to_username[sid]
        print(f'User disconnected: {username} (sid: {sid})')

        if room_id and room_id in rooms:
            # 从房间移除用户
            rooms[room_id]['users'].discard(username)
            # 发送房间系统消息
            system_message = {
                'message': f'{username} 离开房间',
                'type': 'system',
                'sender': 'server',
                'time': datetime.now().strftime('%H:%M')
            }
            emit('message', system_message, room=room_id)
            # 保留空房间，不自动删除
            # 注释掉自动删除房间的代码
            # if not rooms[room_id]['users']:
            #     del rooms[room_id]
            #     print(f'Room {room_id} deleted (empty)')
        else:
            # 没有房间号，从在线用户移除
            online_users.discard(username)
            # 发送系统消息
            system_message = {
                'message': f'{username} 离开聊天',
                'type': 'system',
                'sender': 'server',
                'time': datetime.now().strftime('%H:%M')
            }
            emit('message', system_message, broadcast=True)
    else:
        print(f'Unknown client disconnected: {sid}')

@socketio.on('message')
def handle_message(data):
    global chat_history
    # 获取发送者信息
    sid = request.sid
    user_info = sid_to_username.get(sid)

    if not user_info:
        print(f'Message from unknown client: {sid}')
        return

    username = user_info['username']
    room_id = user_info['room_id']

    # 添加时间戳
    timestamp = datetime.now().strftime('%H:%M')
    message_data = {
        'message': data['message'],
        'sender': username,
        'time': timestamp
    }

    # 如果在房间内，只广播到房间
    if room_id and room_id in rooms:
        # 保存房间聊天历史
        # 这里可以扩展为每个房间有独立的聊天历史
        # 为简化，我们暂时使用全局聊天历史
        chat_history.append(message_data)
        if len(chat_history) > 100:
            chat_history.pop(0)
        save_chat_history()

        emit('message', message_data, room=room_id)
    else:
        # 不在房间内，广播给所有人
        chat_history.append(message_data)
        if len(chat_history) > 100:
            chat_history.pop(0)
        save_chat_history()

        emit('message', message_data, broadcast=True)

# 处理客户端请求聊天历史
@socketio.on('request_history')
def handle_request_history():
    # 获取请求者信息
    sid = request.sid
    user_info = sid_to_username.get(sid)

    if not user_info:
        print(f'History request from unknown client: {sid}')
        return

    room_id = user_info['room_id']

    # 如果在房间内，发送房间聊天历史
    # 为简化，我们暂时只发送全局聊天历史
    emit('chat_history', {'history': chat_history})

# 房间页面路由
@app.route('/room')
def room_page():
    username = request.args.get('username')
    if not username or username not in users['users']:
        return redirect(url_for('login_page'))
    return send_from_directory(os.getcwd(), 'room.html')

# 用户主页路由
@app.route('/home')
def home_page():
    username = request.args.get('username')
    if not username or username not in users['users']:
        return redirect(url_for('login_page'))
    return send_from_directory(os.getcwd(), 'home.html')

# 获取用户信息API
@app.route('/get_user_info')
def get_user_info():
    username = request.args.get('username')
    if not username or username not in users['users']:
        return {'success': False, 'message': '未登录或用户不存在'}
    
    user_info = users['users'][username].copy()
    # 不返回密码信息
    user_info.pop('password', None)
    
    # 检查是否有头像
    if 'avatar' not in user_info:
        user_info['avatar'] = None
    
    return {'success': True, 'user': user_info}

# 上传头像API
@app.route('/upload_avatar', methods=['POST'])
def upload_avatar():
    username = request.form.get('username')
    if not username or username not in users['users']:
        return {'success': False, 'message': '未登录或用户不存在'}

    if 'file' not in request.files:
        return {'success': False, 'message': '没有文件被上传'}

    file = request.files['file']
    if file.filename == '':
        return {'success': False, 'message': '没有选择文件'}

    # 确保头像目录存在
    AVATAR_FOLDER = os.path.join(BASE_DIR, 'avatars')
    if not os.path.exists(AVATAR_FOLDER):
        os.makedirs(AVATAR_FOLDER)

    # 生成唯一的文件名
    unique_filename = f'{username}_{uuid.uuid4()}.png'
    file_path = os.path.join(AVATAR_FOLDER, unique_filename)
    
    # 保存文件
    file.save(file_path)

    # 更新用户信息
    avatar_url = f'/avatars/{unique_filename}'
    users['users'][username]['avatar'] = avatar_url
    save_users()

    return {'success': True, 'avatar_url': avatar_url}

# 获取主题API
@app.route('/get_theme')
def get_theme():
    username = request.args.get('username')
    if not username or username not in users['users']:
        return {'success': False, 'message': '未登录或用户不存在'}

    # 获取用户主题，如果不存在则返回默认值
    theme = users['users'][username].get('theme', '#f2f2f2')
    return {'success': True, 'theme': theme}

# 保存主题API
@app.route('/save_theme', methods=['POST'])
def save_theme():
    data = request.get_json()
    username = data.get('username')
    theme = data.get('theme')

    if not username or username not in users['users']:
        return {'success': False, 'message': '未登录或用户不存在'}

    if not theme:
        return {'success': False, 'message': '主题颜色不能为空'}

    # 更新用户主题
    users['users'][username]['theme'] = theme
    save_users()

    return {'success': True, 'message': '主题保存成功'}

# 清理缓存API
@app.route('/clear_cache')
def clear_cache():
    username = request.args.get('username')
    if not username or username not in users['users']:
        return {'success': False, 'message': '未登录或用户不存在'}

    # 清理上传目录中的文件
    try:
        for filename in os.listdir(UPLOAD_FOLDER):
            file_path = os.path.join(UPLOAD_FOLDER, filename)
            if os.path.isfile(file_path):
                os.unlink(file_path)
        return {'success': True, 'message': '缓存清理成功'}
    except Exception as e:
        return {'success': False, 'message': f'清理缓存时出错: {str(e)}'}

# 提供头像文件的访问路由
@app.route('/avatars/<filename>')
def avatar_file(filename):
    return send_from_directory(os.path.join(BASE_DIR, 'avatars'), filename)

# 提供根目录下的静态文件访问
@app.route('/<filename>')
def static_file(filename):
    if os.path.exists(os.path.join(BASE_DIR, filename)):
        return send_from_directory(BASE_DIR, filename)
    return '', 404

if __name__ == '__main__':
    # 确保在正确的目录运行
    print(f'Serving from directory: {os.getcwd()}')
    
    # 配置HTTP
    # 使用8080端口避免权限问题
    print('Starting HTTP server...')
    socketio.run(app, host='0.0.0.0', port=8080)
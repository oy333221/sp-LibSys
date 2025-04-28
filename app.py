from flask import Flask, render_template, request, redirect, url_for, session, send_file, flash
from supabase import create_client, Client
import bcrypt
import qrcode
from io import BytesIO
import os
from functools import wraps
import requests
from datetime import datetime, timedelta, timezone
import time
import logging
from bs4 import BeautifulSoup
import re
from dotenv import load_dotenv

# 載入環境變數
load_dotenv()

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='static', static_url_path='/static')
app.secret_key = os.environ.get('FLASK_SECRET_KEY', os.urandom(24))

# 從環境變數獲取Supabase認證信息
supabase_url = os.environ.get('SUPABASE_URL')
supabase_key = os.environ.get('SUPABASE_KEY')
supabase: Client = create_client(supabase_url, supabase_key)

# 管理員密碼也從環境變數獲取
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', '1576')  # 預設密碼僅用於開發環境

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 檢查是否在 QR code 模式
        if session.get('qr_mode'):
            return redirect(url_for('borrow_checkin', bag_id=session.get('bag_id')))
        # 檢查是否是管理員
        if 'admin' not in session:
            flash('請先登入管理員帳號！')
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    books = supabase.table('publications')\
        .select('id, title, description, product_link, status, isbn, cover_url')\
        .eq('status', '可借閱')\
        .execute().data
    
    # 處理空描述
    for book in books:
        if book['description'] is None:
            book['description'] = '無描述'

    reservations = supabase.table('reservations')\
        .select('id, publication_id, publications(title), status')\
        .eq('user_id', session['user_id'])\
        .in_('status', ['待處理', '已準備', '已取書'])\
        .execute().data
    
    return render_template('index.html', books=books, reservations=reservations)

def process_book_info(isbn, owner_id):
    """立即處理書籍資訊"""
    try:
        # 爬取書籍資訊
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Referer": "https://www.books.com.tw/",
            "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
            "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive"
        }
        
        # 1. 搜尋頁面
        search_url = f"https://search.books.com.tw/search/query/key/{isbn}/cat/all"
        print(f"訪問搜尋頁面: {search_url}")  # 除錯訊息
        search_response = requests.get(search_url, headers=headers, timeout=10)
        if search_response.status_code != 200:
            print(f"搜尋頁面返回狀態碼: {search_response.status_code}")  # 除錯訊息
            return False
            
        search_soup = BeautifulSoup(search_response.text, 'html.parser')
        product_link = search_soup.select_one('a[href*="/redirect/move/"]')
        if not product_link:
            print("找不到商品連結")  # 除錯訊息
            return False
            
        # 2. 取得商品頁面
        item_id = product_link['href'].split('item/')[1].split('/')[0]
        product_url = f"https://www.books.com.tw/products/{item_id}"
        print(f"訪問商品頁面: {product_url}")  # 除錯訊息
        
        response = requests.get(product_url, headers=headers, timeout=10)
        if response.status_code != 200:
            print(f"商品頁面返回狀態碼: {response.status_code}")  # 除錯訊息
            return False
            
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 3. 提取資訊
        title = soup.select_one('h1').text.strip()
        print(f"找到書名: {title}")  # 除錯訊息
        
        author_elem = soup.select_one('.type02_p003 li')
        author = '未知作者'
        if author_elem:
            author_text = author_elem.text.strip()
            match = re.search(r'作者：\s*([^\s]+)', author_text)
            if match:
                author = match.group(1)
        print(f"找到作者: {author}")  # 除錯訊息
                
        description = soup.select_one('.content')
        description = description.text.strip() if description else '無描述'
        print(f"找到描述，長度: {len(description)}")  # 除錯訊息
        
        # 4. 處理書封
        cover_url = None
        cover_elem = soup.select_one('img.cover')
        if cover_elem and 'src' in cover_elem.attrs:
            cover_url = cover_elem['src']
            print(f"原始書封 URL: {cover_url}")  # 除錯訊息
            if not cover_url.startswith('http'):
                cover_url = "https:" + cover_url
            print(f"處理後書封 URL: {cover_url}")  # 除錯訊息
        else:
            print("找不到書封元素或 src 屬性")  # 除錯訊息
        
        # 5. 更新資料庫
        print("更新資料庫")  # 除錯訊息
        update_data = {
            'title': title,
            'author': author,
            'description': description,
            'product_link': product_url,
            'cover_url': cover_url,  # 直接使用博客來的圖片 URL
            'error_message': None
        }
        print(f"要更新的資料: {update_data}")  # 除錯訊息
        
        result = supabase.table('pending_books')\
            .update(update_data)\
            .eq('isbn', isbn)\
            .eq('owner_id', owner_id)\
            .execute()
            
        print(f"更新結果: {result.data}")  # 除錯訊息
        return True
        
    except Exception as e:
        print(f"處理 ISBN {isbn} 時發生錯誤: {str(e)}")  # 除錯訊息
        supabase.table('pending_books').update({
            'error_message': f'處理失敗: {str(e)}'
        }).eq('isbn', isbn).eq('owner_id', owner_id).execute()
        return False

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        phone = request.form['phone'].strip()
        password = request.form['password']
        name = request.form['name'].strip()
        
        # 基本驗證
        if not phone or not password or not name:
            flash("必填欄位不能為空！")
            return redirect(url_for('register'))
        
        try:
            # 獲取當前最大的書袋編號
            result = supabase.table('users').select('bag_id').order('bag_id', desc=True).limit(1).execute()
            current_max = 0
            if result.data:
                # 從 "BAG1" 格式中提取數字
                match = re.search(r'BAG(\d+)', result.data[0]['bag_id'])
                if match:
                    current_max = int(match.group(1))
            
            # 生成新的書袋編號
            new_bag_id = f"BAG{current_max + 1}"
            
            # 建立新用戶
            hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
            new_user = supabase.table('users').insert({
                'phone': phone,
                'password': hashed_password.decode('utf-8'),
                'name': name,
                'bag_id': new_bag_id,
                'status': '待審核',
                'max_borrow': 2
            }).execute().data[0]

            # 處理書籍 ISBN
            isbns = request.form.get('isbns', '').strip().split('\n')
            added_count = 0
            
            for isbn in isbns:
                isbn = isbn.strip()
                if isbn:
                    try:
                        # 新增到 pending_books 表
                        pending_book = supabase.table('pending_books').insert({
                            'isbn': isbn,
                            'owner_id': new_user['id'],
                            'status': '待審核',
                            'title': '處理中...'  # 添加初始標題
                        }).execute().data[0]
                        added_count += 1
                        
                        # 立即處理書籍資訊
                        process_book_info(isbn, new_user['id'])
                    except Exception as e:
                        print(f"新增書籍失敗 ISBN {isbn}: {str(e)}")
                        continue

            flash("註冊成功，請等待審核！")
            return redirect(url_for('login'))
            
        except Exception as e:
            print(f"Registration error: {str(e)}")
            flash("註冊過程發生錯誤，請稍後再試！")
            return redirect(url_for('register'))

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        phone = request.form['phone']
        password = request.form['password']
        user = supabase.table('users').select('id, phone, password, status').eq('phone', phone).execute().data
        
        if not user:
            flash("手機號碼不存在！")
            return redirect(url_for('login'))
        
        try:
            if not bcrypt.checkpw(password.encode('utf-8'), user[0]['password'].encode('utf-8')):
                flash("密碼錯誤！")
                return redirect(url_for('login'))
        except ValueError:
            flash("密碼驗證失敗，請聯繫管理員！")
            return redirect(url_for('login'))
            
        if user[0]['status'] != '已通過':
            flash("您的帳號尚未通過審核！")
            return redirect(url_for('login'))
            
        session['user_id'] = user[0]['id']
        return redirect(url_for('index'))
        
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/admin', methods=['GET', 'POST'])
def admin_login():
    # 如果在 QR code 模式，直接重定向回借還書頁面
    if session.get('qr_mode'):
        return redirect(url_for('borrow_checkin', bag_id=session.get('bag_id')))
    if 'admin' in session:
        return redirect(url_for('admin_reservations'))
        
    if request.method == 'POST':
        password = request.form['password']
        if password == ADMIN_PASSWORD:
            session['admin'] = True
            return redirect(url_for('admin_reservations'))
        flash("管理員密碼錯誤！")
    return render_template('admin_login.html')

@app.route('/admin/review', methods=['GET', 'POST'])
@admin_required
def admin_review():
    if request.method == 'POST':
        if 'user_id' in request.form:
            user_id = request.form['user_id']
            action = request.form['action']
            supabase.table('users').update({'status': '已通過' if action == 'approved' else '已拒絕'}).eq('id', user_id).execute()
            flash(f"用戶 {user_id} 已處理！")
        elif 'book_id' in request.form:
            book_id = request.form['book_id']
            action = request.form['action']
            supabase.table('pending_books').update({'status': '已通過' if action == 'approved' else '已拒絕'}).eq('id', book_id).execute()
            if action == 'approved':
                # 獲取完整的書籍資訊
                book = supabase.table('pending_books').select('*').eq('id', book_id).execute().data[0]
                supabase.table('publications').insert({
                    'isbn': book['isbn'],
                    'title': book['title'],
                    'author': book['author'],
                    'description': book['description'],
                    'product_link': book['product_link'],
                    'cover_url': book['cover_url'],
                    'owner_id': book['owner_id'],
                    'status': '可借閱'
                }).execute()
            flash(f"書籍 {book_id} 已處理！")
        return redirect(url_for('admin_review'))
    pending_users = supabase.table('users').select('id, phone, name, bag_id').eq('status', '待審核').execute().data
    pending_books = supabase.table('pending_books').select('id, isbn, title, owner_id, status').eq('status', '待審核').execute().data
    return render_template('admin_review.html', pending_users=pending_users, pending_books=pending_books)

@app.route('/admin/book_status')
@admin_required
def admin_book_status():
    # 獲取排序參數
    sort_by = request.args.get('sort', 'title')
    order = request.args.get('order', 'asc')
    
    # 建立基本查詢
    query = supabase.table('publications')\
        .select('''
            *,
            owner:users!publications_owner_id_fkey (
                name,
                phone
            )
        ''')
    
    # 根據排序參數添加排序
    if sort_by == 'title':
        query = query.order('title', desc=(order == 'desc'))
    elif sort_by == 'owner':
        query = query.order('owner(name)', desc=(order == 'desc'))
    elif sort_by == 'status':
        query = query.order('status', desc=(order == 'desc'))
    
    # 執行查詢
    books = query.execute().data
    
    # 獲取借閱資訊
    for book in books:
        # 獲取最新的未完成預約/借閱記錄
        reservation = supabase.table('reservations')\
            .select('''
                *,
                borrower:users!reservations_user_id_fkey (
                    name,
                    phone
                )
            ''')\
            .eq('publication_id', book['id'])\
            .in_('status', ['待處理', '已準備', '已取書'])\
            .limit(1)\
            .execute().data

        # 設置預設值
        book['current_status'] = '可借閱'
        book['status_description'] = '在架上可借閱'
        book['borrower_name'] = '-'
        book['borrower_phone'] = '-'

        if reservation:
            reservation = reservation[0]
            book['current_status'] = reservation['status']
            
            if reservation['status'] == '待處理':
                book['status_description'] = '已申請借閱，待管理員放入書袋'
            elif reservation['status'] == '已準備':
                book['status_description'] = '已放入書袋，待用戶取書'
            elif reservation['status'] == '已取書':
                book['status_description'] = '用戶已取出，待歸還'
            
            book['borrower_name'] = reservation['borrower']['name']
            book['borrower_phone'] = reservation['borrower']['phone']

    # 如果是按借閱者排序，在 Python 中進行排序
    if sort_by == 'borrower':
        books.sort(key=lambda x: (x['borrower_name'] == '-', x['borrower_name']), reverse=(order == 'desc'))

    return render_template('admin_book_status.html', books=books, sort=sort_by, order=order)

@app.route('/admin/reservations', methods=['GET', 'POST'])
@admin_required
def admin_reservations():
    if request.method == 'POST':
        reservation_id = request.form['reservation_id']
        supabase.table('reservations').update({'status': '已準備'}).eq('id', reservation_id).execute()
        flash("書籍已放入書袋！")
        return redirect(url_for('admin_reservations'))
    pending_reservations = supabase.table('reservations').select('id, publication_id, users(name, phone), publications(title)').eq('status', '待處理').execute().data
    return render_template('admin_reservations.html', reservations=pending_reservations)

@app.route('/admin/qr/<bag_id>')
@admin_required
def admin_show_qr(bag_id):
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(url_for('borrow_checkin', bag_id=bag_id, _external=True))
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype='image/png')

@app.route('/admin/qr_codes', methods=['GET', 'POST'])
@admin_required
def admin_qr_codes():
    search_name = request.form.get('search_name', '') if request.method == 'POST' else ''
    query = supabase.table('users').select('id, phone, name, bag_id')
    if search_name:
        query = query.ilike('name', f'%{search_name}%')
    users = query.execute().data
    for user in users:
        user['borrow_url'] = url_for('borrow_checkin', bag_id=user['bag_id'], _external=True)
    return render_template('admin_qr_codes.html', users=users, search_name=search_name)

@app.route('/borrow/<book_id>', methods=['POST'])
def borrow(book_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    current_borrowed = supabase.table('reservations').select('id').eq('user_id', session['user_id']).in_('status', ['待處理', '已準備', '已取書']).execute().data
    user = supabase.table('users').select('max_borrow').eq('id', session['user_id']).execute().data[0]
    if len(current_borrowed) >= user['max_borrow']:
        flash("您已達借書上限！")
        return redirect(url_for('index'))
    
    # 創建預約記錄
    reservation = supabase.table('reservations').insert({
        'user_id': session['user_id'],
        'publication_id': book_id,
        'status': '待處理'
    }).execute().data[0]
    
    # 添加歷史記錄
    supabase.table('reservation_history').insert({
        'reservation_id': reservation['id'],
        'publication_id': book_id,
        'user_id': session['user_id'],
        'action': '預約'
    }).execute()
    
    supabase.table('publications').update({'status': '已借出'}).eq('id', book_id).execute()
    flash("預約成功，請等待管理員放入書袋！")
    return redirect(url_for('index'))

@app.route('/cancel_borrow/<reservation_id>', methods=['POST'])
def cancel_borrow(reservation_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    reservation = supabase.table('reservations').select('publication_id, status').eq('id', reservation_id).eq('user_id', session['user_id']).execute().data
    if reservation:
        if reservation[0]['status'] == '待處理':
            # 添加歷史記錄
            supabase.table('reservation_history').insert({
                'reservation_id': reservation_id,
                'publication_id': reservation[0]['publication_id'],
                'user_id': session['user_id'],
                'action': '取消預約'
            }).execute()
            
            supabase.table('reservations').update({'status': '已取消'}).eq('id', reservation_id).execute()
            supabase.table('publications').update({'status': '可借閱'}).eq('id', reservation[0]['publication_id']).execute()
            flash("已取消預約！")
        else:
            flash("此預約無法取消，因為書籍已經被放入書袋或已被取走。")
    return redirect(url_for('index'))

@app.route('/borrow_checkin/<bag_id>', methods=['GET', 'POST'])
def borrow_checkin(bag_id):
    # 檢查時間戳
    if 'qr_timestamp' in session:
        elapsed_time = time.time() - session['qr_timestamp']
        if elapsed_time > 180:
            session.clear()
            return render_template('qr_expired.html')
    
    # 設置 QR code 模式
    session['qr_mode'] = True
    session['bag_id'] = bag_id
    session['qr_timestamp'] = time.time()

    # 檢查書袋是否有效
    user = supabase.table('users').select('id').eq('bag_id', bag_id).execute().data
    if not user:
        flash("無效的書袋號碼！")
        return redirect(url_for('login'))
    
    user_id = user[0]['id']

    # 如果未登入，重定向到登入頁面
    if 'user_id' not in session:
        session['redirect_after_login'] = request.url
        return redirect(url_for('login'))

    # 檢查是否是正確的用戶
    if session['user_id'] != user_id:
        # 清除 session 中的用戶資訊，但保留 QR 相關資訊
        session.pop('user_id', None)
        flash("您登入的帳號與書袋不符，請使用正確的帳號登入！")
        return redirect(url_for('login'))

    # 處理 POST 請求
    if request.method == 'POST':
        # 再次檢查時間戳
        if 'qr_timestamp' in session:
            elapsed_time = time.time() - session['qr_timestamp']
            if elapsed_time > 180:
                session.clear()
                return render_template('qr_expired.html')
        
        action = request.form.get('action')
        book_ids = request.form.getlist('book_ids')
        if action == 'borrow':
            for book_id in book_ids:
                reservation = supabase.table('reservations').select('id, status').eq('user_id', user_id).eq('publication_id', book_id).eq('status', '已準備').execute().data
                if reservation:
                    # 添加歷史記錄
                    supabase.table('reservation_history').insert({
                        'reservation_id': reservation[0]['id'],
                        'publication_id': book_id,
                        'user_id': user_id,
                        'action': '取書',
                        'borrow_days': 0  # 初始借閱天數為0
                    }).execute()
                    
                    supabase.table('reservations').update({'status': '已取書'}).eq('user_id', user_id).eq('publication_id', book_id).execute()
            flash("已確認取書，您可以帶走書籍了！")
        elif action == 'return':
            for book_id in book_ids:
                reservation = supabase.table('reservations').select('id, status').eq('user_id', user_id).eq('publication_id', book_id).eq('status', '已取書').execute().data
                if reservation:
                    # 計算借閱天數
                    borrow_date_result = supabase.table('reservation_history')\
                        .select('created_at')\
                        .eq('reservation_id', reservation[0]['id'])\
                        .eq('action', '取書')\
                        .execute().data

                    if borrow_date_result:
                        borrow_date = borrow_date_result[0]['created_at']
                        borrow_days = (datetime.now(timezone.utc) - datetime.fromisoformat(borrow_date)).days
                        
                        # 添加歷史記錄
                        supabase.table('reservation_history').insert({
                            'reservation_id': reservation[0]['id'],
                            'publication_id': book_id,
                            'user_id': user_id,
                            'action': '歸還',
                            'borrow_days': borrow_days
                        }).execute()
                        
                        supabase.table('reservations').update({'status': '已歸還'}).eq('user_id', user_id).eq('publication_id', book_id).execute()
                        supabase.table('publications').update({'status': '可借閱'}).eq('id', book_id).execute()
                    else:
                        flash("無法找到借閱日期，請檢查記錄。")
                        continue
            flash("已確認還書，書籍已重新上架！")
        return redirect(url_for('index'))

    # 獲取待取書的書籍
    pending_books = supabase.table('reservations')\
        .select('publication_id, publications(title)')\
        .eq('user_id', user_id)\
        .eq('status', '已準備')\
        .execute().data

    # 獲取已取書的書籍
    borrowed_books = supabase.table('reservations')\
        .select('publication_id, publications(title)')\
        .eq('user_id', user_id)\
        .eq('status', '已取書')\
        .execute().data

    # 移除重複的書籍
    seen_books = set()
    unique_borrowed_books = []
    for book in borrowed_books:
        if book['publication_id'] not in seen_books:
            seen_books.add(book['publication_id'])
            unique_borrowed_books.append(book)

    return render_template('borrow_checkin.html', 
                         pending_books=pending_books, 
                         borrowed_books=unique_borrowed_books,
                         bag_id=bag_id)

@app.route('/exit_qr_mode')
def exit_qr_mode():
    # 清除所有 QR code 相關的 session 數據
    session.pop('qr_mode', None)
    session.pop('bag_id', None)
    session.pop('qr_timestamp', None)
    session.pop('qr_user_id', None)
    flash("已退出 QR 模式")
    return redirect(url_for('index'))

@app.before_request
def check_qr_mode():
    # 如果在 QR code 模式下訪問其他頁面，重定向回借還書頁面
    if session.get('qr_mode') and request.endpoint not in ['borrow_checkin', 'login', 'logout', 'static', 'exit_qr_mode']:
        return redirect(url_for('borrow_checkin', bag_id=session.get('bag_id')))

@app.after_request
def add_header(response):
    if 'Cache-Control' not in response.headers:
        response.headers['Cache-Control'] = 'no-store'
    return response

@app.route('/qr/<bag_id>', methods=['GET'])
def qr_system(bag_id):
    # 重置所有 session，確保是全新的 QR code 操作
    session.clear()
    
    # 檢查書袋是否存在
    bag_user = supabase.table('users').select('id, phone').eq('bag_id', bag_id).execute().data
    if not bag_user:
        return render_template('qr_error.html', message="無效的書袋！")
    
    # 設置新的 QR code 模式
    session['qr_mode'] = True
    session['bag_id'] = bag_id
    session['qr_timestamp'] = time.time()
    
    return redirect(url_for('qr_login', bag_id=bag_id))

@app.route('/qr/login/<bag_id>', methods=['GET', 'POST'])
def qr_login(bag_id):
    # 清除所有 session
    session.clear()
    
    # 檢查書袋是否存在
    bag_user = supabase.table('users').select('id, phone').eq('bag_id', bag_id).execute().data
    if not bag_user:
        return render_template('qr_error.html', message="無效的書袋！")
    
    if request.method == 'POST':
        phone = request.form['phone']
        password = request.form['password']
        
        # 檢查是否是書袋擁有者的手機號碼
        if phone != bag_user[0]['phone']:
            flash("這不是您的書袋！請使用正確的帳號登入。")
            return render_template('qr_login.html', bag_id=bag_id)
        
        # 驗證密碼
        user = supabase.table('users').select('id, password').eq('phone', phone).execute().data
        try:
            if not bcrypt.checkpw(password.encode('utf-8'), user[0]['password'].encode('utf-8')):
                flash("密碼錯誤！")
                return render_template('qr_login.html', bag_id=bag_id)
        except:
            flash("密碼驗證失敗！")
            return render_template('qr_login.html', bag_id=bag_id)
        
        # 設置 QR 系統的 session
        session['qr_mode'] = True
        session['qr_user_id'] = user[0]['id']
        session['qr_timestamp'] = time.time()
        session['bag_id'] = bag_id
        
        return redirect(url_for('qr_borrow_return', bag_id=bag_id))
    
    return render_template('qr_login.html', bag_id=bag_id)

@app.route('/qr/borrow-return/<bag_id>', methods=['GET', 'POST'])
def qr_borrow_return(bag_id):
    if 'qr_timestamp' not in session or time.time() - session['qr_timestamp'] > 180:
        session.clear()
        return render_template('qr_expired.html')
    
    # 檢查是否是正確的書袋
    if session['bag_id'] != bag_id:
        session.clear()
        return redirect(url_for('qr_login', bag_id=bag_id))
    
    # 獲取書籍資訊
    pending_books = supabase.table('reservations')\
        .select('publication_id, publications(title)')\
        .eq('user_id', session['qr_user_id'])\
        .eq('status', '已準備')\
        .execute().data

    borrowed_books = supabase.table('reservations')\
        .select('publication_id, publications(title)')\
        .eq('user_id', session['qr_user_id'])\
        .eq('status', '已取書')\
        .execute().data

    return render_template('qr_borrow_return.html', 
                         pending_books=pending_books, 
                         borrowed_books=borrowed_books,
                         bag_id=bag_id)

@app.route('/qr/logout/<bag_id>')
def qr_logout(bag_id):
    session.clear()
    return redirect(url_for('qr_login', bag_id=bag_id))

@app.route('/admin/pending-books/approve/<isbn>', methods=['POST'])
@admin_required
def approve_book(isbn):
    try:
        # 獲取待審核書籍資訊
        pending_book = supabase.table('pending_books').select('*').eq('isbn', isbn).single().execute()
        
        if not pending_book.data:
            flash('找不到該書籍')
            return redirect(url_for('admin_pending_books'))
        
        # 將書籍資訊複製到 publications
        book_data = {
            'isbn': isbn,
            'title': pending_book.data['title'],
            'author': pending_book.data['author'],
            'description': pending_book.data['description'],
            'cover_url': pending_book.data['cover_url'],
            'product_link': pending_book.data['product_link'],
            'status': '可借閱'
        }
        
        # 新增到 publications
        supabase.table('publications').insert(book_data).execute()
        
        # 更新 pending_books 狀態
        supabase.table('pending_books').update({
            'status': '已審核',
            'processed_at': 'NOW()'
        }).eq('isbn', isbn).execute()
        
        flash('書籍已審核通過並發布')
    except Exception as e:
        flash(f'審核失敗：{str(e)}')
    
    return redirect(url_for('admin_pending_books'))

@app.route('/books')
def books():
    try:
        logger.debug("Accessing books route")
        books_data = supabase.table('publications').select('*').execute()
        logger.debug(f"Retrieved {len(books_data.data)} books")
        return render_template('books.html', books=books_data.data)
    except Exception as e:
        logger.error(f"Error in books route: {e}")
        flash('獲取書籍資料時發生錯誤')
        return redirect(url_for('index'))

@app.route('/add_books', methods=['POST'])
def add_books():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    isbns = request.form.get('isbns', '').strip().split('\n')
    added_count = 0
    errors = []
    
    print(f"收到的 ISBNs: {isbns}")  # 偵錯用
    
    for isbn in isbns:
        isbn = isbn.strip()
        if isbn:
            try:
                print(f"處理 ISBN: {isbn}")  # 偵錯用
                
                # 檢查是否已經存在
                existing = supabase.table('pending_books')\
                    .select('id, status')\
                    .eq('isbn', isbn)\
                    .eq('owner_id', session['user_id'])\
                    .execute()
                
                if existing.data:
                    print(f"ISBN {isbn} 已存在，狀態: {existing.data[0]['status']}")  # 偵錯用
                    errors.append(f"ISBN {isbn} 已經在審核清單中")
                    continue
                
                # 新增到 pending_books
                result = supabase.table('pending_books').insert({
                    'isbn': isbn,
                    'owner_id': session['user_id'],
                    'status': '待審核',
                    'title': '處理中...'  # 添加初始標題
                }).execute()
                
                print(f"新增結果: {result.data}")  # 偵錯用
                
                if result.data:
                    added_count += 1
                    # 立即處理書籍資訊
                    if process_book_info(isbn, session['user_id']):
                        print(f"ISBN {isbn} 資訊處理成功")  # 偵錯用
                    else:
                        print(f"ISBN {isbn} 資訊處理失敗")  # 偵錯用
                        errors.append(f"ISBN {isbn} 資訊處理失敗")
                
            except Exception as e:
                print(f"新增書籍失敗 ISBN {isbn}: {str(e)}")  # 偵錯用
                errors.append(f"ISBN {isbn} 處理時發生錯誤: {str(e)}")
                continue
    
    if added_count > 0:
        flash(f"成功新增 {added_count} 本書籍，請等待審核！")
        if errors:
            flash("部分書籍處理失敗：" + "；".join(errors))
    else:
        if errors:
            flash("新增失敗：" + "；".join(errors))
        else:
            flash("沒有新增任何書籍，請檢查 ISBN 格式是否正確。")
    
    return redirect(url_for('index'))

@app.context_processor
def inject_pending_counts():
    if 'admin' in session:
        pending_users = supabase.table('users').select('id').eq('status', '待審核').execute().data
        pending_books = supabase.table('pending_books').select('id').eq('status', '待審核').execute().data
        pending_reservations = supabase.table('reservations').select('id').eq('status', '待處理').execute().data
        return {
            'pending_users': pending_users,
            'pending_books': pending_books,
            'pending_reservations': pending_reservations
        }
    return {
        'pending_users': [],
        'pending_books': [],
        'pending_reservations': []
    }

@app.route('/admin/logout')
def admin_logout():
    session.clear()
    return redirect(url_for('admin_login'))

@app.route('/admin/reservation_history')
@admin_required
def admin_reservation_history():
    # 獲取頁碼，預設為1
    page = int(request.args.get('page', 1))
    per_page = 50
    
    # 計算偏移量
    offset = (page - 1) * per_page
    
    # 獲取歷史記錄
    history = supabase.table('reservation_history')\
        .select('''
            *,
            publication:publications(title),
            user:users(name, phone)
        ''')\
        .order('created_at', desc=True)\
        .range(offset, offset + per_page - 1)\
        .execute().data
    
    # 獲取總記錄數
    count = supabase.table('reservation_history')\
        .select('id', count='exact')\
        .execute().count
    
    # 計算總頁數
    total_pages = (count + per_page - 1) // per_page
    
    return render_template('admin_reservation_history.html',
                         history=history,
                         current_page=page,
                         total_pages=total_pages)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000, debug=True)
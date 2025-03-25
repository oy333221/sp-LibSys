from flask import Flask, render_template, request, redirect, url_for, session, send_file, flash
from supabase import create_client, Client
import bcrypt
import qrcode
from io import BytesIO
import os
from functools import wraps
import requests
from datetime import datetime, timedelta
import time
import logging
from bs4 import BeautifulSoup
import re

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='static', static_url_path='/static')
app.secret_key = os.urandom(24)

supabase_url = "https://uidcuqimzkzvoscqhyax.supabase.co"
supabase_key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InVpZGN1cWltemt6dm9zY3FoeWF4Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDA2Mzg1OTcsImV4cCI6MjA1NjIxNDU5N30.e3U8j15-VB7fQhSG1VQk99tB8PuV-VjETHFXcvNlMBo"
supabase: Client = create_client(supabase_url, supabase_key)

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
        .select('id, title, description, product_link, status')\
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
        print(f"開始處理 ISBN {isbn} 的資訊")
        
        # 使用博客來爬蟲
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        
        # 1. 搜尋頁面
        search_url = f"https://search.books.com.tw/search/query/key/{isbn}/cat/all"
        search_response = requests.get(search_url, headers=headers, timeout=10)
        if search_response.status_code != 200:
            print(f"搜尋頁面返回狀態碼: {search_response.status_code}")
            return False
            
        search_soup = BeautifulSoup(search_response.text, 'html.parser')
        product_link = search_soup.select_one('a[href*="/redirect/move/"]')
        if not product_link:
            print("找不到商品連結")
            return False
            
        # 2. 取得商品頁面
        item_id = product_link['href'].split('item/')[1].split('/')[0]
        product_url = f"https://www.books.com.tw/products/{item_id}"
        
        response = requests.get(product_url, headers=headers, timeout=10)
        if response.status_code != 200:
            print(f"商品頁面返回狀態碼: {response.status_code}")
            return False
            
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 3. 提取資訊
        title = soup.select_one('h1').text.strip()
        
        author_elem = soup.select_one('.type02_p003 li')
        author = '未知作者'
        if author_elem:
            author_text = author_elem.text.strip()
            match = re.search(r'作者：\s*([^\s]+)', author_text)
            if match:
                author = match.group(1)
                
        description = soup.select_one('.content')
        description = description.text.strip() if description else '無描述'
        
        # 4. 處理書封
        cover_path = None
        cover_elem = soup.select_one('img.cover')
        if cover_elem and 'src' in cover_elem.attrs:
            cover_url = cover_elem['src']
            if not cover_url.startswith('http'):
                cover_url = "https:" + cover_url
                
            img_response = requests.get(cover_url, headers=headers, timeout=10)
            if img_response.status_code == 200:
                cover_path = f"/covers/{isbn}.jpg"
                with open(os.path.join('static/covers', f"{isbn}.jpg"), 'wb') as f:
                    f.write(img_response.content)
        
        # 5. 更新資料庫
        update_data = {
            'title': title,
            'author': author,
            'description': description,
            'product_link': product_url,
            'cover_url': cover_path,
            'error_message': None
        }
        
        result = supabase.table('pending_books')\
            .update(update_data)\
            .eq('isbn', isbn)\
            .eq('owner_id', owner_id)\
            .execute()
        
        print(f"更新結果: {result.data}")
        return True
        
    except Exception as e:
        print(f"處理 ISBN {isbn} 時發生錯誤: {str(e)}")
        supabase.table('pending_books').update({
            'error_message': '無法從博客來找到此書籍'
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
            # 建立新用戶
            hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
            bag_id = f"BAG_{phone}_{os.urandom(4).hex()}"
            new_user = supabase.table('users').insert({
                'phone': phone,
                'password': hashed_password.decode('utf-8'),
                'name': name,
                'bag_id': bag_id,
                'status': '待審核',
                'max_borrow': 2
            }).execute().data[0]

            # 處理書籍 ISBN（使用相同的邏輯）
            isbns = request.form.get('isbns', '').strip().split('\n')
            added_count = 0
            
            for isbn in isbns:
                isbn = isbn.strip()
                if isbn:
                    try:
                        supabase.table('pending_books').insert({
                            'isbn': isbn,
                            'owner_id': new_user['id'],
                            'status': '待審核'
                        }).execute()
                        added_count += 1
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
        return redirect(url_for('admin_review'))
        
    if request.method == 'POST':
        password = request.form['password']
        if password == "1576":
            session['admin'] = True
            return redirect(url_for('admin_review'))
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
                book = supabase.table('pending_books').select('isbn, title, owner_id').eq('id', book_id).execute().data[0]
                supabase.table('publications').insert({
                    'isbn': book['isbn'],
                    'title': book['title'],
                    'author': '未知作者',
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
    # 修正查詢，移除 created_at 排序
    books = supabase.table('publications')\
        .select('''
            *,
            owner:users!publications_owner_id_fkey (
                name,
                phone
            )
        ''')\
        .execute().data

    for book in books:
        # 獲取最新的未完成預約/借閱記錄，移除 order by created_at
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

    return render_template('admin_book_status.html', books=books)

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
    supabase.table('reservations').insert({
        'user_id': session['user_id'],
        'publication_id': book_id,
        'status': '待處理'
    }).execute()
    supabase.table('publications').update({'status': '已借出'}).eq('id', book_id).execute()
    flash("預約成功，請等待管理員放入書袋！")
    return redirect(url_for('index'))

@app.route('/cancel_borrow/<reservation_id>', methods=['POST'])
def cancel_borrow(reservation_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    reservation = supabase.table('reservations').select('publication_id').eq('id', reservation_id).eq('user_id', session['user_id']).execute().data
    if reservation:
        supabase.table('reservations').update({'status': '已取消'}).eq('id', reservation_id).execute()
        supabase.table('publications').update({'status': '可借閱'}).eq('id', reservation[0]['publication_id']).execute()
        flash("已取消預約！")
    return redirect(url_for('index'))

@app.route('/borrow_checkin/<bag_id>', methods=['GET', 'POST'])
def borrow_checkin(bag_id):
    # 設置 QR code 模式
    session['qr_mode'] = True
    session['bag_id'] = bag_id
    session['qr_timestamp'] = time.time()
    
    # 檢查時間戳
    if 'qr_timestamp' in session:
        elapsed_time = time.time() - session['qr_timestamp']
        if elapsed_time > 600:
            session.pop('user_id', None)
            flash('操作時間已過期，請重新掃描 QR Code！')
            return redirect(url_for('login'))

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
            if elapsed_time > 600:
                flash('操作時間已過期，請重新掃描 QR Code！')
                return redirect(url_for('login'))
        
        action = request.form.get('action')
        book_ids = request.form.getlist('book_ids')
        if action == 'borrow':
            for book_id in book_ids:
                reservation = supabase.table('reservations').select('status').eq('user_id', user_id).eq('publication_id', book_id).eq('status', '已準備').execute().data
                if reservation:
                    supabase.table('reservations').update({'status': '已取書'}).eq('user_id', user_id).eq('publication_id', book_id).execute()
            flash("已確認取書，您可以帶走書籍了！")
        elif action == 'return':
            for book_id in book_ids:
                reservation = supabase.table('reservations').select('status').eq('user_id', user_id).eq('publication_id', book_id).eq('status', '已取書').execute().data
                if reservation:
                    supabase.table('reservations').update({'status': '已歸還'}).eq('user_id', user_id).eq('publication_id', book_id).execute()
                    supabase.table('publications').update({'status': '可借閱'}).eq('id', book_id).execute()
            flash("已確認還書，書籍已重新上架！")
        return redirect(url_for('index'))

    # 獲取書籍資訊
    pending_books = supabase.table('reservations')\
        .select('publication_id, publications(title)')\
        .eq('user_id', user_id)\
        .eq('status', '已準備')\
        .execute().data

    borrowed_books = supabase.table('reservations')\
        .select('publication_id, publications(title)')\
        .eq('user_id', user_id)\
        .eq('status', '已取書')\
        .execute().data

    return render_template('borrow_checkin.html', 
                         pending_books=pending_books, 
                         borrowed_books=borrowed_books,
                         bag_id=bag_id)

@app.route('/exit_qr_mode')
def exit_qr_mode():
    session.clear()
    return redirect(url_for('login'))

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
    # 嚴格檢查 QR 模式的 session
    if not all(key in session for key in ['qr_mode', 'qr_user_id', 'qr_timestamp', 'bag_id']):
        return redirect(url_for('qr_login', bag_id=bag_id))
    
    # 檢查是否是正確的書袋
    if session['bag_id'] != bag_id:
        session.clear()
        return redirect(url_for('qr_login', bag_id=bag_id))
    
    # 檢查時間是否過期
    if time.time() - session['qr_timestamp'] > 600:
        session.clear()
        flash('操作時間已過期，請重新掃描 QR Code！')
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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000, debug=True)
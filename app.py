from flask import Flask, render_template, request, redirect, url_for, session, send_file
from supabase import create_client, Client
import bcrypt
import os
import qrcode
from io import BytesIO

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Supabase 連線
supabase_url = "https://uidcuqimzkzvoscqhyax.supabase.co"
supabase_key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InVpZGN1cWltemt6dm9zY3FoeWF4Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDA2Mzg1OTcsImV4cCI6MjA1NjIxNDU5N30.e3U8j15-VB7fQhSG1VQk99tB8PuV-VjETHFXcvNlMBo"
supabase: Client = create_client(supabase_url, supabase_key)

# 生成 QR Code 函數
def generate_qr_code(data):
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill='black', back_color='white')
    img_byte_arr = BytesIO()
    img.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)
    return img_byte_arr

# 首頁 - 顯示可借書籍
@app.route('/')
def index():
    books = supabase.table('publications').select('*').eq('status', 'available').execute().data
    return render_template('index.html', books=books)

# 註冊頁面
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        bag_id = f"BAG_{email.split('@')[0]}_{os.urandom(4).hex()}"

        existing = supabase.table('users').select('email').eq('email', email).execute()
        if existing.data:
            return "此信箱已被註冊！"

        try:
            supabase.table('users').insert({
                'email': email,
                'password': hashed_password,
                'bag_id': bag_id
            }).execute()
            return redirect(url_for('index'))
        except Exception as e:
            return f"註冊失敗: {str(e)}"
    return render_template('register.html')

# 登入頁面
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = supabase.table('users').select('id, email, password').eq('email', email).execute().data
        if not user or not bcrypt.checkpw(password.encode('utf-8'), user[0]['password'].encode('utf-8')):
            return "信箱或密碼錯誤！"
        session['user_id'] = user[0]['id']
        return redirect(url_for('index'))
    return render_template('login.html')

# 登出
@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('index'))

# 新增書籍頁面
@app.route('/add_book', methods=['GET', 'POST'])
def add_book():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        isbn = request.form['isbn']
        title = request.form['title']
        author = request.form['author']
        owner_id = session['user_id']
        description = request.form.get('description', '')
        existing = supabase.table('publications').select('isbn').eq('isbn', isbn).execute()
        if existing.data:
            return "此 ISBN 已存在！"
        try:
            supabase.table('publications').insert({
                'isbn': isbn,
                'title': title,
                'author': author,
                'owner_id': owner_id,
                'status': 'available',
                'description': description
            }).execute()
            return redirect(url_for('index'))
        except Exception as e:
            return f"書籍新增失敗: {str(e)}"
    return render_template('add_book.html')

# 借書功能
@app.route('/borrow/<int:book_id>', methods=['POST'])
def borrow(book_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
    book = supabase.table('publications').select('status').eq('id', book_id).execute().data
    if not book or book[0]['status'] != 'available':
        return "此書已被借出或不存在！"
    supabase.table('publications').update({'status': 'borrowed'}).eq('id', book_id).execute()
    supabase.table('reservations').insert({
        'user_id': user_id,
        'publication_id': book_id,
        'status': 'pending'
    }).execute()
    return redirect(url_for('index'))

# 顯示 QR Code
@app.route('/qr/<action>')
def show_qr(action):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = supabase.table('users').select('bag_id').eq('id', session['user_id']).execute().data[0]
    bag_id = user['bag_id']
    qr_data = f"{action}:{bag_id}"  # 例如 "borrow:BAG_user_1234" 或 "return:BAG_user_1234"
    qr_img = generate_qr_code(qr_data)
    return send_file(qr_img, mimetype='image/png')

# 還書頁面
@app.route('/return', methods=['GET', 'POST'])
def return_book():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']

    if request.method == 'POST':
        book_ids = request.form.getlist('book_ids')  # 用戶勾選要還的書
        for book_id in book_ids:
            # 檢查是否有此預約
            reservation = supabase.table('reservations').select('status').eq('user_id', user_id).eq('publication_id', book_id).execute().data
            if reservation and reservation[0]['status'] in ['pending', 'picked_up']:
                # 更新預約狀態為已還
                supabase.table('reservations').update({'status': 'returned'}).eq('user_id', user_id).eq('publication_id', book_id).execute()
                # 更新書籍狀態為可借
                supabase.table('publications').update({'status': 'available'}).eq('id', book_id).execute()
        return redirect(url_for('index'))

    # 顯示用戶當前借閱的書籍
    borrowed_books = supabase.table('reservations')\
        .select('publication_id, publications(title, author, isbn)')\
        .eq('user_id', user_id)\
        .in_('status', ['pending', 'picked_up'])\
        .execute().data
    return render_template('return.html', borrowed_books=borrowed_books)

if __name__ == '__main__':
    app.run(debug=True)
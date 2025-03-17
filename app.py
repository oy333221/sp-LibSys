from flask import Flask, render_template, request, redirect, url_for, session, send_file, flash
from supabase import create_client, Client
import bcrypt
import os
import qrcode
from io import BytesIO

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', os.urandom(24))

# Supabase 連線
supabase_url = "https://uidcuqimzkzvoscqhyax.supabase.co"
supabase_key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InVpZGN1cWltemt6dm9zY3FoeWF4Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDA2Mzg1OTcsImV4cCI6MjA1NjIxNDU5N30.e3U8j15-VB7fQhSG1VQk99tB8PuV-VjETHFXcvNlMBo"
supabase: Client = create_client(supabase_url, supabase_key)


# 固定管理員密鑰
ADMIN_KEY = "1576"

# 生成 QR Code
def generate_qr_code(data):
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill='black', back_color='white')
    img_byte_arr = BytesIO()
    img.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)
    return img_byte_arr

# 首頁
@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    books = supabase.table('publications').select('*').eq('status', 'available').execute().data
    return render_template('index.html', books=books)

# 註冊頁面
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        isbns = request.form.getlist('isbn')
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        bag_id = f"BAG_{email.split('@')[0]}_{os.urandom(4).hex()}"

        existing_user = supabase.table('users').select('email').eq('email', email).execute()
        if existing_user.data:
            flash("此信箱已被註冊！")
            return redirect(url_for('register'))

        for isbn in isbns:
            if isbn and supabase.table('publications').select('isbn').eq('isbn', isbn).execute().data:
                flash(f"ISBN {isbn} 已存在！")
                return redirect(url_for('register'))

        user_data = {
            'email': email,
            'password': hashed_password,
            'bag_id': bag_id,
            'status': 'pending',
            'max_borrow': 2
        }
        new_user = supabase.table('users').insert(user_data).execute().data[0]

        for isbn in isbns:
            if isbn:
                supabase.table('publications').insert({
                    'isbn': isbn,
                    'title': request.form.get(f'title_{isbn}', '未知書名'),
                    'author': request.form.get(f'author_{isbn}', '未知作者'),
                    'owner_id': new_user['id'],
                    'status': 'available',
                    'description': ''
                }).execute()

        flash("註冊申請已提交，請等待管理員審核！")
        return redirect(url_for('login'))
    return render_template('register.html')

# 登入頁面（僅限普通用戶）
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = supabase.table('users').select('id, email, password, status').eq('email', email).execute().data
        if not user or not bcrypt.checkpw(password.encode('utf-8'), user[0]['password'].encode('utf-8')):
            flash("信箱或密碼錯誤！")
            return redirect(url_for('login'))
        if user[0]['status'] != 'approved':
            flash("您的帳號尚未通過審核！")
            return redirect(url_for('login'))
        session['user_id'] = user[0]['id']
        return redirect(url_for('index'))
    return render_template('login.html')

# 登出
@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))

# 管理員入口
@app.route('/admin', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        key = request.form['key']
        if key == ADMIN_KEY:
            session['admin'] = True
            return redirect(url_for('admin_review'))
        else:
            flash("密鑰錯誤！")
            return redirect(url_for('admin_login'))
    return render_template('admin_login.html')

# 管理員審核頁面
@app.route('/admin/review', methods=['GET', 'POST'])
def admin_review():
    if 'admin' not in session:
        return redirect(url_for('admin_login'))
    
    if request.method == 'POST':
        user_id = request.form['user_id']
        action = request.form['action']
        if action == 'approve':
            supabase.table('users').update({'status': 'approved'}).eq('id', user_id).execute()
            flash("用戶已通過審核！")
        elif action == 'reject':
            supabase.table('users').update({'status': 'rejected'}).eq('id', user_id).execute()
            flash("用戶已被拒絕！")
        return redirect(url_for('admin_review'))

    pending_users = supabase.table('users').select('id, email, bag_id').eq('status', 'pending').execute().data
    return render_template('admin_review.html', pending_users=pending_users)

# 管理員設定借書上限
@app.route('/admin/limits', methods=['GET', 'POST'])
def admin_limits():
    if 'admin' not in session:
        return redirect(url_for('admin_login'))
    
    if request.method == 'POST':
        user_id = request.form['user_id']
        max_borrow = int(request.form['max_borrow'])
        supabase.table('users').update({'max_borrow': max_borrow}).eq('id', user_id).execute()
        flash("借書上限已更新！")
        return redirect(url_for('admin_limits'))

    users = supabase.table('users').select('id, email, max_borrow').execute().data
    return render_template('admin_limits.html', users=users)

# 管理員查看書籍狀態
@app.route('/admin/books')
def admin_books():
    if 'admin' not in session:
        return redirect(url_for('admin_login'))
    books = supabase.table('publications')\
        .select('id, title, isbn, status, owner_id, users(email AS owner_email), reservations(user_id, users(email AS borrower_email))')\
        .execute().data
    return render_template('admin_books.html', books=books)

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
            flash("此 ISBN 已存在！")
            return redirect(url_for('add_book'))
        supabase.table('publications').insert({
            'isbn': isbn,
            'title': title,
            'author': author,
            'owner_id': owner_id,
            'status': 'available',
            'description': description
        }).execute()
        flash("書籍已新增！")
        return redirect(url_for('index'))
    return render_template('add_book.html')

# 借書功能
@app.route('/borrow/<int:book_id>', methods=['POST'])
def borrow(book_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
    user = supabase.table('users').select('max_borrow, bag_id').eq('id', user_id).execute().data[0]
    current_borrows = supabase.table('reservations').select('count').eq('user_id', user_id).in_('status', ['pending', 'picked_up']).execute().data[0]['count']

    if current_borrows >= user['max_borrow']:
        flash("您已達到借書上限！")
        return redirect(url_for('index'))

    book = supabase.table('publications').select('status').eq('id', book_id).execute().data
    if not book or book[0]['status'] != 'available':
        flash("此書已被借出或不存在！")
        return redirect(url_for('index'))

    supabase.table('publications').update({'status': 'borrowed'}).eq('id', book_id).execute()
    supabase.table('reservations').insert({
        'user_id': user_id,
        'publication_id': book_id,
        'status': 'pending'
    }).execute()
    flash(f"已完成借書申請，請於週日 8~13 點前往取書，您的書袋號碼為 {user['bag_id']}，請取書後掃描您的個人條碼完成取書登記。")
    return redirect(url_for('index'))

# 顯示 QR Code
@app.route('/qr/<action>')
def show_qr(action):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = supabase.table('users').select('bag_id').eq('id', session['user_id']).execute().data[0]
    qr_data = f"{action}:{user['bag_id']}"
    qr_img = generate_qr_code(qr_data)
    return send_file(qr_img, mimetype='image/png')

# 借書登記頁面
@app.route('/borrow_checkin', methods=['GET', 'POST'])
def borrow_checkin():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']

    if request.method == 'POST':
        book_ids = request.form.getlist('book_ids')
        for book_id in book_ids:
            reservation = supabase.table('reservations').select('status').eq('user_id', user_id).eq('publication_id', book_id).eq('status', 'pending').execute().data
            if reservation:
                supabase.table('reservations').update({'status': 'picked_up'}).eq('user_id', user_id).eq('publication_id', book_id).execute()
        flash("可以取書了，記得於週日同一時間返還，並提醒還書時掃描還書 QR Code。")
        return redirect(url_for('index'))

    pending_books = supabase.table('reservations')\
        .select('publication_id, publications(title, author, isbn)')\
        .eq('user_id', user_id)\
        .eq('status', 'pending')\
        .execute().data
    return render_template('borrow_checkin.html', pending_books=pending_books)

# 還書頁面
@app.route('/return', methods=['GET', 'POST'])
def return_book():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']

    if request.method == 'POST':
        book_ids = request.form.getlist('book_ids')
        for book_id in book_ids:
            reservation = supabase.table('reservations').select('status').eq('user_id', user_id).eq('publication_id', book_id).in_('status', ['pending', 'picked_up']).execute().data
            if reservation:
                supabase.table('reservations').update({'status': 'returned'}).eq('user_id', user_id).eq('publication_id', book_id).execute()
                supabase.table('publications').update({'status': 'available'}).eq('id', book_id).execute()
        flash("可以將書放入個人書袋，完成還書。")
        return redirect(url_for('index'))

    borrowed_books = supabase.table('reservations')\
        .select('publication_id, publications(title, author, isbn)')\
        .eq('user_id', user_id)\
        .in_('status', ['pending', 'picked_up'])\
        .execute().data
    return render_template('return.html', borrowed_books=borrowed_books)

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
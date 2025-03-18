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
    books = supabase.table('publications').select('id, title, isbn, author, description, product_link').eq('status', 'available').execute().data
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
                supabase.table('pending_books').insert({
                    'isbn': isbn,
                    'author': request.form.get(f'author_{isbn}', '未知作者'),
                    'owner_id': new_user['id'],
                    'status': 'pending'
                }).execute()

        flash("註冊申請已提交，請等待管理員審核！")
        return redirect(url_for('login'))
    return render_template('register.html')

# 登入頁面
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
    session.pop('admin', None)
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
            pending_books = supabase.table('pending_books').select('*').eq('owner_id', user_id).eq('status', 'pending').execute().data
            for book in pending_books:
                supabase.table('publications').insert({
                    'isbn': book['isbn'],
                    'title': '待補充',
                    'author': book['author'],
                    'owner_id': user_id,
                    'status': 'available',
                    'description': '',
                    'product_link': ''
                }).execute()
                supabase.table('pending_books').update({'status': 'approved'}).eq('id', book['id']).execute()
            flash("用戶及其書籍已通過審核！")
        elif action == 'reject':
            supabase.table('users').update({'status': 'rejected'}).eq('id', user_id).execute()
            supabase.table('pending_books').update({'status': 'rejected'}).eq('owner_id', user_id).execute()
            flash("用戶及其書籍已被拒絕！")
        return redirect(url_for('admin_review'))

    pending_users = supabase.table('users').select('id, email, bag_id').eq('status', 'pending').execute().data
    for user in pending_users:
        user['pending_books'] = supabase.table('pending_books').select('isbn, author').eq('owner_id', user['id']).eq('status', 'pending').execute().data
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

    users = supabase.table('users').select('id, email, max_borrow').eq('status', 'approved').execute().data
    return render_template('admin_limits.html', users=users)

# 管理員查看書籍狀態
@app.route('/admin/books')
def admin_books():
    if 'admin' not in session:
        return redirect(url_for('admin_login'))
    try:
        books = supabase.table('publications')\
            .select('id, title, isbn, status, owner_id')\
            .execute().data
        print(f"Books retrieved: {books}")

        if not books:
            print("No books found in publications table.")
            return render_template('admin_books.html', books=[])

        for book in books:
            owner = supabase.table('users')\
                .select('email, bag_id')\
                .eq('id', book['owner_id'])\
                .execute().data
            book['owner_email'] = owner[0]['email'] if owner else '未知用戶'
            book['bag_id'] = owner[0]['bag_id'] if owner else '未知'

            reservation = supabase.table('reservations')\
                .select('user_id')\
                .eq('publication_id', book['id'])\
                .in_('status', ['pending', 'picked_up'])\
                .execute().data
            if reservation:
                borrower = supabase.table('users')\
                    .select('email')\
                    .eq('id', reservation[0]['user_id'])\
                    .execute().data
                book['borrower_email'] = borrower[0]['email'] if borrower else '未知'
            else:
                book['borrower_email'] = '無'

        print(f"Processed books: {books}")
        return render_template('admin_books.html', books=books)
    except Exception as e:
        print(f"Error in admin_books: {str(e)}")
        return f"伺服器錯誤: {str(e)}", 500

# 新增書籍頁面
@app.route('/add_book', methods=['GET', 'POST'])
def add_book():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        isbn = request.form['isbn']
        author = request.form['author']
        owner_id = session['user_id']
        existing = supabase.table('publications').select('isbn').eq('isbn', isbn).execute()
        if existing.data:
            flash("此 ISBN 已存在！")
            return redirect(url_for('add_book'))
        supabase.table('pending_books').insert({
            'isbn': isbn,
            'author': author,
            'owner_id': owner_id,
            'status': 'pending'
        }).execute()
        flash("書籍已提交，請等待管理員審核！")
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
    flash(f"已完成借書申請，請於週日 8~13 點前往取書，您的書袋號碼為 {user['bag_id']}，到現場掃描您的借書 QR Code 確認取書。")
    return redirect(url_for('index'))

# 管理員生成用戶的 QR Code
@app.route('/admin/qr/<action>/<bag_id>')
def admin_show_qr(action, bag_id):
    if 'admin' not in session:
        return redirect(url_for('admin_login'))
    if action not in ['borrow', 'return']:
        return "無效的操作", 400
    # QR Code 指向用戶專屬頁面
    qr_data = url_for('borrow_checkin' if action == 'borrow' else 'return_book', bag_id=bag_id, _external=True)
    qr_img = generate_qr_code(qr_data)
    return send_file(qr_img, mimetype='image/png')

# 借書確認頁面（掃描借書 QR Code 後）
@app.route('/borrow_checkin/<bag_id>', methods=['GET', 'POST'])
def borrow_checkin(bag_id):
    user = supabase.table('users').select('id').eq('bag_id', bag_id).execute().data
    if not user:
        flash("無效的書袋號碼！")
        return redirect(url_for('login'))
    user_id = user[0]['id']

    if 'user_id' not in session:
        return redirect(url_for('login'))

    if session['user_id'] != user_id:
        flash("這不是您的書袋！")
        return redirect(url_for('index'))

    if request.method == 'POST':
        book_ids = request.form.getlist('book_ids')
        for book_id in book_ids:
            reservation = supabase.table('reservations')\
                .select('status')\
                .eq('user_id', user_id)\
                .eq('publication_id', book_id)\
                .eq('status', 'pending')\
                .execute().data
            if reservation:
                supabase.table('reservations').update({'status': 'picked_up'}).eq('user_id', user_id).eq('publication_id', book_id).execute()
        flash("已確認取書，您可以帶走書籍了！")
        return redirect(url_for('index'))

    pending_books = supabase.table('reservations')\
        .select('publication_id, publications(title, author, isbn)')\
        .eq('user_id', user_id)\
        .eq('status', 'pending')\
        .execute().data
    return render_template('borrow_checkin.html', pending_books=pending_books, bag_id=bag_id)

# 還書頁面（掃描還書 QR Code 後）
@app.route('/return/<bag_id>', methods=['GET', 'POST'])
def return_book(bag_id):
    user = supabase.table('users').select('id').eq('bag_id', bag_id).execute().data
    if not user:
        flash("無效的書袋號碼！")
        return redirect(url_for('login'))
    user_id = user[0]['id']

    if request.method == 'POST':
        book_ids = request.form.getlist('book_ids')
        for book_id in book_ids:
            reservation = supabase.table('reservations')\
                .select('status')\
                .eq('user_id', user_id)\
                .eq('publication_id', book_id)\
                .in_('status', ['pending', 'picked_up'])\
                .execute().data
            if reservation:
                supabase.table('reservations').update({'status': 'returned'}).eq('user_id', user_id).eq('publication_id', book_id).execute()
                supabase.table('publications').update({'status': 'available'}).eq('id', book_id).execute()
        flash("已確認還書，請將書籍放入袋中！")
        return redirect(url_for('return_book', bag_id=bag_id))

    borrowed_books = supabase.table('reservations')\
        .select('publication_id, publications(title, author, isbn)')\
        .eq('user_id', user_id)\
        .in_('status', ['pending', 'picked_up'])\
        .execute().data
    return render_template('return.html', borrowed_books=borrowed_books, bag_id=bag_id)

# 管理員查看借閱狀態（確認放入袋子）
@app.route('/admin/reservations', methods=['GET', 'POST'])
def admin_reservations():
    if 'admin' not in session:
        return redirect(url_for('admin_login'))
    if request.method == 'POST':
        reservation_id = request.form['reservation_id']
        supabase.table('reservations').update({'status': 'prepared'}).eq('id', reservation_id).execute()
        flash("已確認放入借書袋！")
        return redirect(url_for('admin_reservations'))

    pending_reservations = supabase.table('reservations')\
        .select('id, user_id, publication_id, users(email, bag_id), publications(title, isbn)')\
        .eq('status', 'pending')\
        .execute().data
    return render_template('admin_reservations.html', pending_reservations=pending_reservations)

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
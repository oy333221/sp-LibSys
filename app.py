from flask import Flask, render_template, request, redirect, url_for, session, send_file, flash
from supabase import create_client, Client
import bcrypt
import qrcode
from io import BytesIO
import os

app = Flask(__name__)
app.secret_key = os.urandom(24)

supabase_url = "https://uidcuqimzkzvoscqhyax.supabase.co"
supabase_key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InVpZGN1cWltemt6dm9zY3FoeWF4Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDA2Mzg1OTcsImV4cCI6MjA1NjIxNDU5N30.e3U8j15-VB7fQhSG1VQk99tB8PuV-VjETHFXcvNlMBo"
supabase: Client = create_client(supabase_url, supabase_key)

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    books = supabase.table('publications').select('id, title, isbn, author, description, product_link').eq('status', 'available').execute().data
    reservations = supabase.table('reservations').select('id, publication_id, publications(title, isbn), status').eq('user_id', session['user_id']).in_('status', ['pending', 'prepared', 'picked_up']).execute().data
    return render_template('index.html', books=books, reservations=reservations)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        phone = request.form['phone']
        password = request.form['password']
        isbn = request.form['isbn']
        title = request.form['title']
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        existing_user = supabase.table('users').select('phone').eq('phone', phone).execute()
        if existing_user.data:
            flash("此手機號碼已被註冊！")
            return redirect(url_for('register'))
        bag_id = f"BAG_uu_{os.urandom(4).hex()}"
        new_user = supabase.table('users').insert({
            'phone': phone,
            'password': hashed_password.decode('utf-8'),
            'bag_id': bag_id,
            'status': 'pending',
            'max_borrow': 2
        }).execute().data[0]
        existing_book = supabase.table('publications').select('isbn').eq('isbn', isbn).execute()
        if existing_book.data:
            flash(f"ISBN {isbn} 已存在！")
        else:
            supabase.table('pending_books').insert({
                'isbn': isbn,
                'title': title,
                'author': '未知作者',  # 預設值，避免 NOT NULL 錯誤
                'owner_id': new_user['id'],
                'status': 'pending'
            }).execute()
        flash("註冊成功，請等待審核！")
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        phone = request.form['phone']
        password = request.form['password']
        user = supabase.table('users').select('id, phone, password, status').eq('phone', phone).execute().data
        if not user or not bcrypt.checkpw(password.encode('utf-8'), user[0]['password'].encode('utf-8')):
            flash("手機號碼或密碼錯誤！")
            return redirect(url_for('login'))
        if user[0]['status'] != 'approved':
            flash("您的帳號尚未通過審核！")
            return redirect(url_for('login'))
        session['user_id'] = user[0]['id']
        redirect_url = session.pop('redirect_after_login', url_for('index'))
        return redirect(redirect_url)
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('admin', None)
    return redirect(url_for('login'))

@app.route('/admin', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        password = request.form['password']  # 如果表單沒 password，這裡會崩潰
        if password == "1576":
            session['admin'] = True
            return redirect(url_for('admin_review'))
        flash("密碼錯誤！")
    return render_template('admin_login.html')

@app.route('/admin/review', methods=['GET', 'POST'])
def admin_review():
    if 'admin' not in session:
        return redirect(url_for('admin_login'))
    if request.method == 'POST':
        user_id = request.form['user_id']
        action = request.form['action']
        supabase.table('users').update({'status': action}).eq('id', user_id).execute()
        if action == 'approved':
            flash(f"用戶 {user_id} 已通過審核！")
        elif action == 'rejected':
            flash(f"用戶 {user_id} 已拒絕！")
        return redirect(url_for('admin_review'))
    pending_users = supabase.table('users').select('id, phone, bag_id').eq('status', 'pending').execute().data
    return render_template('admin_review.html', pending_users=pending_users)

@app.route('/admin/books', methods=['GET', 'POST'])
def admin_books():
    if 'admin' not in session:
        return redirect(url_for('admin_login'))
    if request.method == 'POST':
        book_id = request.form['book_id']
        action = request.form['action']
        supabase.table('pending_books').update({'status': action}).eq('id', book_id).execute()
        if action == 'approved':
            book = supabase.table('pending_books').select('isbn, title, owner_id').eq('id', book_id).execute().data[0]
            supabase.table('publications').insert({
                'isbn': book['isbn'],
                'title': book['title'],
                'author': '未知作者',
                'owner_id': book['owner_id'],
                'status': 'available'
            }).execute()
            flash(f"書籍 {book['title']} 已上架！")
        return redirect(url_for('admin_books'))
    pending_books = supabase.table('pending_books').select('id, isbn, title, owner_id, status').in_('status', ['pending', 'reported']).execute().data
    return render_template('admin_books.html', pending_books=pending_books)

@app.route('/admin/reservations', methods=['GET', 'POST'])
def admin_reservations():
    if 'admin' not in session:
        return redirect(url_for('admin_login'))
    if request.method == 'POST':
        action = request.form['action']
        reservation_id = request.form['reservation_id']
        if action == 'prepare':
            supabase.table('reservations').update({'status': 'prepared'}).eq('id', reservation_id).execute()
            flash("已確認放入借書袋！")
        elif action == 're-shelf':
            reservation = supabase.table('reservations').select('publication_id').eq('id', reservation_id).eq('status', 'returned').execute().data
            if reservation:
                supabase.table('publications').update({'status': 'available'}).eq('id', reservation[0]['publication_id']).execute()
                supabase.table('reservations').update({'status': 'returned'}).eq('id', reservation_id).execute()
                flash("書籍已重新上架！")
        return redirect(url_for('admin_reservations'))
    reservations = supabase.table('reservations').select('id, user_id, publication_id, publications(title, isbn), status').execute().data
    return render_template('admin_reservations.html', reservations=reservations)

@app.route('/admin/qr/<bag_id>')
def admin_show_qr(bag_id):
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(url_for('borrow_checkin', bag_id=bag_id, _external=True))
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype='image/png')

@app.route('/admin/qr_codes')
def admin_qr_codes():
    if 'admin' not in session:
        return redirect(url_for('admin_login'))
    users = supabase.table('users').select('id, phone, bag_id').execute().data
    return render_template('admin_qr_codes.html', users=users)

@app.route('/borrow/<int:book_id>', methods=['POST'])
def borrow(book_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    current_borrowed = supabase.table('reservations').select('id').eq('user_id', session['user_id']).in_('status', ['pending', 'prepared', 'picked_up']).execute().data
    user = supabase.table('users').select('max_borrow').eq('id', session['user_id']).execute().data[0]
    if len(current_borrowed) >= user['max_borrow']:
        flash("您已達借書上限！")
        return redirect(url_for('index'))
    supabase.table('reservations').insert({
        'user_id': session['user_id'],
        'publication_id': book_id,
        'status': 'pending'
    }).execute()
    supabase.table('publications').update({'status': 'borrowed'}).eq('id', book_id).execute()
    flash("預約成功，請等待管理員放入書袋！")
    return redirect(url_for('index'))

@app.route('/cancel_borrow/<reservation_id>', methods=['POST'])
def cancel_borrow(reservation_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    reservation = supabase.table('reservations').select('publication_id').eq('id', reservation_id).eq('user_id', session['user_id']).execute().data
    if reservation:
        supabase.table('reservations').update({'status': 'cancelled'}).eq('id', reservation_id).execute()
        supabase.table('publications').update({'status': 'available'}).eq('id', reservation[0]['publication_id']).execute()
        flash("已取消預約！")
    return redirect(url_for('index'))

@app.route('/borrow_checkin/<bag_id>', methods=['GET', 'POST'])
def borrow_checkin(bag_id):
    user = supabase.table('users').select('id').eq('bag_id', bag_id).execute().data
    if not user:
        flash("無效的書袋號碼！")
        return redirect(url_for('login'))
    user_id = user[0]['id']

    if 'user_id' not in session:
        session['redirect_after_login'] = request.url
        return redirect(url_for('login'))

    if session['user_id'] != user_id:
        flash("這不是您的書袋！")
        return redirect(url_for('index'))

    if request.method == 'POST':
        action = request.form.get('action')
        book_ids = request.form.getlist('book_ids')
        if action == 'borrow':
            for book_id in book_ids:
                reservation = supabase.table('reservations').select('status').eq('user_id', user_id).eq('publication_id', book_id).eq('status', 'prepared').execute().data
                if reservation:
                    supabase.table('reservations').update({'status': 'picked_up'}).eq('user_id', user_id).eq('publication_id', book_id).execute()
            flash("已確認取書，您可以帶走書籍了！")
        elif action == 'return':
            for book_id in book_ids:
                reservation = supabase.table('reservations').select('status').eq('user_id', user_id).eq('publication_id', book_id).in_('status', ['pending', 'picked_up']).execute().data
                if reservation:
                    supabase.table('reservations').update({'status': 'returned'}).eq('user_id', user_id).eq('publication_id', book_id).execute()
                    supabase.table('publications').update({'status': 'returned'}).eq('id', book_id).execute()
            flash("已確認還書，請將書籍放入袋中！")
        return redirect(url_for('index'))

    pending_books = supabase.table('reservations').select('publication_id, publications(title, author, isbn)').eq('user_id', user_id).eq('status', 'prepared').execute().data
    borrowed_books = supabase.table('reservations').select('publication_id, publications(title, author, isbn)').eq('user_id', user_id).in_('status', ['pending', 'picked_up']).execute().data
    return render_template('borrow_checkin.html', pending_books=pending_books, borrowed_books=borrowed_books, bag_id=bag_id)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000, debug=True)
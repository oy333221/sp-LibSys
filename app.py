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
    books = supabase.table('publications').select('id, title, description, product_link, status').eq('status', '可借閱').execute().data
    reservations = supabase.table('reservations').select('id, publication_id, publications(title), status').eq('user_id', session['user_id']).in_('status', ['待處理', '已準備', '已取書']).execute().data
    return render_template('index.html', books=books, reservations=reservations)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        phone = request.form['phone']
        password = request.form['password']
        name = request.form['name']
        
        # 基本驗證
        if not phone or not password or not name:
            flash("必填欄位不能為空！")
            return redirect(url_for('register'))
        
        # 檢查手機號碼格式
        if not phone.isdigit() or len(phone) != 10 or not phone.startswith('09'):
            flash("請輸入有效的手機號碼！")
            return redirect(url_for('register'))

        # 檢查手機號碼是否已被註冊
        existing_user = supabase.table('users').select('phone').eq('phone', phone).execute()
        if existing_user.data:
            flash("此手機號碼已被註冊！")
            return redirect(url_for('register'))

        # 建立新用戶
        try:
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

            # 處理書籍 ISBN
            isbns = request.form.get('isbns', '').strip().split('\n')
            for isbn in isbns:
                isbn = isbn.strip()
                if isbn:  # 只處理非空的 ISBN
                    try:
                        # 檢查 ISBN 是否已存在
                        existing_book = supabase.table('publications').select('isbn').eq('isbn', isbn).execute()
                        if existing_book.data:
                            flash(f"ISBN {isbn} 已存在於系統中")
                            continue
                        
                        # 新增到待處理書籍
                        supabase.table('pending_books').insert({
                            'isbn': isbn,
                            'owner_id': new_user['id'],
                            'status': '待審核'
                        }).execute()
                        
                        # 立即觸發爬蟲更新書籍資訊
                        from scraper import update_pending_book
                        update_pending_book(isbn)
                        
                    except Exception as e:
                        flash(f"處理 ISBN {isbn} 時發生錯誤")
                        continue

            flash("註冊成功，請等待審核！")
            return redirect(url_for('login'))
            
        except Exception as e:
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
        password = request.form['password']
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
def admin_book_status():
    if 'admin' not in session:
        return redirect(url_for('admin_login'))
    
    # 修正查詢語法
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
            .order('created_at', desc=True)\
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
def admin_reservations():
    if 'admin' not in session:
        return redirect(url_for('admin_login'))
    if request.method == 'POST':
        reservation_id = request.form['reservation_id']
        supabase.table('reservations').update({'status': '已準備'}).eq('id', reservation_id).execute()
        flash("書籍已放入書袋！")
        return redirect(url_for('admin_reservations'))
    pending_reservations = supabase.table('reservations').select('id, publication_id, users(name, phone), publications(title)').eq('status', '待處理').execute().data
    return render_template('admin_reservations.html', reservations=pending_reservations)

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

@app.route('/admin/qr_codes', methods=['GET', 'POST'])
def admin_qr_codes():
    if 'admin' not in session:
        return redirect(url_for('admin_login'))
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

    pending_books = supabase.table('reservations').select('publication_id, publications(title, author)').eq('user_id', user_id).eq('status', '已準備').execute().data
    borrowed_books = supabase.table('reservations').select('publication_id, publications(title, author)').eq('user_id', user_id).eq('status', '已取書').execute().data
    return render_template('borrow_checkin.html', pending_books=pending_books, borrowed_books=borrowed_books, bag_id=bag_id)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000, debug=True)
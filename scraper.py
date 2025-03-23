from supabase import create_client, Client
import requests
import time

supabase_url = "https://uidcuqimzkzvoscqhyax.supabase.co"
supabase_key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InVpZGN1cWltemt6dm9zY3FoeWF4Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDA2Mzg1OTcsImV4cCI6MjA1NjIxNDU5N30.e3U8j15-VB7fQhSG1VQk99tB8PuV-VjETHFXcvNlMBo"
supabase: Client = create_client(supabase_url, supabase_key)

def crawl_book_info(isbn):
    url = f"https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn}"
    try:
        response = requests.get(url)
        if response.status_code == 200 and response.json()['totalItems'] > 0:
            book = response.json()['items'][0]['volumeInfo']
            return {
                'title': book.get('title', '未知書名'),
                'author': ', '.join(book.get('authors', ['未知作者'])),
                'description': book.get('description', '無描述'),
                'product_link': f"https://books.google.com/books?isbn={isbn}"
            }
    except Exception as e:
        print(f"Error crawling ISBN {isbn}: {str(e)}")
    return None

def update_pending_book(isbn):
    info = crawl_book_info(isbn)
    if info:
        supabase.table('pending_books').update({
            'title': info['title'],
            'author': info['author'],
            'description': info.get('description', '無描述'),
            'product_link': info['product_link']
        }).eq('isbn', isbn).execute()
        return True
    return False

def monitor_pending_books():
    """持續監控 pending_books 表格，對新的 ISBN 進行爬蟲"""
    print("開始監控 pending_books...")
    last_check = 0
    
    while True:
        try:
            # 獲取最近新增的待處理書籍
            new_books = supabase.table('pending_books')\
                .select('isbn, title')\
                .eq('status', '待審核')\
                .is_('title', 'null')\
                .execute()

            for book in new_books.data:
                print(f"處理 ISBN: {book['isbn']}")
                if update_pending_book(book['isbn']):
                    print(f"成功更新 ISBN {book['isbn']} 的資訊")
                else:
                    print(f"無法找到 ISBN {book['isbn']} 的資訊")
            
            time.sleep(10)  # 每10秒檢查一次
            
        except Exception as e:
            print(f"監控過程發生錯誤: {str(e)}")
            time.sleep(30)  # 發生錯誤時等待30秒後繼續

if __name__ == "__main__":
    monitor_pending_books()
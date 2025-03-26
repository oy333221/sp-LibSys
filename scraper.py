from supabase import create_client, Client
import requests
from bs4 import BeautifulSoup
import time
import os
import re

# Supabase 設定
supabase: Client = create_client(
    "https://uidcuqimzkzvoscqhyax.supabase.co",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InVpZGN1cWltemt6dm9zY3FoeWF4Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDA2Mzg1OTcsImV4cCI6MjA1NjIxNDU5N30.e3U8j15-VB7fQhSG1VQk99tB8PuV-VjETHFXcvNlMBo"
)

# 設定儲存書封的資料夾
STATIC_DIR = "static/covers"
os.makedirs(STATIC_DIR, exist_ok=True)

def is_valid_isbn(isbn):
    """驗證 ISBN 格式"""
    isbn = re.sub(r'[^0-9X]', '', isbn)
    if len(isbn) not in [10, 13]:
        print(f"無效的 ISBN 長度: {len(isbn)}")
        return False
    if len(isbn) == 13:
        if not isbn.startswith('978') and not isbn.startswith('979'):
            print(f"ISBN-13 必須以 978 或 979 開頭: {isbn}")
            return False
    return True

def process_book(isbn):
    print(f"開始從博客來爬取 ISBN: {isbn}")  # 除錯訊息
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Referer": "https://www.books.com.tw/",
        "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive"
    }
    
    try:
        # 1. 搜尋頁面
        search_url = f"https://search.books.com.tw/search/query/key/{isbn}/cat/all"
        print(f"訪問搜尋頁面: {search_url}")  # 除錯訊息
        search_response = requests.get(search_url, headers=headers, timeout=10)
        if search_response.status_code != 200:
            print(f"搜尋頁面返回狀態碼: {search_response.status_code}")  # 除錯訊息
            return None
            
        search_soup = BeautifulSoup(search_response.text, 'html.parser')
        product_link = search_soup.select_one('a[href*="/redirect/move/"]')
        if not product_link:
            print("找不到商品連結")  # 除錯訊息
            return None
            
        # 2. 取得商品頁面
        item_id = product_link['href'].split('item/')[1].split('/')[0]
        product_url = f"https://www.books.com.tw/products/{item_id}"
        print(f"訪問商品頁面: {product_url}")  # 除錯訊息
        
        response = requests.get(product_url, headers=headers, timeout=10)
        if response.status_code != 200:
            print(f"商品頁面返回狀態碼: {response.status_code}")  # 除錯訊息
            return None
            
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
            if not cover_url.startswith('http'):
                cover_url = "https:" + cover_url
            print(f"找到書封 URL: {cover_url}")  # 除錯訊息
        
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
        
        result = supabase.table('pending_books')\
            .update(update_data)\
            .eq('isbn', isbn)\
            .execute()
            
        print(f"更新結果: {result.data}")  # 除錯訊息
        return True
        
    except Exception as e:
        print(f"處理 ISBN {isbn} 時發生錯誤: {str(e)}")  # 除錯訊息
        supabase.table('pending_books').update({
            'error_message': f'處理失敗: {str(e)}'
        }).eq('isbn', isbn).execute()
        return None

def update_pending_book(isbn, owner_id):
    """更新待審核書籍資訊"""
    try:
        # 爬取書籍資訊
        book_info = crawl_book_info(isbn)
        if not book_info:
            return False
            
        # 直接使用博客來的圖片 URL
        cover_url = book_info.get('cover_url')
        
        # 更新資料庫
        update_data = {
            'title': book_info['title'],
            'author': book_info['author'],
            'description': book_info['description'],
            'product_link': book_info['product_link'],
            'cover_url': cover_url,  # 直接使用博客來的圖片 URL
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
        print(f"更新書籍資訊時發生錯誤: {str(e)}")
        supabase.table('pending_books').update({
            'error_message': f'處理失敗: {str(e)}'
        }).eq('isbn', isbn).eq('owner_id', owner_id).execute()
        return False

def main():
    print("啟動博客來爬蟲程式")  # 除錯訊息
    while True:
        try:
            # 獲取待處理的書籍
            result = supabase.table('pending_books').select('*').eq('status', '待審核').execute()
            
            if not result.data:
                print("沒有待處理的書籍")
                time.sleep(10)
                continue
                
            for book in result.data:
                isbn = book['isbn']
                print(f"\n開始處理 ISBN: {isbn}")
                
                if process_book(isbn):
                    print(f"成功處理 ISBN {isbn}")
                else:
                    print(f"更新錯誤訊息: ISBN {isbn}")
                    supabase.table('pending_books').update({
                        'error_message': '無法從博客來找到此書籍'
                    }).eq('isbn', isbn).execute()
                    print(f"無法處理 ISBN {isbn}")
                    
        except Exception as e:
            print(f"執行時發生錯誤: {str(e)}")
            
        time.sleep(10)

if __name__ == "__main__":
    main()
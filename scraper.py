import requests
from bs4 import BeautifulSoup
from supabase import create_client, Client
import os

# Supabase 連線
supabase_url = "https://uidcuqimzkzvoscqhyax.supabase.co"
supabase_key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InVpZGN1cWltemt6dm9zY3FoeWF4Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDA2Mzg1OTcsImV4cCI6MjA1NjIxNDU5N30.e3U8j15-VB7fQhSG1VQk99tB8PuV-VjETHFXcvNlMBo"
supabase: Client = create_client(supabase_url, supabase_key)


def scrape_book_details(isbn):
    # 搜尋頁面
    search_url = f"https://search.books.com.tw/search/query/key/{isbn}/cat/all"
    headers = {'User-Agent': 'Mozilla/5.0'}
    response = requests.get(search_url, headers=headers)
    soup = BeautifulSoup(response.text, 'html.parser')

    # 取得產品編號
    product_div = soup.find('div', class_='table-td', id=lambda x: x and 'prod-itemlist-' in x)
    if not product_div:
        return None
    product_id = product_div.get('id').replace('prod-itemlist-', '')
    book_link = f"https://www.books.com.tw/products/{product_id}?sloc=main"

    # 詳細頁面
    detail_response = requests.get(book_link, headers=headers)
    detail_soup = BeautifulSoup(detail_response.text, 'html.parser')

    # 書名
    title = detail_soup.find('h1', class_='mod type02_p002 clearfix').text.strip()

    # 簡介
    content_div = detail_soup.find('div', class_='content', style='height:auto;')
    description = '\n'.join(p.text.strip() for p in content_div.find_all('p')) if content_div else '無簡介'

    return {
        'title': title,
        'description': description,
        'link': book_link
    }

def update_pending_books():
    pending_books = supabase.table('pending_books').select('id, isbn, author, owner_id').eq('status', 'pending').execute().data
    for book in pending_books:
        details = scrape_book_details(book['isbn'])
        if details:
            supabase.table('publications').insert({
                'isbn': book['isbn'],
                'title': details['title'],
                'author': book['author'],
                'owner_id': book['owner_id'],
                'status': 'available',
                'description': details['description'],
                'product_link': details['link']
            }).execute()
            supabase.table('pending_books').update({'status': 'approved'}).eq('id', book['id']).execute()
            print(f"Updated book: {book['isbn']}")
        else:
            print(f"Failed to scrape: {book['isbn']}")

if __name__ == "__main__":
    update_pending_books()
from supabase import create_client, Client
import requests

supabase_url = "https://uidcuqimzkzvoscqhyax.supabase.co"
supabase_key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InVpZGN1cWltemt6dm9zY3FoeWF4Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDA2Mzg1OTcsImV4cCI6MjA1NjIxNDU5N30.e3U8j15-VB7fQhSG1VQk99tB8PuV-VjETHFXcvNlMBo"
supabase: Client = create_client(supabase_url, supabase_key)

def crawl_book_info(isbn):
    url = f"https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn}"
    response = requests.get(url)
    if response.status_code == 200 and response.json()['totalItems'] > 0:
        book = response.json()['items'][0]['volumeInfo']
        return {
            'title': book.get('title', '未知書名'),
            'author': ', '.join(book.get('authors', ['未知作者'])),
            'description': book.get('description', '無描述'),
            'product_link': f"https://books.google.com/books?isbn={isbn}"
        }
    return None

if __name__ == "__main__":
    approved_books = supabase.table('pending_books').select('isbn, title, owner_id').eq('status', 'approved').execute().data
    for book in approved_books:
        existing = supabase.table('publications').select('isbn').eq('isbn', book['isbn']).execute().data
        if not existing:
            info = crawl_book_info(book['isbn'])
            if info:
                supabase.table('publications').update({
                    'title': info['title'],
                    'author': info['author'],
                    'description': info['description'],
                    'product_link': info['product_link']
                }).eq('isbn', book['isbn']).execute()
                print(f"Updated {book['isbn']} with crawled data.")
            else:
                print(f"No data found for {book['isbn']}.")
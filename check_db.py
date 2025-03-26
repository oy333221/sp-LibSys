from supabase import create_client
import os

supabase_url = "https://uidcuqimzkzvoscqhyax.supabase.co"
supabase_key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InVpZGN1cWltemt6dm9zY3FoeWF4Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDA2Mzg1OTcsImV4cCI6MjA1NjIxNDU5N30.e3U8j15-VB7fQhSG1VQk99tB8PuV-VjETHFXcvNlMBo"
supabase = create_client(supabase_url, supabase_key)

# 查詢所有書籍的資訊
books = supabase.table('publications').select('isbn, title, cover_url').execute()

print("資料庫中的書籍資訊：")
for book in books.data:
    print(f"\nISBN: {book['isbn']}")
    print(f"書名: {book['title']}")
    print(f"封面URL: {book['cover_url']}") 
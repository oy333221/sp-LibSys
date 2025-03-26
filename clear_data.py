from supabase import create_client
import os
from dotenv import load_dotenv
import time
import sys

# 載入環境變數
load_dotenv()

# 獲取 Supabase 認證信息
supabase_url = os.environ.get('SUPABASE_URL')
supabase_key = os.environ.get('SUPABASE_KEY')

if not supabase_url or not supabase_key:
    print("錯誤：無法從環境變數獲取 Supabase 認證信息")
    print("請確保 .env 檔案存在並包含 SUPABASE_URL 和 SUPABASE_KEY")
    sys.exit(1)

# 初始化 Supabase 客戶端
supabase = create_client(supabase_url, supabase_key)

def clear_data():
    print("警告：此操作將清空資料庫中的書籍、用戶和預約資料！")
    print("管理員帳號將會保留")
    confirm = input("確定要繼續嗎？輸入 'yes' 確認：")
    
    if confirm.lower() != 'yes':
        print("已取消操作")
        return

    try:
        # 先刪除有外鍵依賴的表
        print("刪除預約資料...")
        supabase.table('reservations').delete().neq('id', 0).execute()
        
        print("刪除書籍資料...")
        supabase.table('publications').delete().neq('id', 0).execute()
        supabase.table('pending_books').delete().neq('id', 0).execute()
        
        print("刪除一般用戶資料...")
        # 仍保留管理員用戶（如果有的話）
        supabase.table('users').delete().eq('status', '已通過').execute()
        supabase.table('users').delete().eq('status', '待審核').execute()
        supabase.table('users').delete().eq('status', '已拒絕').execute()
        
        print("資料清空完成！")
        print("如果想要重置自動遞增ID，請在 Supabase 控制台手動操作。")
    
    except Exception as e:
        print(f"清空資料時發生錯誤：{str(e)}")

if __name__ == "__main__":
    clear_data() 